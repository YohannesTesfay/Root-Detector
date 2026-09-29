import io
import os

import numpy as np
import PIL.Image
import pytest

from backend import preparation
from backend import security
from backend.app import App


def source_image():
    pixels = np.arange(48 * 32 * 3, dtype='uint32').reshape(32, 48, 3) % 256
    return PIL.Image.fromarray(pixels.astype('uint8'), 'RGB')


def encode(image, format_name='TIFF'):
    output = io.BytesIO()
    image.save(output, format=format_name)
    return output.getvalue()


@pytest.mark.parametrize('format_name,extension', [('TIFF', 'tiff'), ('PNG', 'png'), ('JPEG', 'jpg')])
def test_noop_crop_preserves_decoded_pixels_and_source(format_name, extension, tmp_path):
    original = source_image()
    source = tmp_path / ('Tube_04.04.24_scan.' + extension)
    source.write_bytes(encode(original, format_name))
    source_bytes = source.read_bytes()
    preview = tmp_path / 'preview.png'
    metadata = preparation.inspect_source(str(source), source.name, str(preview))
    output = tmp_path / 'crop.png'
    manifest = preparation.apply_crop(
        str(source), metadata,
        {'left': 0, 'top': 0, 'width': 48, 'height': 32},
        str(output),
    )

    with PIL.Image.open(str(source)) as decoded, PIL.Image.open(str(output)) as prepared:
        np.testing.assert_array_equal(np.asarray(prepared), np.asarray(decoded))
    with PIL.Image.open(str(preview)) as thumbnail:
        assert thumbnail.size == (48, 32)
    assert source.read_bytes() == source_bytes
    assert manifest['source']['source_sha256'] == security.sha256(str(source))
    assert manifest['output_sha256'] == security.sha256(str(output))
    assert manifest['output_name'] == 'Tube_roiL0T0W48H32_04.04.24_scan.png'
    assert len(manifest['preparation_id']) == 64


def test_crop_matches_manual_reference_and_roi_separates_tracking_groups(tmp_path):
    source = tmp_path / 'Tube_04.04.24_scan.tiff'
    source_image().save(str(source))
    metadata = preparation.inspect_source(str(source), source.name, str(tmp_path / 'preview.png'))
    rectangle = {'left': 5, 'top': 7, 'width': 13, 'height': 11}
    output = tmp_path / 'crop.png'
    manifest = preparation.apply_crop(str(source), metadata, rectangle, str(output))
    with PIL.Image.open(str(output)) as actual, PIL.Image.open(str(source)) as original:
        np.testing.assert_array_equal(np.asarray(actual), np.asarray(original.crop((5, 7, 18, 18))))
    matching = preparation.prepared_filename('Tube_12.04.24_scan.tiff', rectangle)
    different = preparation.prepared_filename(
        'Tube_12.04.24_scan.tiff', {'left': 6, 'top': 7, 'width': 13, 'height': 11}
    )
    assert matching.split('12.04.24')[0] == manifest['output_name'].split('04.04.24')[0]
    assert different.split('12.04.24')[0] != matching.split('12.04.24')[0]
    assert preparation.validate_manifest_for_output(manifest, manifest['output_name'], str(output)) == manifest
    output.write_bytes(b'changed')
    with pytest.raises(security.ValidationError, match='hash'):
        preparation.validate_manifest_for_output(manifest, manifest['output_name'], str(output))


def test_preview_is_downscaled_but_noop_analysis_copy_is_not(tmp_path):
    source = tmp_path / 'large.png'
    PIL.Image.new('RGB', (1600, 1200), (12, 34, 56)).save(str(source))
    preview = tmp_path / 'preview.png'
    metadata = preparation.inspect_source(str(source), source.name, str(preview))
    output = tmp_path / 'copy.png'
    preparation.apply_crop(
        str(source), metadata,
        {'left': 0, 'top': 0, 'width': 1600, 'height': 1200},
        str(output),
    )
    with PIL.Image.open(str(preview)) as thumbnail, PIL.Image.open(str(output)) as prepared:
        assert max(thumbnail.size) == 1024
        assert prepared.size == (1600, 1200)
        assert prepared.getpixel((1599, 1199)) == (12, 34, 56)


@pytest.mark.parametrize('rectangle', [
    {'left': -1, 'top': 0, 'width': 2, 'height': 2},
    {'left': 47, 'top': 0, 'width': 2, 'height': 2},
    {'left': 0, 'top': 0, 'width': 0, 'height': 2},
    {'left': 0.5, 'top': 0, 'width': 2, 'height': 2},
    {'left': True, 'top': 0, 'width': 2, 'height': 2},
])
def test_crop_rejects_invalid_rectangles(rectangle):
    with pytest.raises(security.ValidationError, match='[Cc]rop'):
        preparation.validate_rectangle(rectangle, 48, 32)


def test_inspection_rejects_multipage_and_unsupported_bit_depth(tmp_path):
    multi = tmp_path / 'multi.tiff'
    frames = [PIL.Image.new('L', (8, 8)) for _ in range(2)]
    frames[0].save(str(multi), save_all=True, append_images=frames[1:])
    with pytest.raises(security.ValidationError, match='Multi-page TIFFs'):
        preparation.inspect_source(str(multi), multi.name, str(tmp_path / 'preview.png'))

    high_bit = tmp_path / 'high-bit.tiff'
    PIL.Image.new('I;16', (8, 8)).save(str(high_bit))
    with pytest.raises(security.ValidationError, match='8-bit'):
        preparation.inspect_source(str(high_bit), high_bit.name, str(tmp_path / 'preview.png'))


