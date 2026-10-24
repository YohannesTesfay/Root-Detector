from types import SimpleNamespace

import torch

from backend.diagnostics import _torch_details


def test_diagnostics_honor_cpu_selection_on_gpu_machine(monkeypatch):
    monkeypatch.setattr(torch.cuda, 'is_available', lambda: True)
    monkeypatch.setattr(torch.cuda, 'device_count', lambda: 0)
    details = _torch_details(SimpleNamespace(use_gpu=False))
    assert details['cuda_available'] is True
    assert details['requested_device'] == 'cpu'
    assert details['effective_inference_device'] == 'cpu'


def test_diagnostics_do_not_imply_fallback_for_unavailable_gpu(monkeypatch):
    monkeypatch.setattr(torch.cuda, 'is_available', lambda: False)
    details = _torch_details(SimpleNamespace(use_gpu=True))
    assert details['requested_device'] == 'cuda'
    assert details['effective_inference_device'] is None
    assert _torch_details()['effective_inference_device'] is None
