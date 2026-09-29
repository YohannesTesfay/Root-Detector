import sys
from desktop_paths import (
    claim_installed_instance,
    configure_installed_paths,
    mark_installed_app_running,
    prepare_installed_assets,
)
import os


def packaged_startup_error(exc):
    diagnostic_hint = ''
    try:
        from backend import diagnostics
        from backend import jobs
        diagnostic_id = jobs.new_diagnostic_id()
        diagnostics.log_exception(diagnostic_id, 'startup', 'application', exc)
        diagnostic_hint = ' Diagnostic ID: {}. See logs\\rootdetector.log.'.format(
            diagnostic_id
        )
    except Exception:
        pass
    print('[ERROR] RootDetector could not start: {}{}'.format(exc, diagnostic_hint))
    if os.environ.get('ROOTDETECTOR_INSTALLED') == '1':
        print(
            'The installed package includes PyTorch and downloads verified models '
            'on first launch. If the runtime is incomplete, reinstall RootDetector. '
            'For model downloads, check the connection and available disk space.'
        )
    else:
        print(
            'The first launch requires internet access to download the PyTorch runtime '
            'and pretrained models. Check the connection, proxy, firewall, and available '
            'disk space, then run StartRootDetector.bat again.'
        )


if __name__ == '__main__':
    try:
        installed_data = configure_installed_paths()
        if not claim_installed_instance(installed_data):
            print(
                'RootDetector is already running for this Windows user. '
                'Return to its browser tab at http://localhost:5000; '
                'close that copy before starting another.'
            )
            sys.exit(0)
        if installed_data is not None:
            mark_installed_app_running()
            prepare_installed_assets(installed_data)
    except Exception as exc:
        packaged_startup_error(exc)
        sys.exit(1)


try:
    from backend.app import App
    from backend.cli import CLI
except Exception as exc:
    if __name__ == '__main__' and getattr(sys, 'frozen', False):
        packaged_startup_error(exc)
        sys.exit(1)
    raise


if __name__ == '__main__':
    try:
        exit_code = CLI.run()
        if exit_code is None:
            # Start the desktop browser application when no CLI operation was requested.
            print('Starting UI')
            App().run()
    except Exception as exc:
        if getattr(sys, 'frozen', False):
            packaged_startup_error(exc)
            sys.exit(1)
        raise
    raise SystemExit(exit_code)
