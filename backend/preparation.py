"""Bounded, opt-in preparation of decoded 8-bit images.

Pillow 7.1.2 loads the entire image before ``crop``. This module therefore
rejects sources outside a conservative byte/pixel budget before decoding;
it does not claim to region-decode arbitrarily large TIFF scans.
"""

import hashlib
import json
import math
import os
import re
import typing as tp
import warnings

import PIL.Image

from backend import security


PREPARATION_SCHEMA = 1
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_SOURCE_PIXELS = 16_000_000
MAX_PREVIEW_EDGE = 1024
SUPPORTED_MODES = {'RGB', 'L'}
DATE_TOKEN = re.compile(r'^\d{1,4}\.\d{1,2}\.\d{1,4}$')


def inspect_source(path:str, source_name:str, preview_path:str) -> tp.Dict[str, tp.Any]:
    """Validate a single source and create a small display-only thumbnail."""
    security.validate_filename(source_name, security.SUPPORTED_IMAGE_EXTENSIONS)
    source_bytes = os.path.getsize(path)
    if not 0 < source_bytes <= MAX_SOURCE_BYTES:
        raise security.ValidationError(
            'Image preparation accepts files up to 64 MiB. Prepare larger scans externally.',
            'preparation_source_too_large',
            413,
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', PIL.Image.DecompressionBombWarning)
            with PIL.Image.open(path) as image:
                width, height = image.size
                frames = getattr(image, 'n_frames', 1)
                orientation = image.getexif().get(274, 1)
                if image.format not in security.SUPPORTED_IMAGE_FORMATS:
                    raise security.ValidationError('Use PNG, JPEG, or TIFF for image preparation.', 'unsupported_image', 415)
                if frames != 1:
                    raise security.ValidationError(
                        'Multi-page TIFFs need an explicit page-selection workflow. Export one page externally first.',
                        'preparation_multipage_unsupported',
                        415,
                    )
                if width <= 0 or height <= 0 or width * height > MAX_SOURCE_PIXELS:
                    raise security.ValidationError(
                        'Image preparation supports at most 16 million decoded pixels. Prepare this scan externally.',
                        'preparation_pixels_too_large',
                        413,
                    )
                if image.mode not in SUPPORTED_MODES:
                    raise security.ValidationError(
                        'Only 8-bit RGB or grayscale images can be prepared here. Preserve other bit depths externally.',
                        'preparation_mode_unsupported',
                        415,
                    )
                if orientation != 1:
                    raise security.ValidationError(
                        'This image has non-default orientation metadata. Normalize it externally before cropping.',
                        'preparation_orientation_unsupported',
                        415,
                    )
                dpi = image.info.get('dpi')
                source_dpi = None
                if isinstance(dpi, (list, tuple)) and len(dpi) == 2:
                    try:
                        values = [float(dpi[0]), float(dpi[1])]
                        if all(math.isfinite(value) and 0 < value <= 1_000_000 for value in values):
                            source_dpi = values
                    except (TypeError, ValueError):
                        pass
                image.load()
                thumbnail = image.copy()
                thumbnail.thumbnail((MAX_PREVIEW_EDGE, MAX_PREVIEW_EDGE), PIL.Image.LANCZOS)
                thumbnail.save(preview_path, format='PNG')
                image_format = image.format
                mode = image.mode
    except security.ValidationError:
        raise
    except (OSError, ValueError, PIL.Image.DecompressionBombError) as exc:
        raise security.ValidationError(
            'This image could not be decoded for preparation. Re-export it externally and retry.',
            'preparation_decode_failed',
            415,
        ) from exc
    return {
        'source_name': source_name,
        'source_sha256': security.sha256(path),
        'source_bytes': source_bytes,
        'source_format': image_format,
        'source_mode': mode,
        'source_width': width,
        'source_height': height,
        'source_frames': frames,
        'source_orientation': orientation,
        'source_dpi_metadata': source_dpi,
        'pixel_spacing': None,
    }


def validate_rectangle(rectangle:tp.Any, width:int, height:int) -> tp.Dict[str, int]:
    if not isinstance(rectangle, dict):
        raise security.ValidationError('Enter a crop rectangle in original-image pixels.', 'invalid_crop')
    keys = ('left', 'top', 'width', 'height')
    values = {key: rectangle.get(key) for key in keys}
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values.values()):
        raise security.ValidationError('Crop coordinates must be whole pixels.', 'invalid_crop')
    left, top, crop_width, crop_height = (values[key] for key in keys)
    if (
        left < 0 or top < 0 or crop_width < 1 or crop_height < 1
        or left + crop_width > width or top + crop_height > height
    ):
        raise security.ValidationError('The crop rectangle must stay inside the original image.', 'invalid_crop')
    if crop_width * crop_height > MAX_SOURCE_PIXELS or max(crop_width, crop_height) > 32768:
        raise security.ValidationError(
            'The crop exceeds supported analysis dimensions. Select a smaller region.',
            'crop_too_large',
            413,
        )
    return values


