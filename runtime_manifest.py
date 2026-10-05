"""Windows runtime integrity checks. Do not import torch before checking DLLs."""
import hashlib
import json
import os


MANIFEST_NAME = 'rootdetector-runtime.json'
TORCH_VERSION = '1.10.1'
CPU_DLLS = {'c10.dll', 'torch_cpu.dll', 'torch_python.dll'}
CUDA_DLLS = {'c10_cuda.dll', 'torch_cuda.dll'}


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def required_dlls(variant):
    if variant not in ('cpu', 'cu113'):
        raise ValueError('Unsupported PyTorch runtime variant.')
    return CPU_DLLS | (CUDA_DLLS if variant == 'cu113' else set())


def validate_bundled_dlls(source_directory, bundled_directory):
    """Catch PyInstaller omissions, including CUDA dependencies beyond torch_cuda."""
    source_names = [name for name in os.listdir(source_directory) if name.lower().endswith('.dll')]
    if not source_names:
        raise RuntimeError('The build environment has no Windows PyTorch DLLs.')
    for name in source_names:
        source = os.path.join(source_directory, name)
        bundled = os.path.join(bundled_directory, name)
        if not os.path.isfile(bundled) or sha256_file(source) != sha256_file(bundled):
            raise RuntimeError('The packaged PyTorch DLL is missing or mismatched: {}'.format(name))


def write_runtime_manifest(directory, variant):
    names = sorted(os.listdir(directory))
    if not required_dlls(variant).issubset(names):
        raise RuntimeError('The PyTorch runtime is missing required {} libraries.'.format(variant))
    files = {}
    for name in names:
        path = os.path.join(directory, name)
        if name != MANIFEST_NAME and os.path.isfile(path):
            files[name] = {'size': os.path.getsize(path), 'sha256': sha256_file(path)}
    manifest = {'schema': 1, 'torch_version': TORCH_VERSION,
                'variant': variant, 'files': files}
    with open(os.path.join(directory, MANIFEST_NAME), 'w') as target:
        json.dump(manifest, target, indent=2, sort_keys=True)
    return manifest


def validate_runtime(directory, required_variant=None):
    """Reject damaged or mixed copies. Wheel authenticity is checked separately.

    Local manifests detect corruption, not malicious edits to both DLL and manifest.
    """
    try:
        with open(os.path.join(directory, MANIFEST_NAME)) as source:
            manifest = json.load(source)
        variant = manifest['variant']
        files = manifest['files']
        if (manifest['schema'] != 1 or manifest['torch_version'] != TORCH_VERSION
                or (required_variant and variant != required_variant)
                or not isinstance(files, dict) or not required_dlls(variant).issubset(files)):
            raise ValueError('Incorrect runtime manifest.')
        actual_files = {name for name in os.listdir(directory)
                        if name != MANIFEST_NAME and os.path.isfile(os.path.join(directory, name))}
        if actual_files != set(files):
            raise ValueError('Runtime file set does not match its manifest.')
        for name, identity in files.items():
            if not name or name in ('.', '..') or any(char in name for char in '/\\:'):
                raise ValueError('Invalid runtime filename.')
            path = os.path.join(directory, name)
            if (os.path.islink(path) or os.path.getsize(path) != identity['size']
                    or sha256_file(path) != identity['sha256']):
                raise ValueError('Runtime checksum mismatch: {}'.format(name))
        return manifest
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError('The PyTorch runtime is incomplete or damaged: {}.'.format(exc)) from exc
