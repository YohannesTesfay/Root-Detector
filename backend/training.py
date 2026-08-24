from contextlib import contextmanager
from dataclasses import dataclass
import math
import os, sys
import threading
import typing as tp

import torch

from base.backend import GLOBALS
from base.backend import pubsub
from base.backend.app import get_cache_path


TRAINING_STATES = {'completed', 'cancelled', 'failed'}
_cancel_requested = threading.Event()


class TrainingOptionsError(ValueError):
    """Raised when browser or CLI training options are invalid or ambiguous."""


@dataclass(frozen=True)
class TrainingResult:
    """Terminal state returned by both current and released training models."""

    state: str
    message: str = ''
    error_type: tp.Optional[str] = None

    @property
    def completed(self):
        return self.state == 'completed'

    def to_dict(self):
        result = {'state': self.state, 'message': self.message}
        if self.error_type:
            result['error_type'] = self.error_type
        return result


def parse_training_options(training_options:dict) -> dict:
    """Normalize the public learning-rate name and the legacy ``lr`` alias."""
    if not isinstance(training_options, dict):
        raise TrainingOptionsError('Training options must be an object.')

    training_type = training_options.get('training_type')
    if training_type not in ['detection', 'exclusion_mask']:
        raise TrainingOptionsError('Invalid training type.')

    learning_rate = training_options.get('learning_rate')
    legacy_learning_rate = training_options.get('lr')
    if learning_rate is None:
        learning_rate = legacy_learning_rate
    elif legacy_learning_rate is not None:
        try:
            values_match = float(learning_rate) == float(legacy_learning_rate)
        except (TypeError, ValueError):
            values_match = False
        if not values_match:
            raise TrainingOptionsError(
                'learning_rate and lr must match when both are supplied.'
            )
    if learning_rate is None:
        raise TrainingOptionsError('Missing learning_rate (legacy name: lr).')

    try:
        learning_rate = float(learning_rate)
    except (TypeError, ValueError):
        raise TrainingOptionsError('Learning rate must be a number.')
    if not math.isfinite(learning_rate) or learning_rate <= 0 or learning_rate > 1:
        raise TrainingOptionsError('Learning rate must be greater than 0 and at most 1.')

    try:
        epochs = int(training_options.get('epochs', 10))
    except (TypeError, ValueError):
        raise TrainingOptionsError('Epochs must be a whole number.')
    if epochs < 1:
        raise TrainingOptionsError('Epochs must be at least 1.')

    return {
        'training_type': training_type,
        'epochs': epochs,
        'learning_rate': learning_rate,
        # Keep the normalized legacy key for older model/CLI integrations.
        'lr': learning_rate,
    }

def training_progress_callback(x):
    pubsub.PubSub.publish({'progress':x,  'description':'Training...'}, event='training')


@contextmanager
def _capture_legacy_fit_result(model):
    """Expose failures hidden by the released model's training wrapper."""
    captured = {}
    start_method = getattr(model, 'start_training', None)
    function = getattr(start_method, '__func__', start_method)
    namespace = getattr(function, '__globals__', {})
    training_module = namespace.get('traininglib')
    task_class = getattr(training_module, 'SegmentationTask', None)
    owner = next(
        (candidate for candidate in getattr(task_class, '__mro__', ())
         if 'fit' in candidate.__dict__),
        None,
    )
    if owner is None:
        yield captured
        return

    original_fit = owner.fit

    def monitored_fit(task, *args, **kwargs):
        if _cancel_requested.is_set():
            captured['fit_result'] = 'cancelled'
            return 'cancelled'
        result = original_fit(task, *args, **kwargs)
        captured['fit_result'] = result
        if isinstance(result, BaseException):
            raise result
        return result

    owner.fit = monitored_fit
    try:
        yield captured
    finally:
        owner.fit = original_fit


