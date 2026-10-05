import csv
import hashlib
import io
import json
import os
import re
import tempfile
import typing as tp
import uuid
import warnings
import zipfile
import torch, torchvision
import numpy as np
import scipy.ndimage
import PIL.Image
import skimage.morphology

from backend import GLOBALS
from backend import jobs
from backend import postprocessing
from backend import root_detection
from backend import tracking_matcher
from base.backend.pubsub import PubSub
from base.backend import paths


class TooManyRootsError:
    """Sentinel returned when tracking is intentionally skipped for safety."""


TOO_MANY_ROOTS_ERROR = TooManyRootsError()
TrackingStatus = tp.Union[bool, TooManyRootsError]
TrackingResult = tp.Dict[str, tp.Any]
FilePairs = tp.Sequence[tp.Sequence[str]]
TRACKING_CSV_SCHEMA = 2
TRACKING_PROFILE_SCHEMA = 2
RUN_ID_PATTERN = re.compile(r'^[0-9a-f]{32}$')
EXCLUSION_MASK_POLICIES = {'union', 'intersection', 'first', 'second'}
DEFAULT_EXCLUSION_MASK_POLICY = 'first'
TRACKING_SAMPLING_MODES = {'legacy', 'deterministic'}
DEFAULT_TRACKING_SAMPLING_MODE = 'legacy'
TRACKING_CSV_FIELDS = [
    'Filename 1', 'Filename 2',
    'same pixels', 'decay pixels', 'growth pixels',
    'background pixels', 'mask pixels',
    'same skeleton pixels', 'decay skeleton pixels', 'growth skeleton pixels',
    'same kimura length', 'decay kimura length', 'growth kimura length',
    'status',
]


def validate_tracking_run_id(run_id:tp.Any) -> str:
    if not isinstance(run_id, str) or RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError('Invalid tracking result ID. Run tracking again.')
    return run_id


def _array_identity(array:np.ndarray) -> dict:
    contiguous = np.ascontiguousarray(array)
    return {
        'shape': list(contiguous.shape),
        'dtype': str(contiguous.dtype),
        'sha256': hashlib.sha256(memoryview(contiguous).cast('B')).hexdigest(),
    }


