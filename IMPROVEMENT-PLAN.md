# RootDetector Improvement Plan

**Audit baseline:** repository commit `3f93762`, reviewed 22 July 2026.
**Focused update:** static-analysis and template-tooling triage added 12 August 2026.
**Implementation checkpoint:** local-service security and upload-safety foundation added 12 August 2026.
**Correctness checkpoint:** T-001 through T-004 implementation and regression coverage added 12 August 2026.
**Scientific/job checkpoint:** T-005 and T-006 implementation and regression coverage added 12 August 2026.
**Windows acceptance checkpoint:** **PASS.** The 24 August 2026 full retest at `4b64890` cleared packaged tracking cancellation/retry, export, memory cleanup, and Settings keyboard access. The focused retest of `e9b86bb` from Actions run `32685037316` then passed two complete Training Stop -> Interrupted -> Retry -> Completed cycles. PR #3 has no remaining packaged-Windows blocker.
**Branch synchronization checkpoint:** PR #3 was merged into `fix/core-automation`; fork `main` was merged into that branch as `bea78d0`. Its exact head passed Actions run `32690969751` and produced the single `RootDetector-Windows-portable` artifact. The core branch was then merged into `feature/reliability-security-hardening`; the combined 98-test fast suite and two released-model smoke/equivalence tests pass.
**Fork integration checkpoint:** `fix/core-automation` was merged into fork `main` as `01de4e8`, then the resulting `origin/main` was merged back into `feature/reliability-security-hardening` without content conflicts.
**Purpose:** make RootDetector scientifically reliable, secure as a local web application, maintainable, and straightforward to install and use on Windows, macOS, and Linux.

This plan covers the complete application: detection, exclusion masks, tracking, training, CLI, Flask service, browser interface, model distribution, tests, packaging, and contributor workflow. Priorities are **P0** (incorrect or unsafe behavior), **P1** (required for a dependable release), **P2** (major usability or maintainability gain), and **P3** (advanced capability).

## Executive Summary

RootDetector has a useful end-to-end workflow and a clear separation between root-specific code and the `base/` submodule. Its principal limitation is not the model pipeline; it is the aging platform around it. The application is pinned to Python 3.7 and PyTorch 1.10, relies on a local Flask development server, downloads executable model/runtime content without integrity verification, has almost no current CI, and assumes a Linux/X11 or Windows x64 environment in several scripts.

Before adding features, correct the result-export, training-option, cache-invalidation, path-handling, and training-state defects below. Then establish reproducible scientific outputs and a tested CPU baseline on all three desktop operating systems. UI work should follow on that stable service layer.

### Implementation Status

The first three extended tranches are implemented on the current development branch:

- request filenames are validated through one resolved-path containment layer, including symlink-escape tests;
- state-changing browser calls use `POST` or `DELETE`, a random per-launch token, same-origin checks, and loopback-only host validation;
- uploads have request, batch, filename, decoded-format, byte, and pixel limits; corrupt files and basename collisions are rejected without overwriting existing data;
- restrictive response headers are active, and the automated two-image detection/tracking/export workflow has passed a real-browser regression test.
- tracking CSVs use named fields and standards-compliant quoting, combined exports retain all valid rows, and ZIPs identify schema 2 with a warning about older mislabeled exports;
- browser and CLI training share the validated `training_type`, `epochs`, and `lr` schema; completion, cancellation, failure, saving, and CLI exit states are explicit;
- segmentation and exclusion-mask arrays use content-addressed keys and manifests covering input, model/custom-mask hashes, operation versions, and artifact hashes.
- tracking now evaluates both observations' exclusion masks in observation-2 coordinates; the explicit default is conservative union, alternative policies are selectable, and result JSON/ZIP manifests record the policy and pixel provenance;
- analysis and training use run IDs, explicit states, progress, diagnostic IDs, cooperative cancellation, and truthful terminal results; cancelled/failed analysis items can be retried while unsafe partial training models cannot be saved.
- the released tracking weights now run through a versioned application-owned matcher that preserves the 2022 algorithm while checking cancellation and reporting progress after each 512-point batch; deterministic tests compare it directly with the function embedded in the released package.

