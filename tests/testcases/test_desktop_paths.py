import os
import sys
import types
import ctypes
import errno

import pytest

import desktop_paths


def test_source_run_does_not_change_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'frozen', False, raising=False)
    monkeypatch.chdir(tmp_path)
    assert desktop_paths.configure_installed_paths() is None
    assert os.getcwd() == str(tmp_path)


def test_installed_package_uses_per_user_paths_without_deleting_data(tmp_path, monkeypatch):
    root = tmp_path / 'Program Files' / 'RootDetector'
    executable = root / 'main' / 'main.exe'
    executable.parent.mkdir(parents=True)
    static = root / 'static'
    static.mkdir()
    (static / 'index.html').write_text('current browser assets')
    (root / 'INSTALL-MODE.txt').write_text('installed')
    (root / 'BUILD-INFO.txt').write_text('commit abc')
    local = tmp_path / 'AppData' / 'Local'
    user_data = local / 'RootDetector'
    user_data.mkdir(parents=True)
    (user_data / 'settings.json').write_text('{"keep": true}')
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.chdir(tmp_path)
    names = ('ROOT_PATH', 'INSTANCE_PATH', 'ROOTDETECTOR_INSTALLED')
    previous = {name: os.environ.get(name) for name in names}

    try:
        selected = desktop_paths.configure_installed_paths(
            executable=str(executable), local_app_data=str(local)
        )
        desktop_paths.prepare_installed_assets(selected)
        assert selected == str(user_data)
        assert os.getcwd() == str(user_data)
        assert os.environ['ROOT_PATH'] == str(root)
        assert os.environ['INSTANCE_PATH'] == str(user_data)
        assert (user_data / 'static' / 'index.html').read_text() == 'current browser assets'
        assert (user_data / 'settings.json').read_text() == '{"keep": true}'
        assert (user_data / 'BUILD-INFO.txt').read_text() == 'commit abc'
    finally:
        os.chdir(str(tmp_path))
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def test_portable_package_keeps_existing_path_behavior(tmp_path, monkeypatch):
    root = tmp_path / 'portable'
    executable = root / 'main' / 'main.exe'
    executable.parent.mkdir(parents=True)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.chdir(tmp_path)
    assert desktop_paths.configure_installed_paths(
        executable=str(executable), local_app_data=str(tmp_path)
    ) is None
    assert os.getcwd() == str(tmp_path)


def test_installed_package_requires_complete_assets(tmp_path, monkeypatch):
    root = tmp_path / 'installed'
    executable = root / 'main' / 'main.exe'
    executable.parent.mkdir(parents=True)
    (root / 'INSTALL-MODE.txt').write_text('installed')
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.chdir(tmp_path)
    names = ('ROOT_PATH', 'INSTANCE_PATH', 'ROOTDETECTOR_INSTALLED')
    previous = {name: os.environ.get(name) for name in names}
    try:
        selected = desktop_paths.configure_installed_paths(
            executable=str(executable), local_app_data=str(tmp_path)
        )
        desktop_paths.prepare_installed_assets(selected)
    except RuntimeError as exc:
        assert 'browser assets are incomplete' in str(exc)
    else:
        raise AssertionError('Incomplete installed assets were accepted')
    finally:
        os.chdir(str(tmp_path))
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def test_installed_instance_lock_prevents_second_copy(tmp_path, monkeypatch):
    observed = []

    def lock(_fd, _mode, length):
        observed.append(length)
        if len(observed) == 2:
            raise OSError('already locked')

    fake_msvcrt = types.SimpleNamespace(LK_NBLCK=1, locking=lock)
    monkeypatch.setitem(sys.modules, 'msvcrt', fake_msvcrt)
    try:
        assert desktop_paths.claim_installed_instance(str(tmp_path)) is True
        assert desktop_paths.claim_installed_instance(str(tmp_path)) is False
        assert observed == [1, 1]
    finally:
        if desktop_paths._instance_lock is not None:
            desktop_paths._instance_lock.close()
            desktop_paths._instance_lock = None


def test_installer_mutex_matches_package_script():
    from pathlib import Path

    script = Path(__file__).parents[2] / 'packaging' / 'windows' / 'RootDetector.iss'
    assert 'AppMutex={}'.format(desktop_paths.APP_MUTEX_NAME) in script.read_text()
    assert 'CloseApplications=no' in script.read_text()


def test_installed_app_creates_upgrade_mutex():
    class CreateMutex:
        argtypes = None
        restype = None

        def __call__(self, security, initial_owner, name):
            assert security is None
            assert initial_owner == 0
            assert name == desktop_paths.APP_MUTEX_NAME
            return 123

    desktop_paths.mark_installed_app_running(
        kernel32=types.SimpleNamespace(CreateMutexW=CreateMutex())
    )
    assert desktop_paths._upgrade_mutex == 123
    desktop_paths._upgrade_mutex = None


@pytest.mark.parametrize('winerror, error_number', [(32, None), (None, errno.EACCES)])
def test_installation_lock_reports_maintenance(tmp_path, monkeypatch, winerror, error_number):
    def sharing_violation(*args, **kwargs):
        error = OSError(error_number, 'Sharing violation')
        error.winerror = winerror
        raise error

    monkeypatch.setitem(sys.modules, 'msvcrt', types.SimpleNamespace())
    monkeypatch.setattr(desktop_paths, 'open', sharing_violation, raising=False)
    with pytest.raises(RuntimeError, match='installation, update, or uninstall may be in progress'):
        desktop_paths.claim_installed_instance(str(tmp_path))


@pytest.mark.skipif(os.name != 'nt', reason='Windows file-sharing contract requires Windows.')
def test_windows_installer_exclusive_handle_interlocks_with_app(tmp_path):
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                           ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    create_file.restype = ctypes.c_void_p
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int
    invalid_handle = ctypes.c_void_p(-1).value
    exclusive = invalid_handle
    lock_path = str(tmp_path / '.instance.lock')
    try:
        assert desktop_paths.claim_installed_instance(str(tmp_path))
        # Installer cannot acquire deny-sharing access while the app owns its lock.
        exclusive = create_file(lock_path, 0xC0000000, 0, None, 4, 0x80, None)
        assert exclusive == invalid_handle
        assert ctypes.get_last_error() == 32
        desktop_paths._instance_lock.close()
        desktop_paths._instance_lock = None
        exclusive = create_file(lock_path, 0xC0000000, 0, None, 4, 0x80, None)
        assert exclusive != invalid_handle
        with pytest.raises(RuntimeError, match='installation, update, or uninstall may be in progress'):
            desktop_paths.claim_installed_instance(str(tmp_path))
        close_handle(exclusive)
        exclusive = invalid_handle
        # A stale lock file is harmless after the owning handle closes or crashes.
        assert desktop_paths.claim_installed_instance(str(tmp_path))
    finally:
        if exclusive != invalid_handle:
            close_handle(exclusive)
        if desktop_paths._instance_lock is not None:
            desktop_paths._instance_lock.close()
            desktop_paths._instance_lock = None
