import csv
import io
import os
import json
import zipfile

import numpy as np
import pytest

from backend import root_tracking


def test_tracking_csv_header_matches_values_and_quotes_filenames():
    stats = {
        'sum_same': 11,
        'sum_decay': 12,
        'sum_growth': 13,
        'sum_negative': 14,
        'sum_exmask': 15,
        'sum_same_sk': 16,
        'sum_decay_sk': 17,
        'sum_growth_sk': 18,
        'kimura_same': 19,
        'kimura_decay': 20,
        'kimura_growth': 21,
    }
    csv_text = root_tracking.statistics_to_csv(
        stats,
        'first,image.png',
        'second image.png',
        True,
    )
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    assert len(rows) == 1
    row = rows[0]
    assert row['Filename 1'] == 'first,image.png'
    assert row['same pixels'] == '11'
    assert row['decay pixels'] == '12'
    assert row['growth pixels'] == '13'
    assert row['background pixels'] == '14'
    assert row['mask pixels'] == '15'
    assert row['status'] == 'OK'

    skipped = root_tracking.statistics_to_csv(
        {},
        'first.png',
        'second.png',
        root_tracking.TOO_MANY_ROOTS_ERROR,
    )
    skipped_row = list(csv.DictReader(io.StringIO(skipped)))[0]
    assert skipped_row['status'] == 'SKIPPED: Too many roots'

    quoted = root_tracking.statistics_to_csv(
        stats,
        'first,"line\nimage.png',
        'second image.png',
        True,
    )
    quoted_row = list(csv.DictReader(io.StringIO(quoted)))[0]
    assert quoted_row['Filename 1'] == 'first,"line\nimage.png'


def test_combined_tracking_csv_uses_first_valid_header(tmp_path, monkeypatch):
    monkeypatch.setattr(root_tracking.paths, 'get_cache_path', lambda: str(tmp_path))
    first = ('broken-a.png', 'broken-b.png')
    second = ('good,a.png', 'good-b.png')
    with open(os.path.join(str(tmp_path), '{}.{}.csv'.format(*first)), 'w', encoding='utf-8', newline='') as output:
        output.write('incomplete\n')
    with open(os.path.join(str(tmp_path), '{}.{}.csv'.format(*second)), 'w', encoding='utf-8', newline='') as output:
        output.write(root_tracking.statistics_to_csv({}, second[0], second[1], True))

    with pytest.warns(UserWarning, match='incomplete tracking CSV'):
        combined = root_tracking.combine_csv_statistics([first, second])
    rows = list(csv.reader(io.StringIO(combined)))
    assert rows[0][0:2] == ['Filename 1', 'Filename 2']
    assert rows[1][0:2] == list(second)


def test_combined_tracking_csv_keeps_every_valid_data_row(tmp_path, monkeypatch):
    monkeypatch.setattr(root_tracking.paths, 'get_cache_path', lambda: str(tmp_path))
    pair = ('one.png', 'two.png')
    csv_path = tmp_path / '{}.{}.csv'.format(*pair)
    csv_path.write_bytes((
        root_tracking.statistics_to_csv({}, pair[0], pair[1], True)
        + root_tracking.statistics_to_csv(
            {}, 'three.png', 'four.png', True, include_header=False
        )
    ).encode('utf-8'))
    rows = list(csv.DictReader(io.StringIO(root_tracking.combine_csv_statistics([pair]))))
    assert [(row['Filename 1'], row['Filename 2']) for row in rows] == [
        pair,
        ('three.png', 'four.png'),
    ]