This is a foundation, not closure of the full plan. Opaque artifact IDs, per-project runtime directories, trusted non-pickle model distribution, removal of inline/evaluated browser code, dependency modernization, and cross-platform release qualification remain open. T-003 still requires a full training acceptance run with the released model on supported CPU/GPU targets before release. T-005 still needs domain-reviewed annotated golden cases. Cooperative cancellation cannot interrupt a single active PyTorch descriptor operation; strict cancellation deadlines and crash containment require the future subprocess-worker design below. The current Content Security Policy is intentionally transitional because the legacy templates still require inline script/style and `eval` support.

### Active Delivery Checkpoint

Keep the tested core branch, fork `main`, and the larger feature branch behind explicit release gates:

1. **Validated core and narrow follow-up — complete.** Preserve the broad `4b64890` report and focused `e9b86bb` training retest as release evidence. PR #3 is merged into `fix/core-automation`.
2. **Core/main workflow conflict — complete.** Fork `main` was merged into the core branch while retaining the accepted Node-24-native workflow and its single full-portable artifact contract. Actions run `32690969751` passed for exact head `bea78d0`.
3. **Core merge into fork main — complete.** The accepted core branch is present in fork `main` as merge commit `01de4e8`.
4. **Feature synchronization — complete.** The updated fork `main` is merged into `feature/reliability-security-hardening` without reverting asynchronous jobs, request security, content-addressed caches, scientific export fixes, or the application-owned matcher. The combined Docker suites pass 98 fast and two real-model tests.
5. **Feature qualification — next.** Keep the fork PR in draft, build the feature branch's own Windows artifact, and run focused browser and packaged-Windows acceptance. Mark the PR ready and merge only after that evidence is recorded; then prepare a deliberately scoped upstream contribution strategy.

The current `.update.zip` is not an installer or automatic updater. It contains only `main/main.exe` and generated `static/` assets for manual replacement in a compatible existing installation; it omits launchers and most runtime files. New users must receive the full ZIP. A future updater requires signed manifests, compatibility checks, atomic replacement, rollback, and explicit user consent.

### Windows Acceptance Findings — 13 August 2026

The first packaged run at `fc3ac93` was **blocked**, not failed. It passed full-ZIP completeness, extraction and launch from a path containing spaces, first-run runtime/model downloads, browser opening, loopback-only binding, 125% display scaling, and dependency reuse after restart. The Windows automation controller could not observe the legacy label-triggered native file chooser, so it could not evaluate detection, tracking, cancellation, retry, export, training, or power behavior. This is incomplete acceptance evidence rather than evidence that the analysis pipeline failed.

The narrow `fix/windows-acceptance-followup` scope addresses only issues supported by code or acceptance evidence:

- accept the public `learning_rate` training field and the legacy `lr` alias, reject conflicting values, report the effective value, and prove the normalized value reaches the model;
- use native keyboard-operable import buttons, semantic disabled state, accessible Settings actions, a contained modal tab order, and short help for the controls involved in the blocked test;
- replace Node-20 workflow action majors and publish only the full portable Windows ZIP as the user artifact;
- turn packaged first-run download exceptions into a concise recovery message and document required outbound access.

These larger items remain explicitly deferred and must not be lost after the Windows retest:

1. **Bootstrap manager:** provide a graphical readiness/download screen with per-component progress, bounded retries/timeouts, proxy guidance, verified resumable downloads, an offline bundle, partial-file cleanup, and a diagnostic log. A console message is only an interim safeguard.
2. **Restart-safe projects and jobs:** persist imported-file metadata, run state, completed artifacts, settings snapshots, and recovery decisions atomically. On restart, offer Resume, Retry incomplete, or Discard instead of silently presenting an empty session.
3. **Resumable training:** save versioned model, optimizer, scheduler, epoch/batch, dataset, random-state, and hyperparameter checkpoints atomically; validate compatibility before resume and never expose a partial model as completed.
4. **Windows power lifecycle:** hold a system execution request only while analysis or training is active, show its status, release it on every terminal/error/exit path, and test display-off, screen lock, sleep/hibernate, shutdown, and crash recovery with `powercfg /requests` evidence.
5. **Native Windows acceptance automation:** maintain a Windows-hosted test that can select real files and cover launch, import, detection-to-tracking, cancel, retry, export, restart, one-epoch training, keyboard navigation, and supported DPI settings. Browser-controller limitations must be reported separately from application failures.
6. **Complete contextual help and accessibility:** inventory every root and shared-base control, add accessible names and focus/touch alternatives to hover help, replace non-semantic interactive elements, and run keyboard/screen-reader/WCAG checks across every modal and generated row.