def prepared_filename(source_name:str, rectangle:tp.Dict[str, int]) -> str:
    stem = os.path.splitext(source_name)[0]
    roi = 'roiL{}T{}W{}H{}'.format(
        rectangle['left'], rectangle['top'], rectangle['width'], rectangle['height']
    )
    tokens = stem.split('_')
    date_index = next((i for i, token in enumerate(tokens) if DATE_TOKEN.match(token)), None)
    if date_index is None:
        tokens.append(roi)
    else:
        # The pairing parser groups by the prefix before the date. Putting the
        # exact ROI there prevents different crop rectangles from auto-pairing.
        tokens.insert(date_index, roi)
    filename = '_'.join(tokens) + '.png'
    security.validate_filename(filename, {'.png'})
    return filename


def apply_crop(
    source_path:str,
    source_metadata:tp.Dict[str, tp.Any],
    rectangle:tp.Any,
    output_path:str,
) -> tp.Dict[str, tp.Any]:
    """Write a lossless crop and return source/output provenance."""
    roi = validate_rectangle(
        rectangle,
        source_metadata['source_width'],
        source_metadata['source_height'],
    )
    if security.sha256(source_path) != source_metadata['source_sha256']:
        raise security.ValidationError(
            'The staged image changed. Inspect it again.',
            'preparation_source_changed',
            409,
        )
    with PIL.Image.open(source_path) as image:
        if getattr(image, 'n_frames', 1) != 1 or image.mode != source_metadata['source_mode']:
            raise security.ValidationError('The staged image changed. Inspect it again.', 'preparation_source_changed', 409)
        image.load()
        cropped = image.crop((roi['left'], roi['top'], roi['left'] + roi['width'], roi['top'] + roi['height']))
        cropped.save(output_path, format='PNG')
    if os.path.getsize(output_path) > MAX_SOURCE_BYTES:
        os.remove(output_path)
        raise security.ValidationError('The prepared PNG exceeds 64 MiB. Use a smaller region.', 'crop_too_large', 413)
    manifest = {
        'schema': PREPARATION_SCHEMA,
        'operation': 'pixel_preserving_crop',
        'source': source_metadata,
        'page': 0,
        'rectangle': roi,
        'output_name': prepared_filename(source_metadata['source_name'], roi),
        'output_format': 'PNG',
        'output_mode': source_metadata['source_mode'],
        'output_width': roi['width'],
        'output_height': roi['height'],
        'output_sha256': security.sha256(output_path),
        'preview_is_downscaled': True,
    }
    identity = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode('utf-8')
    manifest['preparation_id'] = hashlib.sha256(identity).hexdigest()
    return manifest


def validate_manifest_for_output(
    manifest:tp.Any,
    filename:str,
    output_path:str,
) -> tp.Dict[str, tp.Any]:
    """Reject stale or malformed preparation records at export time."""
    if not isinstance(manifest, dict) or manifest.get('schema') != PREPARATION_SCHEMA:
        raise security.ValidationError('Invalid preparation record.', 'invalid_preparation_manifest')
    if manifest.get('operation') != 'pixel_preserving_crop' or manifest.get('output_name') != filename:
        raise security.ValidationError('Preparation record does not match the image name.', 'invalid_preparation_manifest')
    source = manifest.get('source')
    if not isinstance(source, dict):
        raise security.ValidationError('Preparation source details are missing.', 'invalid_preparation_manifest')
    security.validate_filename(source.get('source_name'), security.SUPPORTED_IMAGE_EXTENSIONS)
    if not re.fullmatch(r'[0-9a-f]{64}', str(source.get('source_sha256', ''))):
        raise security.ValidationError('Invalid original hash in preparation record.', 'invalid_preparation_manifest')
    if source.get('source_frames') != 1 or source.get('source_mode') not in SUPPORTED_MODES:
        raise security.ValidationError('Unsupported original in preparation record.', 'invalid_preparation_manifest')
    width, height = source.get('source_width'), source.get('source_height')
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in (width, height)):
        raise security.ValidationError('Invalid original dimensions in preparation record.', 'invalid_preparation_manifest')
    rectangle = validate_rectangle(manifest.get('rectangle'), width, height)
    if manifest.get('page') != 0 or manifest.get('output_format') != 'PNG':
        raise security.ValidationError('Unsupported preparation record.', 'invalid_preparation_manifest')
    if (manifest.get('output_width'), manifest.get('output_height')) != (
        rectangle['width'], rectangle['height']
    ):
        raise security.ValidationError('Prepared dimensions do not match the crop.', 'invalid_preparation_manifest')
    if manifest.get('output_sha256') != security.sha256(output_path):
        raise security.ValidationError('Prepared image hash does not match its record.', 'invalid_preparation_manifest')
    identity = dict(manifest)
    identifier = identity.pop('preparation_id', None)
    expected = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(',', ':')).encode('utf-8')
    ).hexdigest()
    if identifier != expected:
        raise security.ValidationError('Preparation identity does not match its record.', 'invalid_preparation_manifest')
    with PIL.Image.open(output_path) as image:
        if (
            image.format != 'PNG'
            or image.mode != manifest.get('output_mode')
            or image.size != (rectangle['width'], rectangle['height'])
        ):
            raise security.ValidationError('Prepared image dimensions do not match the record.', 'invalid_preparation_manifest')
    return manifest