def test_compile_tracking_results_records_schema_and_migration_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(root_tracking.paths, 'get_cache_path', lambda: str(tmp_path))
    pair = ('one.png', 'two.png')
    segmentation0 = tmp_path / 'rootdetector-segmentation-a.png'
    segmentation1 = tmp_path / 'rootdetector-segmentation-b.png'
    growthmap = tmp_path / '{}.{}.growthmap.png'.format(*pair)
    for path in [segmentation0, segmentation1, growthmap]:
        path.write_bytes(b'fixture')
    metadata_path = tmp_path / '{}.{}.json'.format(*pair)
    metadata_path.write_text(json.dumps({
        'segmentation0': segmentation0.name,
        'segmentation1': segmentation1.name,
        'growthmap': growthmap.name,
        'tracking_matcher': {
            'name': 'rootdetector-cancellable-bruteforce',
            'version': 1,
            'batch_size': 512,
        },
        'exclusion_mask_policy': 'first',
        'exclusion_masks': {'combined_pixels': 17},
    }))
    (tmp_path / '{}.{}.csv'.format(*pair)).write_bytes(
        root_tracking.statistics_to_csv({}, pair[0], pair[1], True).encode('utf-8')
    )

    preparation = {'prepared_name': 'one.png', 'roi': {'x': 0, 'y': 0, 'width': 10, 'height': 10}}
    archive_path = tmp_path / root_tracking.compile_results_into_zip(
        [pair], preparations={'one.png': preparation}
    )
    with zipfile.ZipFile(str(archive_path)) as archive:
        manifest = json.loads(archive.read('tracking-results-manifest.json'))
        preparation_manifest = json.loads(archive.read('preparation-manifest.json'))
        assert preparation_manifest == {'schema': 1, 'preparations': [preparation]}
        assert manifest['tracking_csv_schema'] == root_tracking.TRACKING_CSV_SCHEMA
        assert manifest['exclusion_mask_coordinate_system'] == 'observation1'
        assert manifest['pair_exclusion_masks'] == [{
            'filename0': 'one.png',
            'filename1': 'two.png',
            'policy': 'first',
            'masks': {'combined_pixels': 17},
            'matcher': {
                'name': 'rootdetector-cancellable-bruteforce',
                'version': 1,
                'batch_size': 512,
            },
        }]
        assert manifest['tracking_matcher_schema'] == 2
        assert 'incorrect headers' in manifest['migration_warning']
        assert any(name.endswith('one.png.segmentation.cache.png') for name in archive.namelist())


def test_failed_zip_write_cannot_be_reused_as_a_complete_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(root_tracking.paths, 'get_cache_path', lambda: str(tmp_path))
    first, second = 'one.png', 'two.png'
    for name in ('first.segmentation.png', 'second.segmentation.png',
                 'one.png.two.png.growthmap.png'):
        (tmp_path / name).write_bytes(b'fixture')
    (tmp_path / '{}.{}.json'.format(first, second)).write_text(json.dumps({
        'filename0': first,
        'filename1': second,
        'segmentation0': 'first.segmentation.png',
        'segmentation1': 'second.segmentation.png',
        'growthmap': 'one.png.two.png.growthmap.png',
    }))
    (tmp_path / '{}.{}.csv'.format(first, second)).write_bytes(
        root_tracking.statistics_to_csv({}, first, second, True).encode('utf-8')
    )

    original_write = zipfile.ZipFile.write
    attempts = []

    def fail_after_first_file(self, *args, **kwargs):
        attempts.append(1)
        if len(attempts) == 2:
            raise OSError('simulated ZIP write failure')
        return original_write(self, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, 'write', fail_after_first_file)
    with pytest.raises(OSError, match='simulated ZIP write failure'):
        root_tracking.compile_results_into_zip([(first, second)])
    assert list(tmp_path.glob('tracking_results.*.zip')) == []
    assert list(tmp_path.glob('.tracking-results-*.zip')) == []

    monkeypatch.setattr(zipfile.ZipFile, 'write', original_write)
    archive_name = root_tracking.compile_results_into_zip([(first, second)])
    with zipfile.ZipFile(str(tmp_path / archive_name)) as archive:
        assert archive.read('statistics.csv')


