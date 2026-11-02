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
ARCHIVE_NAME = 'RootDetector-detection-results.zip'
CSV_HEADER = (
    'Filename, # root pixels, # background pixels, # mask pixels, '
    '# skeleton pixels, # skeleton pixels (<3px width), # skeleton pixels (3-7px width), '
    '# skeleton pixels (>7px width),Kimura length;\n'
)
MAX_IMAGES = 10000
MAX_REQUEST_BYTES = 16 * 1024 * 1024
ARCHIVE_RE = re.compile(r'^detection-results\.([0-9a-f]{32})\.zip$')


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
        self.active_downloads = 0

    def _archive_path(self, export_id):
        if not isinstance(export_id, str) or not re.fullmatch(r'[0-9a-f]{32}', export_id):
            raise security.ValidationError('Invalid export ID.', 'invalid_export_id')
        return os.path.join(self.export_path, 'detection-results.{}.zip'.format(export_id))

    def _snapshot(self, job):
        return {key: job[key] for key in ('id', 'state', 'processed', 'total', 'bytes', 'error')}

    def active(self):
        with self.lock:
            return self.active_id is not None

    def transferring(self):
        with self.lock:
            return self.active_downloads > 0

    def begin_download(self):
        with self.lock:
            self.active_downloads += 1

    def end_download(self):
        with self.lock:
            self.active_downloads = max(0, self.active_downloads - 1)

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
                   'total': len(specs), 'bytes': 0, 'error': None}
            self.jobs[export_id] = job
            self.fingerprints[fingerprint] = export_id
            self.active_id = export_id
            threading.Thread(target=self._build, args=(job, specs), daemon=True).start()
            return self._snapshot(job)

    def _build(self, job, specs):
        export_id = job['id']
        destination = self._archive_path(export_id)
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
                archive.writestr('detection-results-manifest.json', json.dumps({
                    'schema': 1,
                    'created_utc': datetime.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
                    'processed_image_count': len(specs),
                    'image_names': [item['filename'] for item in specs],
                }, ensure_ascii=False, indent=2))
            for item in specs:
                for path, size, modified_ns in item['source_signatures']:
                    current = os.stat(path)
                    if (current.st_size, current.st_mtime_ns) != (size, modified_ns):
                        raise OSError('A detection result changed while the archive was being prepared.')
            os.replace(temporary, destination)
            temporary = None
            with self.lock:
                job['bytes'] = os.path.getsize(destination)
                job['state'] = 'ready'
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
        path = self._archive_path(export_id)
        with self.lock:
            job = self.jobs.get(export_id)
            if job:
                return self._snapshot(job)
        if not os.path.isfile(path) or os.path.islink(path):
            raise security.ValidationError('This archive is not available.', 'export_not_found', 404)
        return {'id': export_id, 'state': 'ready', 'processed': None, 'total': None,
                'bytes': os.path.getsize(path), 'error': None}

    def archive_path(self, export_id):
        path = self._archive_path(export_id)
        if not os.path.isfile(path) or os.path.islink(path):
            raise security.ValidationError('This archive is not ready.', 'export_not_ready', 404)
        return path

    def recent(self):
        paths = []
        for name in os.listdir(self.export_path):
            match = ARCHIVE_RE.fullmatch(name)
            if match:
                path = os.path.join(self.export_path, name)
                if os.path.isfile(path) and not os.path.islink(path):
                    paths.append((os.path.getmtime(path), match.group(1)))
        return [self.status(export_id) for _, export_id in sorted(paths, reverse=True)[:20]]
