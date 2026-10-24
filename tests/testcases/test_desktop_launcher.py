"""Model-free checks for the separate Windows window host."""

import sys
import types

import desktop_main


class RunningProcess:
    def poll(self):
        return None


class Window:
    def __init__(self, confirm=True):
        self.confirm = confirm
        self.prompts = []

    def create_confirmation_dialog(self, title, message):
        self.prompts.append((title, message))
        return self.confirm


def test_backend_environment_preserves_existing_values(monkeypatch, tmp_path):
    monkeypatch.setenv('EXISTING_TEST_VALUE', 'unchanged')
    result = desktop_main.backend_environment(tmp_path)
    assert result['ROOT_PATH'] == str(tmp_path)
    assert result['ROOTDETECTOR_DESKTOP_HOST'] == '1'
    assert result['EXISTING_TEST_VALUE'] == 'unchanged'


def test_status_page_escapes_error_text():
    page = desktop_main.status_page('<unsafe>', '<script>alert(1)</script>')
    assert '<script>' not in page
    assert '&lt;script&gt;' in page


def test_refuses_unknown_process_on_backend_port(tmp_path, monkeypatch):
    executable = tmp_path / 'main' / 'main.exe'
    executable.parent.mkdir()
    executable.touch()
    monkeypatch.setattr(desktop_main, 'loopback_port_busy', lambda: True)
    host = desktop_main.DesktopHost(tmp_path)
    try:
        host.start_backend()
    except RuntimeError as error:
        assert 'unknown local process' in str(error)
    else:
        raise AssertionError('Desktop host must not connect to a pre-existing port.')
    assert host.process is None


def test_close_cancels_active_work_and_waits_for_completion(tmp_path):
    host = desktop_main.DesktopHost(tmp_path)
    host.ready = True
    host.process = RunningProcess()
    host.window = Window()
    calls = []

    def request(path, method='GET'):
        calls.append((path, method))
        if path == '/api/desktop/activity':
            return {'pipeline_runs': [{'id': 'abc', 'state': 'running'}],
                    'training_run': {'id': 'def', 'state': 'running'}}
        return {}

    host.request = request
    assert host.on_closing() is False
    assert calls == [('/api/desktop/activity', 'GET'),
                     ('/api/pipeline/runs/abc/cancel', 'POST'),
                     ('/api/training/runs/def/cancel', 'POST')]
    assert host.window.prompts


def test_idle_close_does_not_cancel(tmp_path):
    host = desktop_main.DesktopHost(tmp_path)
    host.ready = True
    host.process = RunningProcess()
    host.window = Window()
    host.request = lambda path, method='GET': {'pipeline_runs': [], 'training_run': None}
    assert host.on_closing() is True
    assert host.window.prompts == []


def test_startup_close_warns_before_stopping_download(tmp_path):
    host = desktop_main.DesktopHost(tmp_path)
    host.process = RunningProcess()
    host.window = Window(confirm=False)
    assert host.on_closing() is False
    assert 'model downloads' in host.window.prompts[0][1]


def test_package_check_reports_missing_backend(tmp_path, monkeypatch):
    diagnostic = tmp_path / 'check.txt'
    monkeypatch.setenv('ROOTDETECTOR_CHECK_LOG', str(diagnostic))
    monkeypatch.setitem(sys.modules, 'webview', types.ModuleType('webview'))
    assert desktop_main.check_package(tmp_path) == 1
    assert 'main.exe' in diagnostic.read_text(encoding='utf-8')
