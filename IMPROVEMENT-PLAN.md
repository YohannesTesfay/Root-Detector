# RootDetector Improvement Plan

This is the active roadmap, not a log of completed branches. The automated detection-to-tracking workflow, core security and cache fixes, reviewed-label guard, and Windows portable mechanics are implemented and mechanically tested. Historical detail remains in Git history at `51e338a`; software completion does not establish scientific validity or cross-platform support.

Priorities: **P0** blocks trustworthy results or a safe release; **P1** is required for a dependable product; **P2** improves usability or maintainability. Qualify changes in the fork before proposing them upstream.

## Immediate fork release gates

1. **Scientific output review (P0).** Compare the current package with the original RootDetector on the same reviewed image pairs. Assess alignment, false growth/decay, and segmentation. The reliability release retains the released first-observation exclusion-mask calculation; compare alternative dual-mask policies only on the separate experimental branch. Confirm whether reported width is radius or diameter; record physical calibration and units. Do not silently change scientific definitions.
2. **Training quality (P0).** Use independently reviewed image/mask pairs and tube- or site-disjoint holdouts. Compare any candidate model with its base model on untouched images before scientific use. Automatically generated detection masks are predictions, not training ground truth.
3. **Exact release head (P0).** Build the merged fork `main` as a fresh Windows portable package. Check the ZIP hash and `BUILD-INFO.txt`; test launch, detection, tracking, export, restart, and first-run downloads from that exact build before publishing it. Keep known scientific limitations in the release notes.
4. **Deterministic tracking (deferred).** Draft fork PR #6 explores seeded point selection but is not part of the current release. The released sampler remains variable. Review representative matches and turnover against independent annotations, then decide separately whether a reproducible mode belongs in a future release.

## Correctness and data integrity

| ID | Priority | Next change and acceptance criterion |
| --- | --- | --- |
| T-007 | P1 | Preserve floating-point Kimura lengths, validate imported archives, assign collision-free artifact IDs, and version exports. CSV column mapping and quoting are already corrected. |
| T-008 | P1 | Define empty-target/prediction and exclusion-mask evaluation policies; return not-applicable instead of dividing by zero. |
| T-010 | P1 | Let users review and edit site, tube, depth, and date assignments before pairing; test ambiguous names and mixed-site batches. |
| Provenance | P1 | Record input/model hashes, preprocessing, thresholds, device, calibration, units, warnings, and schema/app versions in each result. |
| Image preparation | P1 | Offer optional previewed alignment/cropping of repeated views with preserved originals and a transform record. Never silently crop mismatched images. |

PNG, JPEG, and TIFF images from other scanners can enter detection if decodable. Model suitability still depends on scale, illumination, orientation, and background; tracking requires comparable views of the same physical location at different dates.

## Security, storage, and service architecture

- **Model trust (P0).** Eliminate untrusted pickle discovery; allowlist trusted model identities. Add checksums, limits, timeouts, and atomic installation to the first-launch PyTorch runtime download. Model downloads already use SHA-256 verification.
- **Local-service hardening (P1).** Replace request-visible filenames with opaque IDs and per-project directories; bound archive extraction and event queues; redact sensitive diagnostic paths and remove inline/evaluated browser code for a stricter CSP.
- **Restart-safe work (P1).** Persist project metadata, corrections, settings snapshots, and job state atomically. Offer Resume, Retry incomplete, or Discard after restart.
- **Cancellation (P1).** Measure latency of native PyTorch/CUDA calls, then isolate inference in recoverable workers. Current cancellation is cooperative and cannot interrupt one active native call.
- **Maintainability (P2).** Put inference and domain services behind a headless package shared by Flask and CLI, with typed request/result schemas and a versioned API.

## Runtime, performance, and platform delivery

1. Upgrade the Python 3.7 scientific stack in controlled steps; compare CPU golden results after every dependency change.
2. Build and smoke-test Windows x64, macOS Intel/Apple Silicon, and Linux x64 packages separately. Add signing, checksums, provenance, and clean install/update tests; compare accelerator results with CPU baselines.
3. Benchmark long batches, memory, export size/time, and cancellation. Tune inference sizes or precision only after scientific equivalence checks.
4. Require fast tests on each PR and released-model, browser, and packaged-artifact smoke tests for release candidates. Add scientific golden fixtures and accessibility checks.

## Interface and research workflow

- Guide users through Import & Validate → Detect → Review → Track → Review → Export; present Training as a separate optional workflow.
- Preview dimensions, dates, sites, tubes, depths, and proposed pairs; make corrections possible before a run.
- Provide linked original/segmentation/turnover views, zoom, manual match corrections with undo, and a color-blind-safe legend.
- Show training-label origin, reviewer, split, model comparison, device, epoch, loss, and checkpoint state.
- Use descriptive export names and units, accessible controls, responsive dialogs, and actionable errors; correct the Settings close-button styling.

Do not begin a wholesale frontend rewrite, public multi-user hosting, or an automatic updater before scientific data integrity and portable releases are established.
