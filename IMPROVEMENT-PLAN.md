# RootDetector Improvement Plan

**Audit baseline:** repository commit `3f93762`, reviewed 22 July 2026.
**Focused update:** static-analysis and template-tooling triage added 12 August 2026.
**Purpose:** make RootDetector scientifically reliable, secure as a local web application, maintainable, and straightforward to install and use on Windows, macOS, and Linux.

This plan covers the complete application: detection, exclusion masks, tracking, training, CLI, Flask service, browser interface, model distribution, tests, packaging, and contributor workflow. Priorities are **P0** (incorrect or unsafe behavior), **P1** (required for a dependable release), **P2** (major usability or maintainability gain), and **P3** (advanced capability).

## Executive Summary

RootDetector has a useful end-to-end workflow and a clear separation between root-specific code and the `base/` submodule. Its principal limitation is not the model pipeline; it is the aging platform around it. The application is pinned to Python 3.7 and PyTorch 1.10, relies on a local Flask development server, downloads executable model/runtime content without integrity verification, has almost no current CI, and assumes a Linux/X11 or Windows x64 environment in several scripts.

Before adding features, correct the result-export, training-option, cache-invalidation, path-handling, and training-state defects below. Then establish reproducible scientific outputs and a tested CPU baseline on all three desktop operating systems. UI work should follow on that stable service layer.

## Current Architecture and Constraints

- `main.py` selects the browser application or CLI. Root-specific processing lives in `backend/`; shared Flask, settings, file handling, and UI code comes from the `base/` Git submodule.
- Detection creates probability masks, thresholded segmentations, skeletons, and statistics. Tracking segments two observations, matches points, warps the first mask, creates a turnover map, and exports images, JSON, and CSV. Training fine-tunes detection or exclusion-mask models.
- Browser code is plain JavaScript/jQuery with Jinja-composed HTML and vendored Semantic UI assets. Generated `static/` content is rebuilt from `frontend/` and `templates/`.
- Runtime models are Torch packages loaded through pickle-capable APIs. Missing models and, in packaged Windows builds, Torch libraries can be downloaded during startup.
- The repository is large (roughly 500 MB in the audited checkout), including substantial example imagery and Git history. The only workflow is a manually dispatched legacy Windows build.

## Part I — Technical Improvements

### 1. Correctness and Data Integrity

These changes block a trustworthy release.

| ID | Priority | Finding and evidence | Required change and acceptance criterion |
|---|---|---|---|
| T-001 | P0 | `backend/root_tracking.py:239-259` declares CSV columns as same/decay/growth/background/mask but writes background/mask/same/decay/growth. | Build rows from named fields with Python's `csv` module. Add a test asserting every header/value pairing and safely quoting commas, quotes, Unicode, and newlines. Provide a migration warning for previously exported aggregate CSV files. |
| T-002 | P0 | `frontend/roots/training.js:18-24` sends `learning_rate`; `backend/training.py:27-35` reads `lr`, silently using `0.001`. | Define one typed training request schema and reject unknown/missing fields. Verify the requested value reaches the optimizer in a test. |
| T-003 | P0 | `models_src/2022-07-11_029/models.py` does not return a success value from `start_training`, while callers interpret falsy values as interruption; the root web endpoint ignores the result and always returns `OK`. | Return an explicit `TrainingResult` with `completed`, `cancelled`, or `failed`; propagate exceptions and non-zero CLI exits; save only completed models. Test completion, cancellation, invalid annotations, and runtime failure. |
| T-004 | P0 | Segmentation and exclusion caches in `backend/root_tracking.py:100-120` are keyed only by input filename. Model, threshold, mask, and preprocessing changes can reuse stale results. | Use content-addressed keys containing input hash, model hash/version, operation version, relevant settings, and mask hash. Store a sidecar manifest and invalidate mismatches. |
| T-005 | P0 | Tracking applies only the first image's exclusion mask after turnover classification (`backend/root_tracking.py:29-30,77-94`). | Have domain experts define whether each observation's mask is warped, unioned, intersected, or treated as unknown. Apply that rule before statistics and validate it against annotated golden cases. |
| T-006 | P0 | Training, CLI, and several web operations do not reliably communicate partial failure. CLI dispatch ultimately exits successfully, and browser cancellation stops iteration without necessarily stopping server inference. | Use job IDs and explicit states; map failures to structured HTTP errors and CLI exit codes; implement cooperative cancellation in inference/training loops. |
| T-007 | P1 | Manual CSV assembly, two-line aggregation assumptions, integer-cast Kimura lengths, and filename collision handling can corrupt or reduce output fidelity. | Use `csv.DictWriter`, preserve floating-point measurements, version schemas, validate imported archives, and allocate collision-free artifact IDs. |
| T-008 | P1 | Evaluation metrics can divide by zero for empty target/prediction masks. Red exclusions are not represented as a first-class ignore region. | Define empty-mask and ignore-mask policies, return `null`/not-applicable where scientifically appropriate, and test every boundary case. |
| T-009 | P1 | “Width” bins appear derived from a skeleton distance transform, which is radius-like unless doubled; units are pixels. | Confirm the measurement definition with researchers, rename or correct it, attach pixel/physical units, and include calibration in exports. |
| T-010 | P1 | Dates are inferred from filenames with permissive browser parsing. Invalid dates, two-digit years, and duplicate basenames can group unrelated observations. | Parse strictly, show confidence/errors, preserve source paths as metadata, and let users edit sample, date, and pair assignments before processing. |