def _file_sha256(filename:str) -> str:
    digest = hashlib.sha256()
    with open(filename, 'rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _segmentation_array_path(preview_path:str) -> str:
    return os.path.splitext(preview_path)[0] + '.npy'


def _tracking_profile_id(profile:dict) -> str:
    identity = {key: value for key, value in profile.items() if key != 'profile_id'}
    serialized = json.dumps(identity, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(serialized).hexdigest()


def tracking_run_profile(
    filename0:str,
    filename1:str,
    segmentation0:np.ndarray,
    segmentation1:np.ndarray,
    exclusion0:tp.Optional[np.ndarray],
    exclusion1:tp.Optional[np.ndarray],
    settings:tp.Any,
    sampling_mode:str,
    exclusion_policy:str,
    match_device:str,
    matcher:dict,
    segmentation_previews:tp.Sequence[str],
) -> dict:
    """Record every selected input and scientific option affecting this result."""
    profile = {
        'schema': TRACKING_PROFILE_SCHEMA,
        'inputs': [
            {'name': os.path.basename(path), 'sha256': root_detection._sha256(path)}
            for path in (filename0, filename1)
        ],
        'segmentations': [
            _array_identity(segmentation0), _array_identity(segmentation1)
        ],
        'segmentation_previews': [
            {'name': os.path.basename(path), 'sha256': _file_sha256(path)}
            for path in segmentation_previews
        ],
        'exclusion_masks': [
            _array_identity(mask) if mask is not None else None
            for mask in (exclusion0, exclusion1)
        ],
        'models': {
            kind: root_detection._model_identity(settings, kind)
            for kind in ('detection', 'tracking')
        },
        'sampling_mode': sampling_mode,
        'exclusion_mask_policy': exclusion_policy,
        'match_device': match_device,
        'matcher_version': matcher.get('version'),
        'sampling_seed': matcher.get('seed'),
    }
    profile['profile_id'] = _tracking_profile_id(profile)
    return profile



def process(
    filename0:str,
    filename1:str,
    settings:tp.Any,
    previous_data:tp.Optional[tp.Dict[str, tp.Any]]=None,
) -> tp.Union[TrackingResult, TooManyRootsError]:
    print(f'Performing root tracking on files {filename0} and {filename1}')
    jobs.raise_if_cancelled(settings)
    matchmodel = settings.models['tracking']

    seg0f, seg0 = ensure_segmentation(filename0, settings)
    jobs.raise_if_cancelled(settings)
    seg1f, seg1 = ensure_segmentation(filename1, settings)
    jobs.raise_if_cancelled(settings)
    validate_tracking_pair_shapes(seg0, seg1)
    TOO_MANY_ROOTS_THRESHOLD = settings.too_many_roots
    if should_skip_because_too_many_roots(seg0, seg1, TOO_MANY_ROOTS_THRESHOLD):
        cache_output_for_download(filename0, filename1, TOO_MANY_ROOTS_ERROR, {})
        return TOO_MANY_ROOTS_ERROR
    
    exclusion_policy = validate_exclusion_mask_policy(
        getattr(settings, 'tracking_exclusion_policy', DEFAULT_EXCLUSION_MASK_POLICY)
    )
    exmask0, exmask1 = ensure_pair_exclusion_masks(
        filename0, filename1, settings, exclusion_policy
    )
    sampling_mode = validate_tracking_sampling_mode(
        getattr(settings, 'tracking_sampling_mode', DEFAULT_TRACKING_SAMPLING_MODE)
    )
    run_id = uuid.uuid4().hex
    outputname = f'{filename0}.{os.path.basename(filename1)}.{run_id}'
    device = 'cuda' if settings.use_gpu and torch.cuda.is_available() else 'cpu'
    
    if previous_data is None:  #FIXME: better condition?
        seed_identity = None
        sampling_seed = None
        if sampling_mode == 'deterministic':
            sampling_seed, seed_identity = deterministic_sampling_seed(
                filename0, filename1, seg0, seg1, settings
            )
        img0    = torchvision.transforms.ToTensor()(PIL.Image.open(filename0))
        img1    = torchvision.transforms.ToTensor()(PIL.Image.open(filename1))
        with GLOBALS.processing_lock:
            jobs.raise_if_cancelled(settings)
            def on_progress(value, phase):
                jobs.raise_if_cancelled(settings)
                operation_callback = getattr(
                    settings,
                    'operation_progress_callback',
                    None,
                )
                if operation_callback is not None:
                    operation_callback(value, phase)
                PubSub.publish({
                    'progress': value,
                    'image': '{} -> {}'.format(
                        os.path.basename(filename0),
                        os.path.basename(filename1),
                    ),
                    'stage': 'tracking',
                    'description': phase,
                })

            output = tracking_matcher.match_images(
                matchmodel,
                img0,
                img1,
                seg0,
                seg1,
                n=tracking_matcher.DEFAULT_SAMPLE_COUNT,
                cyclic_threshold=4,
                device=device,
                progress_callback=on_progress,
                cancellation_check=lambda: jobs.raise_if_cancelled(settings),
                sampling_seed=sampling_seed,
            )
            jobs.raise_if_cancelled(settings)
            print()
            print(len(output['points0']))
            print('Matched percentage:', output['matched_percentage'])
            print()
            output['success'] = success = (len(output['points0'])>=16)
            output['n_matched_points'] = len(output['points0'])
            output['tracking_model']     = settings.active_models['tracking']
            output['segmentation_model'] = settings.active_models['detection']
            output['tracking_matcher'] = tracking_matcher.provenance(
                sampling_seed=sampling_seed,
                seed_identity=seed_identity,
            )
            output['match_device'] = device
    else:
        validate_previous_tracking_data(
            previous_data, filename0, filename1, seg0, seg1, settings, sampling_mode
        )
        output      = {
            'points0'            : np.asarray(previous_data['points0']).reshape(-1,2),
            'points1'            : np.asarray(previous_data['points1']).reshape(-1,2),
            'n_matched_points'   : previous_data['n_matched_points'],
            'tracking_model'     : previous_data['tracking_model'],
            'segmentation_model' : previous_data['segmentation_model'],
            'tracking_matcher'   : previous_data.get('tracking_matcher', {
                'name': 'released-model-internal-matcher',
                'version': 0,
            }),
            'match_device'       : previous_data.get('match_device', 'unknown'),
        }
        corrections = np.array(previous_data['corrections']).reshape(-1,4)
        if len(corrections)>0:
            previous_prefix = f'{filename0}.{os.path.basename(filename1)}'
            if previous_data.get('run_id') is not None:
                previous_prefix += '.' + validate_tracking_run_id(previous_data['run_id'])
            previous_map = previous_prefix + '.imap.npy'
            if os.path.isfile(previous_map):
                imap = np.load(previous_map, allow_pickle=False).astype('float32')
            else:
                previous_points0 = np.asarray(previous_data['points0']).reshape(-1, 2)
                previous_points1 = np.asarray(previous_data['points1']).reshape(-1, 2)
                if len(previous_points0) != len(previous_points1) or not len(previous_points0):
                    raise ValueError('Saved match points are incomplete. Run tracking again.')
                imap = matchmodel.interpolation_map(
                    previous_points1, previous_points0, seg0.shape
                )
            corrections_p0 = corrections[:,:2][:,::-1] #xy to yx
            corrections_p1 = corrections[:,2:][:,::-1]
            corrections_p0 = np.stack([
                scipy.ndimage.map_coordinates(imap[...,0], corrections_p0.T, order=1),
                scipy.ndimage.map_coordinates(imap[...,1], corrections_p0.T, order=1),
            ], axis=-1)
            output['points0'] = np.concatenate([output['points0'], corrections_p0])
            output['points1'] = np.concatenate([output['points1'], corrections_p1])
        success = output['success'] = (len(output['points1'])>=1)
    
    if success:
        imap    = matchmodel.interpolation_map(output['points1'], output['points0'], seg0.shape)
    else:
        #dummy interpolation map
        imap    = matchmodel.interpolation_map(np.zeros([1,2]), np.zeros([1,2]), seg0.shape)
    jobs.raise_if_cancelled(settings)
    
    np.save(f'{outputname}.imap.npy', imap.astype('float16'))  #f16 to save space & time

    warped_seg0    = matchmodel.warp(seg0, imap)
    warped_exmask0 = None
    if exmask0 is not None:
        warped_exmask0 = matchmodel.warp(exmask0, imap)
    combined_exmask = combine_exclusion_masks(
        warped_exmask0,
        exmask1,
        exclusion_policy,
        seg1.shape,
    )
    gmap           = matchmodel.create_growth_map_rgba( warped_seg0>0.5, seg1>0.5, )
    gmap           = paste_exclusionmask(gmap, combined_exmask)
    jobs.raise_if_cancelled(settings)

    output_file_rgb  = f'{outputname}.growthmap.png'
    output_file_rgba = f'{outputname}.growthmap_rgba.png'
    PIL.Image.fromarray(gmap).convert('RGB').save( output_file_rgb )
    PIL.Image.fromarray(gmap).save( output_file_rgba )

    output['growthmap']      = output_file_rgb
    output['growthmap_rgba'] = output_file_rgba
    output['segmentation0']  = seg0f
    output['segmentation1']  = seg1f
    output['segmentation_array0'] = _segmentation_array_path(seg0f)
    output['segmentation_array1'] = _segmentation_array_path(seg1f)
    output['exclusion_mask_policy'] = exclusion_policy
    output['exclusion_masks'] = {
        'observation0_present': exmask0 is not None,
        'observation1_present': exmask1 is not None,
        'observation0_pixels': _mask_pixel_count(exmask0),
        'observation1_pixels': _mask_pixel_count(exmask1),
        'combined_pixels': _mask_pixel_count(combined_exmask),
    }
    output['run_id'] = run_id
    output['run_profile'] = tracking_run_profile(
        filename0, filename1, seg0, seg1, exmask0, exmask1, settings,
        sampling_mode, exclusion_policy, output['match_device'],
        output['tracking_matcher'], (seg0f, seg1f),
    )

    output['statistics']     = compute_statistics(gmap)
    
    cache_output_for_download(filename0, filename1, success, output)
    return output


def ensure_segmentation(input_image_path:str, settings:tp.Any) -> tp.Tuple[str, np.ndarray]:
    '''Run root detection (without a threshold) or load a cached result'''
    return root_detection.ensure_soft_segmentation(input_image_path, settings)


def ensure_exclusionmask(input_image_path:str, settings:tp.Any) -> tp.Optional[np.ndarray]:
    '''Run exclusion-mask detection (if enabled) or load a custom/cached mask.'''
    return root_detection.maybe_compute_exclusionmask(input_image_path, settings)


def validate_tracking_sampling_mode(mode:tp.Any) -> str:
    if not isinstance(mode, str) or mode not in TRACKING_SAMPLING_MODES:
        raise ValueError('Invalid tracking sampling mode. Choose legacy or deterministic.')
    return tp.cast(str, mode)


def validate_exclusion_mask_policy(policy:tp.Any) -> str:
    if not isinstance(policy, str) or policy not in EXCLUSION_MASK_POLICIES:
        raise ValueError(
            'Invalid tracking exclusion-mask policy. Choose one of: {}.'.format(
                ', '.join(sorted(EXCLUSION_MASK_POLICIES))
            )
        )
    return tp.cast(str, policy)


def ensure_pair_exclusion_masks(
    filename0:str,
    filename1:str,
    settings:tp.Any,
    policy:str,
) -> tp.Tuple[tp.Optional[np.ndarray], tp.Optional[np.ndarray]]:
    """Load only the masks needed by the selected scientific policy."""
    policy = validate_exclusion_mask_policy(policy)
    exmask0 = None
    exmask1 = None
    if policy in {'first', 'union', 'intersection'}:
        exmask0 = ensure_exclusionmask(filename0, settings)
        jobs.raise_if_cancelled(settings)
    if policy in {'second', 'union', 'intersection'}:
        exmask1 = ensure_exclusionmask(filename1, settings)
        jobs.raise_if_cancelled(settings)
    _validate_combined_mask_availability(exmask0, exmask1, policy)
    return exmask0, exmask1


def deterministic_sampling_seed(
    filename0:str,
    filename1:str,
    segmentation0:np.ndarray,
    segmentation1:np.ndarray,
    settings:tp.Any,
) -> tp.Tuple[int, tp.Dict[str, tp.Any]]:
    """Derive a portable per-pair seed from ordered inputs and model contents."""
    def segmentation_identity(segmentation:np.ndarray) -> dict:
        array = np.ascontiguousarray(segmentation)
        return {
            'shape': list(array.shape),
            'dtype': str(array.dtype),
            'sha256': hashlib.sha256(array.tobytes()).hexdigest(),
        }

    identity = {
        'sampling_version': 2,
        'image0_sha256': root_detection._sha256(filename0),
        'image1_sha256': root_detection._sha256(filename1),
        'segmentation0': segmentation_identity(segmentation0),
        'segmentation1': segmentation_identity(segmentation1),
        'tracking_model': root_detection._model_identity(settings, 'tracking'),
        'detection_model': root_detection._model_identity(settings, 'detection'),
        'sample_count': tracking_matcher.DEFAULT_SAMPLE_COUNT,
        'uniform_sample_count': tracking_matcher.UNIFORM_SAMPLE_COUNT,
    }
    serialized = json.dumps(identity, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return int.from_bytes(hashlib.sha256(serialized).digest()[:4], 'big'), identity


def validate_previous_tracking_data(
    previous_data:tp.Dict[str, tp.Any],
    filename0:str,
    filename1:str,
    segmentation0:np.ndarray,
    segmentation1:np.ndarray,
    settings:tp.Any,
    sampling_mode:str,
) -> None:
    """Reject corrections imported from another pair, model, or sampling mode."""
    for key, path in (('filename0', filename0), ('filename1', filename1)):
        if key in previous_data and previous_data[key] != os.path.basename(path):
            raise ValueError('Saved tracking points belong to a different image pair. Run tracking again.')
    for key, kind in (('tracking_model', 'tracking'), ('segmentation_model', 'detection')):
        if previous_data.get(key) != settings.active_models[kind]:
            raise ValueError(
                'Saved tracking points used a different {}. Run tracking again before correcting.'.format(
                    key.replace('_', ' ')
                )
            )

    provenance = previous_data.get('tracking_matcher')
    if provenance is None:
        # Older exports omitted matcher metadata and always used original sampling.
        provenance = {'version': 0}
    if not isinstance(provenance, dict):
        raise ValueError('Saved tracking points have unknown matcher metadata. Run tracking again.')
    version = provenance.get('version')
    if type(version) is not int or version not in {0, 1, 2}:
        raise ValueError('Saved tracking points have unknown matcher metadata. Run tracking again.')
    stored_mode = 'deterministic' if version == 2 else 'legacy'
    if stored_mode != sampling_mode:
        raise ValueError(
            'Saved tracking points used a different sampling mode. Restore that mode '
            'or run tracking again before correcting.'
        )
    if stored_mode == 'deterministic':
        expected_seed, expected_identity = deterministic_sampling_seed(
            filename0, filename1, segmentation0, segmentation1, settings
        )
        if (provenance.get('seed') != expected_seed
                or provenance.get('seed_identity') != expected_identity):
            raise ValueError(
                'Saved seeded tracking points do not match these images, segmentations, '
                'or models. Run tracking again before correcting.'
            )
    if 'run_id' in previous_data:
        validate_tracking_run_id(previous_data['run_id'])
    saved_profile = previous_data.get('run_profile')
    if 'run_id' in previous_data and saved_profile is None:
        raise ValueError('Saved tracking points lack their result profile. Run tracking again.')
    if saved_profile is not None:
        if (not isinstance(saved_profile, dict)
                or saved_profile.get('schema') not in {1, TRACKING_PROFILE_SCHEMA}
                or saved_profile.get('profile_id') != _tracking_profile_id(saved_profile)):
            raise ValueError('Saved tracking points have unknown profile metadata. Run tracking again.')
        current_inputs = [
            {'name': os.path.basename(path), 'sha256': root_detection._sha256(path)}
            for path in (filename0, filename1)
        ]
        current_segmentations = [
            _array_identity(segmentation0), _array_identity(segmentation1)
        ]
        current_models = {
            kind: root_detection._model_identity(settings, kind)
            for kind in ('detection', 'tracking')
        }
        if (saved_profile.get('inputs') != current_inputs
                or saved_profile.get('segmentations') != current_segmentations
                or saved_profile.get('models') != current_models):
            raise ValueError(
                'Saved tracking points do not match these images, segmentations, or models. '
                'Run tracking again before correcting.'
            )


def validate_tracking_pair_shapes(
    segmentation0:np.ndarray,
    segmentation1:np.ndarray,
) -> tp.Tuple[int, ...]:
    """Require comparable pixel grids before matching or turnover analysis."""
    shape0 = tuple(np.asarray(segmentation0).squeeze().shape)
    shape1 = tuple(np.asarray(segmentation1).squeeze().shape)
    if len(shape0) != 2 or len(shape1) != 2:
        raise ValueError(
            'Tracking requires two-dimensional segmentations; received {} and {}.'.format(
                shape0,
                shape1,
            )
        )
    if shape0 != shape1:
        raise ValueError(
            'Tracking requires images with identical pixel dimensions; received '
            '{} and {}. Use comparable scans of the same location, or explicitly '
            'align and crop copies before tracking while preserving the originals '
            'and transformation record.'.format(shape0, shape1)
        )
    return shape0


def _mask_pixel_count(mask:tp.Optional[np.ndarray]) -> int:
    if mask is None:
        return 0
    return int((np.asarray(mask).squeeze() > 0.5).sum())


def _binary_mask(mask:tp.Optional[np.ndarray], shape:tp.Tuple[int, ...]) -> np.ndarray:
    if mask is None:
        return np.zeros(shape, dtype=bool)
    array = np.asarray(mask).squeeze()
    if array.shape != shape:
        raise ValueError(
            'Exclusion mask shape {} does not match tracking image shape {}.'.format(
                array.shape,
                shape,
            )
        )
    return array > 0.5


def _validate_combined_mask_availability(
    observation0:tp.Optional[np.ndarray],
    observation1:tp.Optional[np.ndarray],
    policy:str,
) -> None:
    """Do not silently treat one missing mask as an empty observation."""
    if policy in {'union', 'intersection'} and ((observation0 is None) != (observation1 is None)):
        raise ValueError(
            'The {} exclusion-mask policy needs masks for both observations. '
            'One is missing; provide both masks or select the available observation.'.format(
                policy
            )
        )


def combine_exclusion_masks(
    warped_observation0:tp.Optional[np.ndarray],
    observation1:tp.Optional[np.ndarray],
    policy:str=DEFAULT_EXCLUSION_MASK_POLICY,
    shape:tp.Optional[tp.Tuple[int, ...]]=None,
) -> tp.Optional[np.ndarray]:
    """Combine masks in observation-2 coordinates under an explicit policy."""
    policy = validate_exclusion_mask_policy(policy)
    _validate_combined_mask_availability(warped_observation0, observation1, policy)
    if warped_observation0 is None and observation1 is None:
        return None
    resolved_shape = shape
    if resolved_shape is None:
        source = observation1 if observation1 is not None else warped_observation0
        resolved_shape = tuple(np.asarray(source).squeeze().shape)
    first = _binary_mask(warped_observation0, resolved_shape)
    second = _binary_mask(observation1, resolved_shape)
    if policy == 'union':
        return first | second
    if policy == 'intersection':
        return first & second
    if policy == 'first':
        return first
    return second


class COLORS:
    NEGATIVE = ( 39, 54, 59,  0)
    SAME     = (255,255,255,255)
    DECAY    = (226,106,116,255)
    GROWTH   = ( 96,209,130,255)
    EXMASK   = (255,  0,  0,255)

def paste_exclusionmask(turnovermap_rgba:np.ndarray, exmask:tp.Union[np.ndarray, None]) -> np.ndarray:
    if exmask is None:
        return turnovermap_rgba
    return np.where(np.asarray(exmask)[...,None]>0.5, COLORS.EXMASK, turnovermap_rgba).astype('uint8')


def skeletonized_turnovermap(gmap):
    seg0w = (gmap==1) | (gmap==2)  #warped segmentation 0 = same+decay
    seg1  = (gmap==1) | (gmap==3)  #segmentation 1        = same+growth
    sk0   = skimage.morphology.skeletonize(seg0w)
    sk1   = skimage.morphology.skeletonize(seg1)
    return np.stack([
        np.zeros_like(sk0),
        (sk1 == 1) & (gmap == 1),
        (sk0 == 1) & (gmap == 2),
        (sk1 == 1) & (gmap == 3),
    ]).argmax(0)

def turnovermap_from_rgba(rgba:np.ndarray) -> np.ndarray:
    '''Convert a RGBA encoded turnover map into a labeled array
       with classes 0(negative),1(same),2(decay),3(growth),4(exclude)'''
    
    return np.stack([
        (rgba == COLORS.NEGATIVE).all(-1),
        (rgba == COLORS.SAME).all(-1),
        (rgba == COLORS.DECAY).all(-1),
        (rgba == COLORS.GROWTH).all(-1),
        (rgba == COLORS.EXMASK).all(-1),
    ]).argmax(0)


def compute_statistics(turnovermap_rgba):
    turnovermap    = turnovermap_from_rgba(turnovermap_rgba)
    turnovermap_sk = skeletonized_turnovermap(turnovermap)

    kimura_same   = postprocessing.kimura_length(turnovermap_sk==1)
    kimura_decay  = postprocessing.kimura_length(turnovermap_sk==2)
    kimura_growth = postprocessing.kimura_length(turnovermap_sk==3)

    return {
        'sum_same' :        int( (turnovermap==1).sum() ),
        'sum_decay' :       int( (turnovermap==2).sum() ),
        'sum_growth':       int( (turnovermap==3).sum() ),
        'sum_negative':     int( (turnovermap==0).sum() ),
        'sum_exmask':       int( (turnovermap==4).sum() ),

        'sum_same_sk' :     int( (turnovermap_sk==1).sum() ),
        'sum_decay_sk' :    int( (turnovermap_sk==2).sum() ),
        'sum_growth_sk':    int( (turnovermap_sk==3).sum() ),
        'sum_negative_sk':  int( (turnovermap_sk==0).sum() ),

        'kimura_same':      int( kimura_same ),
        'kimura_decay':     int( kimura_decay ),
        'kimura_growth':    int( kimura_growth ),
    }

def should_skip_because_too_many_roots(
    seg0:np.ndarray, 
    seg1:np.ndarray, 
    threshold:int
) -> bool:
    n_roots0 = skimage.morphology.skeletonize(seg0>0.5).sum()
    n_roots1 = skimage.morphology.skeletonize(seg1>0.5).sum()
    return (n_roots0 > threshold) or (n_roots1 > threshold)


def cache_output_for_download(
    filename0: str,
    filename1: str,
    success:   TrackingStatus,
    output:    tp.Dict[str, tp.Any],
) -> None:
    dirname     =   paths.get_cache_path()
    filename0   =   os.path.basename(filename0)
    filename1   =   os.path.basename(filename1)
    pair_prefix = os.path.join(dirname, f'{filename0}.{filename1}')
    run_id = output.get('run_id')
    outputname = pair_prefix + ('.' + validate_tracking_run_id(run_id) if run_id else '')
    csv_text = statistics_to_csv(
        output.get('statistics', {}), filename0, filename1, success
    )
    with open(f'{outputname}.csv', 'w') as destination:
        destination.write(csv_text)
    if run_id:
        # The pair-named file remains a latest-result compatibility alias.
        with open(f'{pair_prefix}.csv', 'w') as destination:
            destination.write(csv_text)

    if isinstance(success, TooManyRootsError):
        # A skipped rerun must not leave the previous successful pair alias
        # pointing at stale growth maps. Run-specific artifacts stay intact.
        with open(f'{pair_prefix}.json', 'w') as destination:
            json.dump({
                'filename0': filename0,
                'filename1': filename1,
                'status': 'skipped',
            }, destination)
        return

    metadata = {
        'filename0'             : filename0,
        'filename1'             : filename1,
        'run_id'                : run_id,
        'run_profile'           : output.get('run_profile'),
        'match_device'          : output.get('match_device', 'unknown'),
        'points0'               : output['points0'].tolist(),
        'points1'               : output['points1'].tolist(),
        'n_matched_points'      : output['n_matched_points'],
        'tracking_model'        : output['tracking_model'],
        'segmentation_model'    : output['segmentation_model'],
        'tracking_matcher'      : output['tracking_matcher'],
        'segmentation0'         : os.path.basename(output['segmentation0']),
        'segmentation1'         : os.path.basename(output['segmentation1']),
        'segmentation_array0'   : os.path.basename(output.get(
            'segmentation_array0', _segmentation_array_path(output['segmentation0'])
        )),
        'segmentation_array1'   : os.path.basename(output.get(
            'segmentation_array1', _segmentation_array_path(output['segmentation1'])
        )),
        'growthmap'             : os.path.basename(output['growthmap']),
        'statistics_file'       : os.path.basename(f'{outputname}.csv'),
        'exclusion_mask_policy' : output['exclusion_mask_policy'],
        'exclusion_masks'       : output['exclusion_masks'],
    }
    with open(f'{outputname}.json', 'w') as destination:
        json.dump(metadata, destination)
    if run_id:
        with open(f'{pair_prefix}.json', 'w') as destination:
            json.dump(metadata, destination)


def _statistics_record(
    stats:tp.Dict[str, tp.Any],
    filename0:str,
    filename1:str,
    success:TrackingStatus,
) -> tp.Dict[str, tp.Any]:
    status_map = {
        True: 'OK',
        False: 'WARNING: No matching roots found',
        TOO_MANY_ROOTS_ERROR: 'SKIPPED: Too many roots',
    }
    return {
        'Filename 1': filename0,
        'Filename 2': filename1,
        'same pixels': stats.get('sum_same', ''),
        'decay pixels': stats.get('sum_decay', ''),
        'growth pixels': stats.get('sum_growth', ''),
        'background pixels': stats.get('sum_negative', ''),
        'mask pixels': stats.get('sum_exmask', ''),
        'same skeleton pixels': stats.get('sum_same_sk', ''),
        'decay skeleton pixels': stats.get('sum_decay_sk', ''),
        'growth skeleton pixels': stats.get('sum_growth_sk', ''),
        'same kimura length': stats.get('kimura_same', ''),
        'decay kimura length': stats.get('kimura_decay', ''),
        'growth kimura length': stats.get('kimura_growth', ''),
        'status': status_map[success],
    }

def statistics_to_csv(
    stats:     tp.Dict[str, tp.Any],
    filename0: str,
    filename1: str,
    success:   TrackingStatus,
    include_header=True
) -> str:
    '''Convert statistics from Python dicts as computed in process() to CSV'''
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=TRACKING_CSV_FIELDS, extrasaction='raise')
    if include_header:
        writer.writeheader()
    writer.writerow(_statistics_record(stats, filename0, filename1, success))
    return output.getvalue()


def _pair_result_metadata(
    filename0:str, filename1:str, run_id:tp.Optional[str]=None
) -> tp.Optional[tp.Tuple[str, dict]]:
    cache_path = paths.get_cache_path()
    suffix = '.' + validate_tracking_run_id(run_id) if run_id is not None else ''
    metadata_path = os.path.join(cache_path, f'{filename0}.{filename1}{suffix}.json')
    try:
        with open(metadata_path, 'r') as source:
            metadata = json.load(source)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(metadata, dict):
        return None
    if metadata.get('filename0', filename0) != filename0 or metadata.get('filename1', filename1) != filename1:
        return None
    if run_id is not None and metadata.get('run_id') != run_id:
        return None
    return metadata_path, metadata


def _cached_file_identity(path:str, kind:str, cache:tp.Optional[dict]) -> tp.Any:
    signature = os.stat(path)
    version = (signature.st_ino, signature.st_size, signature.st_mtime_ns,
               signature.st_ctime_ns)
    key = (kind, path)
    if cache is not None and key in cache and cache[key][0] == version:
        return cache[key][1]
    if kind == 'preview':
        identity = _file_sha256(path)
    else:
        identity = _array_identity(np.load(path, mmap_mode='r', allow_pickle=False))
    if cache is not None:
        cache[key] = (version, identity)
    return identity


def _verify_segmentation_cache(
    cache_path:str, metadata:dict, identity_cache:tp.Optional[dict]=None
) -> None:
    """Do not export a run under a profile whose cached masks have changed."""
    if not metadata.get('run_id'):
        return  # Older pair-named results had no saved profile to check.
    profile = metadata.get('run_profile')
    if (not isinstance(profile, dict)
            or profile.get('schema') != TRACKING_PROFILE_SCHEMA
            or profile.get('profile_id') != _tracking_profile_id(profile)):
        raise ValueError('Tracking result profile is incomplete. Run tracking again before exporting.')
    segmentations = profile.get('segmentations')
    previews = profile.get('segmentation_previews')
    if (not isinstance(segmentations, list) or len(segmentations) != 2
            or not isinstance(previews, list) or len(previews) != 2):
        raise ValueError('Tracking result profile is incomplete. Run tracking again before exporting.')
    for index in (0, 1):
        preview_name = metadata.get('segmentation{}'.format(index))
        array_name = metadata.get('segmentation_array{}'.format(index))
        expected_preview = previews[index]
        if (not isinstance(preview_name, str) or not isinstance(array_name, str)
                or os.path.basename(preview_name) != preview_name
                or os.path.basename(array_name) != array_name
                or not array_name.endswith('.npy')
                or not isinstance(expected_preview, dict)
                or expected_preview.get('name') != preview_name):
            raise ValueError('Tracking segmentation cache is incomplete. Run tracking again before exporting.')
        preview_path = os.path.join(cache_path, preview_name)
        array_path = os.path.join(cache_path, array_name)
        try:
            preview_hash = _cached_file_identity(preview_path, 'preview', identity_cache)
            array_identity = _cached_file_identity(array_path, 'array', identity_cache)
        except (OSError, EOFError, ValueError) as error:
            raise ValueError(
                'Tracking segmentation cache is unavailable. Run tracking again before exporting.'
            ) from error
        if (preview_hash != expected_preview.get('sha256')
                or array_identity != segmentations[index]):
            raise ValueError(
                'Tracking segmentation cache changed after this run. '
                'Run tracking again before exporting.'
            )


def collect_result_files(
    filename0:str, filename1:str, run_id:tp.Optional[str]=None,
    identity_cache:tp.Optional[dict]=None,
) -> tp.Optional[tp.List[str]]:
    cache_path = paths.get_cache_path()
    loaded = _pair_result_metadata(filename0, filename1, run_id)
    if loaded is None:
        return None
    metadata_path, metadata = loaded
    if metadata.get('status') == 'skipped':
        return None

    segmentation0 = metadata.get('segmentation0', filename0 + '.segmentation.cache.png')
    segmentation1 = metadata.get('segmentation1', filename1 + '.segmentation.cache.png')
    growthmap = metadata.get('growthmap', f'{filename0}.{filename1}.growthmap.png')
    files = [
        os.path.join(cache_path, os.path.basename(segmentation0)),
        os.path.join(cache_path, os.path.basename(segmentation1)),
        os.path.join(cache_path, os.path.basename(growthmap)),
        os.path.join(cache_path, os.path.basename(
            metadata.get('statistics_file', f'{filename0}.{filename1}.csv')
        )),
        metadata_path,

    ]
    if all(map(os.path.exists, files)):
        _verify_segmentation_cache(cache_path, metadata, identity_cache)
        return files
    #else: return None


def _selected_pair(pair:tp.Sequence[str]) -> tp.Tuple[str, str, tp.Optional[str]]:
    if not isinstance(pair, (list, tuple)) or len(pair) not in {2, 3}:
        raise ValueError('A tracking selection must contain two image names and an optional result ID.')
    filename0, filename1 = pair[:2]
    run_id = validate_tracking_run_id(pair[2]) if len(pair) == 3 else None
    return filename0, filename1, run_id


def _selected_csv_path(filename0:str, filename1:str, run_id:tp.Optional[str]) -> str:
    cache_path = paths.get_cache_path()
    loaded = _pair_result_metadata(filename0, filename1, run_id)
    if loaded is None:
        if run_id is not None:
            raise ValueError('Selected tracking result was not found. Run tracking again.')
        return os.path.join(cache_path, f'{filename0}.{filename1}.csv')
    _metadata_path, metadata = loaded
    return os.path.join(cache_path, os.path.basename(
        metadata.get('statistics_file', f'{filename0}.{filename1}.csv')
    ))

def combine_csv_statistics(
    file_pairs:FilePairs, include_index:bool=False
) -> tp.Union[str, tp.Tuple[str, tp.List[dict]]]:
    combined = io.StringIO(newline='')
    writer = csv.writer(combined)
    header_written = False
    row_index = []
    for selection_index, pair in enumerate(file_pairs):
        filename0, filename1, run_id = _selected_pair(pair)
        csv_file = _selected_csv_path(filename0, filename1, run_id)
        with open(csv_file, 'r', newline='') as source:
            rows = list(csv.reader(source))
        if len(rows) < 2:
            warnings.warn('Skipping incomplete tracking CSV: {}'.format(csv_file))
            continue
        if rows[0] != TRACKING_CSV_FIELDS:
            warnings.warn(
                'Skipping tracking CSV with an unsupported or legacy schema: {}'.format(csv_file)
            )
            continue
        loaded = _pair_result_metadata(filename0, filename1, run_id)
        metadata = loaded[1] if loaded is not None else {}
        profile = metadata.get('run_profile')
        if not isinstance(profile, dict):
            profile = {}
        if not header_written:
            writer.writerow(rows[0])
            header_written = True
        for row in rows[1:]:
            if len(row) != len(TRACKING_CSV_FIELDS):
                warnings.warn('Skipping malformed tracking CSV row in {}'.format(csv_file))
                continue
            writer.writerow(row)
            row_index.append({
                'statistics_row': len(row_index) + 1,
                'selection_index': selection_index,
                'filename0': filename0,
                'filename1': filename1,
                'run_id': run_id or metadata.get('run_id'),
                'profile_id': profile.get('profile_id'),
                'sampling_mode': profile.get('sampling_mode'),
                'exclusion_mask_policy': metadata.get('exclusion_mask_policy'),
                'status': row[-1],
            })
    if include_index:
        return combined.getvalue(), row_index
    return combined.getvalue()

    

def compile_results_into_zip(
    file_pairs:FilePairs,
    preparations:tp.Optional[tp.Dict[str, tp.Dict[str, tp.Any]]]=None,
) -> str:
    '''Create a zip file containing the processed tracking results.
       (Doing this here in Python because frontend passes out if too many files)'''
    
    cache_path = paths.get_cache_path()
    selected_pairs = []
    selected_records = []
    pair_exclusion_masks = []
    segmentation_identities = {}
    for pair in file_pairs:
        filename0, filename1, run_id = _selected_pair(pair)
        loaded = _pair_result_metadata(filename0, filename1, run_id)
        if run_id is not None and loaded is None:
            raise ValueError('Selected tracking result was not found. Run tracking again.')
        metadata = loaded[1] if loaded is not None else {}
        effective_id = run_id or metadata.get('run_id')
        result_files = collect_result_files(
            filename0, filename1, run_id, segmentation_identities
        )
        if effective_id is not None and result_files is None:
            raise ValueError('Selected tracking result files are incomplete. Run tracking again.')
        csv_path = _selected_csv_path(filename0, filename1, run_id)
        if not os.path.isfile(csv_path):
            raise ValueError('Selected tracking statistics are missing. Run tracking again.')
        selected_pairs.append((filename0, filename1, effective_id))
        selected_records.append((filename0, filename1, effective_id, result_files))
        if result_files is not None:
            pair_entry = {
                'filename0': filename0,
                'filename1': filename1,
                'policy': metadata.get(
                    'exclusion_mask_policy', DEFAULT_EXCLUSION_MASK_POLICY
                ),
                'masks': metadata.get('exclusion_masks'),
                'matcher': metadata.get('tracking_matcher'),
            }
            if metadata.get('run_id'):
                pair_entry['run_id'] = metadata['run_id']
                pair_entry['run_profile'] = metadata.get('run_profile')
            pair_exclusion_masks.append(pair_entry)

    # Parse statistics before creating an archive, so malformed/missing input
    # cannot leave a seemingly complete ZIP at the final download path.
    combined_stats, statistics_rows = combine_csv_statistics(
        file_pairs, include_index=True
    )
    selection_json = json.dumps({
        'pairs': selected_pairs, 'preparations': preparations or {},
    }, sort_keys=True, separators=(',', ':')).encode('utf-8')
    archive_id = hashlib.sha256(selection_json).hexdigest()[:24]
    resultpath = os.path.join(cache_path, 'tracking_results.{}.zip'.format(archive_id))
    if (all(run_id is not None for _first, _second, run_id in selected_pairs)
            and os.path.isfile(resultpath) and zipfile.is_zipfile(resultpath)):
        return os.path.basename(resultpath)
    handle, temporary_path = tempfile.mkstemp(
        prefix='.tracking-results-', suffix='.zip', dir=cache_path
    )
    os.close(handle)
    try:
        with zipfile.ZipFile(temporary_path, 'w') as resultzip:
            if preparations:
                resultzip.writestr(
                    'preparation-manifest.json',
                    json.dumps({
                        'schema': 1,
                        'preparations': [preparations[name] for name in sorted(preparations)],
                    }, indent=2, sort_keys=True),
                )
            for filename0, filename1, run_id, result_files in selected_records:
                if result_files is None:
                    continue
                outputname = f'{filename0}.{filename1}'
                if run_id is not None:
                    outputname += '.' + run_id
                archive_names = [
                    filename0 + '.segmentation.cache.png',
                    filename1 + '.segmentation.cache.png',
                ] + [os.path.basename(path) for path in result_files[2:]]
                for path, archive_name in zip(result_files, archive_names):
                    resultzip.write(path, '{}/{}'.format(outputname, archive_name))
            resultzip.writestr('statistics.csv', combined_stats)
            resultzip.writestr(
                'tracking-results-manifest.json',
                json.dumps({
                    'tracking_csv_schema': TRACKING_CSV_SCHEMA,
                    'exclusion_mask_coordinate_system': 'observation1',
                    'pair_exclusion_masks': pair_exclusion_masks,
                    'statistics_rows': statistics_rows,
                    'tracking_matcher_schema': 2,
                    'migration_warning': (
                        'Tracking CSV files exported by RootDetector before schema 2 may have '
                        'background, mask, same, decay, and growth values under incorrect headers. '
                        'Re-export those analyses before comparing or aggregating them.'
                    ),
                }, indent=2, sort_keys=True),
            )
        # Inputs can be refreshed while the archive is being written. Check
        # once more before publishing the completed ZIP under its final name.
        for _first, _second, run_id, _files in selected_records:
            if run_id is not None:
                loaded = _pair_result_metadata(_first, _second, run_id)
                if loaded is None:
                    raise ValueError('Selected tracking result was removed. Run tracking again.')
                _verify_segmentation_cache(cache_path, loaded[1], segmentation_identities)
        os.replace(temporary_path, resultpath)
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)
    return os.path.basename(resultpath)
