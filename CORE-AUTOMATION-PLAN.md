# Core Automation Recovery Plan

## Purpose

This is the short implementation plan to make RootDetector's primary workflow reliable before beginning the broader work in `IMPROVEMENT-PLAN.md`. The larger plan remains the long-term roadmap and must not be replaced or reduced.

The immediate product goal is:

```text
Select images -> validate and pair -> upload once -> detect every image
              -> track every valid adjacent pair -> review failures -> export
```

After the user starts the run, the application must advance through these stages without requiring another button click for each image or pair. Inference may remain sequential to protect CPU/GPU memory, but workflow control must be automatic, observable, and resilient.

## Confirmed Starting Point

- Image selection currently builds two UI tables but does not start an end-to-end job.
- Detection and tracking have separate manual `Process All` actions.
- Detection stops the entire batch at the first rejected image.
- Cache clearing, result loading, mask uploading, and some tracking setup operations are not awaited.
- Detection and tracking do not share a single segmentation artifact contract, so work can be repeated.
- Tracking treats “too many roots” as HTTP 500 and has no structured retry/skip result.
- Tests process one image or pair at a time; none covers upload through final export.
- The host currently has Python 3.14 but no project dependencies. The project pins a Python 3.7/PyTorch 1.10-era stack and no model files are installed.
- Docker Desktop 4.83 is running with an amd64 Linux engine on this Intel Mac. No RootDetector test image exists yet.
- The existing Docker wrapper uses `sudo`, an interactive terminal, moving `ubuntu:latest`, obsolete browsers, and fragile relative paths. It is not the baseline to preserve unchanged.

## Scope and Non-Goals

### Included now

- A reproducible local development/test environment.
- A single automated detection-and-tracking run controller.
- Explicit item states, failure isolation, retry, cancellation between items, and a final summary.
- Correct promise/await behavior and reliable cache/upload ordering.
- Reuse of compatible detection artifacts by tracking.
- Fast model-free tests plus one real-model smoke workflow.
- PNG, JPEG, TIFF, duplicate-name, malformed-file, and filename/pair-validation behavior.

### Deferred to the larger plan

- Full dependency modernization, signed installers, public/multi-user deployment, a frontend rewrite, cloud processing, new ML models, and complete UI/accessibility redesign.
- Training workflow repair, except where shared job-state code requires a compatible interface.
- Scientific metric changes. Existing output values must remain stable unless a separately reviewed correctness fix requires a versioned change.

## Implementation Decisions

1. **Use Docker for the initial reference environment.** Do not install Python 3.7 or legacy scientific packages into the host Python. Pin the image and dependencies once a clean build succeeds.
2. **Separate fast and real-model testing.** Most orchestration tests will use deterministic fake detection/tracking models. Real weights are used only for a small integration smoke test.
3. **Keep inference sequential initially.** Sequential computation is acceptable; manual orchestration and stop-on-first-error are not. A bounded queue can be introduced later without changing the result contract.
4. **Represent a run as data.** Every image and pair receives a stable ID and state: `queued`, `uploading`, `detecting`, `tracking`, `completed`, `skipped`, `failed`, or `cancelled`.
5. **One failure must not terminate unrelated work.** The final run status is `completed`, `completed_with_errors`, `cancelled`, or `failed` only when no useful work could run.
6. **Manual correction is optional review.** Low-confidence/no-match pairs appear in the summary and remain correctable, but they do not block other pairs.

## Phase 0 — Reproducible Baseline

### Work

- Create a topic branch such as `fix/core-automation`.
- Add a small CPU-only Docker development image for the exact legacy runtime. Pin the Linux base instead of using `ubuntu:latest`; avoid `sudo`, X11, AppImages, and browser drivers in the application image.
- Add a Compose configuration with:
  - an `app` service exposing the Flask port;
  - persistent model and test-cache volumes;
  - a `test-fast` service for Python/JavaScript tests;
  - a separate modern browser-test service or host Playwright runner.
- Repair the test entrypoint so paths are based on the script/repository location, commands are non-interactive, exit codes propagate, and test artifacts remain writable.
- Download pretrained models explicitly rather than during app construction. Record size and SHA-256 after comparing the files with the published release assets; fail clearly when offline or incomplete.
- Run the current unit tests and one detection/tracking smoke case before changing workflow code. Record failures as the baseline rather than masking them.

### Intended commands after the harness is added

```bash
docker compose -f compose.core.yml build
docker compose -f compose.core.yml run --rm test-fast
docker compose -f compose.core.yml run --rm model-fetch
docker compose -f compose.core.yml run --rm test-smoke
```

### Exit gate

A new checkout can build the container, obtain verified models, start the app, and run the recorded baseline without modifying the host Python installation.

## Phase 1 — Correct the Existing Batch Mechanics

### Work

- Make file selection asynchronous and await cache reset before changing/uploading files.
- Upload each source image and exclusion mask exactly once. Await every upload and return a stable server-side file ID rather than treating a basename as identity.
- Accept and decode supported PNG, JPEG, TIFF/TIF inputs consistently for file, folder, and drag-and-drop selection. Reject unsupported or corrupt files with an item-level message.
- Replace detection's `catch { break; }` behavior with failure recording followed by the next item. Preserve a user-requested cancellation check between items.
- Await `set_results()` and all segmentation/skeleton fetches before declaring an image complete.
- Remove deferred/untracked tracking-table construction. Pair construction must complete before the run begins.
- Await imported segmentation and mask uploads before post-processing or tracking.
- Disable settings/import mutations while a run is active, or snapshot settings into the run so later UI changes cannot alter work already queued.

