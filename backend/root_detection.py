import glob
import hashlib
import json
import os
import tempfile
import typing as tp
import numpy as np

import PIL.Image
from backend import postprocessing
import backend
from base.backend.pubsub import PubSub
from base.backend.app import get_cache_path, get_models_path

import torch


SEGMENTATION_CACHE_SCHEMA = 1
_FILE_HASH_CACHE = {}
_FILE_HASH_CACHE_LIMIT = 32


def run_model(image_path:str, settings:tp.Any, modeltype:str, **kwargs) -> np.ndarray:
    basename   = os.path.basename(image_path)
    device     = 'cuda' if settings.use_gpu and torch.cuda.is_available() else 'cpu'
    with backend.GLOBALS.processing_lock:
        progress_callback = lambda x: PubSub.publish({'progress':x, 'image':basename, 'stage':modeltype})
        model  = settings.models[modeltype].to(device)
        result = model.process_image(image_path, progress_callback=progress_callback, **kwargs)
        model.cpu()
    return result


def _sha256(path:str) -> str:
    stat = os.stat(path)
    key = (os.path.realpath(path), stat.st_size, stat.st_mtime_ns)
    cached = _FILE_HASH_CACHE.get(key)
    if cached is not None:
        return cached

    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    value = digest.hexdigest()
    if len(_FILE_HASH_CACHE) >= _FILE_HASH_CACHE_LIMIT:
        _FILE_HASH_CACHE.pop(next(iter(_FILE_HASH_CACHE)))
    _FILE_HASH_CACHE[key] = value
    return value


def _model_identity(settings:tp.Any, modeltype:str='detection') -> dict:
    modelname = settings.active_models.get(modeltype, '')
    identity = {'name': modelname}
    for ending in ['.pt.zip', '.pt', '.pkl']:
        candidate = os.path.join(get_models_path(), modeltype, modelname + ending)
        if modelname and os.path.isfile(candidate):
            identity.update({
                'sha256': _sha256(candidate),
                'size': os.path.getsize(candidate),
            })
            break
    return identity


def segmentation_cache_paths(image_path:str) -> dict:
    prefix = image_path + '.segmentation.cache'
    return {
        'array': prefix + '.npy',
        'preview': prefix + '.png',
        'manifest': prefix + '.json',
    }


def segmentation_cache_manifest(image_path:str, settings:tp.Any) -> dict:
    return {
        'schema': SEGMENTATION_CACHE_SCHEMA,
        'kind': 'root-probability-map',
        'operation': {
            'threshold': None,
            'storage_dtype': 'float32',
        },
        'input': {
            'name': os.path.basename(image_path),
            'sha256': _sha256(image_path),
            'size': os.path.getsize(image_path),
        },
        'model': _model_identity(settings, 'detection'),
    }