Every result should include a machine-readable manifest with application version, model names and SHA-256 hashes, input hashes, preprocessing and threshold settings, device/provider, calibration, timestamps, units, schema version, and warnings. Tracking should optionally normalize growth/decay by elapsed time. Never silently change a scientific definition: version algorithms and publish migration notes.

### 2. Local-Service Security and Resource Safety

“Localhost only” is not a security boundary by itself: another browser origin, a crafted file/archive, DNS rebinding, or another local process can reach a weak local service.

1. **Contain all paths (P0).** `backend/app.py:27-48` and shared routes in `base/backend/app.py:73-88,162-168` join request data to writable directories without a resolved-path containment check. Replace client-supplied paths with opaque file/model IDs. Centralize `safe_resolve(base, relative)`, reject absolute paths, traversal, separators in IDs, symlink escapes, and unapproved model types. Add adversarial tests for encoded `..`, mixed separators, Unicode, and symlinks.
2. **Correct HTTP semantics (P0).** Convert processing, model saving, cache clearing, deletion, shutdown, and cancellation from `GET` to `POST`/`DELETE`. Require a random per-launch session token and same-origin/CSRF validation. Bind explicitly to `127.0.0.1` and `::1`; reject unexpected `Host` and `Origin` values.
3. **Constrain uploads (P1).** Set request, form-memory, part-count, archive-entry, decompressed-size, image-dimension, pixel-count, and batch-count limits. Validate decoded image content rather than extensions. Use per-project temporary directories and never overwrite on basename collision.
4. **Treat models as executable content (P0).** Torch packages and legacy `.pkl` files can execute code during deserialization. Remove `.pkl` discovery, accept only trusted release models with allowlisted hashes/signatures, and document this trust boundary. Longer term, migrate inference artifacts to a non-pickle format after equivalence validation.
5. **Harden downloads (P0).** Add TLS timeouts, retries, size limits, SHA-256 verification, atomic temporary writes, and actionable offline errors to model/runtime downloads. A partial file must never count as installed. Publish checksums and signatures with releases.
6. **Harden the browser surface (P1).** Escape filenames before DOM insertion and CSS-selector use; remove `eval`-style template execution and inline handlers; enable Jinja autoescaping. Add CSP, `X-Content-Type-Options`, `Referrer-Policy`, and restrictive frame/permissions policies.
7. **Isolate runtime state (P1).** Replace the shared working-directory cache, settings, and whole-cache deletion with `platformdirs` locations and unique session/project directories. Use atomic settings writes and a single-instance lock where needed.
8. **Make progress streaming finite (P2).** Unsubscribe SSE queues on disconnect, send heartbeats, bound queues, and surface reconnect state. Redact local paths and sensitive metadata from support logs.

### 3. Maintainable Service Architecture

Create a headless Python package that both Flask and CLI call:

```text
src/rootdetector/
  domain/        # validated requests, results, scientific definitions
  inference/     # detection, exclusion, tracking, device providers
  services/      # projects, jobs, exports, model registry
  adapters/      # Flask API, CLI, filesystem, model formats
```

