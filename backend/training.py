from base.backend import GLOBALS
from base.backend import pubsub
from base.backend.app import get_cache_path

import math
import os, sys
import torch


class TrainingOptionsError(ValueError):
    """Raised when browser or CLI training options are invalid or ambiguous."""


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


def start_training(imagefiles, targetfiles, training_options:dict, settings, callback=training_progress_callback):
    training_options = parse_training_options(training_options)
    locked = GLOBALS.processing_lock.acquire(blocking=False)
    if not locked:
        raise RuntimeError('Cannot start training. Already processing.')

    training_type = training_options['training_type']

    device = 'cuda' if settings.use_gpu and torch.cuda.is_available() else 'cpu'
    with GLOBALS.processing_lock:
        GLOBALS.processing_lock.release()  #decrement recursion level bc acquired twice
        model = settings.models[training_type]
        #indicate that the current model is unsaved
        settings.active_models[training_type] = ''

        ok = model.start_training(
            imagefiles, 
            targetfiles, 
            epochs      = training_options['epochs'],
            lr          = training_options['learning_rate'],
            num_workers = 'auto' if 'win' not in sys.platform else 0,
            callback    = callback,
            ds_kwargs   = {'tmpdir':get_cache_path()},
            fit_kwargs  = {'device':device},
        )
        model.cpu()
        return 'OK' if ok else 'INTERRUPTED'

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
