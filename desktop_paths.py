"""Prepare writable paths before importing the frozen application.

The installed package carries an ``INSTALL-MODE.txt`` marker beside its
``main`` directory. Portable ZIPs have no marker and keep their existing
in-place behavior.
"""

import os
import shutil
import sys


INSTALL_MARKER = 'INSTALL-MODE.txt'


def package_root(executable=None):
    executable = executable or sys.executable
    return os.path.dirname(os.path.dirname(os.path.abspath(executable)))


def configure_installed_paths(executable=None, local_app_data=None):
    """Select per-user data paths for a marker-bearing frozen package.

    Returns the selected data directory, or ``None`` for source/portable runs.
    No existing user data is removed. The program directory is treated as
    read-only; compiled browser assets are copied into the user directory.
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
    os.environ['ROOT_PATH'] = root
    os.environ['INSTANCE_PATH'] = data
    os.chdir(data)  # base.Settings still saves settings.json relative to CWD.
    return data
