# RootDetector Improvement Plan

This is the **active** roadmap, not a log of completed branches. The automated detection-to-tracking pipeline, core security/caching fixes, reviewed-label guard, and Windows portable mechanics have implementation and regression coverage. Detailed prior evidence remains in Git history at `51e338a`; completion in code must not be mistaken for scientific or cross-platform approval.

Priorities: **P0** blocks trustworthy results or a safe release; **P1** is required for a dependable product; **P2** improves usability or maintainability. Work against the fork first. Keep upstream unchanged until the fork's exact release candidate is qualified and reviewed.

## Immediate fork release gates

1. **Deterministic tracking (P0 for quantitative use; T-012).** Draft fork PR #6 adds opt-in, version-2 seeded point sampling and records its seed/input/model identities. The released stochastic mode remains the default. Build the PR head as a Windows portable ZIP; repeat valid Eldena pairs in one process and after restart, compare matched points and contained results, and investigate CPU/GPU differences. Obtain ecological review of overlays and turnover before changing the default or treating quantitative output as validated.
2. **Tracking scientific definitions (P0; T-005, T-009).** Review the default union of both exclusion masks against annotated cases. Confirm whether current skeleton distance-transform “width” is a radius or diameter, and add explicit pixel/physical units and calibration to outputs. Do not silently change definitions; version schemas and publish migration notes.
3. **Training quality and provenance (P0; T-003).** Browser training mechanics and cancellation/retry have passed packaged tests, but independently reviewed labels, site/tube-disjoint holdouts, base-model comparison, and ecological approval remain required. Automatically generated masks are predictions, not ground truth. A completed training run is not evidence that its model generalizes.
4. **Exact release head.** Keep PR #6 draft until its remaining gates are recorded. After merge into fork `main`, build and smoke-test that exact head, record the ZIP hash and `BUILD-INFO.txt`, and publish only the tested full portable package. Summarize limitations plainly before proposing an upstream draft PR.

## Correctness and data integrity

| ID | Priority | Next change and acceptance criterion |
| --- | --- | --- |
| T-007 | P1 | Preserve floating-point Kimura lengths, validate imported archives, allocate collision-free artifact IDs, and version export schemas. Regression-test numeric fidelity and multiple files with the same basename. CSV column mapping and quoting are already fixed. |
| T-008 | P1 | Define empty-target/prediction and red exclusion-mask policies for evaluation metrics. Return not-applicable rather than divide by zero; test every boundary case. |
| T-010 | P1 | Let users review and edit sample/date/level assignments before pairing. Keep original paths as metadata, define a two-digit-year policy, and test ambiguous names and cross-site batches. Calendar validation and same-day duplicate rejection already exist. |
| Tracking provenance | P1 | Include input/model hashes, sampling mode, preprocessing, thresholds, device, calibration, units, warnings, and schema/app versions in every complete result. Never compare results from different matcher versions without identifying them. |
| Image preparation | P1 | Design an **opt-in**, previewed alignment/crop workflow for repeated views of the same physical tube and level. Preserve originals and a transform manifest; require a physical anchor and ecological approval. Never silently crop unequal images—the Eldena L003 mismatch must remain an actionable validation error until a reviewed transform exists. |

RootDetector should remain acquisition-source agnostic. PNG/JPEG/TIFF inputs from other scanners can enter detection if fully decodable, but model validity depends on resolution, illumination, scale, orientation, and background. Tracking additionally requires comparable views of the same physical location at different dates.

## Security, storage, and service architecture