- Introduce typed dataclasses or Pydantic models for settings, requests, manifests, results, and errors. Validate at boundaries; remove assertions for user input.
- Replace mutable module/class globals with dependency-injected application state. A `JobManager` should own queued/running/completed/failed/cancelled jobs, progress, cancellation tokens, and cleanup.
- Give every import a project/workspace. Persist source metadata, processing history, corrections, results, and manifests so a session can resume after restart.
- Return a versioned JSON API under `/api/v1`; use consistent status codes and error bodies. Generate API documentation from schemas.
- Eliminate duplicated base/root training and processing paths. Decide whether `base/` remains a pinned fork, becomes a versioned dependency, or is absorbed into a monorepo. Cross-repository changes currently make atomic fixes difficult.
- Add structured logging with run/job correlation IDs and an opt-in diagnostic-bundle exporter.

### 4. Supported Runtime and Dependencies

Python 3.7 reached end of life in 2023, while current PyTorch requires Python 3.9 or newer. Adopt one conservative baseline—preferably Python 3.11 or 3.12 after scientific regression testing—rather than immediately chasing the newest interpreter.

- Add `pyproject.toml` with build metadata, console entry points, minimum Python, platform markers, and `dev`, `test`, `docs`, and optional accelerator dependency groups.
- Produce a reviewed, hash-locked environment. Keep direct dependencies separate from transitive pins and automate update PRs.
- Upgrade Flask/Werkzeug, NumPy, SciPy, scikit-image, Pillow, PyTorch/torchvision, PyInstaller, ONNX Runtime, pytest, and browser tooling in controlled groups. Resolve deprecations and compare golden outputs after each scientific-stack change.
- Replace `ubuntu:latest`, obsolete x86 Miniconda installers, fixed Chromium/Firefox AppImages, old ChromeDriver, Deno 1.30, `wmic`, and CP37 Windows-wheel URLs. Pin supported versions or use current managed actions/toolchains.
- Do not delete tracked `requirements.txt` from `.gitpod.yml`. Replace Gitpod and shell bootstraps with the same documented environment command used locally and in CI.

### 5. Cross-Platform Execution and Packaging

Establish a CPU-first baseline; acceleration is an optional provider, not a requirement.

| Platform | Minimum release target | Acceleration target | Distribution |
|---|---|---|---|
| Windows 10/11 x64 | CPU detection/tracking/training smoke test | CUDA where compatible; evaluate Windows ML/ONNX only after parity tests | Signed installer or MSIX plus portable ZIP |
| macOS 13+ Intel | CPU workflows | Optional MPS/Core ML provider after validation | Signed/notarized `.app` in DMG |
| macOS 13+ Apple Silicon | Native arm64 CPU workflows | Optional MPS/Core ML | Signed/notarized arm64 or universal app |
| Ubuntu LTS x64 | CPU workflows and headless CLI | Optional CUDA package/container | AppImage or Flatpak plus archive/package |
| Linux arm64 | Headless CPU smoke test first | Provider dependent | Multi-arch container/archive |

- PyInstaller is not a cross-compiler: build and smoke-test separately on Windows, macOS, and Linux. Replace the current single manual Windows workflow with an OS/architecture matrix.
- Remove assumptions such as `/main/main`, X11-only test controls, unquoted paths, fixed port 5000, and platform checks based on substring matching.
- Use a free loopback port, wait on a health endpoint, open the browser only after readiness, and display the URL if automatic opening fails. Handle spaces, Unicode, and long paths.
- Publish platform-specific, signed artifacts with checksums, SBOM, provenance, model compatibility metadata, and an offline model bundle. Add an in-app version/model compatibility screen; updates should be opt-in and verifiable.
- Build multi-platform `linux/amd64` and `linux/arm64` CPU containers with Buildx and pinned base digests. Publish a separate NVIDIA image rather than embedding GPU assumptions in the baseline.
- Evaluate an embedded desktop shell only after API hardening. A browser-hosted UI remains viable and simpler; a desktop wrapper is worthwhile only if it materially improves file dialogs, lifecycle, signing, and offline installation.

### 6. Performance and Scalability

- Keep validated model sessions warm per device instead of loading/moving models for each file. Use `torch.inference_mode()`, adaptive patch batching, and mixed precision only after numerical validation.
- Replace the global lock with a bounded job queue that exposes order and ETA while still preventing unsafe concurrent GPU use.
- Stream server-created archives rather than holding every detection result in browser memory. Stream or tile previews for very large TIFFs and retain lossless originals for analysis.
- Make patch size, overlap, and tracking sample count (`n=5000` is hard-coded in `backend/root_tracking.py:39`) device-aware and benchmarked. Store safe cache artifacts without quantizing probability maps unless equivalence is demonstrated.
- Stop regenerating and deleting all static files on each development request. Build assets incrementally and use fingerprinted production assets with normal caching.
- Define benchmark fixtures for large images, 100/1,000/10,000-file projects, CPU and GPU memory, startup, inference, tracking, export, and cancellation latency. Prevent material regressions in CI.