The narrow branch passed packaged Windows acceptance. Retain the Docker/Playwright checks for fast regression feedback, but continue to require packaged-host testing for release-sensitive Windows behavior.

### Windows Acceptance Retest — 18 August 2026

The full portable ZIP passed provenance/hash verification, launch, two-TIFF import, automatic detection-to-tracking handoff, default root-threshold protection, detection export, restart, and 125% display scaling. This clears the earlier file-chooser uncertainty: import works in the packaged application.

The retest confirmed three application defects. Forcing a 149,085-pixel pair past the safety threshold made tracking consume about 12 GB while cancellation hid the modal but did not stop the active match; interrupted training showed 100% and could not be restarted from the same page; and Settings focus did not advance from Close. The narrow follow-up therefore adds bounded 512-point matching with cooperative cancellation and visible internal progress, cancelled-item retry, explicit training interruption/retry controls, deterministic Settings focus containment, improved control semantics, and source/build provenance.

The Windows controller—not RootDetector—blocked `powercfg`, lock/display-off observation, native UI automation, the 100% scaling pass, and final process cleanup. Treat those checks as unverified. Rebuild and rerun with a genuinely sequential lower-root pair for ordinary success, then separately exercise cancellation on a deliberately heavier pair without bypassing the threshold for routine use. Do not merge the core PR until packaged cancellation and training retry pass.

### Windows Acceptance Retest — 24 August 2026

The full portable artifact from commit `4b648901b0dbe98e8fe5bb5fd5ae8999b5090d73` and Actions run `32149823478` passed provenance, spaced-path extraction, launch, verified first-run downloads, automatic detection-to-tracking handoff, truthful tracking cancellation, cancelled-job retry, detection/tracking export, warm restart, Settings keyboard navigation, and 125% DPI checks. Tracking cancellation became terminal in about 13.65 seconds and private memory fell from about 5.88 GB to 1.40 GB. Peak working set remained about 6.93 GB for one identical-image pair, so scaling and batching remain performance work rather than a blocker for this narrow branch.

Training Stop reached a truthful interrupted state, but two retries ran to 100% and were again labeled interrupted. This was an application defect, not Windows interference: each `/training` request returned HTTP 200, and the released model wrapper returns `None` after both ordinary completion and interruption. The narrow follow-up records cancellation independently, clears it before every run, adapts the released fit result, restores the saved starting model after cancellation/failure, blocks saving incomplete weights, and reserves displayed 100% for backend-confirmed completion.

The focused packaged-Windows retest of `e9b86bb` is **PASS**. Artifact SHA-256 `75ee7918e6807027ec5d7f2eb0ae7a6da2e885c17c0bbbbcdad634902cc908b7` matched GitHub and `BUILD-INFO.txt`. In two independent cycles, Stop at 25% ended Interrupted at 38% with no Save Model; Retry ended Training finished at 100% with Save Model available. No model was saved, no application traceback was reported, and the test process tree was stopped afterward. This closes the final acceptance blocker for PR #3. It validates training mechanics and state truthfulness, not model quality or the complete CPU/GPU scientific training matrix.

The retest also confirms these planned, non-blocking follow-ups:

