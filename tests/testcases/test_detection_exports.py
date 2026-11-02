"""Regression coverage for retryable, disk-backed detection downloads."""

import io
import json
import os
import time
import zipfile

import PIL.Image
import pytest

from backend import detection_exports, security
from backend.app import App


def _png():
    output = io.BytesIO()
    PIL.Image.new('RGB', (8, 8), (255, 0, 0)).save(output, format='PNG')
    return output.getvalue()


def _source(cache_path, filename):
    for suffix in ('.segmentation.png', '.skeleton.png'):
        with open(os.path.join(cache_path, filename + suffix), 'wb') as output:
            output.write(_png())
    return {'filename': filename, 'csv_row': filename + ', 1, 2, 3, 4, 5, 6, 7, 8;\n'}


def _await(manager, export_id):
    for _ in range(200):
        status = manager.status(export_id)
        if status['state'] != 'preparing' and not manager.active():
            return status
        time.sleep(0.025)
    pytest.fail('Archive did not finish within five seconds')


def test_export_survives_restart_and_preserves_csv_and_images(tmp_path):
    cache = tmp_path / 'cache'
    exports = tmp_path / 'exports'
    cache.mkdir()
    files = [_source(str(cache), 'one.tiff'), _source(str(cache), 'two.tiff')]
    manager = detection_exports.DetectionExportManager(str(cache), str(exports))
    started = manager.start({'files': files})
    assert _await(manager, started['id'])['state'] == 'ready'
    assert manager.start({'files': files})['id'] == started['id']
    path = manager.archive_path(started['id'])
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        assert archive.read('one.tiff/one.tiff.segmentation.png') == _png()
        assert archive.read('two.tiff/two.tiff.skeleton.png') == _png()
        assert archive.read('one.tiff/statistics.csv').decode() == (
            detection_exports.CSV_HEADER + files[0]['csv_row']
        )
        assert archive.read('statistics.csv').decode() == (
            detection_exports.CSV_HEADER + files[0]['csv_row'] + files[1]['csv_row']
        )
        manifest = json.loads(archive.read('detection-results-manifest.json'))
        assert manifest['processed_image_count'] == 2
    restarted = detection_exports.DetectionExportManager(str(cache), str(exports))
    assert restarted.status(started['id'])['state'] == 'ready'
    assert restarted.recent()[0]['id'] == started['id']


