"""Prepare Windows PyTorch DLLs before importing torch."""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

from runtime_manifest import validate_runtime, write_runtime_manifest

WHEEL_URLS = {
    'torch==1.10.1+cpu'     : 'https://download.pytorch.org/whl/cpu/torch-1.10.1%2Bcpu-cp37-cp37m-win_amd64.whl',
    'torch==1.10.1+cu113'   : 'https://download.pytorch.org/whl/cu113/torch-1.10.1%2Bcu113-cp37-cp37m-win_amd64.whl',
}
# SHA-256 values from the official PyTorch CPU/cu113 wheel indexes.
WHEEL_SHA256 = {
    'cpu': '4aaf4aacfb85dc9273032d184b39c32c65f45362a0cc80c2bbb83673db6a4dd0',
    'cu113': '1db379fd49122aae782ef06b538a8b15a1f438bb47be0e35a3e9c01d6171eafc',
}
MAX_WHEEL_BYTES = 3 * 1024 ** 3
MAX_EXPANDED_BYTES = 6 * 1024 ** 3

def is_nvidia_gpu_present() -> bool:
    """Detect NVIDIA hardware without depending on deprecated WMIC alone."""
    commands = [
        [
            'nvidia-smi',
            '--query-gpu=name',
            '--format=csv,noheader',
        ],
        [
            'powershell',
            '-NoProfile',
            '-NonInteractive',
            '-Command',
            '(Get-CimInstance Win32_VideoController | '
            'Select-Object -ExpandProperty Name) -join "`n"',
        ],
        [
            'wmic',
            'path',
            'win32_videocontroller',
            'get',
            'name',
        ],
    ]
    for command in commands:
        try:
            gpu_info = subprocess.check_output(
                command,
                stderr=subprocess.STDOUT,
                timeout=10,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            continue
        if b'nvidia' in gpu_info.lower():
            return True
    return False

def guess_torch_url() -> str:
    if is_nvidia_gpu_present():
        return WHEEL_URLS['torch==1.10.1+cu113']
    else:
        return WHEEL_URLS['torch==1.10.1+cpu']

def download_and_extract_pytorch_libs(destination:str) -> None:
    """Stream, authenticate and stage DLLs before replacing a portable runtime.

    A failed download leaves the previous runtime untouched. Staging and the
    destination share a filesystem; an interrupted swap is recovered next start.
    """
    url = guess_torch_url()
    variant = 'cu113' if url == WHEEL_URLS['torch==1.10.1+cu113'] else 'cpu'
    torch_root = os.path.join(destination, 'torch')
    os.makedirs(torch_root, exist_ok=True)
    library_dir = os.path.join(torch_root, 'lib')
    backup_dir = os.path.join(torch_root, 'lib.previous')
    if os.path.isdir(backup_dir) and not os.path.exists(library_dir):
        os.replace(backup_dir, library_dir)
    if os.path.exists(backup_dir):
        raise RuntimeError('A previous runtime update needs recovery. Close other '
                           'RootDetector copies and re-extract the portable package.')
    print('Downloading verified PyTorch {} runtime ...'.format(variant))
    with tempfile.TemporaryDirectory(prefix='.runtime-', dir=torch_root) as temporary:
        wheel_path = os.path.join(temporary, 'torch.whl')
        digest = hashlib.sha256()
        downloaded = 0
        with urllib.request.urlopen(url, timeout=60) as source, open(wheel_path, 'wb') as target:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                downloaded += len(block)
                if downloaded > MAX_WHEEL_BYTES:
                    raise RuntimeError('PyTorch download exceeded the expected size limit.')
                digest.update(block)
                target.write(block)
        if digest.hexdigest() != WHEEL_SHA256[variant]:
            raise RuntimeError('PyTorch download checksum mismatch. Please retry the launch.')
        staged_libs = os.path.join(temporary, 'lib')
        os.mkdir(staged_libs)
        expanded = 0
        names = set()
        with zipfile.ZipFile(wheel_path) as archive:
            for entry in archive.infolist():
                if not entry.filename.startswith('torch/lib/') or entry.is_dir():
                    continue
                name = entry.filename[len('torch/lib/'):]
                if (not name or name in ('.', '..') or any(char in name for char in '/\\:')
                        or name.lower() in names or (entry.external_attr >> 16) & 0o170000 == 0o120000):
                    raise RuntimeError('Invalid filename in PyTorch runtime archive.')
                names.add(name.lower())
                expanded += entry.file_size
                if expanded > MAX_EXPANDED_BYTES:
                    raise RuntimeError('PyTorch libraries exceeded the expected size limit.')
                with archive.open(entry) as source, open(os.path.join(staged_libs, name), 'wb') as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
        write_runtime_manifest(staged_libs, variant)
        validate_runtime(staged_libs, required_variant=variant)
        if os.path.exists(library_dir):
            os.replace(library_dir, backup_dir)
        try:
            os.replace(staged_libs, library_dir)
        except OSError:
            if os.path.exists(backup_dir) and not os.path.exists(library_dir):
                os.replace(backup_dir, library_dir)
            raise
        if os.path.isdir(backup_dir):
            shutil.rmtree(backup_dir)


def ensure_torch() -> None:
    """Check bundled installed DLLs or provision verified portable DLLs."""
    if sys.argv[0].endswith('.py') or sys.platform != 'win32':
        return
    executable_dir = os.path.dirname(os.path.abspath(sys.executable))
    library_dir = os.path.join(executable_dir, 'torch', 'lib')
    if os.environ.get('ROOTDETECTOR_INSTALLED') == '1':
        try:
            # Bundled CUDA libraries support CPU and supported NVIDIA GPUs.
            # Installed binaries are never replaced by a first-launch download.
            validate_runtime(library_dir, required_variant='cu113')
        except RuntimeError as exc:
            raise RuntimeError('{} Reinstall RootDetector.'.format(exc)) from exc
        return
    try:
        validate_runtime(library_dir)
        return
    except RuntimeError:
        download_and_extract_pytorch_libs(executable_dir)
