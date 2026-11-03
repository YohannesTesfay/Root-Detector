"""Disk-backed detection archives that survive a failed browser download."""

import datetime
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import tempfile
import threading
import zipfile

from base.backend.paths import get_instance_path
from backend import preparation, security


LOGGER = logging.getLogger('rootdetector')
MANIFEST_NAME = 'detection-results-manifest.json'
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
CSV_HEADER = (
    'Filename, # root pixels, # background pixels, # mask pixels, '
    '# skeleton pixels, # skeleton pixels (<3px width), # skeleton pixels (3-7px width), '
    '# skeleton pixels (>7px width),Kimura length;\n'
)
MAX_IMAGES = 10000
MAX_REQUEST_BYTES = 16 * 1024 * 1024
ARCHIVE_RE = re.compile(r'^detection-results\.([0-9a-f]{32})\.zip$')
MANAGED_ARCHIVE_RE = re.compile(r'^managed-detection-results\.([0-9a-f]{32})\.zip$')


def _created_utc(timestamp=None):
    date = (datetime.datetime.utcnow() if timestamp is None
            else datetime.datetime.utcfromtimestamp(timestamp))
    return date.replace(microsecond=0).isoformat() + 'Z'


def _download_name(export_id, created):
    stamp = created.replace('T', '_').replace(':', '-')
    return 'RootDetector-detection-results_{}_{}.zip'.format(stamp, export_id[:8])


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _file_path(cache_path, name):
    path = security.safe_resolve(cache_path, name, {'.png'}, must_exist=True)
    if not os.path.isfile(path) or os.path.islink(path):
        raise security.ValidationError('A detection result is no longer available.', 'missing_detection_result', 409)
    return path


def _validated_spec(cache_path, item):
    if not isinstance(item, dict):
        raise security.ValidationError('Invalid detection export entry.', 'invalid_detection_export')
    filename = security.validate_filename(item.get('filename'), security.SUPPORTED_IMAGE_EXTENSIONS)
    row = item.get('csv_row')
    if (not isinstance(row, str) or len(row.encode('utf-8')) > 4096
            or not row.startswith(filename + ', ') or not row.endswith(';\n')
            or row.count('\n') != 1 or '\r' in row or '\x00' in row):
        raise security.ValidationError('Invalid detection statistics row.', 'invalid_detection_statistics')
    segmentation = _file_path(cache_path, filename + '.segmentation.png')
    skeleton = _file_path(cache_path, filename + '.skeleton.png')
    manifest = item.get('preparation')
    companions = item.get('companions') or []
    if not isinstance(companions, list) or len(companions) > 32:
        raise security.ValidationError('Invalid prepared companion list.', 'invalid_companion')
    if manifest is not None:
        source = security.safe_resolve(
            cache_path, filename, security.SUPPORTED_IMAGE_EXTENSIONS, must_exist=True,
        )
        preparation.validate_manifest_for_output(manifest, filename, source)
    elif companions:
        raise security.ValidationError('Prepared companions require a crop record.', 'invalid_companion')
    companion_paths = []
    seen = set()
    for record in companions:
        preparation.validate_companion_provenance(record, manifest, cache_path)
        name = record['output_name']
        if name in seen:
            continue
        seen.add(name)
        companion_paths.append((name, _file_path(cache_path, name), record))
    return {
        'filename': filename, 'csv_row': row,
        'segmentation': segmentation, 'skeleton': skeleton,
        'preparation': manifest, 'companions': companion_paths,
    }


