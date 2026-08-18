import math
import os

import pytest

from backend import training
from backend.app import App


@pytest.mark.parametrize('key', ['learning_rate', 'lr'])
def test_training_accepts_public_and_legacy_learning_rate_names(key):
    options = training.parse_training_options({
        'training_type': 'detection',
        'epochs': 3,
        key: 0.0002,
    })

    assert options['learning_rate'] == pytest.approx(0.0002)
    assert options['lr'] == pytest.approx(0.0002)


def test_public_and_legacy_learning_rate_must_not_conflict():
    with pytest.raises(training.TrainingOptionsError, match='must match'):
        training.parse_training_options({
            'training_type': 'detection',
            'epochs': 3,
            'learning_rate': 0.0002,
            'lr': 0.001,
        })


@pytest.mark.parametrize('value', [None, 0, -0.1, 2, math.nan, math.inf, 'invalid'])
def test_training_rejects_missing_or_invalid_learning_rate(value):
    options = {'training_type': 'detection', 'epochs': 3}
    if value is not None:
        options['learning_rate'] = value

    with pytest.raises(training.TrainingOptionsError):
        training.parse_training_options(options)


def test_training_forwards_learning_rate_to_model():
    class Model:
        def __init__(self):
            self.kwargs = None

        def start_training(self, _images, _targets, **kwargs):
            self.kwargs = kwargs
            return True

        def cpu(self):
            return self

    class Settings:
        use_gpu = False
        active_models = {'detection': 'test-model'}
        models = {'detection': Model()}

    settings = Settings()
    result = training.start_training(
        ['image.tiff'],
        ['image.segmentation.png'],
        {
            'training_type': 'detection',
            'epochs': 2,
            'learning_rate': 0.0003,
        },
        settings,
    )

    assert result == 'OK'
    assert settings.models['detection'].kwargs['lr'] == pytest.approx(0.0003)


@pytest.mark.parametrize('key', ['learning_rate', 'lr'])
def test_training_api_reports_the_effective_learning_rate(key, tmp_path, monkeypatch):
    class Settings:
        active_models = {'detection': 'test-model'}
        models = {}
        use_gpu = False
        exmask_enabled = False
        too_many_roots = 100000

        def get_settings_as_dict(self):
            return {'settings': {}, 'available_models': {}}

    monkeypatch.setenv('ROOT_PATH', os.getcwd())
    monkeypatch.setenv('INSTANCE_PATH', str(tmp_path))
    monkeypatch.setenv('DO_NOT_RELOAD', '1')
    monkeypatch.setattr('backend.settings.ensure_pretrained_models', lambda: None)
    monkeypatch.setattr('backend.settings.Settings', Settings)
    captured = {}

    def start_training(_images, _targets, options, _settings):
        captured.update(options)
        return 'OK'

    monkeypatch.setattr(training, 'start_training', start_training)
    app = App()
    app.testing = True
    image = os.path.join(app.cache_path, 'image.png')
    target = image + '.segmentation.png'
    os.makedirs(app.cache_path, exist_ok=True)
    open(image, 'wb').close()
    open(target, 'wb').close()

    response = app.test_client().post('/training', json={
        'filenames': ['image.png'],
        'options': {
            'training_type': 'detection',
            'epochs': 2,
            key: 0.0004,
        },
    })

    assert response.status_code == 200
    assert response.get_json()['effective_options']['learning_rate'] == pytest.approx(0.0004)
    assert captured['learning_rate'] == pytest.approx(0.0004)
    assert captured['lr'] == pytest.approx(0.0004)
