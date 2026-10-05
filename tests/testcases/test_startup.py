import subprocess
import sys
import hashlib
import io
import zipfile

import pytest

import backend.startup as startup
from runtime_manifest import required_dlls, validate_bundled_dlls, validate_runtime, write_runtime_manifest


def test_nvidia_detection_prefers_nvidia_smi(monkeypatch):
    calls = []

    def check_output(command, **_kwargs):
        calls.append(command)
        return b'NVIDIA GeForce RTX 3080\r\n'

    monkeypatch.setattr(startup.subprocess, 'check_output', check_output)

    assert startup.is_nvidia_gpu_present() is True
    assert calls == [[
        'nvidia-smi',
        '--query-gpu=name',
        '--format=csv,noheader',
    ]]
    assert startup.guess_torch_url() == startup.WHEEL_URLS['torch==1.10.1+cu113']


def test_nvidia_detection_uses_powershell_when_wmic_is_unavailable(monkeypatch):
    calls = []

    def check_output(command, **_kwargs):
        calls.append(command)
        if command[0] == 'nvidia-smi':
            raise OSError('nvidia-smi is not on PATH')
        return b'NVIDIA GeForce RTX 3080\r\n'

    monkeypatch.setattr(startup.subprocess, 'check_output', check_output)

    assert startup.is_nvidia_gpu_present() is True
    assert [command[0] for command in calls] == ['nvidia-smi', 'powershell']


def test_nvidia_detection_falls_back_to_cpu_when_probes_fail(monkeypatch):
    def check_output(_command, **_kwargs):
        raise subprocess.CalledProcessError(1, 'probe')

    monkeypatch.setattr(startup.subprocess, 'check_output', check_output)

    assert startup.is_nvidia_gpu_present() is False
    assert startup.guess_torch_url() == startup.WHEEL_URLS['torch==1.10.1+cpu']


def test_installed_runtime_requires_bundled_libraries(tmp_path, monkeypatch):
    executable = tmp_path / 'program' / 'main' / 'main.exe'
    executable.parent.mkdir(parents=True)
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(sys, 'argv', [str(executable)])
    monkeypatch.setattr(sys, 'executable', str(executable))
    monkeypatch.setenv('ROOTDETECTOR_INSTALLED', '1')
    with pytest.raises(RuntimeError, match='runtime is incomplete'):
        startup.ensure_torch()

    libraries = executable.parent / 'torch' / 'lib'
    libraries.mkdir(parents=True)
    for name in required_dlls('cu113'):
        (libraries / name).write_bytes(b'placeholder')
    write_runtime_manifest(str(libraries), 'cu113')
    startup.ensure_torch()

    (libraries / 'torch_cuda.dll').write_bytes(b'damaged')
    with pytest.raises(RuntimeError, match='Reinstall RootDetector'):
        startup.ensure_torch()


