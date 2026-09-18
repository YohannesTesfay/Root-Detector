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


def test_exclusion_mask_union_is_conservative_for_one_available_mask():
    second = np.asarray([[0.0, 0.75], [0.0, 0.0]])
    combined = root_tracking.combine_exclusion_masks(None, second)
    assert combined.tolist() == [[False, True], [False, False]]
    intersection = root_tracking.combine_exclusion_masks(None, second, 'intersection')
    assert not intersection.any()


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


def test_tracking_uses_both_observation_masks_and_exports_provenance(tmp_path, monkeypatch):
    image0 = str(tmp_path / 'observation0.png')
    image1 = str(tmp_path / 'observation1.png')
    PIL.Image.new('RGB', (2, 2)).save(image0)
    PIL.Image.new('RGB', (2, 2)).save(image1)

    segmentation = np.ones((2, 2), dtype='float32')
    masks = {
        image0: np.asarray([[1.0, 0.0], [0.0, 0.0]], dtype='float32'),
        image1: np.asarray([[0.0, 1.0], [0.0, 0.0]], dtype='float32'),
    }
    monkeypatch.setattr(
        root_tracking,
        'ensure_segmentation',
        lambda path, _settings: (path + '.soft.png', segmentation.copy()),
    )
    monkeypatch.setattr(
        root_tracking,
        'ensure_exclusionmask',
        lambda path, _settings: masks[path].copy(),
    )
    monkeypatch.setattr(root_tracking.paths, 'get_cache_path', lambda: str(tmp_path))

    points = np.arange(32, dtype='float32').reshape(16, 2)
    monkeypatch.setattr(
        root_tracking.tracking_matcher,
        'match_images',
        lambda *_args, **_kwargs: {
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
        tracking_exclusion_policy = 'union'

    result = root_tracking.process(image0, image1, Settings())
    assert result['statistics']['sum_exmask'] == 2
    assert result['exclusion_mask_policy'] == 'union'
    assert result['tracking_matcher']['name'] == 'rootdetector-cancellable-bruteforce'
    assert result['exclusion_masks'] == {
        'observation0_present': True,
        'observation1_present': True,
        'observation0_pixels': 1,
        'observation1_pixels': 1,
        'combined_pixels': 2,
    }

    metadata_path = tmp_path / '{}.{}.json'.format(
        os.path.basename(image0),
        os.path.basename(image1),
    )
    metadata = json.loads(metadata_path.read_text())
    assert metadata['exclusion_mask_policy'] == 'union'
    assert metadata['exclusion_masks']['combined_pixels'] == 2
    assert metadata['tracking_matcher']['version'] == 1