def test_tracking_variants_keep_separate_artifacts_and_selected_exports(tmp_path, monkeypatch):
    monkeypatch.setattr(root_tracking.paths, 'get_cache_path', lambda: str(tmp_path))
    first, second = 'one.png', 'two.png'
    for name in ('one.segmentation.png', 'two.segmentation.png'):
        (tmp_path / name).write_bytes(b'segmentation')
        np.save(tmp_path / (name[:-4] + '.npy'), np.zeros((2, 2), dtype='float32'))

    selected = []
    profile_ids = []
    for index, policy in enumerate(('first', 'union'), 1):
        run_id = str(index) * 32
        prefix = '{}.{}.{}'.format(first, second, run_id)
        growthmap = tmp_path / (prefix + '.growthmap.png')
        growthmap.write_bytes(policy.encode('ascii'))
        profile = {
            'schema': root_tracking.TRACKING_PROFILE_SCHEMA,
            'exclusion_mask_policy': policy,
            'segmentations': [
                root_tracking._array_identity(np.zeros((2, 2), dtype='float32'))
                for _ in range(2)
            ],
            'segmentation_previews': [
                {'name': name, 'sha256': root_tracking._file_sha256(str(tmp_path / name))}
                for name in ('one.segmentation.png', 'two.segmentation.png')
            ],
        }
        profile['profile_id'] = root_tracking._tracking_profile_id(profile)
        profile_ids.append(profile['profile_id'])
        output = {
            'run_id': run_id,
            'run_profile': profile,
            'match_device': 'cpu',
            'points0': np.zeros((1, 2)),
            'points1': np.zeros((1, 2)),
            'n_matched_points': 1,
            'tracking_model': 'track-a',
            'segmentation_model': 'detect-a',
            'tracking_matcher': {'name': 'matcher', 'version': index},
            'segmentation0': str(tmp_path / 'one.segmentation.png'),
            'segmentation1': str(tmp_path / 'two.segmentation.png'),
            'growthmap': str(growthmap),
            'exclusion_mask_policy': policy,
            'exclusion_masks': {'combined_pixels': index},
            'statistics': {'sum_same': index},
        }
        root_tracking.cache_output_for_download(first, second, True, output)
        selected.append((first, second, run_id))

    assert json.loads((tmp_path / '{}.{}.json'.format(first, second)).read_text())['run_id'] == selected[-1][2]
    for _first, _second, run_id in selected:
        assert (tmp_path / '{}.{}.{}.json'.format(first, second, run_id)).exists()
        assert (tmp_path / '{}.{}.{}.csv'.format(first, second, run_id)).exists()

    archive_name = root_tracking.compile_results_into_zip(selected)
    with zipfile.ZipFile(str(tmp_path / archive_name)) as archive:
        names = archive.namelist()
        for _first, _second, run_id in selected:
            assert any(name.startswith('{}.{}.{}/'.format(first, second, run_id)) for name in names)
        rows = list(csv.DictReader(io.StringIO(archive.read('statistics.csv').decode('utf-8'))))
        assert [row['same pixels'] for row in rows] == ['1', '2']
        manifest = json.loads(archive.read('tracking-results-manifest.json'))
        assert [item['run_id'] for item in manifest['pair_exclusion_masks']] == [
            pair[2] for pair in selected
        ]
        assert [item['run_id'] for item in manifest['statistics_rows']] == [
            pair[2] for pair in selected
        ]
        assert [item['statistics_row'] for item in manifest['statistics_rows']] == [1, 2]
        assert [item['profile_id'] for item in manifest['statistics_rows']] == profile_ids
        assert [item['run_profile']['exclusion_mask_policy'] for item in manifest['pair_exclusion_masks']] == [
            'first', 'union'
        ]
    assert root_tracking.compile_results_into_zip([selected[0]]) != archive_name
    assert root_tracking.compile_results_into_zip(selected) == archive_name
    latest_name = root_tracking.compile_results_into_zip([(first, second)])
    with zipfile.ZipFile(str(tmp_path / latest_name)) as archive:
        latest = list(csv.DictReader(io.StringIO(archive.read('statistics.csv').decode('utf-8'))))
        assert [row['same pixels'] for row in latest] == ['2']
    assert json.loads((tmp_path / '{}.{}.json'.format(first, second)).read_text())['run_id'] == selected[-1][2]


@pytest.mark.parametrize('index', [0, 1])
@pytest.mark.parametrize('artifact', ['array', 'preview'])
def test_tracking_export_rejects_changed_segmentation_cache(tmp_path, monkeypatch, index, artifact):
    monkeypatch.setattr(root_tracking.paths, 'get_cache_path', lambda: str(tmp_path))
    first, second = 'one.png', 'two.png'
    run_id = 'a' * 32
    previews = [tmp_path / 'one.segmentation.png', tmp_path / 'two.segmentation.png']
    arrays = [tmp_path / 'one.segmentation.npy', tmp_path / 'two.segmentation.npy']
    for preview, array in zip(previews, arrays):
        preview.write_bytes(b'preview')
        np.save(array, np.zeros((2, 2), dtype='float32'))
    profile = {
        'schema': root_tracking.TRACKING_PROFILE_SCHEMA,
        'segmentations': [root_tracking._array_identity(np.load(array)) for array in arrays],
        'segmentation_previews': [
            {'name': preview.name, 'sha256': root_tracking._file_sha256(str(preview))}
            for preview in previews
        ],
    }
    profile['profile_id'] = root_tracking._tracking_profile_id(profile)
    growthmap = tmp_path / '{}.{}.{}.growthmap.png'.format(first, second, run_id)
    growthmap.write_bytes(b'growth map')
    root_tracking.cache_output_for_download(first, second, True, {
        'run_id': run_id, 'run_profile': profile, 'match_device': 'cpu',
        'points0': np.zeros((1, 2)), 'points1': np.zeros((1, 2)),
        'n_matched_points': 1, 'tracking_model': 'track-a',
        'segmentation_model': 'detect-a', 'tracking_matcher': {'version': 1},
        'segmentation0': str(previews[0]), 'segmentation1': str(previews[1]),
        'growthmap': str(growthmap), 'exclusion_mask_policy': 'first',
        'exclusion_masks': {}, 'statistics': {'sum_same': 1},
    })
    selection = [(first, second, run_id)]
    archive_name = root_tracking.compile_results_into_zip(selection)
    assert (tmp_path / archive_name).is_file()
    if artifact == 'array':
        np.save(arrays[index], np.ones((2, 2), dtype='float32'))
    else:
        previews[index].write_bytes(b'changed preview')
    with pytest.raises(ValueError, match='segmentation cache changed'):
        root_tracking.compile_results_into_zip(selection)