- **Model trust (P0).** Legacy PyTorch packages and `.pkl` files can execute code when loaded. Remove untrusted pickle discovery, allowlist trusted model hashes/signatures, and validate any later non-pickle inference format against scientific golden outputs. Harden the first-launch PyTorch runtime download with checksums, timeouts, size limits, atomic installation, and offline guidance; model downloads already have verified SHA-256 and atomic writes.
- **Local-service hardening (P1).** Existing loopback binding, request token, Origin/Host checks, path containment, upload limits, and response headers are a foundation. Replace request-visible filenames with opaque IDs and per-project directories; bound archive extraction and SSE queues, remove inline/evaluated browser code so CSP can be strict, and redact sensitive paths from diagnostics.
- **Restart-safe work (P1).** Persist projects, imported-file metadata, corrections, results, settings snapshots, and job state atomically outside the working directory. On restart, offer Resume, Retry incomplete, or Discard. Add collision-free storage, backup/migration, and a single-instance policy where necessary.
- **Cancellation and isolation (P1).** Current checks are cooperative and cannot interrupt one active native PyTorch/CUDA call. After measuring latency, use a `spawn`-based worker per device with typed IPC, staged artifacts, heartbeat, a bounded cancellation grace period, and worker recovery. Test no orphan processes, partial exports, or GPU-memory leaks on packaged Windows, macOS, and Linux.
- **Maintainability (P2).** Move inference/domain services behind a headless package shared by Flask and CLI. Introduce typed request/result/manifest schemas and a versioned API. Resolve ownership of duplicated `base/` behavior rather than accumulating overrides; keep root-specific fixes reviewable in this repository meanwhile.

## Runtime, performance, and platform delivery

1. **Supported environment (P1).** Move from Python 3.7 and its pinned scientific stack in controlled steps, with a lockfile, `pyproject.toml`, and CPU golden-result comparison after each upgrade. Replace obsolete bootstraps, browser binaries, and platform probes. Do not treat a dependency update as scientifically neutral.
2. **CPU-first cross-platform packages (P1).** Build and smoke-test separately on Windows x64, macOS Intel/Apple Silicon, and Linux x64; PyInstaller does not cross-compile them. Add signing/notarization, checksums, SBOM/provenance, verified offline model installation, and clean install/update/uninstall tests. CUDA, MPS, and other providers require parity checks against CPU baselines.
3. **Resource budgets (P1).** Benchmark large images, long batches, peak CPU/GPU memory, export time, startup, and cancellation latency. Keep validated models warm, use a bounded queue, stream large archives/previews, and tune patch/tracking sample sizes only with equivalence evidence. Do not quantize scientific arrays or use mixed precision without validation.
4. **Required CI (P1).** Run fast unit/API/security checks on every PR and opt-in released-model tests for candidates. Add scientific golden fixtures, browser keyboard/accessibility tests, and clean packaged-artifact smoke tests. Track formatting, linting, types, dependency audits, and coverage against a ratcheted baseline. Test rendered Jinja output rather than treating raw-template editor warnings as application failures.

## Interface and research workflow

- **Visible sequence (P1).** Guide users through Import & Validate → Detect → Review/Correct → Track → Review/Correct → Analyze & Export; show Training as a separate optional workflow. Explain pairing, masks, epochs, and outputs in context. Tooltips should supplement visible instructions and work with keyboard and touch.
- **Import and pairing (P1).** Preview decoded format, dimensions, orientation, dates, site/tube/level, duplicate/conflict status, disk use, and proposed chronological pairs before starting. Make metadata editable; do not require every acquisition system to adopt one filename convention.
- **Review tools (P1).** Offer linked source/segmentation/turnover views, opacity and zoom, a clear match list, visible add/remove/correct tools, undo/redo, and distinction between automatic and manual points. Use a color-blind-safe legend and distinguish excluded/unknown regions from biological change.
- **Training (P1).** Preview image/annotation pairs and label origin, record reviewer/corrections, create disjoint train/validation/holdout splits, show device/epoch/loss/checkpoint state, and compare the candidate with its base model on untouched data. Protect active models from interrupted or unapproved training outputs.
- **Results and accessibility (P2).** Give exports descriptive names, schema/units/warnings, profiles, and previews; provide actionable errors and privacy-reviewed diagnostics. Correct Settings close-button styling, semantic controls, focus/restoration, live progress announcements, responsive layout, and English/German-ready number/date formatting. Audit core workflows against WCAG 2.2 AA.

## Delivery order and non-goals

1. Qualify PR #6 and finish the scientific gates above while retaining the old matcher mode.
2. Establish restart-safe projects, trusted models, and a supported CPU baseline.
3. Ship and qualify portable/signed artifacts per operating system.
4. Improve workflow guidance, review tools, accessibility, and calibrated longitudinal outputs.

Do not begin a wholesale frontend rewrite, public multi-user hosting, cloud collaboration, native mobile app, or automatic updater before data integrity, reproducibility, and portable releases are established. Each would need its own security and scientific validation plan.