- reduce tracking's multi-gigabyte peak with measured descriptor/matching memory budgets and larger-dataset benchmarks;
- persist projects, results, and recoverable job/checkpoint state across restart instead of returning to `No Files Loaded`;
- implement an application-owned Windows execution request during active analysis/training, with guaranteed release and elevated `powercfg /requests` acceptance evidence;
- complete accessible contextual help for result-row view/overlay icons, overflow actions, and training parameter effects/ranges;
- sign future Windows executables/installers to reduce SmartScreen uncertainty and qualify both 100% and 125% DPI on supported Windows versions.

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
| T-001 | P0 — implemented | Earlier tracking CSV rows placed background/mask values under same/decay headers and used fragile aggregation. | Named `csv.DictWriter` records, quoting tests, multi-row aggregation, schema-2 manifests, and an old-export migration warning are implemented. Re-export pre-schema-2 tracking results before comparison. |
| T-002 | P0 — implemented and carried into the feature branch | The browser previously sent `learning_rate` while the backend read `lr`, silently substituting `0.001`. | `learning_rate` is canonical, legacy `lr` remains accepted, conflicting/invalid values are rejected, the effective value is reported, and regression tests prove the normalized value reaches the model. |
| T-003 | P0 — implemented; Windows mechanics accepted | Training previously returned ambiguous values, swallowed model exceptions, reported web success unconditionally, saved partial runs, and discarded CLI exit codes. | `TrainingResult` now distinguishes completed/cancelled/failed; a compatibility adapter exposes errors from released model packages; model source propagates results; web and CLI callers preserve failure/cancellation; only completed runs can be saved. Packaged Windows Stop/Retry mechanics passed twice at `e9b86bb`; full model-quality and CPU/GPU scientific acceptance remains before release. |
| T-004 | P0 — implemented | Segmentation and exclusion caches were previously reusable under changed inputs, models, or masks. | Cache keys and manifests now include input hashes, model names and hashes, custom-mask hashes, operation/schema versions, shapes, dtypes, and artifact hashes. Corrupt artifacts and changed dependencies recompute; adversarial regressions cover each invalidation path. |
| T-005 | P0 — implemented; scientific acceptance pending | Tracking previously applied only the first image's exclusion mask after turnover classification. | The first mask is warped into observation-2 coordinates and combined with observation 2 using an explicit `union` (default), `intersection`, `first`, or `second` policy. JSON and ZIP manifests record presence and pixel counts. Domain experts must still approve the default against annotated golden cases. |
| T-006 | P0 — implemented; hard-isolation follow-up planned | Training, CLI, and several web operations did not reliably communicate partial failure, and browser cancellation did not stop active inference. | Analysis and training now use run IDs and explicit states; failures have diagnostic IDs; CLI exits are nonzero; detection checks per inference patch, training per batch callback, and tracking before/after descriptor operations plus every 512-point matching batch. The application-owned matcher is exactly compared with the released algorithm. Process isolation remains a future hard-cancellation improvement. |
| T-007 | P1 | Manual CSV assembly, two-line aggregation assumptions, integer-cast Kimura lengths, and filename collision handling can corrupt or reduce output fidelity. | Use `csv.DictWriter`, preserve floating-point measurements, version schemas, validate imported archives, and allocate collision-free artifact IDs. |
| T-008 | P1 | Evaluation metrics can divide by zero for empty target/prediction masks. Red exclusions are not represented as a first-class ignore region. | Define empty-mask and ignore-mask policies, return `null`/not-applicable where scientifically appropriate, and test every boundary case. |
| T-009 | P1 | “Width” bins appear derived from a skeleton distance transform, which is radius-like unless doubled; units are pixels. | Confirm the measurement definition with researchers, rename or correct it, attach pixel/physical units, and include calibration in exports. |
| T-010 | P1 | Dates are inferred from filenames with permissive browser parsing. Invalid dates, two-digit years, and duplicate basenames can group unrelated observations. | Parse strictly, show confidence/errors, preserve source paths as metadata, and let users edit sample, date, and pair assignments before processing. |

Every result should include a machine-readable manifest with application version, model names and SHA-256 hashes, input hashes, preprocessing and threshold settings, device/provider, calibration, timestamps, units, schema version, and warnings. Tracking should optionally normalize growth/decay by elapsed time. Never silently change a scientific definition: version algorithms and publish migration notes.

### 2. Local-Service Security and Resource Safety

“Localhost only” is not a security boundary by itself: another browser origin, a crafted file/archive, DNS rebinding, or another local process can reach a weak local service.

