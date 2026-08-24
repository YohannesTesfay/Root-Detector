# Repository Guidelines

## Project Structure & Module Organization

`main.py` starts the Flask application. Backend logic is in `backend/`, including the automated pipeline, detection, tracking, training, settings, and CLI modules. RootDetector-specific browser code lives in `frontend/roots/`; shared UI and test infrastructure come from the `base/` Git submodule. HTML templates are in `templates/`, model implementations are in `models_src/`, model download metadata is in `models/pretrained_models.txt`, and sample images are under `images/`. Python tests live in `tests/testcases/`; JavaScript tests are in `tests/testcases_js/`. Generated `static/`, downloaded model weights, `builds/`, caches, and test logs are ignored.

## Build, Test, and Development Commands

- `git submodule update --init --recursive` — populate or refresh the shared `base/` UI.
- `python3.7 -m venv venv && source venv/bin/activate` — create the supported development environment.
- `pip install -r requirements.txt` — install CPU inference and packaging dependencies.
- `python fetch_pretrained_models.py` — download the configured pretrained models.
- `python main.py` — run the app; open `http://localhost:5000`.
- `docker compose -f compose.core.yml build` — build the pinned Python 3.7 core environment.
- `docker compose -f compose.core.yml run --rm test-fast` — run model-free regression tests.
- `docker compose -f compose.core.yml run --rm test-smoke` — run the released-model detection/tracking/export smoke test.
- `python build.py --zip --prune-torchlibs` — generate a distributable PyInstaller bundle.

## Coding Style & Naming Conventions

Use four-space indentation in Python and JavaScript. Follow existing conventions: `snake_case` for Python functions and JavaScript handlers, `PascalCase` for classes, and descriptive lowercase module names. Keep shared behavior in `base/`; add project-specific overrides in `backend/` or `frontend/roots/`. Do not edit generated `static/` or vendored/minified assets directly.

## Testing Guidelines

Pytest drives backend tests; browser tests and coverage are delegated to the base submodule. Name Python tests `test_*.py` and test functions `test_*`. Add focused regression coverage for behavior changes. Run the Docker suite before opening a pull request and report any intentionally skipped tests.

## Commit & Pull Request Guidelines

History favors brief, imperative subjects such as `Update README.md` or `Add input slicing for large files`. Keep commits focused. Pull requests should explain the problem and solution, link relevant issues, list test commands and results, and include screenshots for UI changes. Call out submodule pointer, model URL, dependency, or generated-binary changes explicitly.

## Fork Workflow

Push feature branches to `origin` (`YohannesTesfay/Root-Detector`) and fetch upstream changes from `upstream` (`ExPlEcoGreifswald/RootDetector`). Keep `main` aligned with upstream and develop on topic branches such as `fix/tracking-download`.
