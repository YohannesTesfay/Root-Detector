import subprocess
import sys

import pytest

import backend.startup as startup


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
    (libraries / 'torch_cpu.dll').write_bytes(b'placeholder')
    startup.ensure_torch()