### 7. Testing, CI, and Release Quality

Create fast required checks and separate slow/model-dependent checks:

1. **Unit tests:** CSV mapping, cache keys, safe paths, strict date parsing, filename collisions, settings recovery, download hashes, image validation, empty metrics, calibration, and job state transitions.
2. **Scientific golden tests:** approved masks, skeletons, matches, turnover classes, and statistics across dependency upgrades. Compare with documented tolerances across CPU/GPU and OS; investigate rather than blindly refresh fixtures.
3. **Integration tests:** versioned API, project persistence, archive import/export, cancellation, corrupt inputs/models, offline first launch, and concurrent sessions.
4. **Browser tests:** replace ancient AppImage/Selenium assumptions with current Playwright-managed Chromium, Firefox, and WebKit coverage. Add keyboard-only, touch/drag-alternative, responsive, and automated accessibility checks.
5. **Release tests:** install and launch each packaged artifact on a clean VM/runner, complete a tiny detection/tracking workflow, verify signatures/checksums, and uninstall cleanly.

Run formatting, linting, type checks, dependency auditing, secret scanning, CodeQL, shell/Docker linting, and coverage in pull requests. Use pinned current GitHub Actions, a Python/OS matrix, dependency caching, and uploaded failure artifacts. Keep large model tests opt-in or scheduled, but require a small deterministic smoke model on every PR.

- **Static-analysis baseline (P2).** Run Pyright/Pylance against the same supported environment used by tests, add a versioned configuration, and declare the `base/` import path explicitly. Incrementally type dynamic settings, model/result dictionaries, CLI overrides, optional returns, and shared-module exports. Ratchet the existing baseline so new or changed code cannot add diagnostics; do not hide unresolved dependencies or use blanket `type: ignore` directives.
- **Jinja/editor tooling (P2).** Configure Jinja-aware HTML editing and validate both templates and rendered output. Move inline scripts and event handlers into external JavaScript with data attributes so raw `{{ ... }}` expressions are not parsed as malformed JavaScript. Lint emitted JavaScript and HTML in CI rather than relying only on the editor's raw-template parser.

### 8. Repository and Delivery Hygiene

- Move large demonstration datasets to Git LFS, a release asset, or a versioned data registry; retain only compact licensed fixtures needed by tests. Record source, license, checksum, and expected result.
- Add `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`, issue/PR templates, release policy, support boundaries, model/data cards, and citation information where missing.
- Use semantic versions for the application, schemas, and model compatibility. Keep `main` releasable, require focused PRs and passing checks, and document fork/upstream synchronization.
- Generate developer and user documentation in CI. Include installation per OS, offline setup, tutorials for all three workflows, output-schema definitions, troubleshooting, GPU compatibility, privacy, backup, and upgrade/migration guides.

## Part II — Interface and User Experience

### 9. Information Architecture and Onboarding

Replace the implicit tab sequence with a visible workflow:

```text
Create/Open Project -> Import & Validate -> Detect -> Review/Correct
                    -> Track -> Review/Correct -> Analyze & Export
                    -> Train Model (optional)
```

- On first launch, show system readiness: app/model versions, storage location/free space, selected compute device, model availability, and a sample-project option.
- Use persistent projects rather than a disposable browser session. Auto-save edits, show saved/dirty state, and offer recent projects, backup, duplicate, and archive actions.
- Keep primary actions visible and name them with verbs: “Import images,” “Run detection,” “Review matches,” and “Export results.” Add contextual help with scientific definitions, not only tooltips.
- Provide a global job center with per-file progress, queue order, ETA, pause/cancel/retry, warnings, and completion notifications.

### 10. Import, Organization, and Validation

- Support file and folder selection, drag-and-drop, ZIP import, thumbnails, sortable metadata, duplicate detection, and clear accepted-format/size guidance.
- Validate decode, dimensions, bit depth, orientation, naming, dates, masks, and available disk space before starting. Show errors beside affected files and allow retry/removal without clearing valid imports.
- Add a grouping editor for experiment/sample/observation date and an explicit tracking-pair timeline or matrix. Never make filename inference irreversible.
- Preserve original names and paths as metadata while using internal IDs. Show how collisions are resolved. Offer calibration and time-interval setup once per project with per-image overrides.

### 11. Detection Review

