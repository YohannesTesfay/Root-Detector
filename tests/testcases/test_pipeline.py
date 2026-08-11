import os

import numpy as np
import pytest

from backend.pipeline import PipelineManager
from backend import root_tracking


class FakeSettings:
    mode = 'initial'
    active_models = {
        'detection': 'fake-detection',
        'tracking': 'fake-tracking',
    }


def detection_result(path):
    basename = os.path.basename(path)
    return {
        'segmentation': basename + '.segmentation.png',
        'skeleton': basename + '.skeleton.png',
        'statistics': {'sum': 1},
    }


def tracking_result(path0, path1, _settings):
    output = path0 + '.' + os.path.basename(path1)
    return {
        'points0': np.asarray([[1, 2], [3, 4]]),
        'points1': np.asarray([[2, 3], [4, 5]]),
        'growthmap': output + '.growthmap.png',
        'growthmap_rgba': output + '.growthmap_rgba.png',
        'segmentation0': path0 + '.segmentation.cache.png',
        'segmentation1': path1 + '.segmentation.cache.png',
        'success': True,
        'n_matched_points': 2,
        'tracking_model': 'fake-tracking',
        'segmentation_model': 'fake-detection',
        'statistics': {'sum_same': 1},
    }


def create_inputs(folder, filenames):
    for filename in filenames:
        with open(os.path.join(folder, filename), 'wb') as output:
            output.write(filename.encode('utf-8'))


def test_pipeline_continues_after_detection_failure(tmp_path):
    filenames = ['good-a.png', 'bad.png', 'good-b.png']
    create_inputs(str(tmp_path), filenames)
    detected = []
    tracked = []

    def detect(path, _settings):
        detected.append(os.path.basename(path))
        if path.endswith('bad.png'):
            raise ValueError('corrupt image')
        return detection_result(path)

    def track(path0, path1, settings):
        tracked.append((os.path.basename(path0), os.path.basename(path1)))
        return tracking_result(path0, path1, settings)

    manager = PipelineManager(
        FakeSettings(),
        cache_path=str(tmp_path),
        detection_func=detect,
        tracking_func=track,
    )
    run = manager.create(filenames, [
        ['good-a.png', 'bad.png'],
        ['good-a.png', 'good-b.png'],
    ])
    assert run.wait(5)

    result = run.snapshot()
    assert detected == filenames
    assert tracked == [('good-a.png', 'good-b.png')]
    assert result['state'] == 'completed_with_errors'
    assert result['images']['bad.png']['state'] == 'failed'
    assert result['images']['good-b.png']['state'] == 'completed'
    assert result['pairs'][0]['state'] == 'skipped'
    assert result['pairs'][0]['error']['code'] == 'dependency_failed'
    assert result['pairs'][1]['state'] == 'completed'
    assert result['progress'] == {'finished': 5, 'total': 5, 'fraction': 1.0}


def test_pipeline_retries_only_failed_items(tmp_path):
    filename = 'retry.png'
    create_inputs(str(tmp_path), [filename])
    attempts = []

    def detect(path, _settings):
        attempts.append(path)
        if len(attempts) == 1:
            raise RuntimeError('temporary failure')
        return detection_result(path)

    manager = PipelineManager(
        FakeSettings(),
        cache_path=str(tmp_path),
        detection_func=detect,
        tracking_func=tracking_result,
    )
    run = manager.create([filename], [])
    assert run.wait(5)
    assert run.snapshot()['images'][filename]['state'] == 'failed'

    run.retry_failed()
    assert run.wait(5)
    result = run.snapshot()
    assert len(attempts) == 2
    assert result['state'] == 'completed'
    assert result['images'][filename]['state'] == 'completed'


def test_pipeline_rejects_missing_and_duplicate_inputs(tmp_path):
    manager = PipelineManager(FakeSettings(), cache_path=str(tmp_path))
    with pytest.raises(ValueError, match='missing'):
        manager.create(['missing.png'], [])

    create_inputs(str(tmp_path), ['same.png'])
    with pytest.raises(ValueError, match='unique'):
        manager.create(['same.png', 'same.png'], [])

    create_inputs(str(tmp_path), ['notes.txt'])
    with pytest.raises(ValueError, match='Unsupported input format'):
        manager.create(['notes.txt'], [])


def test_pipeline_snapshots_settings_for_the_run(tmp_path):
    filename = 'settings.png'
    create_inputs(str(tmp_path), [filename])
    started = __import__('threading').Event()
    release = __import__('threading').Event()
    observed = []
    settings = FakeSettings()
    settings.mode = 'initial'

    def detect(path, run_settings):
        started.set()
        release.wait(5)
        observed.append(run_settings.mode)
        return detection_result(path)

    manager = PipelineManager(
        settings,
        cache_path=str(tmp_path),
        detection_func=detect,
        tracking_func=tracking_result,
    )
    run = manager.create([filename], [])
    assert started.wait(2)
    settings.mode = 'changed'
    release.set()
    assert run.wait(5)
    assert observed == ['initial']


def test_pipeline_cancel_marks_queued_work(tmp_path):
    filenames = ['first.png', 'second.png']
    create_inputs(str(tmp_path), filenames)

    started = __import__('threading').Event()
    release = __import__('threading').Event()

    def detect(path, _settings):
        started.set()
        release.wait(5)
        return detection_result(path)

    manager = PipelineManager(
        FakeSettings(),
        cache_path=str(tmp_path),
        detection_func=detect,
        tracking_func=tracking_result,
    )
    run = manager.create(filenames, [])
    assert started.wait(2)
    run.request_cancel()
    release.set()
    assert run.wait(5)

    result = run.snapshot()
    assert result['state'] == 'cancelled'
    assert result['images']['first.png']['state'] == 'completed'
    assert result['images']['second.png']['state'] == 'cancelled'


def test_pipeline_reports_too_many_roots_as_skipped(tmp_path):
    filenames = ['first.png', 'second.png']
    create_inputs(str(tmp_path), filenames)

    manager = PipelineManager(
        FakeSettings(),
        cache_path=str(tmp_path),
        detection_func=lambda path, settings: detection_result(path),
        tracking_func=lambda path0, path1, settings: root_tracking.TOO_MANY_ROOTS_ERROR,
    )
    run = manager.create(filenames, [filenames])
    assert run.wait(5)

    result = run.snapshot()
    assert result['state'] == 'completed_with_errors'
    assert result['pairs'][0]['state'] == 'skipped'
    assert result['pairs'][0]['error']['code'] == 'too_many_roots'
