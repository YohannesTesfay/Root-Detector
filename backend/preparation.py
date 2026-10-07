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
import shutil
import tempfile
import secrets
import zipfile

import PIL.Image

from backend import security


PREPARATION_SCHEMA = 1
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_SOURCE_PIXELS = 16_000_000
MAX_PREVIEW_EDGE = 1024
MIN_ANALYSIS_DIMENSION = 1280
MAX_BATCH_BYTES = 256 * 1024 * 1024
MAX_BATCH_IMAGES = 20
MAX_MANIFEST_BYTES = 1024 * 1024
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


def validate_rectangle(
    rectangle:tp.Any, width:int, height:int, min_dimension:int=0
) -> tp.Dict[str, int]:
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
    if crop_width < min_dimension or crop_height < min_dimension:
        raise security.ValidationError(
            'The released detection model needs a prepared image at least 1280 × 1280 pixels. '
            'Select a larger crop or prepare this scan externally.',
            'crop_too_small',
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
    min_analysis_dimension:int=0,
) -> tp.Dict[str, tp.Any]:
    """Write a lossless crop and return source/output provenance."""
    roi = validate_rectangle(
        rectangle,
        source_metadata['source_width'],
        source_metadata['source_height'],
        min_analysis_dimension,
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
    if width * height > MAX_SOURCE_PIXELS:
        raise security.ValidationError('Original dimensions exceed the preparation limit.', 'invalid_preparation_manifest')
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
    try:
        with PIL.Image.open(output_path) as image:
            if (
                image.format != 'PNG'
                or image.mode != manifest.get('output_mode')
                or image.mode != source['source_mode']
                or image.size != (rectangle['width'], rectangle['height'])
                or getattr(image, 'n_frames', 1) != 1
            ):
                raise security.ValidationError('Prepared image dimensions do not match the record.', 'invalid_preparation_manifest')
            image.load()
    except security.ValidationError:
        raise
    except (OSError, ValueError, PIL.Image.DecompressionBombError) as exc:
        raise security.ValidationError('Prepared PNG could not be decoded.', 'invalid_preparation_manifest') from exc
    return manifest


def _copy_bounded(source, destination, limit):
    total = 0
    with open(destination, 'wb') as target:
        while True:
            block = source.read(min(1024 * 1024, limit - total + 1))
            if not block:
                break
            total += len(block)
            if total > limit:
                raise security.ValidationError('Prepared import exceeds its byte budget.', 'preparation_import_too_large', 413)
            target.write(block)
    return total


def restore_prepared_files(uploaded_files, cache_path, max_file_bytes=MAX_SOURCE_BYTES):
    """Validate a prepared ZIP or loose PNG+sidecar set before retaining copies.

    Uploaded objects need ``filename`` and ``stream`` (Werkzeug FileStorage).
    Returned generated cache files persist until the caller clears its test/app
    cache. Failed imports leave neither outputs nor staging files behind.
    """
    uploads = list(uploaded_files)
    if not uploads or len(uploads) > min(MAX_BATCH_IMAGES + 1, security.MAX_UPLOAD_FILES):
        raise security.ValidationError('Import at most 20 prepared images with their manifest.', 'invalid_preparation_import')
    limit = min(max_file_bytes, MAX_SOURCE_BYTES)
    staging = tempfile.mkdtemp(prefix='.prepared-import-', dir=cache_path)
    retained = []
    try:
        inputs = {}
        total = 0
        if len(uploads) == 1 and uploads[0].filename.lower().endswith('.zip'):
            archive_path = os.path.join(staging, 'input.zip')
            _copy_bounded(uploads[0].stream, archive_path, min(max_file_bytes, MAX_BATCH_BYTES))
            try:
                with zipfile.ZipFile(archive_path) as archive:
                    entries = archive.infolist()
                    if not 2 <= len(entries) <= MAX_BATCH_IMAGES + 1:
                        raise security.ValidationError('Prepared ZIP must contain up to 20 PNGs and one manifest.', 'invalid_preparation_import')
                    for entry in entries:
                        name = security.validate_filename(entry.filename, {'.png', '.json'})
                        if entry.is_dir() or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                            raise security.ValidationError('Prepared ZIP cannot contain directories or links.', 'invalid_preparation_import')
                        key = name.casefold()
                        if key in inputs:
                            raise security.ValidationError('Prepared ZIP contains duplicate filenames.', 'invalid_preparation_import')
                        entry_limit = MAX_MANIFEST_BYTES if name == 'preparation-manifest.json' else limit
                        if entry.file_size > entry_limit or total + entry.file_size > MAX_BATCH_BYTES:
                            raise security.ValidationError('Prepared ZIP exceeds its expanded byte budget.', 'preparation_import_too_large', 413)
                        destination = os.path.join(staging, 'file-' + str(len(inputs)))
                        with archive.open(entry) as source:
                            total += _copy_bounded(source, destination, min(entry_limit, MAX_BATCH_BYTES - total))
                        inputs[key] = (name, destination)
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
                raise security.ValidationError('The prepared ZIP is corrupt, encrypted, or unsupported.', 'invalid_preparation_import') from exc
        else:
            for upload in uploads:
                name = security.validate_filename(upload.filename, {'.png', '.json'})
                key = name.casefold()
                if key in inputs:
                    raise security.ValidationError('Prepared import contains duplicate filenames.', 'invalid_preparation_import')
                entry_limit = MAX_MANIFEST_BYTES if name == 'preparation-manifest.json' else limit
                destination = os.path.join(staging, 'file-' + str(len(inputs)))
                total += _copy_bounded(upload.stream, destination, min(entry_limit, MAX_BATCH_BYTES - total))
                inputs[key] = (name, destination)
        sidecar = inputs.pop('preparation-manifest.json', None)
        if sidecar is None:
            raise security.ValidationError('Include preparation-manifest.json with the prepared PNG copies.', 'missing_preparation_manifest')
        try:
            with open(sidecar[1], encoding='utf-8') as source:
                document = json.load(source)
        except (ValueError, UnicodeError) as exc:
            raise security.ValidationError('The preparation manifest is not valid JSON.', 'invalid_preparation_manifest') from exc
        records = document.get('preparations') if isinstance(document, dict) else None
        if not isinstance(document, dict) or document.get('schema') != PREPARATION_SCHEMA or not isinstance(records, list) or not 1 <= len(records) <= MAX_BATCH_IMAGES:
            raise security.ValidationError('Invalid preparation manifest list.', 'invalid_preparation_manifest')
        outputs = []
        for record in records:
            name = record.get('output_name') if isinstance(record, dict) else None
            security.validate_filename(name, {'.png'})
            candidate = inputs.pop(name.casefold(), None)
            if candidate is None or candidate[0] != name:
                raise security.ValidationError('A prepared PNG is missing, duplicated, or renamed: {}.'.format(name), 'invalid_preparation_manifest')
            validate_manifest_for_output(record, name, candidate[1])
            validate_rectangle(record['rectangle'], record['source']['source_width'], record['source']['source_height'], MIN_ANALYSIS_DIMENSION)
            outputs.append((candidate[1], record))
        if inputs:
            raise security.ValidationError('Every imported image must have exactly one preparation record.', 'invalid_preparation_manifest')
        result = []
        for source, record in outputs:
            output = 'prepare-restored-' + secrets.token_hex(12) + '.png'
            destination = os.path.join(cache_path, output)
            os.replace(source, destination)
            retained.append(destination)
            result.append({'output': output, 'manifest': record})
        return {'files': result}
    except Exception:
        for output in retained:
            if os.path.isfile(output):
                os.remove(output)
        raise
    finally:
        shutil.rmtree(staging)


def transform_companion(upload, manifest, prepared_path, output_path, confirmed=False, kind='training_annotation', max_file_bytes=MAX_SOURCE_BYTES):
    """Copy/crop a mask without resampling; return separate companion provenance."""
    if kind not in ('training_annotation', 'exclusion_mask'):
        raise security.ValidationError('Choose a training annotation or exclusion mask.', 'invalid_companion')
    if not isinstance(manifest, dict):
        raise security.ValidationError('Prepared image record is required.', 'invalid_preparation_manifest')
    validate_manifest_for_output(manifest, manifest.get('output_name'), prepared_path)
    security.validate_filename(upload.filename, security.SUPPORTED_IMAGE_EXTENSIONS)
    handle, staged = tempfile.mkstemp(prefix='.prepare-mask-', dir=os.path.dirname(output_path))
    os.close(handle)
    try:
        _copy_bounded(upload.stream, staged, min(max_file_bytes, MAX_SOURCE_BYTES))
        with PIL.Image.open(staged) as image:
            if image.format not in security.SUPPORTED_IMAGE_FORMATS or image.mode not in ('1', 'L', 'P', 'RGB') or getattr(image, 'n_frames', 1) != 1:
                raise security.ValidationError('Use a single 8-bit PNG, JPEG, or TIFF mask; indexed PNG palettes are preserved.', 'unsupported_companion')
            if image.getexif().get(274, 1) != 1 or image.width * image.height > MAX_SOURCE_PIXELS:
                raise security.ValidationError('Mask orientation or pixel dimensions are unsupported.', 'unsupported_companion')
            source_size = (manifest['source']['source_width'], manifest['source']['source_height'])
            output_size = (manifest['output_width'], manifest['output_height'])
            rectangle = manifest['rectangle']
            if image.size == output_size:
                operation = 'already_prepared_mask'
            elif image.size == source_size:
                if confirmed is not True:
                    raise security.ValidationError('Confirm that the mask uses the original image coordinates before applying the same crop.', 'companion_confirmation_required')
                operation = 'pixel_preserving_crop'
            else:
                raise security.ValidationError('Mask dimensions must match the original source or prepared image exactly.', 'companion_dimensions_mismatch')
            image.load()
            source_width, source_height = image.size
            output = image.copy() if operation == 'already_prepared_mask' else image.crop((rectangle['left'], rectangle['top'], rectangle['left'] + rectangle['width'], rectangle['top'] + rectangle['height']))
            output.save(output_path, format='PNG')
        return {
            'schema': 1, 'kind': kind, 'preparation_id': manifest['preparation_id'],
            'source_mask_name': upload.filename, 'source_mask_sha256': security.sha256(staged),
            'source_mask_width': source_width, 'source_mask_height': source_height,
            'output_name': os.path.basename(output_path),
            'output_sha256': security.sha256(output_path), 'operation': operation,
            'rectangle': rectangle, 'user_confirmed_original_coordinates': confirmed is True,
        }
    except security.ValidationError:
        if os.path.isfile(output_path):
            os.remove(output_path)
        raise
    except (OSError, ValueError, PIL.Image.DecompressionBombError) as exc:
        if os.path.isfile(output_path):
            os.remove(output_path)
        raise security.ValidationError('The mask could not be decoded. Use a single 8-bit mask image.', 'unsupported_companion') from exc
    finally:
        os.remove(staged)


def validate_companion_provenance(record, manifest, cache_path):
    """Validate an export sidecar against the actual retained transformed mask."""
    if not isinstance(record, dict) or record.get('schema') != 1:
        raise security.ValidationError('Invalid prepared mask record.', 'invalid_companion')
    if record.get('kind') not in ('training_annotation', 'exclusion_mask'):
        raise security.ValidationError('Invalid prepared mask kind.', 'invalid_companion')
    if record.get('preparation_id') != manifest.get('preparation_id') or record.get('rectangle') != manifest.get('rectangle'):
        raise security.ValidationError('Prepared mask belongs to a different crop.', 'invalid_companion')
    operation = record.get('operation')
    if operation not in ('pixel_preserving_crop', 'already_prepared_mask'):
        raise security.ValidationError('Invalid prepared mask operation.', 'invalid_companion')
    if operation == 'pixel_preserving_crop' and record.get('user_confirmed_original_coordinates') is not True:
        raise security.ValidationError('Original mask coordinates were not confirmed.', 'invalid_companion')
    expected_size = (manifest['source']['source_width'], manifest['source']['source_height']) if operation == 'pixel_preserving_crop' else (manifest['output_width'], manifest['output_height'])
    if (record.get('source_mask_width'), record.get('source_mask_height')) != expected_size:
        raise security.ValidationError('Prepared mask source dimensions do not match.', 'invalid_companion')
    security.validate_filename(record.get('source_mask_name'), security.SUPPORTED_IMAGE_EXTENSIONS)
    if not re.fullmatch(r'[0-9a-f]{64}', str(record.get('source_mask_sha256', ''))):
        raise security.ValidationError('Invalid source mask hash.', 'invalid_companion')
    output_path = security.safe_resolve(cache_path, record.get('output_name'), {'.png'}, must_exist=True)
    if security.sha256(output_path) != record.get('output_sha256'):
        raise security.ValidationError('Prepared mask changed since import.', 'invalid_companion')
    with PIL.Image.open(output_path) as image:
        if image.size != (manifest['output_width'], manifest['output_height']):
            raise security.ValidationError('Prepared mask dimensions do not match.', 'invalid_companion')
    return record


def bind_exclusion_companion(record, manifest, cache_path):
    """Atomically bind a validated retained mask to the detector's lookup name."""
    validate_companion_provenance(record, manifest, cache_path)
    if record['kind'] != 'exclusion_mask':
        raise security.ValidationError('Only exclusion masks can be bound for detection.', 'invalid_companion')
    canonical = os.path.splitext(manifest['output_name'])[0] + '.exclusionmask.png'
    destination = security.safe_resolve(cache_path, canonical, {'.png'})
    source = security.safe_resolve(cache_path, record['output_name'], {'.png'}, must_exist=True)
    handle, temporary = tempfile.mkstemp(prefix='.prepared-exclusion-', dir=cache_path)
    os.close(handle)
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    finally:
        if os.path.isfile(temporary):
            os.remove(temporary)
    return canonical
