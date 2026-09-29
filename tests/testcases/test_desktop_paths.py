import os
import sys
import types

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
    previous = os.environ.get('ROOTDETECTOR_INSTALLED')
    try:
        desktop_paths.configure_installed_paths(
            executable=str(executable), local_app_data=str(tmp_path)
        )
    except RuntimeError as exc:
        assert 'browser assets are incomplete' in str(exc)
    else:
        raise AssertionError('Incomplete installed assets were accepted')
    finally:
        if previous is None:
            os.environ.pop('ROOTDETECTOR_INSTALLED', None)
        else:
            os.environ['ROOTDETECTOR_INSTALLED'] = previous


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
