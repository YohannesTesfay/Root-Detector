# Packaged API acceptance

`api_acceptance.py` uses only Python's standard library (Python 3.7+). Run it on
the same machine as a **dedicated running package**, through its loopback URL.
It does not launch, install, upgrade, or shut down the app. Do not point it at a
research session: `--allow-clear` explicitly permits clearing that app's entire
image/result cache. Original fixture files are read only. Use disposable copies.

## Inputs and quick check

Choose at least two actual observations of the same tube and scan level, with
underscore-delimited dates such as `tube01_L001_10.04.24_scan.tif` and
`tube01_L001_20.04.24_scan.tif`. PNG, JPEG, and TIFF are supported. The runner
groups names by everything before the date and pairs adjacent dates; it records
the pairs and source SHA-256 hashes before clearing the cache. Renaming unrelated
images into a sequence does not create valid scientific tracking evidence.

Example in PowerShell (replace paths, port, and commit with the tested package):

```powershell
py -3 tests/acceptance/api_acceptance.py `
  --url http://127.0.0.1:5000 --device cpu --allow-clear `
  --images 'C:\Tests\tube01_L001_10.04.24_scan.tif' 'C:\Tests\tube01_L001_20.04.24_scan.tif' `
  --output 'C:\Tests\evidence\installer-cpu-quick-01' `
  --build-info 'C:\Path\To\RootDetector\BUILD-INFO.txt' --expected-commit 0123456789abcdef `
  --cases repeats --repeats 2
```

The output directory **must not exist**. The server's diagnostic `BUILD-INFO.txt`
is authoritative. The optional local `--build-info` sidecar is saved separately
and must match the server when both are present. It never substitutes for missing
live-server provenance.
Without `--expected-commit`, build identity is saved but not independently checked.
An available system Python runs this harness; the app still uses its own packaged
runtime. On macOS/Linux use `python3` and normal shell line continuations.

## Full run and optional training

Omit `--cases` and `--repeats` for ten Original runs followed by ten Seeded runs,
all eight sampling/mask-policy combinations, and cancellation/retry. Repeat with
`--device cuda` in a fresh output directory for **each** installer and portable
build. CUDA acceptance requires an available GPU and successful tracking on CUDA,
not merely a reported PyTorch build string. CPU success does not qualify GPU.
`--detection-model NAME` selects a saved detection model; otherwise the app's
currently selected saved models are used. `--run-timeout` bounds each job.

Training is opt-in. Add `training` to `--cases` and provide
`--training-image PATH --training-label PATH --confirm-reviewed-label` only for a
genuinely reviewed matching label. For training alone, use `--cases training`.
The runner performs one epoch, saves a uniquely named `acceptance-smoke-*` model,
switches away/reloads it, and detects/tracks the input sequence with it. This
tests plumbing, **not model quality**. The smoke model is deliberately retained;
its name is recorded for later manual cleanup. Original settings are restored
only after job termination is confirmed. Cache contents are not restored.

## Evidence and limits

- `summary.json`: distinct success, failure, timeout, unconfirmed, review-required,
  and not-exercised cases. Exit 0 means selected software cases passed, not full
  release qualification. Check skipped/not-exercised cases explicitly.
- Per-run JSON, settings/runtime snapshots, tracking ZIP exports, and diagnostics
  capture the exact job and output provenance. Selected runs also save a custom
  detection evidence ZIP containing masks, skeletons, and statistics JSON.
- Seeded point arrays, seed identity, statistics, and device must match exactly
  across repeats. Original variability is reported descriptively. Detection
  caches may be reused; this is not a cold-start/restart reproducibility test.
- The eight-option matrix deliberately disables exclusion masks: it checks option
  propagation and zero-exclusion behavior, **not** genuine mask-policy correctness.
- Cancellation uses a known active job only. A run finishing first is recorded as
  not exercised. Lost pipeline creation responses are not retried blindly: inspect
  the dedicated app before further use if the report says unconfirmed.
- Session tokens are not saved. Diagnostics may contain workstation paths and
  filenames: review evidence before sharing it publicly.

Separate release checks still cover genuine exclusion masks, human ecological
review, GUI/display scaling, launcher/installer lifecycle, cold starts, sleep,
and prolonged resource use. This harness does not certify those areas.

Harness-only unit tests (no app, models, or GPU needed):

```sh
python3 -m unittest discover -s tests/acceptance -p 'test_*.py' -v
```
