import json
import os

import numpy as np
import PIL.Image
import pytest

from backend import root_tracking


@pytest.mark.parametrize('policy, expected', [
    ('union', [[True, True], [False, False]]),
    ('intersection', [[False, False], [False, False]]),
    ('first', [[True, False], [False, False]]),
    ('second', [[False, True], [False, False]]),
])
def test_combine_exclusion_masks_has_explicit_policies(policy, expected):
    first = np.asarray([[1.0, 0.0], [0.0, 0.0]])
    second = np.asarray([[0.0, 1.0], [0.0, 0.0]])
    combined = root_tracking.combine_exclusion_masks(first, second, policy)
    assert combined.tolist() == expected


def test_exclusion_mask_policy_and_shape_are_validated():
    with pytest.raises(ValueError, match='Choose one of'):
        root_tracking.combine_exclusion_masks(np.zeros((2, 2)), None, 'implicit')
    with pytest.raises(ValueError, match='shape'):
        root_tracking.combine_exclusion_masks(
            np.zeros((2, 2)),
            np.zeros((3, 3)),
            'union',
            (2, 2),
        )


@pytest.mark.parametrize('policy', ['union', 'intersection'])
@pytest.mark.parametrize('missing', ['first', 'second'])
def test_combined_policy_rejects_one_missing_mask(policy, missing):
    mask = np.zeros((2, 2), dtype='float32')
    first = None if missing == 'first' else mask
    second = None if missing == 'second' else mask
    with pytest.raises(ValueError, match='needs masks for both observations'):
        root_tracking.combine_exclusion_masks(first, second, policy)


@pytest.mark.parametrize('policy', ['union', 'intersection'])
def test_combined_policy_without_either_mask_preserves_optional_masking(policy):
    assert root_tracking.combine_exclusion_masks(None, None, policy) is None


@pytest.mark.parametrize('policy, requested', [
    ('first', ['first']),
    ('second', ['second']),
    ('union', ['first', 'second']),
    ('intersection', ['first', 'second']),
])
def test_exclusion_policy_loads_only_required_masks(monkeypatch, policy, requested):
    calls = []
    monkeypatch.setattr(
        root_tracking,
        'ensure_exclusionmask',
        lambda path, _settings: calls.append(path) or np.zeros((2, 2)),
    )
    root_tracking.ensure_pair_exclusion_masks('first', 'second', object(), policy)
    assert calls == requested


@pytest.mark.parametrize('policy', ['union', 'intersection'])
def test_combined_policy_detects_missing_mask_before_matching(monkeypatch, policy):
    monkeypatch.setattr(
        root_tracking,
        'ensure_exclusionmask',
        lambda path, _settings: np.zeros((2, 2)) if path == 'first' else None,
    )
    with pytest.raises(ValueError, match='needs masks for both observations'):
        root_tracking.ensure_pair_exclusion_masks('first', 'second', object(), policy)


def test_tracking_pair_shapes_are_validated_before_matching():
    assert root_tracking.validate_tracking_pair_shapes(
        np.zeros((48, 52)),
        np.zeros((48, 52)),
    ) == (48, 52)

    with pytest.raises(ValueError, match='identical pixel dimensions') as error:
        root_tracking.validate_tracking_pair_shapes(
            np.zeros((48, 52)),
            np.zeros((47, 52)),
        )
    assert 'align and crop copies' in str(error.value)

    with pytest.raises(ValueError, match='two-dimensional'):
        root_tracking.validate_tracking_pair_shapes(
            np.zeros((2, 2, 3)),
            np.zeros((2, 2)),
        )


