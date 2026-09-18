import json
import os

import numpy as np
import PIL.Image
import pytest

from backend import root_tracking


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
    assert metadata['exclusion_mask_policy'] == 'first'
    assert metadata['exclusion_masks']['combined_pixels'] == 1
    assert metadata['tracking_matcher']['version'] == 2
    assert metadata['tracking_matcher']['seed_identity']['image0_sha256']


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