class DetectionExportManager:
    """One archive job at a time; completed ZIPs live outside the cleared cache."""

    def __init__(self, cache_path, export_path=None):
        self.cache_path = cache_path
        self.export_path = export_path or os.path.join(get_instance_path(), 'exports')
        os.makedirs(self.export_path, exist_ok=True)
        self.lock = threading.RLock()
        self.jobs = {}
        self.fingerprints = {}
        self.active_id = None
        self.active_downloads = {}
        managed = self._stored_archives(MANAGED_ARCHIVE_RE)
        self.latest_managed_id = managed[0][1] if managed else None
        self._prune_managed()

    def _managed_path(self, export_id):
        return os.path.join(self.export_path, 'managed-detection-results.{}.zip'.format(export_id))

    def _archive_path(self, export_id):
        if not isinstance(export_id, str) or not re.fullmatch(r'[0-9a-f]{32}', export_id):
            raise security.ValidationError('Invalid export ID.', 'invalid_export_id')
        managed = self._managed_path(export_id)
        if os.path.lexists(managed):
            return managed
        return os.path.join(self.export_path, 'detection-results.{}.zip'.format(export_id))

    def _snapshot(self, job):
        return {key: job[key] for key in ('id', 'state', 'processed', 'total', 'bytes', 'error',
                                         'created_utc', 'download_name')}

    def active(self):
        with self.lock:
            return self.active_id is not None

    def transferring(self):
        with self.lock:
            return bool(self.active_downloads)

    def begin_download(self, export_id):
        # Pin before send_file opens the archive, under the same lock as pruning.
        with self.lock:
            path = self.archive_path(export_id)
            name = self.status(export_id)['download_name']
            self.active_downloads[export_id] = self.active_downloads.get(export_id, 0) + 1
            return path, name

    def end_download(self, export_id):
        with self.lock:
            remaining = self.active_downloads.get(export_id, 0) - 1
            if remaining > 0:
                self.active_downloads[export_id] = remaining
            else:
                self.active_downloads.pop(export_id, None)
                self._prune_managed()

    def _stored_archives(self, pattern):
        paths = []
        for name in os.listdir(self.export_path):
            match = pattern.fullmatch(name)
            if match:
                path = os.path.join(self.export_path, name)
                if os.path.isfile(path) and not os.path.islink(path):
                    paths.append((os.path.getmtime(path), match.group(1)))
        return sorted(paths, reverse=True)

    def _prune_managed(self):
        # The legacy name is deliberately excluded: never auto-delete pre-RC8 ZIPs.
        try:
            for _, export_id in self._stored_archives(MANAGED_ARCHIVE_RE):
                if export_id == self.latest_managed_id or export_id in self.active_downloads:
                    continue
                try:
                    os.remove(self._managed_path(export_id))
                except OSError:
                    LOGGER.warning('Could not prune superseded detection ZIP %s', export_id, exc_info=True)
                    continue
                self.jobs.pop(export_id, None)
                self.fingerprints = {key: value for key, value in self.fingerprints.items() if value != export_id}
        except OSError:
            LOGGER.warning('Could not list managed detection ZIPs for cleanup', exc_info=True)

    def start(self, payload):
        items = payload.get('files') if isinstance(payload, dict) else None
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_IMAGES:
            raise security.ValidationError('Choose 1 to {} processed images.'.format(MAX_IMAGES), 'invalid_detection_export')
        specs = [_validated_spec(self.cache_path, item) for item in items]
        if len({item['filename'] for item in specs}) != len(specs):
            raise security.ValidationError('Duplicate image in detection export.', 'invalid_detection_export')
        source_stats = []
        for item in specs:
            item['source_signatures'] = []
            for path in [item['segmentation'], item['skeleton']] + [row[1] for row in item['companions']]:
                stat = os.stat(path)
                source_stats.append((os.path.basename(path), stat.st_size, stat.st_mtime_ns))
                item['source_signatures'].append((path, stat.st_size, stat.st_mtime_ns))
        fingerprint = hashlib.sha256(_json_bytes({
            'files': items, 'source_stats': source_stats,
        })).hexdigest()
        with self.lock:
            old_id = self.fingerprints.get(fingerprint)
            if old_id and (self.jobs[old_id]['state'] == 'preparing'
                           or os.path.isfile(self._archive_path(old_id))):
                return self._snapshot(self.jobs[old_id])
            if self.active_id is not None:
                raise security.ValidationError('An archive is already being prepared.', 'export_busy', 409)
            export_id = secrets.token_hex(16)
            job = {'id': export_id, 'state': 'preparing', 'processed': 0,
                   'total': len(specs), 'bytes': 0, 'error': None,
                   'created_utc': None, 'download_name': None}
            self.jobs[export_id] = job
            self.fingerprints[fingerprint] = export_id
            self.active_id = export_id
            threading.Thread(target=self._build, args=(job, specs), daemon=True).start()
            return self._snapshot(job)

    def _build(self, job, specs):
        export_id = job['id']
        destination = self._managed_path(export_id)
        temporary = None
        try:
            source_bytes = sum(
                os.path.getsize(path)
                for item in specs
                for path in [item['segmentation'], item['skeleton']]
                + [row[1] for row in item['companions']]
            )
            reserve = max(128 * 1024 * 1024, source_bytes // 20)
            if shutil.disk_usage(self.export_path).free < source_bytes + reserve:
                raise OSError('Not enough free disk space for the archive and safety reserve.')
            handle, temporary = tempfile.mkstemp(
                prefix='.detection-export-', suffix='.partial', dir=self.export_path,
            )
            os.close(handle)
            preparations = [item['preparation'] for item in specs if item['preparation']]
            all_companions = {}
            with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
                for item in specs:
                    prefix = item['filename'] + '/'
                    for key in ('segmentation', 'skeleton'):
                        archive.write(item[key], prefix + os.path.basename(item[key]))
                    archive.writestr(prefix + 'statistics.csv', CSV_HEADER + item['csv_row'])
                    if item['preparation']:
                        archive.writestr(prefix + 'preparation-manifest.json', json.dumps({
                            'schema': 1, 'preparations': [item['preparation']],
                        }, ensure_ascii=False, indent=2))
                    if item['companions']:
                        records = [record for _, _, record in item['companions']]
                        archive.writestr(prefix + 'preparation-companions.json', json.dumps({
                            'schema': 1, 'companions': records,
                        }, ensure_ascii=False, indent=2))
                        for name, path, record in item['companions']:
                            archive.write(path, prefix + 'preparation-companions/' + name)
                            all_companions[name] = (path, record)
                    with self.lock:
                        job['processed'] += 1
                archive.writestr('statistics.csv', CSV_HEADER + ''.join(item['csv_row'] for item in specs))
                if preparations:
                    archive.writestr('preparation-manifest.json', json.dumps({
                        'schema': 1, 'preparations': preparations,
                    }, ensure_ascii=False, indent=2))
                if all_companions:
                    archive.writestr('preparation-companions.json', json.dumps({
                        'schema': 1, 'companions': [record for _, record in all_companions.values()],
                    }, ensure_ascii=False, indent=2))
                    for name, (path, _) in all_companions.items():
                        archive.write(path, 'preparation-companions/' + name)
                created = _created_utc()
                archive.writestr(MANIFEST_NAME, json.dumps({
                    'schema': 1,
                    'created_utc': created,
                    'processed_image_count': len(specs),
                    'image_names': [item['filename'] for item in specs],
                }, ensure_ascii=False, indent=2))
            for item in specs:
                for path, size, modified_ns in item['source_signatures']:
                    current = os.stat(path)
                    if (current.st_size, current.st_mtime_ns) != (size, modified_ns):
                        raise OSError('A detection result changed while the archive was being prepared.')
            with self.lock:
                archive_bytes = os.path.getsize(temporary)
                os.replace(temporary, destination)
                temporary = None
                job['bytes'] = archive_bytes
                job['created_utc'] = created
                job['download_name'] = _download_name(export_id, created)
                job['state'] = 'ready'
                self.latest_managed_id = export_id
                self._prune_managed()
        except Exception as exc:
            LOGGER.exception('Detection archive %s failed', export_id)
            with self.lock:
                job['state'] = 'failed'
                job['error'] = ('Archive preparation failed. Check available disk space or changed results, and keep '
                                'the current session open before retrying.')
                if isinstance(exc, security.ValidationError):
                    job['error'] = str(exc)
        finally:
            try:
                if temporary and os.path.isfile(temporary):
                    os.remove(temporary)
            except OSError:
                LOGGER.exception('Could not remove partial detection archive %s', export_id)
            finally:
                with self.lock:
                    self.active_id = None

    def status(self, export_id):
        with self.lock:
            path = self._archive_path(export_id)
            job = self.jobs.get(export_id)
            if job:
                return self._snapshot(job)
            if not os.path.isfile(path) or os.path.islink(path):
                raise security.ValidationError('This archive is not available.', 'export_not_found', 404)
            stat = os.stat(path)
            created, total = _created_utc(stat.st_mtime), None
            try:
                with zipfile.ZipFile(path) as archive:
                    entry = archive.getinfo(MANIFEST_NAME)
                    if entry.file_size <= MAX_MANIFEST_BYTES:
                        manifest = json.loads(archive.read(entry))
                        if isinstance(manifest, dict):
                            stamp = manifest.get('created_utc')
                            if isinstance(stamp, str):
                                date = datetime.datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%SZ')
                                created = date.isoformat() + 'Z'
                            count = manifest.get('processed_image_count')
                            if type(count) is int and 1 <= count <= MAX_IMAGES:
                                total = count
            except (OSError, ValueError, KeyError, zipfile.BadZipFile, RuntimeError):
                pass  # Older archives may lack usable metadata; keep them recoverable.
            return {'id': export_id, 'state': 'ready', 'processed': total, 'total': total,
                    'bytes': stat.st_size, 'error': None, 'created_utc': created,
                    'download_name': _download_name(export_id, created)}

    def archive_path(self, export_id):
        path = self._archive_path(export_id)
        if not os.path.isfile(path) or os.path.islink(path):
            raise security.ValidationError('This archive is not ready.', 'export_not_ready', 404)
        return path

    def recent(self):
        with self.lock:
            if self.latest_managed_id:
                path = self._managed_path(self.latest_managed_id)
                if os.path.isfile(path) and not os.path.islink(path):
                    return [self.status(self.latest_managed_id)]
            legacy = self._stored_archives(ARCHIVE_RE)
            return [self.status(legacy[0][1])] if legacy else []
