import threading
import pytest

from backend import training
from backend import training_jobs


class Settings:
    models = {}


def options():
    return {'training_type': 'detection', 'epochs': 2, 'lr': 0.001}


def test_training_job_reports_progress_and_completion():
    def train(_images, _targets, _options, _settings, callback, cancel_event):
        assert not cancel_event.is_set()
        callback(0.25)
        callback(1.0)
        return training.TrainingResult('completed')

    results = {}
    manager = training_jobs.TrainingManager(
        Settings(),
        result_sink=results,
        training_func=train,
    )
    run = manager.create(['image.png'], ['target.png'], options())
    assert run.wait(2)
    snapshot = run.snapshot()
    assert snapshot['state'] == 'completed'
    assert snapshot['progress'] == 1.0
    assert snapshot['attempts'] == 1
    assert results['detection'].completed


def test_training_job_cancels_cooperatively():
    started = threading.Event()

    def train(_images, _targets, _options, _settings, callback, cancel_event):
        callback(0.1)
        started.set()
        assert cancel_event.wait(2)
        return training.TrainingResult('cancelled', 'Training cancellation was requested.')

    manager = training_jobs.TrainingManager(Settings(), training_func=train)
    run = manager.create(['image.png'], ['target.png'], options())
    assert started.wait(1)
    run.request_cancel()
    assert run.wait(2)
    assert run.snapshot()['state'] == 'cancelled'


def test_training_job_failure_has_diagnostic_id():
    def train(*_args, **_kwargs):
        return training.TrainingResult('failed', 'bad model', 'RuntimeError')

    manager = training_jobs.TrainingManager(Settings(), training_func=train)
    run = manager.create(['image.png'], ['target.png'], options())
    assert run.wait(2)
    error = run.snapshot()['error']
    assert error['code'] == 'training_failed'
    assert error['message'] == 'bad model'
    assert len(error['diagnostic_id']) == 12


def test_training_request_identity_recovers_active_and_finished_run_without_retraining():
    started, finish = threading.Event(), threading.Event()
    calls = []

    def train(*_args, **_kwargs):
        calls.append(1)
        started.set()
        assert finish.wait(2)
        return training.TrainingResult('completed')

    manager = training_jobs.TrainingManager(Settings(), training_func=train)
    request_id = 'a' * 32
    first = manager.create(['image.png'], ['target.png'], options(), request_id=request_id)
    try:
        assert started.wait(1)
        assert manager.create(['image.png'], ['target.png'], options(), request_id=request_id) is first
        with pytest.raises(RuntimeError, match='different inputs'):
            manager.create(['different.png'], ['target.png'], options(), request_id=request_id)
    finally:
        finish.set()
    assert first.wait(2)
    assert manager.create(['image.png'], ['target.png'], options(), request_id=request_id) is first
    assert len(calls) == 1


def test_expired_training_request_cannot_silently_start_again():
    manager = training_jobs.TrainingManager(
        Settings(), training_func=lambda *_args, **_kwargs: training.TrainingResult('completed'), max_runs=1,
    )
    first = manager.create(['image.png'], ['target.png'], options(), request_id='a' * 32)
    assert first.wait(2)
    second = manager.create(['image.png'], ['target.png'], options(), request_id='b' * 32)
    assert second.wait(2)
    with pytest.raises(RuntimeError, match='already handled'):
        manager.create(['image.png'], ['target.png'], options(), request_id='a' * 32)


@pytest.mark.parametrize('request_id', [1, '', 'not-an-id', 'A' * 32])
def test_training_rejects_invalid_request_identity(request_id):
    manager = training_jobs.TrainingManager(Settings())
    with pytest.raises(RuntimeError, match='Invalid training request identity'):
        manager.create(['image.png'], ['target.png'], options(), request_id=request_id)