1. **Contain all paths (P0; foundation complete).** Request-controlled RootDetector filenames now pass through `backend/security.py`, which rejects absolute paths, traversal, separators, control characters, unapproved extensions, missing files, and symlink escapes. Adversarial regression tests cover these boundaries. Opaque artifact IDs and removal or upstream hardening of the shadowed legacy `base/` implementations remain open.
2. **Correct HTTP semantics (P0; foundation complete).** State-changing browser calls now use `POST`/`DELETE`, require a random per-launch token, validate `Origin` and `Host`, and bind to loopback in ordinary runs. Legacy mutation-by-`GET` routes return `405`. A documented Docker-only flag permits container binding while port publishing remains loopback-only.
3. **Constrain uploads (P1; partially complete).** Request, form-memory, part-count, batch-count, filename, decoded image-format, byte, dimension, and pixel limits are enforced. Uploads use temporary files, identical re-uploads are safe, and differing basename collisions return `409` without overwriting. Per-project directories and archive decompression controls remain open; archives are not currently accepted by this upload endpoint.
4. **Treat models as executable content (P0).** Torch packages and legacy `.pkl` files can execute code during deserialization. Remove `.pkl` discovery, accept only trusted release models with allowlisted hashes/signatures, and document this trust boundary. Longer term, migrate inference artifacts to a non-pickle format after equivalence validation.
5. **Harden downloads (P0).** Add TLS timeouts, retries, size limits, SHA-256 verification, atomic temporary writes, and actionable offline errors to model/runtime downloads. A partial file must never count as installed. Publish checksums and signatures with releases.
6. **Harden the browser surface (P1; partially complete).** CSP, `X-Content-Type-Options`, `Referrer-Policy`, frame denial, and restrictive permissions headers are active. Filename escaping, Jinja autoescaping, inline-handler removal, and removal of `eval`-style template execution remain open; until then, CSP still permits inline script/style and `eval` for compatibility.
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
- Keep GitHub-hosted action runtimes current. Replace Node-20 action majors with Node-24-native releases and add a lightweight workflow validation check so deprecation annotations do not accumulate unnoticed.
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

#### Future: hard cancellation and worker isolation

Cooperative checks are the correct baseline, but they cannot pre-empt a single native PyTorch/BLAS/CUDA operation or contain a native crash. Add an isolated inference worker only after the current adapter is qualified on every release target:

1. Use a `spawn`-based worker protocol, not Unix-only `fork`. Send validated job/model identifiers and paths over a typed IPC channel; never pickle live request objects or trust worker-supplied paths.
2. Load models inside a long-lived worker per device, emit heartbeat/progress/result messages, and stage outputs in a job-specific temporary directory. The parent atomically commits artifacts only after a complete success message.
3. Cancellation first sets the cooperative token. If the worker misses a measured grace deadline, terminate and recreate it. Mark the active item cancelled, delete only its temporary artifacts, and leave completed items retryable.
4. On CUDA, use one worker per device and verify that termination releases GPU memory before admitting another job. Do not terminate threads inside the Flask process.
5. Add Windows `multiprocessing.freeze_support()`, PyInstaller hidden-import/resource coverage, graceful application shutdown, orphan-process cleanup, and equivalent macOS/Linux tests.
6. Acceptance requires a bounded cancellation SLA, no partial exports, no orphan workers, successful next-job recovery, identical CPU results, and documented GPU tolerance across all packaged platforms.

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
- Give every icon-only, abbreviated, or scientifically ambiguous control a short accessible explanation. Tooltips must also open by keyboard focus and have a touch/click alternative; essential instructions must remain visible in the workflow rather than existing only on hover.
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
- Treat display-off, screen lock, system sleep, application exit, and power loss as different states. Keep Windows awake only while an active job needs CPU/GPU execution, release the inhibition immediately afterward, warn before exit, and write restart-safe job/model checkpoints so interrupted work can be resumed or clearly restarted.
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
- Correct the Settings dialog's visually mis-styled `X` control with a narrowly scoped icon-button style, while retaining its accessible name, keyboard operation, visible focus, touch target, and modal-close behavior. Apply the same close-control pattern consistently to other dialogs.
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

- Complete domain acceptance for T-005, run released-model training acceptance for T-003, measure cancellation latency, and address frontend upload races. T-001 through T-006, including the cancellable released-compatible matcher, path containment, model/download integrity, and HTTP mutation semantics now have implementation coverage. Treat subprocess isolation as a later reliability enhancement rather than a Phase-0 blocker.
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