- Present original, probability heatmap, binary mask, exclusion mask, and skeleton in synchronized split/overlay views. Include opacity, threshold, zoom, pan, fit, and color legend controls.
- Add explicit brush/erase/polygon/region-of-interest tools with adjustable size, undo/redo history, before/after comparison, and keyboard/touch equivalents.
- Display quality indicators and warnings (blank/saturated mask, unexpected dimensions, low foreground, edge clipping) without implying unsupported statistical certainty.
- Make batch decisions efficient: filter/sort by status, apply reviewed settings to selected images, and require confirmation before overwriting manual corrections.

### 12. Tracking Review

- Replace Ctrl/Shift-only mouse gestures with a visible tool palette: select, add match, remove match, correct correspondence, pan, and zoom. Keep shortcuts as accelerators and show them in a shortcut panel.
- Use linked side-by-side images plus turnover overlay, synchronized zoom, numbered/colored correspondences, confidence/quality indicators, and a searchable match list.
- Provide undo/redo, revert automatic matches, mark regions unknown, rerun selected pairs, and clearly distinguish automatic from manual points.
- Add a color-blind-safe turnover palette with text/shape legend and optional patterns. Excluded/unknown regions must be visually and numerically distinct.
- Show the exact interval, models, settings, calibration, match count, warnings, and analysis eligibility before export.

### 13. Training Experience

- Turn training into a guided workflow: validate image/annotation pairs, preview labels, split train/validation data, select a compatible base model, review hyperparameters, estimate resources, then confirm.
- Show live loss and validation metrics, epoch/step, elapsed/estimated time, device/memory, checkpoints, logs, and a genuine cancellation state. Preserve a recoverable checkpoint after interruption.
- Record dataset/model provenance and compare the candidate to the base model on a held-out set. Do not allow a model to replace the active one until validation and an explicit save/name action succeed.
- Add model cards covering intended specimens, image conditions, limitations, training data, metrics, version compatibility, and checksum.

### 14. Results, Export, and Diagnostics

- Provide a results dashboard with summary cards, distributions/trends, filters, sortable tables, pair previews, warnings, and drill-down into source images.
- Offer export profiles: compact results, complete reproducibility bundle, images only, and table only. Preview columns, delimiter, decimal format, units, and exclusions before export.
- Include a `manifest.json`, schema documentation, warnings, and checksums in every complete bundle. Stream large exports and report progress.
- Replace generic toasts/HTTP 500s with actionable messages containing what failed, affected files, safe recovery steps, retry, and a copyable diagnostic ID. Offer an explicit privacy-reviewed support bundle.

### 15. Accessibility, Responsiveness, and International Use

Target **WCAG 2.2 AA** for all primary workflows.

- Add `<!doctype html>`, language, charset, and viewport metadata; semantic landmarks/headings; meaningful image alternatives; real buttons and links; accessible names; and valid label/input relationships.
- Make every action operable by keyboard. Provide visible focus, logical focus order, dialog focus trapping/restoration, skip links, and non-drag alternatives. Announce progress, errors, selection, and completion through appropriate live regions.
- Never rely on color, icon, hover, modifier keys, or font weight alone. Meet text/UI contrast, honor reduced motion, and provide high-contrast and color-blind-safe themes.
- Replace fixed-size panels/tables with responsive reflow for laptop, tablet, zoomed, and 320-CSS-pixel layouts. Use adequate touch targets and test 200%/400% zoom.
- Externalize UI strings, units, number/date formats, and decimal conventions. Start with English and German-ready localization infrastructure. Keep scientific export schemas locale-neutral and explicit.

### 16. Frontend Modernization

Modernize incrementally rather than beginning with a framework rewrite.

1. Put third-party frontend dependencies under a package manager and lockfile; update old jQuery/Semantic UI and remove checked-in generated/minified duplicates where licensing permits.
2. Add an asset build pipeline with ES modules, formatting, linting, tests, source maps, hashed production assets, and CSP-compatible event listeners.
3. Extract API, state, projects, jobs, image viewers, dialogs, and form validation into testable modules. TypeScript can reduce contract drift such as the `learning_rate`/`lr` defect.
4. Reassess the UI library after workflow components and accessibility requirements are known. Choose a framework only if it reduces lifecycle and accessibility complexity enough to justify migration.

## Prioritized Delivery Roadmap

### Phase 0 — Trustworthy Baseline

- Fix T-001 through T-006, path containment, HTTP mutation semantics, model/download integrity, frontend upload races, and truthful exit/error states.
- Write regression tests before or with each fix. Publish a known-issues notice for current CSV exports and model trust.
- Freeze scientific definitions and assemble reviewed golden fixtures.

