import json
import os

import numpy as np
import PIL.Image

from backend import root_detection
from backend import root_tracking


class FakeSettings:
    use_gpu = False
    active_models = {'detection': 'model-a'}


def test_soft_segmentation_cache_reuse_and_invalidation(tmp_path, monkeypatch):
    image_path = str(tmp_path / 'input.png')
    PIL.Image.fromarray(np.zeros([8, 8, 3], dtype='uint8')).save(image_path)
    calls = []

    def run_model(path, settings, modeltype, **kwargs):
        calls.append((path, settings.active_models[modeltype], kwargs))
        return np.full([8, 8], 0.75, dtype='float32')

    monkeypatch.setattr(root_detection, 'run_model', run_model)
    settings = FakeSettings()

    preview, first = root_detection.ensure_soft_segmentation(image_path, settings)
    tracking_preview, second = root_tracking.ensure_segmentation(image_path, settings)
    assert preview == tracking_preview
    assert len(calls) == 1
    assert np.array_equal(first, second)

    paths = root_detection.segmentation_cache_paths(image_path)
    assert all(os.path.exists(path) for path in paths.values())
    with open(paths['manifest']) as source:
        manifest = json.load(source)
    assert manifest['schema'] == root_detection.SEGMENTATION_CACHE_SCHEMA
    assert manifest['model']['name'] == 'model-a'
    assert manifest['operation']['storage_dtype'] == 'float32'
    assert manifest['artifact'] == {'shape': [8, 8], 'dtype': 'float32'}

    settings.active_models['detection'] = 'model-b'
    root_detection.ensure_soft_segmentation(image_path, settings)
    assert len(calls) == 2

    PIL.Image.fromarray(np.ones([8, 8, 3], dtype='uint8')).save(image_path)
    root_detection.ensure_soft_segmentation(image_path, settings)
    assert len(calls) == 3