def fake_wheel(monkeypatch, variant='cpu', extra=None):
    content = io.BytesIO()
    with zipfile.ZipFile(content, 'w') as archive:
        for name in required_dlls(variant):
            archive.writestr('torch/lib/' + name, b'test library ' + name.encode())
        for name, value in (extra or {}).items():
            archive.writestr(name, value)
    raw = content.getvalue()
    monkeypatch.setattr(startup, 'guess_torch_url', lambda: startup.WHEEL_URLS['torch==1.10.1+' + variant])
    monkeypatch.setitem(startup.WHEEL_SHA256, variant, hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(startup.urllib.request, 'urlopen', lambda *_args, **_kwargs: io.BytesIO(raw))
    return raw


@pytest.mark.parametrize('variant', ['cpu', 'cu113'])
def test_portable_download_verified_runtime_and_offline_relaunch(tmp_path, monkeypatch, variant):
    fake_wheel(monkeypatch, variant)
    executable = tmp_path / 'main' / 'main.exe'
    executable.parent.mkdir()
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(sys, 'argv', [str(executable)])
    monkeypatch.setattr(sys, 'executable', str(executable))
    monkeypatch.delenv('ROOTDETECTOR_INSTALLED', raising=False)
    # Startup uses the executable location even when launched from another folder.
    monkeypatch.chdir(tmp_path)
    startup.ensure_torch()
    libraries = executable.parent / 'torch' / 'lib'
    assert validate_runtime(str(libraries))['variant'] == variant

    def no_network(*_args, **_kwargs):
        raise AssertionError('Offline relaunch must not download runtime libraries.')

    monkeypatch.setattr(startup.urllib.request, 'urlopen', no_network)
    startup.ensure_torch()


def test_failed_download_does_not_replace_existing_runtime(tmp_path, monkeypatch):
    fake_wheel(monkeypatch)
    libraries = tmp_path / 'torch' / 'lib'
    libraries.mkdir(parents=True)
    (libraries / 'old.dll').write_bytes(b'keep old runtime until new one is ready')
    monkeypatch.setitem(startup.WHEEL_SHA256, 'cpu', '0' * 64)
    with pytest.raises(RuntimeError, match='checksum mismatch'):
        startup.download_and_extract_pytorch_libs(str(tmp_path))
    assert (libraries / 'old.dll').read_bytes() == b'keep old runtime until new one is ready'
    assert sorted(path.name for path in libraries.parent.iterdir()) == ['lib']


@pytest.mark.parametrize('filename', ['torch/lib/../../outside.dll', 'torch/lib/bad\\file.dll',
                                     'torch/lib/c10.dll:stream', 'torch/lib/C10.DLL'])
def test_runtime_extraction_rejects_unsafe_or_duplicate_names(tmp_path, monkeypatch, filename):
    fake_wheel(monkeypatch, extra={filename: b'bad'})
    with pytest.raises(RuntimeError, match='Invalid filename'):
        startup.download_and_extract_pytorch_libs(str(tmp_path))
    assert not (tmp_path / 'torch' / 'lib').exists()


def test_interrupted_runtime_swap_restores_previous_copy(tmp_path, monkeypatch):
    fake_wheel(monkeypatch)
    backup = tmp_path / 'torch' / 'lib.previous'
    backup.mkdir(parents=True)
    (backup / 'old.dll').write_bytes(b'old runtime')
    monkeypatch.setitem(startup.WHEEL_SHA256, 'cpu', '0' * 64)
    with pytest.raises(RuntimeError, match='checksum mismatch'):
        startup.download_and_extract_pytorch_libs(str(tmp_path))
    assert (tmp_path / 'torch' / 'lib' / 'old.dll').read_bytes() == b'old runtime'


def test_interrupted_download_is_cleanly_retryable(tmp_path, monkeypatch):
    raw = fake_wheel(monkeypatch)

    class InterruptedDownload(io.BytesIO):
        def read(self, size=-1):
            if self.tell():
                raise OSError('Connection interrupted')
            return super().read(5)

    monkeypatch.setattr(startup.urllib.request, 'urlopen',
                        lambda *_args, **_kwargs: InterruptedDownload(raw))
    with pytest.raises(OSError, match='Connection interrupted'):
        startup.download_and_extract_pytorch_libs(str(tmp_path))
    assert list((tmp_path / 'torch').iterdir()) == []
    fake_wheel(monkeypatch)
    startup.download_and_extract_pytorch_libs(str(tmp_path))
    assert validate_runtime(str(tmp_path / 'torch' / 'lib'))['variant'] == 'cpu'


def test_failed_swap_restores_previous_runtime(tmp_path, monkeypatch):
    fake_wheel(monkeypatch)
    libraries = tmp_path / 'torch' / 'lib'
    libraries.mkdir(parents=True)
    (libraries / 'old.dll').write_bytes(b'old runtime')
    real_replace = startup.os.replace

    def fail_staged_swap(source, target):
        if '.runtime-' in str(source):
            raise OSError('File is in use')
        return real_replace(source, target)

    monkeypatch.setattr(startup.os, 'replace', fail_staged_swap)
    with pytest.raises(OSError, match='File is in use'):
        startup.download_and_extract_pytorch_libs(str(tmp_path))
    assert (libraries / 'old.dll').read_bytes() == b'old runtime'
    assert sorted(path.name for path in libraries.parent.iterdir()) == ['lib']


def test_installed_runtime_rejects_cpu_only_bundle_without_downloading(tmp_path, monkeypatch):
    executable = tmp_path / 'main' / 'main.exe'
    libraries = executable.parent / 'torch' / 'lib'
    libraries.mkdir(parents=True)
    for name in required_dlls('cpu'):
        (libraries / name).write_bytes(b'test')
    write_runtime_manifest(str(libraries), 'cpu')
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(sys, 'argv', [str(executable)])
    monkeypatch.setattr(sys, 'executable', str(executable))
    monkeypatch.setenv('ROOTDETECTOR_INSTALLED', '1')
    with pytest.raises(RuntimeError, match='Reinstall RootDetector'):
        startup.ensure_torch()


def test_manifest_detects_unexpected_dlls(tmp_path):
    for name in required_dlls('cpu'):
        (tmp_path / name).write_bytes(b'test')
    write_runtime_manifest(str(tmp_path), 'cpu')
    (tmp_path / 'unexpected.dll').write_bytes(b'wrong runtime')
    with pytest.raises(RuntimeError, match='file set'):
        validate_runtime(str(tmp_path))


def test_build_rejects_omitted_or_mixed_cuda_dependency(tmp_path):
    source = tmp_path / 'source'
    bundled = tmp_path / 'bundle'
    source.mkdir()
    bundled.mkdir()
    (source / 'cudnn64_8.dll').write_bytes(b'cuda dependency')
    with pytest.raises(RuntimeError, match='missing or mismatched'):
        validate_bundled_dlls(str(source), str(bundled))
    (bundled / 'cudnn64_8.dll').write_bytes(b'wrong version')
    with pytest.raises(RuntimeError, match='missing or mismatched'):
        validate_bundled_dlls(str(source), str(bundled))
    (bundled / 'cudnn64_8.dll').write_bytes(b'cuda dependency')
    validate_bundled_dlls(str(source), str(bundled))