def test_tracking_uses_released_observation0_mask_and_exports_provenance(tmp_path, monkeypatch):
    image0 = str(tmp_path / 'observation0.png')
    image1 = str(tmp_path / 'observation1.png')
    PIL.Image.new('RGB', (2, 2)).save(image0)
    PIL.Image.new('RGB', (2, 2)).save(image1)

    segmentation = np.ones((2, 2), dtype='float32')
    mask_requests = []
    monkeypatch.setattr(
        root_tracking,
        'ensure_segmentation',
        lambda path, _settings: (path + '.soft.png', segmentation.copy()),
    )
    def ensure_exclusionmask(path, _settings):
        mask_requests.append(path)
        return np.asarray([[1.0, 0.0], [0.0, 0.0]], dtype='float32')

    monkeypatch.setattr(root_tracking, 'ensure_exclusionmask', ensure_exclusionmask)
    monkeypatch.setattr(root_tracking.paths, 'get_cache_path', lambda: str(tmp_path))

    points = np.arange(32, dtype='float32').reshape(16, 2)
    captured = []
    monkeypatch.setattr(
        root_tracking.tracking_matcher,
        'match_images',
        lambda *_args, **kwargs: captured.append(kwargs['sampling_seed']) or {
            'points0': points,
            'points1': points,
            'matched_percentage': 1.0,
        },
    )

    class MatchModel:
        def interpolation_map(self, *_args, **_kwargs):
            yy, xx = np.indices((2, 2), dtype='float32')
            return np.stack([yy, xx], axis=-1)

        def warp(self, value, _imap):
            return np.asarray(value)

        def create_growth_map_rgba(self, _first, _second):
            return np.broadcast_to(root_tracking.COLORS.SAME, (2, 2, 4)).copy()

    class Settings:
        models = {'tracking': MatchModel()}
        active_models = {'tracking': 'tracking-a', 'detection': 'detection-a'}
        use_gpu = False
        too_many_roots = 100000
        tracking_sampling_mode = 'deterministic'

    result = root_tracking.process(image0, image1, Settings())
    assert mask_requests == [image0]
    assert result['statistics']['sum_exmask'] == 1
    assert result['exclusion_mask_policy'] == 'first'
    assert result['tracking_matcher']['name'] == 'rootdetector-cancellable-bruteforce'
    assert isinstance(captured[0], int)
    assert result['tracking_matcher']['seed'] == captured[0]
    assert len(result['run_id']) == 32
    assert result['run_profile']['sampling_mode'] == 'deterministic'
    assert result['run_profile']['exclusion_mask_policy'] == 'first'
    assert result['run_profile']['match_device'] == 'cpu'
    assert result['exclusion_masks'] == {
        'observation0_present': True,
        'observation1_present': False,
        'observation0_pixels': 1,
        'observation1_pixels': 0,
        'combined_pixels': 1,
    }

    metadata_path = tmp_path / '{}.{}.json'.format(
        os.path.basename(image0),
        os.path.basename(image1),
    )
    metadata = json.loads(metadata_path.read_text())
    assert metadata['run_id'] == result['run_id']
    assert metadata['run_profile']['profile_id'] == result['run_profile']['profile_id']
    assert (tmp_path / '{}.{}.{}.json'.format(
        os.path.basename(image0), os.path.basename(image1), result['run_id']
    )).exists()
    assert metadata['exclusion_mask_policy'] == 'first'
    assert metadata['exclusion_masks']['combined_pixels'] == 1
    assert metadata['tracking_matcher']['version'] == 2
    assert metadata['tracking_matcher']['seed_identity']['image0_sha256']

    Settings.tracking_sampling_mode = 'legacy'
    original = root_tracking.process(image0, image1, Settings())
    assert captured[-1] is None
    assert original['run_id'] != result['run_id']
    assert original['run_profile']['profile_id'] != result['run_profile']['profile_id']
    assert original['growthmap'] != result['growthmap']
    assert os.path.isfile(result['growthmap'])
    assert os.path.isfile(original['growthmap'])
    assert json.loads(metadata_path.read_text())['run_id'] == original['run_id']

    saved = {
        'filename0': os.path.basename(image0),
        'filename1': os.path.basename(image1),
        'points0': original['points0'].tolist(),
        'points1': original['points1'].tolist(),
        'corrections': [[0, 0, 1, 1]],
        'n_matched_points': original['n_matched_points'],
        'tracking_model': original['tracking_model'],
        'segmentation_model': original['segmentation_model'],
        'tracking_matcher': original['tracking_matcher'],
        'run_id': original['run_id'],
        'run_profile': original['run_profile'],
        'match_device': original['match_device'],
    }
    corrected = root_tracking.process(image0, image1, Settings(), saved)
    assert corrected['run_id'] not in {result['run_id'], original['run_id']}
    assert len(corrected['points0']) == len(original['points0']) + 1
    assert os.path.isfile(original['growthmap'])

    # Older imported results lacked a result ID and can recompute the prior map.
    legacy_import = dict(saved)
    legacy_import.pop('run_id')
    legacy_import.pop('run_profile')
    legacy_import.pop('match_device')
    legacy_import.pop('tracking_matcher')
    imported_correction = root_tracking.process(image0, image1, Settings(), legacy_import)
    assert len(imported_correction['points0']) == len(original['points0']) + 1
    assert imported_correction['tracking_matcher']['version'] == 0

    # Existing local corrections still reuse the original pair-named map.
    original_map_path = '{}.{}.imap.npy'.format(image0, os.path.basename(image1))
    old_map = np.ones((2, 2, 2), dtype='float32')
    np.save(original_map_path, old_map)
    local_correction = root_tracking.process(image0, image1, Settings(), legacy_import)
    assert local_correction['points0'][-1].tolist() == [1.0, 1.0]


