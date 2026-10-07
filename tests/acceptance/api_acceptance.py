#!/usr/bin/env python3
"""Stdlib-only acceptance against a dedicated running RootDetector package."""
import argparse
import copy
import csv
import datetime as dt
import hashlib
import io
import json
import mimetypes
from pathlib import Path
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile


TERMINAL = {'completed', 'completed_with_errors', 'failed', 'cancelled'}
SECRET_KEYS = {'token', 'session_token', 'authorization', 'x-rootdetector-token'}


def redact(value):
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items() if key.lower() not in SECRET_KEYS}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def digest_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def loopback_url(value):
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != 'http' or parsed.hostname not in {'localhost', '127.0.0.1', '::1'}
            or parsed.username or parsed.password or parsed.path not in ('', '/')
            or parsed.query or parsed.fragment):
        raise ValueError('Use an HTTP loopback origin, e.g. http://127.0.0.1:5000.')
    return value.rstrip('/')


def chronological_pairs(paths):
    """Match the app's underscore-delimited date tokens and pre-date groups."""
    groups = {}
    for path in paths:
        name = path.name
        matched = None
        for token in name.split('_'):
            if not re.fullmatch(r'\d+\.\d+\.\d+', token):
                continue
            a, b, c = token.split('.')
            if len(a) > 2:
                year, month, day = int(a), int(b), int(c)
            elif len(c) > 2:
                year, month, day = int(c), int(b), int(a)
            else:
                year, month, day = int(c), int(b), int(a)
                year += 2000 if year < 70 else 1900
            try:
                date = dt.date(year, month, day)
            except ValueError:
                continue
            prefix = name.split(token)[0]
            if prefix:
                matched = prefix, date
                break
        if matched is None:
            raise ValueError('No valid app-compatible observation date in {}'.format(name))
        prefix, date = matched
        group = groups.setdefault(prefix, {})
        if date in group:
            raise ValueError('Duplicate observation date for {}: {}'.format(prefix, date))
        group[date] = name
    pairs = []
    for prefix in sorted(groups):
        names = [groups[prefix][date] for date in sorted(groups[prefix])]
        pairs.extend([first, second] for first, second in zip(names, names[1:]))
    if not pairs:
        raise ValueError('Provide at least two dates from the same pre-date filename group.')
    return pairs


class HTTPFailure(RuntimeError):
    def __init__(self, status, payload):
        self.status = status
        self.payload = redact(payload)
        super().__init__('HTTP {}: {}'.format(status, self.payload))


