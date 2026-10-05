"""Exercise lifecycle rejection on a disposable installed Windows package.

This CI helper deliberately launches the supplied installer and uninstaller.
The simulated running app owns only the per-user file lock, never AppMutex, so
the test cannot accidentally pass due to the older session-local mutex gate.
"""
import argparse
import hashlib
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading


def hold_app_lock(data_directory):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import desktop_paths
    if not desktop_paths.claim_installed_instance(str(data_directory)):
        raise RuntimeError('Test installation is already in use.')
    print('LOCKED', flush=True)
    sys.stdin.read()


def fingerprint(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def assert_blocked(executable, preserved):
    process = subprocess.Popen([str(executable), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'])
    try:
        code = process.wait(timeout=45)
    except subprocess.TimeoutExpired:
        # Inno Setup may have a loader/child process. Stop the full test tree.
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], check=False)
        process.wait(timeout=15)
        raise RuntimeError('Installer/uninstaller did not refuse a live data lock in time.')
    if code == 0:
        raise RuntimeError('Installer/uninstaller accepted a live data lock.')
    for path, expected in preserved.items():
        if not path.is_file() or fingerprint(path) != expected:
            raise RuntimeError('Blocked lifecycle operation changed {}'.format(path))


def check_lifecycle(installer, installed, data_directory):
    uninstaller = next(installed.glob('unins*.exe'), None)
    if uninstaller is None:
        raise RuntimeError('Disposable test installation has no uninstaller.')
    sentinels = []
    helper = None
    try:
        for directory in [installed / 'main' / 'torch' / 'lib', data_directory]:
            descriptor, name = tempfile.mkstemp(prefix='lifecycle-sentinel-', dir=str(directory))
            with os.fdopen(descriptor, 'wb') as target:
                target.write(b'Do not modify while an application owns its data lock.')
            sentinels.append(Path(name))
        preserved = {path: fingerprint(path) for path in sentinels + [
            installed / 'main' / 'main.exe', installed / 'BUILD-INFO.txt',
            installed / 'main' / 'torch' / 'lib' / 'rootdetector-runtime.json',
        ]}
        helper = subprocess.Popen(
            [sys.executable, __file__, '--hold-lock', str(data_directory)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        readiness = queue.Queue()
        threading.Thread(
            target=lambda stream=helper.stdout: readiness.put(stream.readline()), daemon=True,
        ).start()
        try:
            ready_message = readiness.get(timeout=15)
        except queue.Empty:
            raise RuntimeError('Timed out establishing the test application data lock.')
        if ready_message.strip() != 'LOCKED':
            raise RuntimeError('Could not establish the test application data lock.')
        assert_blocked(installer, preserved)
        assert_blocked(uninstaller, preserved)
        # Simulate a crash: no explicit lock release or deletion of the lock file.
        helper.kill()
        helper.wait(timeout=15)
        helper = None
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        import desktop_paths
        if not desktop_paths.claim_installed_instance(str(data_directory)):
            raise RuntimeError('A stale lock file prevented recovery after process exit.')
        desktop_paths._instance_lock.close()
        desktop_paths._instance_lock = None
        print('Lock-only upgrade/uninstall rejection and crash recovery passed.')
    finally:
        if helper is not None:
            helper.kill()
            helper.wait(timeout=15)
        for sentinel in sentinels:
            if sentinel.exists():
                sentinel.unlink()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hold-lock', type=Path)
    parser.add_argument('--installer', type=Path)
    parser.add_argument('--installed', type=Path)
    parser.add_argument('--data', type=Path)
    options = parser.parse_args()
    if options.hold_lock:
        hold_app_lock(options.hold_lock)
    elif options.installer and options.installed and options.data:
        check_lifecycle(options.installer.resolve(), options.installed.resolve(), options.data.resolve())
    else:
        parser.error('Provide --installer, --installed, and --data for a disposable installation.')
