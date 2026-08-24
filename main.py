from backend.app import App
from backend.cli import CLI


if __name__ == '__main__':
    exit_code = CLI.run()

    if exit_code is None:
        # Start the desktop browser application when no CLI operation was requested.
        print('Starting UI')
        App().run()
    raise SystemExit(exit_code)