def _normalize_model_result(value, captured, maximum_progress):
    if isinstance(value, TrainingResult):
        return value
    if isinstance(value, dict) and value.get('state') in TRAINING_STATES:
        return TrainingResult(
            value['state'],
            str(value.get('message', '')),
            value.get('error_type'),
        )
    if isinstance(value, str) and value.lower() in TRAINING_STATES:
        return TrainingResult(value.lower())
    if isinstance(value, BaseException):
        return TrainingResult('failed', str(value), value.__class__.__name__)
    if value is True:
        return TrainingResult('completed')
    if value is False:
        return TrainingResult('cancelled', 'Training was interrupted.')

    legacy_fit_result = captured.get('fit_result')
    if isinstance(legacy_fit_result, str) and legacy_fit_result.lower() in TRAINING_STATES:
        return TrainingResult(legacy_fit_result.lower())
    if _cancel_requested.is_set():
        return TrainingResult('cancelled', 'Training cancellation was requested.')
    # Released model packages return None after successful training. Their
    # progress callback is the only completion signal retained by the wrapper.
    if value is None and maximum_progress >= 1:
        return TrainingResult('completed')
    if value is None:
        return TrainingResult(
            'failed',
            'Training ended before reporting completion.',
            'IncompleteTraining',
        )
    return TrainingResult(
        'failed',
        'The model returned an unsupported training result.',
        type(value).__name__,
    )


def _restore_previous_model(settings, training_type, previous_model_name):
    """Discard partial weights after cancellation or failure when possible."""
    if not previous_model_name or not hasattr(settings, 'load_model'):
        return False
    try:
        restored = settings.load_model(training_type, previous_model_name)
    except Exception as exc:
        print('[WARNING] Could not restore the pre-training model: {}'.format(exc))
        return False
    if restored is None:
        return False
    settings.models[training_type] = restored
    settings.active_models[training_type] = previous_model_name
    return True


def start_training(imagefiles, targetfiles, training_options:dict, settings, callback=training_progress_callback):
    training_options = parse_training_options(training_options)
    locked = GLOBALS.processing_lock.acquire(blocking=False)
    if not locked:
        raise RuntimeError('Cannot start training. Already processing.')

    training_type = training_options['training_type']
    previous_model_name = settings.active_models.get(training_type, '')
    device = 'cuda' if settings.use_gpu and torch.cuda.is_available() else 'cpu'
    progress = {'maximum': 0.0}
    model = None
    _cancel_requested.clear()

    def monitored_callback(value):
        progress['maximum'] = max(progress['maximum'], float(value))
        callback(value)

    try:
        model = settings.models[training_type]
        # Indicate that the in-memory model differs from the saved starting point.
        settings.active_models[training_type] = ''
        with _capture_legacy_fit_result(model) as captured:
            value = model.start_training(
                imagefiles,
                targetfiles,
                epochs      = training_options['epochs'],
                lr          = training_options['learning_rate'],
                num_workers = 'auto' if 'win' not in sys.platform else 0,
                callback    = monitored_callback,
                ds_kwargs   = {'tmpdir':get_cache_path()},
                fit_kwargs  = {'device':device},
            )
        result = _normalize_model_result(value, captured, progress['maximum'])
    except KeyboardInterrupt:
        result = TrainingResult('cancelled', 'Training was interrupted.')
    except Exception as exc:
        result = TrainingResult(
            'failed',
            str(exc) or exc.__class__.__name__,
            exc.__class__.__name__,
        )
    finally:
        try:
            if model is not None:
                try:
                    model.cpu()
                except Exception as exc:
                    result = TrainingResult(
                        'failed',
                        'Training cleanup failed: {}'.format(
                            str(exc) or exc.__class__.__name__
                        ),
                        exc.__class__.__name__,
                    )
        finally:
            GLOBALS.processing_lock.release()

    if not result.completed:
        _restore_previous_model(settings, training_type, previous_model_name)
    return result


def request_stop(settings):
    """Record cancellation before asking every compatible model to stop."""
    _cancel_requested.set()
    for model in settings.models.values():
        if hasattr(model, 'stop_training'):
            try:
                model.stop_training()
            except Exception as exc:
                print('[WARNING] A model rejected the training stop request: {}'.format(exc))

def find_targetfiles(inputfiles):
    def find_targetfile(imgf):
        no_ext_imgf = os.path.splitext(imgf)[0]
        for f in [
            f'{imgf}.segmentation.png', 
            f'{no_ext_imgf}.segmentation.png', 
            f'{no_ext_imgf}.png'
        ]:
            if os.path.exists(f):
                return f
    return list(map(find_targetfile, inputfiles))
