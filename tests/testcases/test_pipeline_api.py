import os
import threading

from backend.app import App


class FakeSettings:
    active_models = {'detection': 'fake-detection', 'tracking': 'fake-tracking'}
    models = {}
    use_gpu = False
    exmask_enabled = False
    too_many_roots = 100000

    def get_settings_as_dict(self):
        return {'settings': {}, 'available_models': {}}


def detection_result(path):
    basename = os.path.basename(path)
    return {
        'segmentation': basename + '.segmentation.png',
        'skeleton': basename + '.skeleton.png',
        'statistics': {'sum': 1},
    }


def test_pipeline_api_reports_validation_busy_completion_and_missing_run(tmp_path, monkeypatch):
    monkeypatch.setenv('ROOT_PATH', os.getcwd())
    monkeypatch.setenv('INSTANCE_PATH', str(tmp_path))
    monkeypatch.setenv('DO_NOT_RELOAD', '1')
    monkeypatch.setattr('backend.settings.ensure_pretrained_models', lambda: None)
    monkeypatch.setattr('backend.settings.Settings', FakeSettings)

    app = App()
    app.testing = True
    started = threading.Event()
    release = threading.Event()

    def detect(path, _settings):
        started.set()
        release.wait(5)
        return detection_result(path)

    app.pipeline_manager.detection_func = detect
    filename = 'input.png'
    with open(os.path.join(app.cache_path, filename), 'wb') as output:
        output.write(b'fixture')

    client = app.test_client()
    invalid = client.post('/api/pipeline/runs', json={'filenames': ['../input.png']})
    assert invalid.status_code == 400
    assert invalid.get_json()['code'] == 'invalid_pipeline_request'

    wrong_shape = client.post('/api/pipeline/runs', json={'filenames': filename})
    assert wrong_shape.status_code == 400
    assert wrong_shape.get_json()['code'] == 'invalid_pipeline_request'

    created = client.post('/api/pipeline/runs', json={'filenames': [filename], 'file_pairs': []})
    assert created.status_code == 202
    run_id = created.get_json()['id']
    assert started.wait(2)

    busy = client.post('/api/pipeline/runs', json={'filenames': [filename], 'file_pairs': []})
    assert busy.status_code == 409
    assert busy.get_json()['code'] == 'pipeline_busy'

    release.set()
    assert app.pipeline_manager.get(run_id).wait(5)
    completed = client.get('/api/pipeline/runs/' + run_id)
    assert completed.status_code == 200
    assert completed.get_json()['state'] == 'completed'

    missing = client.get('/api/pipeline/runs/not-a-run')
    assert missing.status_code == 404
    assert missing.get_json()['code'] == 'pipeline_not_found'
