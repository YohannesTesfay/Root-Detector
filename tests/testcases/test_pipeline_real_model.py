import os
import shutil
import zipfile

import pytest

from backend.pipeline import PipelineManager
from backend import root_tracking
from backend.settings import Settings
from base.backend.app import get_cache_path, setup_cache


@pytest.mark.real_model
def test_released_models_complete_detection_and_tracking_pipeline():
    filenames = [
        'PD_T088_L004_17.10.18_140056_014_SS_crop.tiff',
        'PD_T088_L004_13.11.18_091057_015_SS_crop.tiff',
    ]
    setup_cache(get_cache_path())
    for filename in filenames:
        shutil.copy(
            os.path.join('tests', 'testcases', 'assets', filename),
            get_cache_path(filename),
        )

    settings = Settings()
    manager = PipelineManager(settings, cache_path=get_cache_path())
    run = manager.create(filenames, [filenames])
    assert run.wait(180), 'real-model pipeline timed out'

    result = run.snapshot()
    assert result['state'] == 'completed'
    assert all(item['state'] == 'completed' for item in result['images'].values())
    assert result['pairs'][0]['state'] == 'completed'
    assert result['pairs'][0]['result']['success'] is True
    assert result['pairs'][0]['result']['n_matched_points'] >= 16
    for item in result['images'].values():
        assert os.path.exists(get_cache_path(item['result']['segmentation']))
        assert os.path.exists(get_cache_path(item['result']['skeleton']))

    archive_name = root_tracking.compile_results_into_zip([filenames])
    archive_path = get_cache_path(archive_name)
    assert os.path.exists(archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        assert 'statistics.csv' in names
        assert any(name.endswith('.growthmap.png') for name in names)
        assert any(name.endswith('.json') for name in names)
