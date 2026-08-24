import sys


def packaged_startup_error(exc):
    print('[ERROR] RootDetector could not start: {}'.format(exc))
    print(
        'The first launch requires internet access to download the PyTorch runtime '
        'and pretrained models. Check the connection, proxy, firewall, and available '
        'disk space, then run Start RootDetector.bat again.'
    )


try:
    from backend.app import App
    from backend.cli import CLI
except Exception as exc:
    if __name__ == '__main__' and getattr(sys, 'frozen', False):
        packaged_startup_error(exc)
        sys.exit(1)
    raise

if __name__ == '__main__':
    ok = CLI.run()

    if not ok:
        #start UI
        print('Starting UI')
        try:
            App().run()
        except Exception as exc:
            if getattr(sys, 'frozen', False):
                packaged_startup_error(exc)
                sys.exit(1)
            raise