def _atomic_save_array(path:str, value:np.ndarray) -> None:
    folder = os.path.dirname(path) or '.'
    os.makedirs(folder, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='.segmentation-', suffix='.npy', dir=folder)
    try:
        with os.fdopen(handle, 'wb') as output:
            np.save(output, np.asarray(value, dtype='float32'), allow_pickle=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def _atomic_save_json(path:str, value:dict) -> None:
    folder = os.path.dirname(path) or '.'
    os.makedirs(folder, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='.manifest-', suffix='.json', dir=folder)
    try:
        with os.fdopen(handle, 'w') as output:
            json.dump(value, output, sort_keys=True, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def ensure_soft_segmentation(image_path:str, settings:tp.Any) -> tp.Tuple[str, np.ndarray]:
    """Return a model-specific probability map, computing it only when stale."""
    paths = segmentation_cache_paths(image_path)
    expected = segmentation_cache_manifest(image_path, settings)

    try:
        with open(paths['manifest'], 'r') as source:
            actual = json.load(source)
        comparable_actual = {
            key: actual.get(key)
            for key in expected
        }
        if comparable_actual == expected and os.path.exists(paths['array']) and os.path.exists(paths['preview']):
            cached = np.load(paths['array'], allow_pickle=False).astype('float32')
            artifact = actual.get('artifact', {})
            if artifact.get('shape') == list(cached.shape) and artifact.get('dtype') == str(cached.dtype):
                return paths['preview'], cached
    except (OSError, ValueError, json.JSONDecodeError):
        pass

    segmentation = np.asarray(
        run_model(image_path, settings, 'detection', threshold=None),
        dtype='float32',
    )
    _atomic_save_array(paths['array'], segmentation)

    preview_tmp = paths['preview'] + '.tmp.png'
    try:
        backend.write_as_png(preview_tmp, segmentation)
        os.replace(preview_tmp, paths['preview'])
    finally:
        if os.path.exists(preview_tmp):
            os.remove(preview_tmp)
    manifest = dict(expected)
    manifest['artifact'] = {
        'shape': list(segmentation.shape),
        'dtype': str(segmentation.dtype),
    }
    _atomic_save_json(paths['manifest'], manifest)
    return paths['preview'], segmentation

def process_image(image_path:str, settings:tp.Any) -> dict:
    _, probability = ensure_soft_segmentation(image_path, settings)
    segmentation = (probability > 0.5).astype('uint8')
    exmask       = maybe_compute_exclusionmask(image_path, settings)
    result       = paste_exmask(segmentation, exmask)
    result       = postprocess(result)
    return save_result(result, image_path)


def postprocess_segmentation_file(path:str) -> dict:
    assert path.endswith('.segmentation.png')
    image_path   = path.replace('.segmentation.png', '')
    segmentation = PIL.Image.open(path).convert('RGB') / np.float32(255)
    segmentation = result_from_rgb(segmentation)

    result = postprocess(segmentation)
    return save_result(result, image_path)


def postprocess(segmentation_result:np.ndarray) -> dict:
    skeleton           = postprocessing.skeletonize(segmentation_result)
    stats              = postprocessing.compute_statistics(segmentation_result, skeleton)
    segmentation_rgb   = result_to_rgb(segmentation_result)
    skeleton_rgb       = result_to_rgb(skeleton)

    return {
        'segmentation': segmentation_rgb,
        'skeleton'    : skeleton_rgb,
        'statistics'  : stats,
    }

def save_result(result:dict, image_path:str) -> dict:
    basename           = os.path.basename(image_path)
    output_folder      = get_cache_path()
    segmentation_fname = f'{basename}.segmentation.png'
    skeleton_fname     = f'{basename}.skeleton.png'
    segmentation_path  = os.path.join(output_folder, segmentation_fname)
    skeleton_path      = os.path.join(output_folder, skeleton_fname)
    
    backend.write_as_png(segmentation_path, result['segmentation'])
    backend.write_as_png(skeleton_path, result['skeleton'])

    return {
        'segmentation': segmentation_fname,
        'skeleton'    : skeleton_fname,
        'statistics'  : result['statistics'],
    }


def result_to_rgb(x:np.ndarray) -> np.ndarray:
    '''Convert a segmentation map with classes 0,1,2 to RGB format'''
    assert len(x.shape)==2
    x     = x[...,np.newaxis]
    WHITE = (1.,1.,1.)
    RED   = (1.,0.,0.)
    x     = (x==1) * WHITE   +  (x==2) * RED
    return x

def result_from_rgb(x:np.ndarray) -> np.ndarray:
    '''Convert a RGB array to a segmentation map with classes 0,1,2'''
    assert len(x.shape)==3
    WHITE  = (1.,1.,1.)
    RED    = (1.,0.,0.)
    result = (x == WHITE).all(-1) *1 \
           + (x == RED  ).all(-1) *2
    return result


def paste_exmask(segmentation:np.ndarray, exmask:tp.Union[np.ndarray,None]) -> np.ndarray:
    '''Combine two binary masks into a label map with classes 0,1,2'''
    if exmask is None:
        return segmentation
    exmask_array = np.asarray(exmask).squeeze()
    TAPE_VALUE = 2
    return np.where(exmask_array>0, TAPE_VALUE, segmentation)

def maybe_compute_exclusionmask(image_path:str, settings:tp.Any) -> tp.Optional[np.ndarray]:
    '''Compute the exclusion mask if enabled or load a custom mask file'''
    exmask  = search_for_custom_maskfile(image_path)
    if settings.exmask_enabled and exmask is None:
        exmask   = run_model(image_path, settings, 'exclusion_mask')
    return exmask

def search_for_custom_maskfile(input_image_path:str) -> tp.Union[np.ndarray, None]:
    '''Search for a mask file that was manually uploaded by user in the same directory as input_image_path'''
    basename = os.path.splitext(os.path.basename(input_image_path))[0]
    pattern  = os.path.join( os.path.dirname(input_image_path), f'{basename}.exclusionmask.png')
    masks    = glob.glob(pattern)
    if len(masks)==1:
        mask = PIL.Image.open(masks[0]).convert('RGB') / np.float32(255)
        #convert rgb to binary array
        mask = np.any(mask, axis=-1)
        return mask
