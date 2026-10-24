"""Small Windows window host for the existing local RootDetector backend.

The scientific runtime remains in main/main.exe. This process only owns the
WebView2 window and a child process, so it does not duplicate CUDA libraries.
"""

import ctypes
import html
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request


BASE_URL = 'http://127.0.0.1:5000'
STARTUP_TIMEOUT_SECONDS = 1800  # First launch may download verified models/runtime.


def package_root():
    entry = sys.executable if getattr(sys, 'frozen', False) else __file__
    return Path(entry).resolve().parent


def backend_path(root):
    return root / 'main' / 'main.exe'


def log_path(root):
    if (root / 'INSTALL-MODE.txt').is_file():
        local_data = os.environ.get('LOCALAPPDATA')
        if not local_data or not os.path.isabs(local_data):
            raise RuntimeError('Windows LOCALAPPDATA is required for the installed app.')
        folder = Path(local_data) / 'RootDetector' / 'logs'
    else:
        folder = root / 'logs'
    folder.mkdir(parents=True, exist_ok=True)
    return folder / 'desktop-host.log'


def backend_environment(root):
    environment = os.environ.copy()
    environment['ROOT_PATH'] = str(root)
    environment['ROOTDETECTOR_DESKTOP_HOST'] = '1'
    return environment


def loopback_port_busy():
    try:
        with socket.create_connection(('127.0.0.1', 5000), timeout=0.3):
            return True
    except OSError:
        return False


def status_page(title, detail):
    return (
        '<!doctype html><html><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<style>body{{font:16px system-ui,sans-serif;max-width:48rem;'
        'margin:12vh auto;padding:0 2rem;color:#183843;line-height:1.5}}'
        'h1{{font-size:1.5rem}}p{{white-space:pre-wrap}}</style>'
        '<h1>{}</h1><p>{}</p></html>'
    ).format(html.escape(title), html.escape(detail))


class DesktopHost:
    def __init__(self, root=None, opener=None):
        self.root = Path(root) if root is not None else package_root()
        self.opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.window = None
        self.process = None
        self.log_file = None
        self.token = None
        self.ready = False
        self.closed = threading.Event()

    def request(self, path, method='GET'):
        headers = {'Accept': 'application/json'}
        if method != 'GET':
            headers['X-RootDetector-Token'] = self.token or ''
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(
            BASE_URL + path,
            data=b'{}' if method != 'GET' else None,
            headers=headers,
            method=method,
        )
        with self.opener.open(request, timeout=3) as response:
            return json.load(response)

    def start_backend(self):
        executable = backend_path(self.root)
        if not executable.is_file():
            raise RuntimeError('The package is incomplete: main/main.exe is missing. Re-extract or reinstall RootDetector.')
        if loopback_port_busy():
            raise RuntimeError(
                'Port 5000 is already in use. Close other RootDetector copies and retry. '
                'This window will not connect to an unknown local process.'
            )
        path = log_path(self.root)
        self.log_file = open(str(path), 'a', encoding='utf-8')
        self.log_file.write('\n--- RootDetector desktop launch ---\n')
        self.log_file.flush()
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        self.process = subprocess.Popen(
            [str(executable)],
            cwd=str(self.root),
            env=backend_environment(self.root),
            stdin=subprocess.DEVNULL,
            stdout=self.log_file,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )

    def start_and_monitor(self):
        try:
            self.start_backend()
            deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
            while not self.closed.is_set() and time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError(
                        'The local analysis process exited during startup. '
                        'See {} for details.'.format(log_path(self.root))
                    )
                try:
                    session = self.request('/api/session')
                    if session.get('asset_schema') and session.get('token'):
                        self.token = session['token']
                        self.ready = True
                        self.window.load_url(BASE_URL + '/')
                        return
                except (OSError, ValueError, KeyError):
                    pass
                time.sleep(1)
            if not self.closed.is_set():
                raise RuntimeError(
                    'RootDetector did not become ready within 30 minutes. '
                    'Check the network, disk space, and {}.'.format(log_path(self.root))
                )
        except Exception as exc:
            if not self.closed.is_set():
                self.window.load_html(status_page('RootDetector could not start', str(exc)))

    def on_closing(self, _window=None):
        if self.process is None or self.process.poll() is not None:
            self.stop_backend()
            return True
        if not self.ready:
            confirmed = self.window.create_confirmation_dialog(
                'RootDetector is still starting',
                'Closing now will interrupt startup or model downloads. Close anyway?',
            )
            if confirmed:
                self.stop_backend()
            return confirmed
        try:
            activity = self.request('/api/desktop/activity')
        except (OSError, ValueError):
            confirmed = self.window.create_confirmation_dialog(
                'RootDetector status unavailable',
                'The local analysis process is not responding. Closing may interrupt work. Close anyway?',
            )
            if confirmed:
                self.stop_backend()
            return confirmed
        active = activity.get('pipeline_runs', [])
        training = activity.get('training_run')
        if not active and not training:
            self.stop_backend()
            return True
        if not self.window.create_confirmation_dialog(
            'Analysis or training is running',
            'Cancel the active work? Keep this window open until cancellation finishes, then close it again.',
        ):
            return False
        try:
            for run in active:
                self.request('/api/pipeline/runs/{}/cancel'.format(run['id']), 'POST')
            if training:
                self.request('/api/training/runs/{}/cancel'.format(training['id']), 'POST')
        except (OSError, ValueError, KeyError):
            pass  # Never close blindly when cancellation status is uncertain.
        return False

    def stop_backend(self):
        self.closed.set()
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if self.log_file is not None:
            self.log_file.close()


