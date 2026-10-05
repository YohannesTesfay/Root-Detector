from types import SimpleNamespace

import pytest

from backend import device


def test_explicit_cpu_does_not_initialize_cuda(monkeypatch):
    def broken_driver():
        raise AssertionError('CPU selection must not initialize CUDA.')

    monkeypatch.setattr(device.torch.cuda, 'is_available', broken_driver)
    assert device.resolve_device(SimpleNamespace(use_gpu=False)) == 'cpu'


def test_available_gpu_is_selected_and_reported(monkeypatch):
    monkeypatch.setattr(device.torch.cuda, 'is_available', lambda: True)
    monkeypatch.setattr(device.torch.cuda, 'get_device_name', lambda: 'NVIDIA RTX test')
    assert device.resolve_device(SimpleNamespace(use_gpu=True)) == 'cuda'
    status = device.get_device_status(use_gpu=True)
    assert status['available_gpu'] == 'NVIDIA RTX test'
    assert status['effective_device'] == 'cuda'
    assert status['warning'] is None


@pytest.mark.parametrize('cuda_runtime', [None, '11.3'])
def test_requested_gpu_never_silently_falls_back(monkeypatch, cuda_runtime):
    monkeypatch.setattr(device.torch.version, 'cuda', cuda_runtime)
    monkeypatch.setattr(device.torch.cuda, 'is_available', lambda: False)
    with pytest.raises(device.DeviceUnavailableError, match='choose CPU processing'):
        device.resolve_device(SimpleNamespace(use_gpu=True))
    status = device.get_device_status(use_gpu=True)
    assert status['requested_device'] == 'cuda'
    assert status['effective_device'] is None


@pytest.mark.parametrize('failing_probe', ['is_available', 'get_device_name'])
def test_driver_failure_does_not_break_settings(monkeypatch, failing_probe):
    monkeypatch.setattr(device.torch.cuda, 'is_available', lambda: True)

    def broken_driver():
        raise RuntimeError('Driver initialization failed')

    monkeypatch.setattr(device.torch.cuda, failing_probe, broken_driver)
    status = device.get_device_status(use_gpu=True)
    assert status['available_gpu'] is None
    assert status['effective_device'] is None
    assert 'Driver initialization failed' in status['warning']
    assert device.get_device_status(use_gpu=False)['effective_device'] == 'cpu'
    with pytest.raises(device.DeviceUnavailableError, match='Driver initialization failed'):
        device.resolve_device(SimpleNamespace(use_gpu=True))