def test_skipped_rerun_does_not_export_a_stale_pair_result(tmp_path, monkeypatch):
    monkeypatch.setattr(root_tracking.paths, 'get_cache_path', lambda: str(tmp_path))
    first, second = 'one.png', 'two.png'
    run_id = 'a' * 32
    pair_prefix = '{}.{}'.format(first, second)
    for name in ('one.segmentation.png', 'two.segmentation.png'):
        (tmp_path / name).write_bytes(b'segmentation')
    growthmap = tmp_path / (pair_prefix + '.' + run_id + '.growthmap.png')
    growthmap.write_bytes(b'previous result')
    output = {
        'run_id': run_id,
        'run_profile': {'schema': 1},
        'match_device': 'cpu',
        'points0': np.zeros((1, 2)),
        'points1': np.zeros((1, 2)),
        'n_matched_points': 1,
        'tracking_model': 'track-a',
        'segmentation_model': 'detect-a',
        'tracking_matcher': {'version': 1},
        'segmentation0': str(tmp_path / 'one.segmentation.png'),
        'segmentation1': str(tmp_path / 'two.segmentation.png'),
        'growthmap': str(growthmap),
        'exclusion_mask_policy': 'first',
        'exclusion_masks': {'combined_pixels': 0},
        'statistics': {'sum_same': 1},
    }
    root_tracking.cache_output_for_download(first, second, True, output)
    root_tracking.cache_output_for_download(
        first, second, root_tracking.TOO_MANY_ROOTS_ERROR, {}
    )

    archive_name = root_tracking.compile_results_into_zip([(first, second)])
    with zipfile.ZipFile(str(tmp_path / archive_name)) as archive:
        assert not any(name.endswith('growthmap.png') for name in archive.namelist())
        rows = list(csv.DictReader(io.StringIO(archive.read('statistics.csv').decode('utf-8'))))
        assert rows[0]['status'] == 'SKIPPED: Too many roots'
        manifest = json.loads(archive.read('tracking-results-manifest.json'))
        assert manifest['statistics_rows'][0]['status'] == 'SKIPPED: Too many roots'
        assert manifest['statistics_rows'][0]['run_id'] is None
    assert (tmp_path / (pair_prefix + '.' + run_id + '.json')).exists()


def test_tracking_csv_files_preserve_utf8_and_crlf_on_windows(tmp_path, monkeypatch):
    """Exercise both cache write sites with Windows newline/codepage behavior."""
    monkeypatch.setattr(root_tracking.paths, 'get_cache_path', lambda: str(tmp_path))

    def windows_open(path, mode='r', **kwargs):
        if str(path).endswith('.csv') and 'b' not in mode:
            kwargs.setdefault('encoding', 'cp1252')
            if 'w' in mode:
                kwargs.setdefault('newline', '\r\n')
        return io.open(path, mode, **kwargs)

    monkeypatch.setattr(root_tracking, 'open', windows_open, raising=False)
    first, second = 'one-根.png', 'two-ä.png'
    run_id = 'a' * 32
    root_tracking.cache_output_for_download(
        first, second, root_tracking.TOO_MANY_ROOTS_ERROR, {'run_id': run_id}
    )
    expected = root_tracking.statistics_to_csv(
        {}, first, second, root_tracking.TOO_MANY_ROOTS_ERROR
    ).encode('utf-8')
    for suffix in ('', '.' + run_id):
        raw = (tmp_path / ('{}.{}{}.csv'.format(first, second, suffix))).read_bytes()
        assert raw == expected
        assert b'\r\r\n' not in raw
        rows = list(csv.reader(io.StringIO(raw.decode('utf-8'), newline='')))
        assert len(rows) == 2
        assert rows[1][:2] == [first, second]
    combined = root_tracking.combine_csv_statistics([(first, second)])
    rows = list(csv.reader(io.StringIO(combined, newline='')))
    assert len(rows) == 2
    assert rows[1][:2] == [first, second]
