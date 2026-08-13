import csv
import io
import os

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


def test_combined_tracking_csv_uses_first_valid_header(tmp_path, monkeypatch):
    monkeypatch.setattr(root_tracking.paths, 'get_cache_path', lambda: str(tmp_path))
    first = ('broken-a.png', 'broken-b.png')
    second = ('good,a.png', 'good-b.png')
    with open(os.path.join(str(tmp_path), '{}.{}.csv'.format(*first)), 'w') as output:
        output.write('incomplete\n')
    with open(os.path.join(str(tmp_path), '{}.{}.csv'.format(*second)), 'w') as output:
        output.write(root_tracking.statistics_to_csv({}, second[0], second[1], True))

    rows = list(csv.reader(io.StringIO(root_tracking.combine_csv_statistics([first, second]))))
    assert rows[0][0:2] == ['Filename 1', 'Filename 2']
    assert rows[1][0:2] == list(second)