### Exit gate

A deterministic fake-model batch containing successful, corrupt, and rejected inputs processes every eligible item exactly once and produces the correct per-item states without unhandled promise rejections.

## Phase 2 — Add One Pipeline Controller

### Minimal design

Introduce a `PipelineController` at the application/service boundary. It owns one `PipelineRun` and exposes start, status, cancel, retry-failed, and result-summary operations. Flask and browser code must call the same orchestration behavior rather than implement independent loops.

For each run:

1. Validate inputs, settings, model availability, unique IDs, dates, and proposed pairs.
2. Upload/persist accepted inputs.
3. Detect each unique image once.
4. Track every valid adjacent pair whose two detections succeeded.
5. Mark dependent pairs `skipped` when an input failed; do not send them to the model.
6. Produce an export-ready summary containing successes, failures, skips, warnings, and retryable items.

The browser should provide one primary **Run analysis** action. An optional “start automatically after validation” preference may be added, but silently starting expensive computation immediately on file selection should not be the only behavior.

### API/result behavior

- Replace generic strings and HTTP 500 quality outcomes with structured JSON containing `code`, `message`, `item_id`, `stage`, `retryable`, and optional details.
- Treat too-many-roots and insufficient-matches as `skipped` or `review_required`, not server crashes.
- Report real progress by completed work units. The current model loop accepts a callback but does not invoke it per patch; add safe progress calls.
- Cancellation prevents new items from starting and leaves completed artifacts valid. It need not interrupt a model operation mid-patch in the first version.

### Exit gate

One action completes detection, tracking, and summary generation for a valid multi-date dataset. A failed image does not prevent independent images or pairs from completing, and retrying failures does not recompute successful items.

## Phase 3 — Connect Detection and Tracking Artifacts

### Work

- Define one versioned segmentation artifact manifest containing input hash, model hash/name, threshold/preprocessing settings, shape, and artifact kind.
- During detection, retain the compatible probability/soft-mask artifact needed by tracking while also producing the normal binary segmentation and skeleton outputs.
- Make tracking request that artifact through the manifest instead of inventing `<filename>.segmentation.cache.png` independently.
- Invalidate artifacts when the input, detection model, preprocessing, exclusion mask, or relevant settings change.
- Validate dimensions before tracking; report mismatched source/mask/segmentation shapes before model execution.

### Exit gate

Each unique image is segmented once per compatible settings/model combination. Logs and tests demonstrate cache reuse, correct invalidation, and no stale-result reuse.

## Phase 4 — Test the Complete Workflow

### Required automated coverage

- Unit tests for state transitions, continue-on-error, retry, cancellation, dependency skips, pairing, duplicate names, format validation, and cache keys.
- Flask/service tests with fake models for all success and error responses.
- Browser test: select multiple images, run once, wait for final summary, inspect one result, and export.
- Mixed-result browser test: one corrupt image plus valid images; valid independent work must finish.
- Real-model smoke test using the smallest licensed fixture set: two dated images, detection outputs, one tracking pair, and export contents.
- Regression checks for output filenames, statistics, manifests, and the already identified aggregate tracking CSV column defect.
- Repeat the fast suite several times to expose races; no sleeps should be used as synchronization in new tests.

### Exit gate

The complete workflow passes from a clean Docker build, twice consecutively, with no browser console errors, unhandled promise rejections, unexpected HTTP 500s, or changed approved scientific outputs.

## Phase 5 — Local Acceptance and Handoff

Run a representative project through the UI and verify:

- All accepted images are listed before execution.
- The proposed chronological pairs are visible and correctable.
- One action advances the run to completion.
- Progress and current item/stage remain visible.
- Failures identify the image/pair and cause without stopping unrelated work.
- Cancel and retry-failed behave predictably.
- Results remain downloadable after partial failure.
- Restart/reload behavior and cleanup are documented.

Document the final setup, commands, known model/runtime constraints, and baseline timing in `README.md`. Then return to `IMPROVEMENT-PLAN.md` for supported-Python upgrades, packaging, accessibility, and broader architecture work.

## Recommended Commit Sequence

1. `test: add reproducible core Docker harness`
2. `test: add pipeline state and mixed-result fixtures`
3. `fix: await uploads cache reset and result loading`
4. `fix: continue batch processing after item failures`
5. `feat: add automated analysis pipeline controller`
6. `fix: share versioned segmentation artifacts with tracking`
7. `test: cover complete upload to export workflow`
8. `docs: document core workflow and local validation`

Each commit should keep fast tests passing. Scientific-output changes must be isolated from orchestration changes so reviewers can distinguish workflow fixes from numerical changes.

## Definition of Done

- A clean local checkout can be built and tested through documented Docker commands.
- A user starts a multi-image analysis once; no per-image or per-pair processing click is required.
- Every item reaches a terminal state and every failure is visible and retryable where appropriate.
- One bad input cannot abort unrelated work.
- Detection is not redundantly recomputed for tracking when a compatible artifact exists.
- The end-to-end workflow is covered with fake-model tests and a real-model smoke test.
- Existing approved outputs remain equivalent, and known output defects are corrected with explicit regression tests.
- `IMPROVEMENT-PLAN.md` remains intact as the next-stage roadmap.