**Exit gate:** no known silent result corruption, traversal, unverified executable download, or false-success path remains.

### Phase 1 — Reproducible Core

- Introduce the package/service boundary, typed schemas, project storage, manifests, job manager, structured errors/logging, and supported Python environment.
- Upgrade dependencies in controlled steps and establish unit, API, scientific, and security CI.

**Exit gate:** headless CPU workflows are deterministic, resumable, versioned, and tested on Windows, macOS, and Linux runners.

### Phase 2 — Portable Releases

- Build signed platform artifacts and multi-arch containers; add offline model installation, release smoke tests, SBOM/provenance, migration tooling, and user installation guides.
- Validate optional CUDA and Apple acceleration against CPU golden outputs.

**Exit gate:** a non-developer can install, run a sample, export, update, and uninstall on every supported desktop platform.

### Phase 3 — Workflow and Accessibility Redesign

- Implement projects/onboarding, validated import, job center, accessible detection/tracking tool palettes, responsive layout, improved errors, and export preview.
- Run keyboard, screen-reader, zoom, touch, color, and usability studies with representative researchers.

**Exit gate:** every core workflow is keyboard-accessible, recoverable after interruption, understandable without filename conventions, and meets audited WCAG 2.2 AA criteria.

### Phase 4 — Advanced Scientific Platform

- Add training evaluation/model registry, calibrated longitudinal analytics, plugin/provider interfaces, scalable batch processing, and optional desktop shell or remote worker.
- Consider ONNX Runtime providers, collaboration, cloud execution, or public-service deployment only with separately validated model parity and a new security/operations design.

## Definition of Done for a Stable 2.0 Release

- All P0/P1 findings are closed with regression tests and reviewed scientific acceptance criteria.
- CPU results match approved golden data on Windows, macOS Intel/x64, macOS arm64, and Linux x64 within documented tolerances.
- Installers are signed/notarized, checksummed, SBOM-attached, reproducibly built where practical, and smoke-tested on clean systems.
- No critical/high dependency or application security finding is open; uploads, paths, archives, models, and localhost requests are constrained.
- Core detection, tracking, correction, training, and export workflows meet WCAG 2.2 AA and pass keyboard-only testing.
- A complete result can be traced to exact inputs, models, settings, code/schema version, device, calibration, and warnings.
- User, administrator, model, output-schema, troubleshooting, contribution, security, and migration documentation is current.

## Deliberate Non-Goals Until the Baseline Is Stable

Do not prioritize a wholesale frontend rewrite, a public multi-user server, cloud collaboration, mobile-native apps, a new segmentation architecture, or automatic updates ahead of correctness, reproducibility, current dependencies, and portable tested releases. Each of those expands the validation and threat surface and should begin with a separate design proposal.

## Reference Basis

- [Python version status](https://devguide.python.org/versions/) — official lifecycle dates.
- [PyTorch local installation guidance](https://docs.pytorch.org/get-started/locally/) — current Python and operating-system support.
- [PyInstaller documentation](https://pyinstaller.org/en/stable/index.html) and [usage notes](https://pyinstaller.org/en/stable/usage.html) — per-platform builds and supported systems.
- [Flask development server](https://flask.palletsprojects.com/en/stable/server/) and [web security guidance](https://flask.palletsprojects.com/en/stable/web-security/) — deployment warning, host validation, request limits, and browser security controls.
- [GitHub-hosted runners](https://docs.github.com/en/actions/concepts/runners/github-hosted-runners) and [matrix jobs](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/run-job-variations) — Windows, macOS, and Linux CI design.
- [Docker multi-platform builds](https://docs.docker.com/build/building/multi-platform/) and [GitHub Actions example](https://docs.docker.com/build/ci/github-actions/multi-platform/) — amd64/arm64 images.
- [PyPA dependency groups](https://packaging.python.org/en/latest/specifications/dependency-groups/) and [`pylock.toml`](https://packaging.python.org/en/latest/specifications/pylock-toml/) — standardized dependency metadata and locking.
- [ONNX Runtime execution providers](https://onnxruntime.ai/docs/execution-providers/) — optional cross-device provider architecture.
- [WCAG 2.2](https://www.w3.org/TR/WCAG22/) and [WCAG 2.2 additions](https://www.w3.org/WAI/standards-guidelines/wcag/new-in-22/) — keyboard, focus, target size, status, contrast, and dragging requirements.
