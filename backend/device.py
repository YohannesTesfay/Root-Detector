"""Explicit processing-device selection without silently changing GPU requests."""
import torch


class DeviceUnavailableError(RuntimeError):
    pass


def get_device_status(use_gpu=False):
    """Report CUDA capability without letting driver errors break Settings."""
    cuda_runtime = getattr(torch.version, 'cuda', None)
    available_gpu = None
    reason = None
    try:
        if not torch.cuda.is_available():
            reason = ('This PyTorch runtime has no CUDA support.' if not cuda_runtime
                      else 'A compatible NVIDIA GPU and driver could not be initialized.')
        else:
            # Some driver problems appear only when CUDA performs lazy initialization.
            available_gpu = torch.cuda.get_device_name()
    except Exception as exc:
        reason = 'CUDA initialization failed: {}'.format(str(exc) or type(exc).__name__)
    warning = None
    if use_gpu and reason:
        warning = ('GPU processing was requested but is unavailable. {} '
                   'Check the NVIDIA driver and runtime, or choose CPU processing '
                   'in Settings and retry.').format(reason)
    return {
        'requested_device': 'cuda' if use_gpu else 'cpu',
        'effective_device': ('cuda' if available_gpu else None) if use_gpu else 'cpu',
        'available_gpu': available_gpu,
        'cuda_available': bool(available_gpu),
        'cuda_runtime': cuda_runtime,
        'warning': warning,
        'unavailable_reason': reason,
    }


def resolve_device(settings):
    """Honor CPU selection and fail clearly when requested CUDA is unavailable."""
    if not getattr(settings, 'use_gpu', False):
        return 'cpu'
    status = get_device_status(use_gpu=True)
    if status['effective_device'] != 'cuda':
        raise DeviceUnavailableError(status['warning'])
    return 'cuda'