def test_export_rejects_missing_duplicate_and_unsafe_inputs(tmp_path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    manager = detection_exports.DetectionExportManager(str(cache), str(tmp_path / 'exports'))
    good = _source(str(cache), 'one.tiff')
    with pytest.raises(security.ValidationError):
        manager.start({'files': [good, good]})
    with pytest.raises(security.ValidationError):
        manager.start({'files': [{**good, 'filename': '../one.tiff'}]})
    os.remove(str(cache / 'one.tiff.skeleton.png'))
    with pytest.raises(security.ValidationError):
        manager.start({'files': [good]})
    assert not list((tmp_path / 'exports').glob('*.zip'))


def test_failure_keeps_source_and_removes_partial_archive(tmp_path, monkeypatch):
    cache = tmp_path / 'cache'
    exports = tmp_path / 'exports'
    cache.mkdir()
    item = _source(str(cache), 'one.tiff')
    manager = detection_exports.DetectionExportManager(str(cache), str(exports))
    def fail_write(*_args, **_kwargs):
        raise OSError('simulated full disk')
    monkeypatch.setattr(detection_exports.zipfile.ZipFile, 'write', fail_write)
    status = _await(manager, manager.start({'files': [item]})['id'])
    assert status['state'] == 'failed'
    assert 'disk space' in status['error']
    assert not list(exports.iterdir())
    assert (cache / 'one.tiff.segmentation.png').exists()


def test_prepared_sidecars_are_preserved_in_archive(tmp_path, monkeypatch):
    cache = tmp_path / 'cache'
    cache.mkdir()
    item = _source(str(cache), 'one.tiff')
    (cache / 'one.tiff').write_bytes(b'prepared image fixture')
    (cache / 'mask.png').write_bytes(_png())
    manifest = {'preparation_id': 'crop-one', 'output_name': 'one.tiff'}
    companion = {'output_name': 'mask.png', 'kind': 'training_annotation'}
    item.update(preparation=manifest, companions=[companion])
    monkeypatch.setattr(detection_exports.preparation, 'validate_manifest_for_output',
                        lambda *_args: None)
    monkeypatch.setattr(detection_exports.preparation, 'validate_companion_provenance',
                        lambda *_args: None)
    manager = detection_exports.DetectionExportManager(str(cache), str(tmp_path / 'exports'))
    export_id = manager.start({'files': [item]})['id']
    assert _await(manager, export_id)['state'] == 'ready'
    with zipfile.ZipFile(manager.archive_path(export_id)) as archive:
        assert json.loads(archive.read('preparation-manifest.json'))['preparations'] == [manifest]
        assert json.loads(archive.read('preparation-companions.json'))['companions'] == [companion]
        assert archive.read('one.tiff/preparation-companions/mask.png') == _png()
        assert archive.read('preparation-companions/mask.png') == _png()


class FakeSettings:
    active_models = {'detection': 'fake-detection', 'tracking': 'fake-tracking'}
    models = {}
    use_gpu = False
    exmask_enabled = False
    too_many_roots = 100000

    def get_settings_as_dict(self):
        return {'settings': {}, 'available_models': {}}


def test_api_download_has_stable_name_length_and_range(tmp_path, monkeypatch):
    monkeypatch.setenv('ROOT_PATH', os.getcwd())
    monkeypatch.setenv('INSTANCE_PATH', str(tmp_path))
    monkeypatch.setenv('DO_NOT_RELOAD', '1')
    monkeypatch.setattr('backend.settings.ensure_pretrained_models', lambda: None)
    monkeypatch.setattr('backend.settings.Settings', FakeSettings)
    app = App()
    app.testing = True
    item = _source(app.cache_path, 'one.tiff')
    client = app.test_client()
    page = client.get('/', headers={'Host': 'localhost'})
    assert page.status_code == 200
    assert page.data.count(b'id="detection-export-retry"') == 1
    assert page.data.count(b'id="detection-export-notice"') == 1
    headers = {'Host': 'localhost', 'Origin': 'http://localhost',
               'X-RootDetector-Token': app.session_token}
    started = client.post('/api/exports/detection', json={'files': [item]}, headers=headers)
    assert started.status_code in (200, 202)
    export_id = started.get_json()['id']
    assert _await(app.detection_exports, export_id)['state'] == 'ready'
    url = '/api/exports/detection/{}/download'.format(export_id)
    first = client.get(url, headers={'Host': 'localhost'})
    assert first.status_code == 200
    assert first.headers['Content-Length'] == str(len(first.data))
    assert 'RootDetector-detection-results.zip' in first.headers['Content-Disposition']
    assert zipfile.ZipFile(io.BytesIO(first.data)).testzip() is None
    assert app.detection_exports.transferring()
    first.close()
    repeated = client.get(url, headers={'Host': 'localhost', 'Range': 'bytes=0-15'})
    assert repeated.status_code == 206
    assert repeated.data == first.data[:16]
    repeated.close()
    assert not app.detection_exports.transferring()
    cleared = client.post('/clear_cache', headers=headers)
    assert cleared.status_code == 200
    preserved = client.get(url, headers={'Host': 'localhost'})
    assert preserved.status_code == 200
    assert preserved.data == first.data
    preserved.close()
    assert client.get('/api/exports/detection', headers={'Host': 'localhost'}).get_json()['exports'][0]['id'] == export_id
    invalid = client.get('/api/exports/detection/not-an-id/download', headers={'Host': 'localhost'})
    assert invalid.status_code == 400
