"""Prepare writable paths before importing the frozen application.

The installed package carries an ``INSTALL-MODE.txt`` marker beside its
``main`` directory. Portable ZIPs have no marker and keep their existing
in-place behavior.
"""

import os
import shutil
import sys
import ctypes
import errno


INSTALL_MARKER = 'INSTALL-MODE.txt'
APP_MUTEX_NAME = 'Local\\RootDetector-C4886A85-376C-4C2A-BD59-956A8A3CA12F'
_instance_lock = None
_upgrade_mutex = None


def package_root(executable=None):
    executable = executable or sys.executable
    return os.path.dirname(os.path.dirname(os.path.abspath(executable)))


def configure_installed_paths(executable=None, local_app_data=None):
    """Select per-user data paths for a marker-bearing frozen package.

    Returns the selected data directory, or ``None`` for source/portable runs.
    No existing user data is removed. Callers must claim the instance lock
    before copying browser assets into the user directory.
    """
    if not getattr(sys, 'frozen', False):
        return None
    root = package_root(executable)
    if not os.path.isfile(os.path.join(root, INSTALL_MARKER)):
        return None
    os.environ['ROOTDETECTOR_INSTALLED'] = '1'
    local_app_data = local_app_data or os.environ.get('LOCALAPPDATA')
    if not local_app_data or not os.path.isabs(local_app_data):
        raise RuntimeError('Windows LOCALAPPDATA is required for an installed RootDetector.')

    data = os.path.join(local_app_data, 'RootDetector')
    os.makedirs(data, exist_ok=True)
    os.environ['ROOT_PATH'] = root
    os.environ['INSTANCE_PATH'] = data
    os.chdir(data)  # base.Settings still saves settings.json relative to CWD.
    return data


def prepare_installed_assets(data):
    """Copy packaged assets only after this process owns the user lock."""
    root = os.environ['ROOT_PATH']
    source_static = os.path.join(root, 'static')
    if not os.path.isfile(os.path.join(source_static, 'index.html')):
        raise RuntimeError('Installed RootDetector browser assets are incomplete.')
    target_static = os.path.join(data, 'static')
    os.makedirs(target_static, exist_ok=True)
    for current, _dirs, files in os.walk(source_static):
        relative = os.path.relpath(current, source_static)
        target = os.path.join(target_static, relative)
        os.makedirs(target, exist_ok=True)
        for name in files:
            shutil.copy2(os.path.join(current, name), os.path.join(target, name))

    build_info = os.path.join(root, 'BUILD-INFO.txt')
    if os.path.isfile(build_info):
        shutil.copy2(build_info, os.path.join(data, 'BUILD-INFO.txt'))


def claim_installed_instance(data):
    """Keep a second installed copy from deleting the first copy's cache.

    The lock is retained for the process lifetime. Windows releases use
    ``msvcrt`` byte-range locking, which the OS releases after a crash.
    """
    global _instance_lock
    if data is None:
        return True
    import msvcrt

    try:
        handle = open(os.path.join(data, '.instance.lock'), 'a+b')
    except OSError as exc:
        # Python's CRT file open can translate a sharing violation to EACCES
        # without preserving winerror. Do not mislabel a folder permission error
        # as a broken runtime requiring reinstallation.
        if getattr(exc, 'winerror', None) in (32, 33) or exc.errno == errno.EACCES:
            raise RuntimeError(
                'RootDetector user data is unavailable. An installation, update, '
                'or uninstall may be in progress. Wait for it to finish and retry. '
                'If no maintenance is running, check permissions on the user-data folder.'
            ) from exc
        raise
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b'0')
        handle.flush()
    handle.seek(0)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        return False
    _instance_lock = handle
    return True


def mark_installed_app_running(kernel32=None):
    """Expose the running application to the installer's AppMutex gate."""
    global _upgrade_mutex
    if kernel32 is None:
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    create_mutex = kernel32.CreateMutexW
    create_mutex.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
    create_mutex.restype = ctypes.c_void_p
    handle = create_mutex(None, 0, APP_MUTEX_NAME)
    if not handle:
        raise OSError(ctypes.get_last_error(), 'Could not create the installer safety mutex')
    _upgrade_mutex = handle  # Keep the OS handle until this process exits.