class Client:
    def __init__(self, origin, timeout):
        self.origin, self.timeout, self.token = origin, timeout, None

    def request(self, path, method='GET', payload=None, data=None, content_type=None, binary=False):
        headers = {'Origin': self.origin}
        if self.token and method != 'GET':
            headers['X-RootDetector-Token'] = self.token
        if payload is not None:
            data, content_type = json.dumps(payload).encode('utf-8'), 'application/json'
        if content_type:
            headers['Content-Type'] = content_type
        request = urllib.request.Request(self.origin + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = response.read()
                if binary:
                    return result
                if 'json' in response.headers.get('Content-Type', ''):
                    return json.loads(result.decode('utf-8'))
                return result.decode('utf-8').strip()
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                detail = json.loads(raw.decode('utf-8'))
            except (ValueError, UnicodeError):
                detail = {'message': raw.decode('utf-8', 'replace')[:2000]}
            raise HTTPFailure(exc.code, detail) from None

    def upload(self, path, name=None):
        # Fixtures are deliberately bounded by the application's upload limit.
        boundary = 'RootDetectorAcceptance' + uuid.uuid4().hex
        name = name or path.name
        if any(char in name for char in '\r\n"'):
            raise ValueError('Unsupported multipart filename.')
        header = ('--{}\r\nContent-Disposition: form-data; name="files"; filename="{}"\r\n'
                  'Content-Type: {}\r\n\r\n').format(boundary, name, mimetypes.guess_type(name)[0] or 'application/octet-stream')
        body = header.encode('utf-8') + path.read_bytes() + ('\r\n--{}--\r\n'.format(boundary)).encode('ascii')
        return self.request('/file_upload', 'POST', data=body,
                            content_type='multipart/form-data; boundary=' + boundary)


def comparison_record(run):
    records = []
    for pair in run.get('pairs', []):
        result = pair.get('result') or {}
        matcher = result.get('tracking_matcher') or {}
        records.append({
            'pair': [pair['filename0'], pair['filename1']],
            'points0': result.get('points0'), 'points1': result.get('points1'),
            'seed': matcher.get('seed'), 'seed_identity': matcher.get('seed_identity'),
            'statistics': result.get('statistics'), 'match_device': result.get('match_device'),
        })
    return records


class Acceptance:
    def __init__(self, args, paths, pairs):
        self.args, self.paths, self.pairs = args, paths, pairs
        self.output = Path(args.output)
        self.output.mkdir(parents=True, exist_ok=False)
        self.client = Client(loopback_url(args.url), args.http_timeout)
        self.active = None
        self.unconfirmed_submission = None
        self.original_settings = None
        self.settings_changed = False
        self.summary = {'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                        'device': args.device, 'cases': [], 'status': 'running',
                        'scope': 'Mechanical package/API acceptance; not ecological or scientific validity.',
                        'mask_scope': 'No exclusion masks: all eight options exercised without exclusion effects.',
                        'repeat_scope': 'Same process/device/models; detection caches may be reused.'}

    def save(self, name, value):
        path = self.output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(redact(value), indent=2, sort_keys=True, allow_nan=False), encoding='utf-8')

    def record(self, name, status, **details):
        self.summary['cases'].append(dict(name=name, status=status, **details))
        self.save('summary.json', self.summary)
        print('{}: {}'.format(name, status), flush=True)

    def diagnostics(self, tag):
        data = self.client.request('/api/diagnostics', binary=True)
        (self.output / (tag + '-diagnostics.zip')).write_bytes(data)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            snapshot = json.loads(archive.read('diagnostics.json').decode('utf-8'))
            self.save(tag + '-runtime.json', snapshot)
            return archive.read('BUILD-INFO.txt').decode('utf-8') if 'BUILD-INFO.txt' in archive.namelist() else ''

    def settings(self, mode, policy, detection_model=None):
        selected = copy.deepcopy(self.original_settings)
        selected.update(use_gpu=self.args.device == 'cuda', exmask_enabled=False,
                        tracking_sampling_mode=mode, tracking_exclusion_policy=policy)
        if detection_model or self.args.detection_model:
            selected['active_models']['detection'] = detection_model or self.args.detection_model
        self.settings_changed = True
        self.client.request('/settings', 'POST', selected)
        actual = self.client.request('/settings')
        for key in ('use_gpu', 'active_models', 'exmask_enabled', 'tracking_sampling_mode', 'tracking_exclusion_policy'):
            if actual['settings'].get(key) != selected[key]:
                raise AssertionError('Requested setting was not retained: ' + key)
        return actual

    def check_build(self, build):
        # Only evidence returned by the running server identifies that instance.
        # A local sidecar must never substitute for a missing/mismatched server file.
        (self.output / 'BUILD-INFO.txt').write_text(build or 'Unavailable; package identity not independently verified.\n', encoding='utf-8')
        if self.args.build_info:
            supplied = Path(self.args.build_info).read_text(encoding='utf-8')
            (self.output / 'supplied-BUILD-INFO.txt').write_text(supplied, encoding='utf-8')
            if build and supplied.strip() != build.strip():
                raise AssertionError('Supplied package BUILD-INFO differs from the running server.')
        if self.args.expected_commit and self.args.expected_commit.lower() not in build.lower():
            raise AssertionError('Running server build provenance does not contain the expected commit.')
        self.summary['build_provenance_verified'] = bool(self.args.expected_commit)

    def poll(self, kind, run_id, tag):
        endpoint = '/api/{}/runs/{}'.format(kind, run_id)
        deadline, failures = time.monotonic() + self.args.run_timeout, 0
        self.active = (kind, run_id)
        last_progress = None
        while time.monotonic() < deadline:
            try:
                run = self.client.request(endpoint)
            except (urllib.error.URLError, socket.timeout, TimeoutError, HTTPFailure) as exc:
                failures += 1
                self.save(tag + '-poll-error-{}.json'.format(failures), {'type': type(exc).__name__, 'message': str(exc)})
                if failures >= 3:
                    raise RuntimeError('Polling failed three times; job state is unconfirmed.') from exc
                time.sleep(self.args.poll_interval)
                continue
            self.save(tag + '-latest.json', run)
            progress = (run.get('state'), run.get('current'), run.get('progress'))
            if progress != last_progress:
                print('{}: {} {}'.format(tag, run.get('state'), run.get('current') or ''), flush=True)
                last_progress = progress
            if run['state'] in TERMINAL:
                self.active = None
                return run
            time.sleep(self.args.poll_interval)
        raise TimeoutError('{} exceeded {} seconds; last state saved.'.format(tag, self.args.run_timeout))

    def verify_run(self, run, mode, policy):
        if run['state'] not in {'completed', 'completed_with_errors'}:
            raise AssertionError('Pipeline did not finish: ' + run['state'])
        if set(run['images']) != {path.name for path in self.paths}:
            raise AssertionError('Pipeline image list differs from the requested fixtures.')
        if [[pair['filename0'], pair['filename1']] for pair in run['pairs']] != self.pairs:
            raise AssertionError('Pipeline pairs differ from the requested chronological pairs.')
        if any(item['state'] != 'completed' for item in run['images'].values()):
            raise AssertionError('One or more detection items failed; see saved run.')
        review = 0
        for pair in run['pairs']:
            if pair['state'] not in {'completed', 'review_required'} or not pair.get('result'):
                raise AssertionError('Tracking pair failed/skipped: ' + pair['id'])
            review += pair['state'] == 'review_required'
            result = pair['result']
            profile = result['run_profile']
            if profile['sampling_mode'] != mode or profile['exclusion_mask_policy'] != policy:
                raise AssertionError('Tracking profile does not match the chosen options.')
            if result['match_device'] != self.args.device:
                raise AssertionError('Tracking used a different device than requested.')
            masks = result['exclusion_masks']
            if masks['observation0_present'] or masks['observation1_present'] or masks['combined_pixels']:
                raise AssertionError('No-mask acceptance unexpectedly used an exclusion mask.')
            if mode == 'deterministic' and (result['tracking_matcher'].get('seed') is None
                    or not result['tracking_matcher'].get('seed_identity')):
                raise AssertionError('Seeded tracking omitted its seed or seed identity.')
        return review

    def export(self, run, tag, detection=False):
        selected = [[pair['filename0'], pair['filename1'], pair['result']['run_id']] for pair in run['pairs']]
        result = self.client.request('/compile_tracking_results', 'POST', {'file_pairs': selected})
        data = self.client.request('/images/' + urllib.parse.quote(result, safe=''), binary=True)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            manifest = json.loads(archive.read('tracking-results-manifest.json').decode('utf-8'))
            rows = list(csv.reader(io.StringIO(archive.read('statistics.csv').decode('utf-8'))))
            if len(rows) != len(selected) + 1 or len(manifest['statistics_rows']) != len(selected):
                raise AssertionError('Tracking export row count does not match selected pairs.')
        (self.output / (tag + '-tracking.zip')).write_bytes(data)
        if detection:
            with zipfile.ZipFile(str(self.output / (tag + '-detection.zip')), 'w', zipfile.ZIP_DEFLATED) as archive:
                for name, item in run['images'].items():
                    archive.writestr(name + '/statistics.json', json.dumps(item['result']['statistics']))
                    for kind in ('segmentation', 'skeleton'):
                        filename = item['result'][kind]
                        archive.writestr(name + '/' + filename, self.client.request('/images/' + urllib.parse.quote(filename, safe=''), binary=True))

    def pipeline(self, tag, mode='legacy', policy='first', detection_model=None):
        self.save(tag + '-settings.json', self.settings(mode, policy, detection_model))
        run = self.create_run('pipeline', {
            'filenames': [path.name for path in self.paths], 'file_pairs': self.pairs,
        })
        self.save(tag + '-created.json', run)
        result = self.poll('pipeline', run['id'], tag)
        review = self.verify_run(result, mode, policy)
        expected_model = detection_model or self.args.detection_model or self.original_settings['active_models']['detection']
        for pair in result['pairs']:
            output = pair['result']
            if (output['segmentation_model'] != expected_model
                    or output['run_profile']['models']['detection']['name'] != expected_model):
                raise AssertionError('Pipeline did not use the requested saved detection model.')
        self.export(result, tag, detection=tag.endswith('01'))
        self.diagnostics(tag)
        self.record(tag, 'passed_with_review_required' if review else 'passed', review_required_pairs=review)
        return result

    def cancellation(self):
        self.settings('legacy', 'first')
        run = self.create_run('pipeline', {
            'filenames': [path.name for path in self.paths], 'file_pairs': self.pairs,
        })
        self.active = ('pipeline', run['id'])
        current = self.client.request('/api/pipeline/runs/' + run['id'])
        if current['state'] in TERMINAL:
            self.active = None
            self.verify_run(current, 'legacy', 'first')
            self.record('cancellation', 'not_exercised', reason='Run finished before cancellation could be requested.')
            return
        self.save('cancel-request.json', self.client.request('/api/pipeline/runs/' + run['id'] + '/cancel', 'POST'))
        result = self.poll('pipeline', run['id'], 'cancel')
        if result['state'] != 'cancelled':
            self.verify_run(result, 'legacy', 'first')
            self.record('cancellation', 'not_exercised', reason='Completion won the cancellation race.', final_state=result['state'])
            return
        self.record('cancellation', 'passed')
        self.active = ('pipeline', run['id'])
        self.client.request('/api/pipeline/runs/' + run['id'] + '/retry', 'POST')
        retried = self.poll('pipeline', run['id'], 'cancel-retry')
        review = self.verify_run(retried, 'legacy', 'first')
        self.export(retried, 'cancel-retry')
        self.record('cancel-retry', 'passed_with_review_required' if review else 'passed')

    def create_run(self, kind, payload):
        # A lost creation response does not prove the server rejected the job.
        # Training alone supports idempotent resubmission with a request identity.
        self.unconfirmed_submission = kind
        try:
            run = self.client.request('/api/{}/runs'.format(kind), 'POST', payload)
        except (urllib.error.URLError, socket.timeout, TimeoutError):
            if kind != 'training':
                raise
            run = self.client.request('/api/training/runs', 'POST', payload)
        self.active = (kind, run['id'])
        self.unconfirmed_submission = None
        return run

    def training(self):
        image, label = Path(self.args.training_image), Path(self.args.training_label)
        self.settings('legacy', 'first')
        self.client.upload(image)
        label_name = 'acceptance-reviewed-label-' + uuid.uuid4().hex + '.png'
        self.client.upload(label, label_name)
        options = {'training_type': 'detection', 'epochs': 1, 'learning_rate': 0.0001}
        payload = {'request_id': uuid.uuid4().hex, 'filenames': [image.name],
                   'label_filenames': [label_name], 'options': options,
                   'label_review': {'source': 'user_reviewed', 'confirmed': True}}
        run = self.create_run('training', payload)
        self.save('training-created.json', run)
        result = self.poll('training', run['id'], 'training')
        if result['state'] != 'completed':
            raise AssertionError('Training smoke did not complete; see saved result.')
        model = 'acceptance-smoke-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
        saved = self.client.request('/save_model', 'POST', {'newname': model, 'options': options})
        self.save('training-save.json', saved)
        if saved.get('saved') != model or saved.get('model_type') != 'detection':
            raise AssertionError('Training save did not confirm the requested model name/type.')
        # Switch away, then reload the saved package rather than only using its in-memory weights.
        self.settings('legacy', 'first')
        self.pipeline('trained-model-01', detection_model=model)
        self.summary['saved_smoke_model'] = model
        self.record('training-save-reload-detect', 'passed', meaning='One-epoch plumbing smoke only; not model quality or scientific validity.')

    def cleanup(self):
        if self.unconfirmed_submission:
            self.record('submission-state', 'unconfirmed', job_kind=self.unconfirmed_submission,
                        reason='Creation response was not confirmed. Inspect the dedicated app before further use; settings are not restored.')
        if self.active:
            kind, run_id = self.active
            try:
                self.client.request('/api/{}/runs/{}/cancel'.format(kind, run_id), 'POST')
                old_timeout = self.args.run_timeout
                self.args.run_timeout = min(60, old_timeout)
                try:
                    self.poll(kind, run_id, 'cleanup-cancel')
                finally:
                    self.args.run_timeout = old_timeout
            except Exception as exc:
                self.record('cleanup-cancellation', 'unconfirmed', error=str(exc))
        if self.settings_changed and self.original_settings is not None and self.active is None and not self.unconfirmed_submission:
            try:
                self.client.request('/settings', 'POST', self.original_settings)
                self.record('restore-settings', 'passed')
            except Exception as exc:
                self.record('restore-settings', 'failed', error=str(exc))
        try:
            self.diagnostics('final')
        except Exception as exc:
            self.record('final-diagnostics', 'failed', error=str(exc))

    def run(self):
        try:
            session = self.client.request('/api/session')
            self.client.token = session['token']
            self.save('session.json', session)
            settings = self.client.request('/settings')
            self.original_settings = copy.deepcopy(settings['settings'])
            if any(not name for name in self.original_settings['active_models'].values()):
                raise ValueError('The dedicated instance contains unsaved/unselected models; select saved models first.')
            self.save('original-settings.json', settings)
            build = self.diagnostics('initial')
            self.check_build(build)
            if self.args.device == 'cuda' and not settings.get('available_gpu'):
                raise ValueError('CUDA was requested but the application reports no available GPU.')
            self.save('sources.json', [{'path': str(path.resolve()), 'name': path.name,
                       'bytes': path.stat().st_size, 'sha256': digest_file(path)} for path in self.paths])
            self.save('pairs.json', self.pairs)
            if self.args.training_image:
                self.save('training-sources.json', [{'path': str(Path(path).resolve()), 'sha256': digest_file(path)}
                          for path in [self.args.training_image, self.args.training_label]])
            maximum = session.get('limits', {}).get('max_upload_bytes')
            if maximum and any(path.stat().st_size > maximum for path in self.paths):
                raise ValueError('A fixture exceeds the configured upload limit.')
            self.client.request('/clear_cache', 'POST')
            for index, path in enumerate(self.paths):
                self.save('uploads/{:02d}.json'.format(index), self.client.upload(path))
            if 'repeats' in self.args.cases:
                for mode in ('legacy', 'deterministic'):
                    fingerprints = []
                    for repeat in range(1, self.args.repeats + 1):
                        result = self.pipeline('{}-{:02d}'.format(mode, repeat), mode)
                        fingerprint = comparison_record(result)
                        self.save('{}-{:02d}-comparison.json'.format(mode, repeat), fingerprint)
                        if mode == 'deterministic' and fingerprints and fingerprint != fingerprints[0]:
                            raise AssertionError('Seeded points, seed identities, device, or statistics changed on repeat {}.'.format(repeat))
                        fingerprints.append(fingerprint)
                    self.save(mode + '-repeat-comparison.json', fingerprints)
                    distinct = len({json.dumps(item, sort_keys=True) for item in fingerprints})
                    self.record(mode + '-repeatability', 'passed' if self.args.repeats > 1 else 'not_exercised',
                                repeats=self.args.repeats, distinct_outputs=distinct,
                                interpretation='Original variation is descriptive; seeded outputs must match exactly on the same device.')
            if 'matrix' in self.args.cases:
                for mode in ('legacy', 'deterministic'):
                    for policy in ('first', 'second', 'union', 'intersection'):
                        self.pipeline('matrix-{}-{}'.format(mode, policy), mode, policy)
            if 'cancel' in self.args.cases:
                self.cancellation()
            if 'training' in self.args.cases:
                self.training()
            self.summary['status'] = 'software_cases_passed'
        except (Exception, KeyboardInterrupt) as exc:
            self.summary['status'] = 'failed'
            self.record('runner', 'timeout' if isinstance(exc, TimeoutError) else 'failed',
                        error_type=type(exc).__name__, error=str(exc))
        finally:
            self.cleanup()
            if any(item['status'] in {'failed', 'unconfirmed', 'timeout'} for item in self.summary['cases']):
                self.summary['status'] = 'failed'
            self.summary['finished_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
            self.save('summary.json', self.summary)
        return 0 if self.summary['status'] == 'software_cases_passed' else 1


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:5000')
    parser.add_argument('--images', nargs='+', required=True)
    parser.add_argument('--output', required=True, help='New evidence directory; must not exist.')
    parser.add_argument('--allow-clear', action='store_true', help='Confirm this dedicated app cache may be cleared.')
    parser.add_argument('--device', choices=('cpu', 'cuda'), required=True)
    parser.add_argument('--repeats', type=int, default=10)
    parser.add_argument('--cases', nargs='+', choices=('repeats', 'matrix', 'cancel', 'training'), default=['repeats', 'matrix', 'cancel'])
    parser.add_argument('--detection-model')
    parser.add_argument('--build-info', help='Optional exact package BUILD-INFO.txt path on this machine.')
    parser.add_argument('--expected-commit', help='Expected package Git commit, checked against BUILD-INFO.')
    parser.add_argument('--run-timeout', type=float, default=3600)
    parser.add_argument('--http-timeout', type=float, default=120)
    parser.add_argument('--poll-interval', type=float, default=2)
    parser.add_argument('--training-image')
    parser.add_argument('--training-label')
    parser.add_argument('--confirm-reviewed-label', action='store_true')
    args = parser.parse_args(argv)
    if not args.allow_clear:
        parser.error('--allow-clear is required; use a dedicated package instance and copied data.')
    if args.repeats < 1 or min(args.run_timeout, args.http_timeout, args.poll_interval) <= 0:
        parser.error('Repeat count and timeout/interval values must be positive.')
    if 'training' in args.cases and not (args.training_image and args.training_label and args.confirm_reviewed_label):
        parser.error('Training needs --training-image, --training-label, and --confirm-reviewed-label.')
    if bool(args.training_image) != bool(args.training_label):
        parser.error('Supply both training image and label.')
    if args.expected_commit and not re.fullmatch(r'[0-9a-fA-F]{7,40}', args.expected_commit):
        parser.error('--expected-commit must be a hexadecimal Git commit.')
    paths = [Path(path) for path in args.images]
    if len(paths) < 2 or any(not path.is_file() for path in paths):
        parser.error('Provide at least two existing image files.')
    if any(path.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.tif', '.tiff'} for path in paths):
        parser.error('Provide original PNG, JPEG, or TIFF image files.')
    if len({path.name.casefold() for path in paths}) != len(paths):
        parser.error('Source filenames must be unique, ignoring case.')
    for name in ('training_image', 'training_label', 'build_info'):
        value = getattr(args, name)
        if value and not Path(value).is_file():
            parser.error('{} must reference an existing file.'.format(name))
    loopback_url(args.url)
    return args, paths, chronological_pairs(paths)


if __name__ == '__main__':
    try:
        arguments, image_paths, image_pairs = parse_args()
        sys.exit(Acceptance(arguments, image_paths, image_pairs).run())
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