def show_native_error(message):
    if sys.platform == 'win32':
        ctypes.windll.user32.MessageBoxW(None, message, 'RootDetector', 0x10)
    else:
        print(message, file=sys.stderr)


def check_package(root):
    try:
        import webview  # Verify frozen window dependencies without opening a GUI.
        if not backend_path(root).is_file():
            raise FileNotFoundError('Missing {}'.format(backend_path(root)))
        return 0
    except Exception:
        diagnostic_path = os.environ.get('ROOTDETECTOR_CHECK_LOG')
        if diagnostic_path:
            with open(diagnostic_path, 'w', encoding='utf-8') as output:
                traceback.print_exc(file=output)
        return 1


def configure_webview(webview):
    # pywebview disables downloads by default. Detection/tracking exports use
    # blob or generated links, so the desktop host must permit Save dialogs.
    webview.settings['ALLOW_DOWNLOADS'] = True


def main():
    root = package_root()
    if sys.argv[1:] == ['--check-package']:
        return check_package(root)
    host = DesktopHost(root)
    try:
        import webview
        configure_webview(webview)
        host.window = webview.create_window(
            'RootDetector',
            html=status_page('Starting RootDetector', 'Preparing the local analysis process. First launch may take several minutes.'),
            width=1200,
            height=800,
            min_size=(800, 600),
        )
        host.window.events.closing += host.on_closing
        webview.start(host.start_and_monitor, gui='edgechromium')
        return 0
    except Exception:
        try:
            path = log_path(root)
            with open(str(path), 'a', encoding='utf-8') as output:
                traceback.print_exc(file=output)
            location = ' See {} for details.'.format(path)
        except OSError:
            location = ''
        show_native_error(
            'The RootDetector window could not open. Install the Microsoft WebView2 Runtime '
            'or use the browser fallback.{}'.format(location)
        )
        return 1
    finally:
        host.stop_backend()


if __name__ == '__main__':
    diagnostic_path = os.environ.get('ROOTDETECTOR_CHECK_LOG')
    if diagnostic_path:
        with open(diagnostic_path, 'w', encoding='utf-8') as output:
            output.write('RootDetector desktop entry; argv={!r}\n'.format(sys.argv[1:]))
    raise SystemExit(main())
