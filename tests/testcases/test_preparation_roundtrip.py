import io
import json
import zipfile
import os

import numpy as np
import PIL.Image
import pytest
from werkzeug.datastructures import FileStorage

from backend import preparation, security, root_detection
from types import SimpleNamespace
from backend.app import App


def upload(name, contents):
    return FileStorage(stream=io.BytesIO(contents), filename=name)


def fixture(tmp_path):
    original = tmp_path / 'Tube_04.04.24_scan.png'
    pixels = np.arange(48 * 32, dtype='uint32').reshape(32, 48).astype('uint8')
    PIL.Image.fromarray(pixels).save(str(original))
    metadata = preparation.inspect_source(str(original), original.name, str(tmp_path / 'preview.png'))
    crop = tmp_path / 'prepared.png'
    record = preparation.apply_crop(str(original), metadata, {'left': 5, 'top': 7, 'width': 13, 'height': 11}, str(crop))
    return original, crop, record


def prepared_zip(crop, record, extra=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('preparation-manifest.json', json.dumps({'schema': 1, 'preparations': [record]}))
        archive.writestr(record['output_name'], crop.read_bytes())
        if extra:
            archive.writestr(extra, b'bad')
    return upload('RootDetector-prepared-images.zip', output.getvalue())


@pytest.mark.parametrize('zipped', [False, True])
def test_prepared_roundtrip_preserves_bytes_and_manifest(tmp_path, monkeypatch, zipped):
    monkeypatch.setattr(preparation, 'MIN_ANALYSIS_DIMENSION', 1)
    _original, crop, record = fixture(tmp_path)
    inputs = [prepared_zip(crop, record)] if zipped else [
        upload(record['output_name'], crop.read_bytes()),
        upload('preparation-manifest.json', json.dumps({'schema': 1, 'preparations': [record]}).encode()),
    ]
    result = preparation.restore_prepared_files(inputs, str(tmp_path))
    assert result['files'][0]['manifest'] == record
    assert (tmp_path / result['files'][0]['output']).read_bytes() == crop.read_bytes()
    assert not list(tmp_path.glob('.prepared-import-*'))


@pytest.mark.parametrize('failure', ['changed', 'missing_manifest', 'duplicate', 'traversal', 'expanded_budget', 'extra', 'invalid_json'])
def test_prepared_import_rejects_invalid_bundle_and_cleans_staging(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(preparation, 'MIN_ANALYSIS_DIMENSION', 1)
    _original, crop, record = fixture(tmp_path)
    if failure == 'changed':
        crop.write_bytes(b'changed')
    if failure == 'expanded_budget':
        monkeypatch.setattr(preparation, 'MAX_SOURCE_BYTES', 8)
    extra = {'duplicate': record['output_name'], 'traversal': '../escape.png', 'extra': 'extra.png'}.get(failure)
    files = [prepared_zip(crop, record, extra)]
    if failure == 'missing_manifest':
        files = [upload(record['output_name'], crop.read_bytes())]
    if failure == 'invalid_json':
        files = [upload('preparation-manifest.json', b'[]'), upload(record['output_name'], crop.read_bytes())]
    with pytest.raises(security.ValidationError):
        preparation.restore_prepared_files(files, str(tmp_path))
    assert not list(tmp_path.glob('.prepared-import-*'))
    assert not list(tmp_path.glob('prepare-restored-*'))


@pytest.mark.parametrize('mode', ['L', 'P'])
def test_original_coordinate_mask_crop_preserves_values_and_palette(tmp_path, mode):
    original, crop, record = fixture(tmp_path)
    mask = PIL.Image.open(str(original)).convert(mode)
    if mode == 'P':
        mask.putpalette([channel for value in range(256) for channel in (value, 255 - value, value)])
    encoded = io.BytesIO()
    mask.save(encoded, format='PNG')
    destination = tmp_path / 'cropped-mask.png'
    manifest = preparation.transform_companion(
        upload('Tube_04.04.24_scan.png', encoded.getvalue()), record, str(crop), str(destination), confirmed=True,
    )
    with PIL.Image.open(str(destination)) as actual:
        np.testing.assert_array_equal(np.asarray(actual), np.asarray(mask)[7:18, 5:18])
        assert actual.mode == mode
        if mode == 'P':
            assert actual.getpalette() == mask.getpalette()
    assert manifest['operation'] == 'pixel_preserving_crop'
    assert manifest['user_confirmed_original_coordinates'] is True
    assert manifest['preparation_id'] == record['preparation_id']
    assert manifest['output_sha256'] == security.sha256(str(destination))


def test_companion_requires_confirmation_or_exact_prepared_dimensions(tmp_path):
    original, crop, record = fixture(tmp_path)
    destination = tmp_path / 'mask.png'
    with pytest.raises(security.ValidationError, match='Confirm') as error:
        preparation.transform_companion(upload('mask.png', original.read_bytes()), record, str(crop), str(destination))
    assert error.value.code == 'companion_confirmation_required'
    assert not destination.exists()
    provenance = preparation.transform_companion(upload('mask.png', crop.read_bytes()), record, str(crop), str(destination))
    assert provenance['operation'] == 'already_prepared_mask'
    small = io.BytesIO()
    PIL.Image.new('L', (4, 3)).save(small, format='PNG')
    with pytest.raises(security.ValidationError, match='dimensions'):
        preparation.transform_companion(upload('mask.png', small.getvalue()), record, str(crop), str(destination), confirmed=True)
    assert not list(tmp_path.glob('.prepare-mask-*'))


def test_companion_rejects_stale_prepared_identity_and_high_bit_mask(tmp_path):
    _original, crop, record = fixture(tmp_path)
    high = io.BytesIO()
    PIL.Image.new('I;16', (48, 32)).save(high, format='TIFF')
    with pytest.raises(security.ValidationError, match='8-bit'):
        preparation.transform_companion(upload('mask.tiff', high.getvalue()), record, str(crop), str(tmp_path / 'out.png'), confirmed=True)
    crop.write_bytes(b'stale')
    with pytest.raises(security.ValidationError, match='hash'):
        preparation.transform_companion(upload('mask.tiff', high.getvalue()), record, str(crop), str(tmp_path / 'out.png'), confirmed=True)


def test_preparation_import_validate_and_mask_routes(tmp_path, monkeypatch):
    class Settings:
        active_models = {}
        models = {}
        use_gpu = False
        def get_settings_as_dict(self):
            return {'settings': {}, 'available_models': {}}
    monkeypatch.setenv('ROOT_PATH', os.getcwd())
    monkeypatch.setenv('INSTANCE_PATH', str(tmp_path))
    monkeypatch.setenv('DO_NOT_RELOAD', '1')
    monkeypatch.setattr('backend.settings.ensure_pretrained_models', lambda: None)
    monkeypatch.setattr('backend.settings.Settings', Settings)
    monkeypatch.setattr(preparation, 'MIN_ANALYSIS_DIMENSION', 1)
    app = App()
    app.testing = True
    client = app.test_client()
    headers = {'Host': 'localhost', 'Origin': 'http://localhost', 'X-RootDetector-Token': app.session_token}
    original, crop, record = fixture(tmp_path)
    denied = client.post('/api/preparation/import', data={'files': (prepared_zip(crop, record).stream, 'prepared.zip')}, headers={'Host': 'localhost'})
    assert denied.status_code == 403
    imported = client.post('/api/preparation/import', data={'files': (prepared_zip(crop, record).stream, 'prepared.zip')}, headers=headers)
    assert imported.status_code == 200
    restored = imported.get_json()['files'][0]
    assert restored['manifest'] == record
    assert client.get('/images/' + restored['output']).data == crop.read_bytes()
    assert client.post('/file_upload', data={'files': (io.BytesIO(crop.read_bytes()), record['output_name'])}, headers=headers).status_code == 200
    checked = client.post('/api/preparation/validate', json={'filename': record['output_name'], 'manifest': record, 'companions': []}, headers=headers)
    assert checked.status_code == 200
    assert checked.get_json()['manifest'] == record
    data = {'prepared_filename': record['output_name'], 'manifest': json.dumps(record), 'kind': 'training_annotation'}
    unconfirmed = client.post('/api/preparation/companion', data={**data, 'files': (io.BytesIO(original.read_bytes()), original.name)}, headers=headers)
    assert unconfirmed.status_code == 400
    assert unconfirmed.get_json()['code'] == 'companion_confirmation_required'
    confirmed = client.post('/api/preparation/companion', data={**data, 'confirmed': 'true', 'files': (io.BytesIO(original.read_bytes()), original.name)}, headers=headers)
    assert confirmed.status_code == 200
    provenance = confirmed.get_json()['provenance']
    rechecked = client.post('/api/preparation/validate', json={'filename': record['output_name'], 'manifest': record, 'companions': [provenance]}, headers=headers)
    assert rechecked.status_code == 200
    assert rechecked.get_json()['companions'] == [provenance]
    exclusion = client.post('/api/preparation/companion', data={
        **data, 'kind': 'exclusion_mask', 'confirmed': 'true',
        'files': (io.BytesIO(original.read_bytes()), original.name),
    }, headers=headers)
    assert exclusion.status_code == 200
    exclusion_record = exclusion.get_json()['provenance']
    canonical = os.path.join(app.cache_path, os.path.splitext(record['output_name'])[0] + '.exclusionmask.png')
    assert os.path.isfile(canonical)
    os.remove(canonical)  # Simulate a fresh input set before restoring an exported companion.
    restored_mask = client.post('/api/preparation/validate', json={
        'filename': record['output_name'], 'manifest': record,
        'companions': [provenance, exclusion_record], 'restore_exclusion_masks': True,
    }, headers=headers)
    assert restored_mask.status_code == 200
    assert security.sha256(canonical) == exclusion_record['output_sha256']
    with open(os.path.join(app.cache_path, provenance['output_name']), 'wb') as target:
        target.write(b'changed')
    stale = client.post('/api/preparation/validate', json={'filename': record['output_name'], 'manifest': record, 'companions': [provenance]}, headers=headers)
    assert stale.status_code == 400


def test_bound_exclusion_mask_is_used_by_fresh_detection_cache(tmp_path):
    original, crop, record = fixture(tmp_path)
    image_path = tmp_path / record['output_name']
    image_path.write_bytes(crop.read_bytes())
    transformed = tmp_path / 'prepare-companion-unit.png'
    companion = preparation.transform_companion(
        upload(original.name, original.read_bytes()), record, str(image_path), str(transformed),
        confirmed=True, kind='exclusion_mask',
    )
    canonical = preparation.bind_exclusion_companion(companion, record, str(tmp_path))
    assert (tmp_path / canonical).read_bytes() == transformed.read_bytes()
    computed = root_detection.maybe_compute_exclusionmask(str(image_path), SimpleNamespace(exmask_enabled=False))
    with PIL.Image.open(str(crop)) as expected:
        np.testing.assert_array_equal(computed, np.asarray(expected) > 0)
    original_bound_bytes = (tmp_path / canonical).read_bytes()
    transformed.write_bytes(b'changed')
    with pytest.raises(security.ValidationError, match='changed'):
        preparation.bind_exclusion_companion(companion, record, str(tmp_path))
    assert (tmp_path / canonical).read_bytes() == original_bound_bytes