def test_deterministic_seed_follows_contents_and_model_identity(tmp_path, monkeypatch):
    first = tmp_path / 'first.png'
    second = tmp_path / 'second.png'
    first.write_bytes(b'first observation')
    second.write_bytes(b'second observation')
    models = {'tracking': {'name': 'tracking-a'}, 'detection': {'name': 'detection-a'}}
    monkeypatch.setattr(
        root_tracking.root_detection,
        '_model_identity',
        lambda _settings, kind: models[kind].copy(),
    )
    first_seg = np.zeros((4, 4), dtype='float32')
    second_seg = np.ones((4, 4), dtype='float32')
    seed, identity = root_tracking.deterministic_sampling_seed(
        str(first), str(second), first_seg, second_seg, object()
    )
    repeated, repeated_identity = root_tracking.deterministic_sampling_seed(
        str(first), str(second), first_seg, second_seg, object()
    )
    assert (seed, identity) == (repeated, repeated_identity)
    assert seed != root_tracking.deterministic_sampling_seed(
        str(second), str(first), second_seg, first_seg, object()
    )[0]
    modified_seg = first_seg.copy()
    modified_seg[0, 0] = 1
    assert seed != root_tracking.deterministic_sampling_seed(
        str(first), str(second), modified_seg, second_seg, object()
    )[0]
    first.write_bytes(b'changed first observation')
    assert seed != root_tracking.deterministic_sampling_seed(
        str(first), str(second), first_seg, second_seg, object()
    )[0]
    first.write_bytes(b'first observation')
    models['tracking']['name'] = 'tracking-b'
    assert seed != root_tracking.deterministic_sampling_seed(
        str(first), str(second), first_seg, second_seg, object()
    )[0]
    with pytest.raises(ValueError, match='sampling mode'):
        root_tracking.validate_tracking_sampling_mode([])


def test_saved_tracking_points_require_matching_pair_model_and_sampling(tmp_path, monkeypatch):
    first = tmp_path / 'first.png'
    second = tmp_path / 'second.png'
    first.write_bytes(b'first')
    second.write_bytes(b'second')
    segmentation = np.zeros((2, 2), dtype='float32')

    class Settings:
        active_models = {'tracking': 'track-a', 'detection': 'detect-a'}

    saved = {
        'filename0': first.name,
        'filename1': second.name,
        'tracking_model': 'track-a',
        'segmentation_model': 'detect-a',
    }
    def validate(data, mode):
        root_tracking.validate_previous_tracking_data(
            data, str(first), str(second), segmentation, segmentation, Settings(), mode
        )
    # Older exports without matcher metadata remain correctable in original mode.
    validate(saved, 'legacy')
    with pytest.raises(ValueError, match='different image pair'):
        validate(dict(saved, filename1='another.png'), 'legacy')
    with pytest.raises(ValueError, match='different tracking model'):
        validate(dict(saved, tracking_model='track-b'), 'legacy')
    with pytest.raises(ValueError, match='different sampling mode'):
        validate(saved, 'deterministic')

    monkeypatch.setattr(
        root_tracking, 'deterministic_sampling_seed',
        lambda *_args: (12345, {'input': 'expected'}),
    )
    seeded = dict(saved, tracking_matcher={
        'version': 2,
        'seed': 12345,
        'seed_identity': {'input': 'expected'},
    })
    validate(seeded, 'deterministic')
    with pytest.raises(ValueError, match='do not match these images'):
        validate(
            dict(seeded, tracking_matcher=dict(seeded['tracking_matcher'], seed=1)),
            'deterministic',
        )
    with pytest.raises(ValueError, match='different sampling mode'):
        validate(seeded, 'legacy')

    profile = root_tracking.tracking_run_profile(
        str(first), str(second), segmentation, segmentation,
        None, None, Settings(), 'legacy', 'first', 'cpu', {'version': 1},
    )
    profiled = dict(saved, run_id='a' * 32, run_profile=profile,
                    tracking_matcher={'version': 1})
    validate(profiled, 'legacy')
    with pytest.raises(ValueError, match='unknown profile metadata'):
        validate(dict(profiled, run_profile=dict(profile, sampling_mode='deterministic')),
                 'legacy')
    first.write_bytes(b'changed first')
    with pytest.raises(ValueError, match='do not match these images'):
        validate(profiled, 'legacy')


def test_tracking_run_profile_separates_sampling_and_mask_choices(tmp_path, monkeypatch):
    first, second = tmp_path / 'first.png', tmp_path / 'second.png'
    first.write_bytes(b'first')
    second.write_bytes(b'second')
    monkeypatch.setattr(
        root_tracking.root_detection, '_model_identity',
        lambda _settings, kind: {'name': kind + '-a'},
    )
    segmentation = np.zeros((2, 2), dtype='float32')
    mask = np.ones((2, 2), dtype='float32')
    args = (
        str(first), str(second), segmentation, segmentation,
        mask, None, object(),
    )
    original = root_tracking.tracking_run_profile(
        *args, 'legacy', 'first', 'cpu', {'version': 1}
    )
    assert original == root_tracking.tracking_run_profile(
        *args, 'legacy', 'first', 'cpu', {'version': 1}
    )
    seeded = root_tracking.tracking_run_profile(
        *args, 'deterministic', 'first', 'cpu', {'version': 2, 'seed': 123}
    )
    second_mask = root_tracking.tracking_run_profile(
        *args, 'legacy', 'second', 'cpu', {'version': 1}
    )
    assert len({original['profile_id'], seeded['profile_id'], second_mask['profile_id']}) == 3
    assert root_tracking._tracking_profile_id(original) == original['profile_id']
    assert root_tracking._tracking_profile_id(dict(original, sampling_mode='deterministic')) != original['profile_id']
    first.write_bytes(b'changed')
    changed = root_tracking.tracking_run_profile(
        *args, 'legacy', 'first', 'cpu', {'version': 1}
    )
    assert changed['profile_id'] != original['profile_id']
