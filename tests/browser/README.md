# Rendered browser acceptance

This suite replaces the three obsolete SeleniumBase RootDetector tests. It uses a
real Chromium browser and the released models through the live Flask server. Core
pytest does not silently skip browser tests or require SeleniumBase/pyppeteer.

Use **only a disposable app instance**: uploading the fixtures clears its cache;
model settings are temporarily changed and restored at the end. With Docker and
models already installed, start the app in one terminal:

```sh
docker compose -f compose.core.yml run --rm --no-deps -p 127.0.0.1:5505:5000 app
```

Use Node.js 20 or newer in another terminal (independent of pinned Python 3.7):

```sh
npm --prefix tests/browser ci
npm --prefix tests/browser run install-browser
ROOTDETECTOR_BROWSER_TEST_URL=http://127.0.0.1:5505 \
ROOTDETECTOR_BROWSER_TEST_ALLOW_CLEAR=1 npm --prefix tests/browser test
ROOTDETECTOR_BROWSER_TEST_URL=http://127.0.0.1:5505 \
ROOTDETECTOR_BROWSER_TEST_ALLOW_CLEAR=1 npm --prefix tests/browser run test:preparation
```

The script fails explicitly if dependencies, Chromium, both released detection
models, or a reachable server are missing. Set `HEADED=1` to watch the browser;
increase `ROOTDETECTOR_BROWSER_TEST_TIMEOUT_MS` for a slower machine. On Windows,
set the environment variables with PowerShell before `npm ... test`.

Coverage: import ZIP and plain PNG annotations, detection completion state,
segmentation/skeleton/CSV downloads, rendered model selection followed by fresh
inference, chronological tracking completion, and tracking export. It asserts
there are no JavaScript errors or failed HTTP responses. Downloads, logs and
success/failure screenshots are under ignored `tests/browser/artifacts/`.
The preparation suite creates a synthetic 1400-pixel image, crops it through the
UI, restores its downloaded ZIP, applies an explicitly confirmed original-size
mask, and verifies result/provenance roundtrip without automatic training review.

This is CPU browser acceptance. GPU use, installer lifecycle, cancellation/retry,
training, large-scan limitations, display scaling, and ecological correctness require
their separate release checks. Imported fixture masks are test data, not proof of
human review or scientific ground truth.