def test_inspection_rejects_pixel_and_byte_over_budget(tmp_path, monkeypatch):
    source = tmp_path / 'source.png'
    source_image().save(str(source))
    monkeypatch.setattr(preparation, 'MAX_SOURCE_PIXELS', 100)
    with pytest.raises(security.ValidationError, match='decoded pixels'):
        preparation.inspect_source(str(source), source.name, str(tmp_path / 'preview.png'))
    monkeypatch.setattr(preparation, 'MAX_SOURCE_BYTES', 10)
    with pytest.raises(security.ValidationError, match='64 MiB'):
        preparation.inspect_source(str(source), source.name, str(tmp_path / 'preview.png'))


class FakeSettings:
    active_models = {'detection': 'fake-detection', 'tracking': 'fake-tracking'}
    models = {}
    use_gpu = False
    exmask_enabled = False
    too_many_roots = 100000

    def get_settings_as_dict(self):
        return {'settings': {}, 'available_models': {}}


def request_headers(app):
    return {'Host': 'localhost', 'Origin': 'http://localhost', 'X-RootDetector-Token': app.session_token}


def test_preparation_api_stages_crops_and_discards_without_mutating_original(tmp_path, monkeypatch):
    monkeypatch.setenv('ROOT_PATH', os.getcwd())
    monkeypatch.setenv('INSTANCE_PATH', str(tmp_path))
    monkeypatch.setenv('DO_NOT_RELOAD', '1')
    monkeypatch.setattr('backend.settings.ensure_pretrained_models', lambda: None)
    monkeypatch.setattr('backend.settings.Settings', FakeSettings)
    app = App()
    app.testing = True
    client = app.test_client()
    headers = request_headers(app)
    original = encode(source_image())
    session = client.get('/api/session').get_json()
    assert session['limits']['preparation_source_bytes'] == preparation.MAX_SOURCE_BYTES
    without_token = client.post(
        '/api/preparation/inspect',
        data={'files': (io.BytesIO(original), 'Tube_04.04.24_scan.tiff')},
        headers={'Host': 'localhost'},
    )
    assert without_token.status_code == 403

    inspected = client.post(
        '/api/preparation/inspect',
        data={'files': (io.BytesIO(original), 'Tube_04.04.24_scan.tiff')},
        headers=headers,
    )
    assert inspected.status_code == 200
    stage = inspected.get_json()
    assert client.get('/images/' + stage['preview']).status_code == 200
    busy = client.post(
        '/api/preparation/inspect',
        data={'files': (io.BytesIO(original), 'another.tiff')},
        headers=headers,
    )
    assert busy.status_code == 409
    malformed_id = client.post(
        '/api/preparation/apply',
        json={'id': {}, 'rectangle': {'left': 0, 'top': 0, 'width': 1, 'height': 1}},
        headers=headers,
    )
    assert malformed_id.status_code == 400
    assert malformed_id.get_json()['code'] == 'invalid_preparation_id'

    applied = client.post(
        '/api/preparation/apply',
        json={'id': stage['id'], 'rectangle': {'left': 5, 'top': 7, 'width': 13, 'height': 11}},
        headers=headers,
    )
    assert applied.status_code == 200
    result = applied.get_json()
    assert result['manifest']['output_name'] == 'Tube_roiL5T7W13H11_04.04.24_scan.png'
    with PIL.Image.open(io.BytesIO(client.get('/images/' + result['output']).data)) as image:
        assert image.size == (13, 11)

    discarded = client.post('/api/preparation/{}/discard'.format(stage['id']), headers=headers)
    assert discarded.status_code == 200
    assert client.get('/images/' + stage['preview']).status_code == 404
    assert client.get('/images/' + result['output']).status_code == 404
    assert not list((tmp_path / 'cache').glob('prepare-*'))


def test_preparation_respects_smaller_configured_upload_limit(tmp_path, monkeypatch):
    monkeypatch.setenv('ROOT_PATH', os.getcwd())
    monkeypatch.setenv('INSTANCE_PATH', str(tmp_path))
    monkeypatch.setenv('DO_NOT_RELOAD', '1')
    monkeypatch.setenv('ROOTDETECTOR_MAX_UPLOAD_MIB', '1')
    monkeypatch.setattr('backend.settings.ensure_pretrained_models', lambda: None)
    monkeypatch.setattr('backend.settings.Settings', FakeSettings)
    app = App()
    app.testing = True
    client = app.test_client()
    assert client.get('/api/session').get_json()['limits']['preparation_source_bytes'] == 1024 * 1024
    response = client.post(
        '/api/preparation/inspect',
        data={'files': (io.BytesIO(b'x' * (1024 * 1024 + 1)), 'large.tiff')},
        headers=request_headers(app),
    )
    assert response.status_code == 413
    assert response.get_json()['code'] == 'preparation_source_too_large'
    assert not list((tmp_path / 'cache').glob('prepare-*'))
