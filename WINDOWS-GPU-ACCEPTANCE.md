# Windows GPU Release-Candidate Acceptance

Use this checklist for the latest portable ZIP built from the Windows batch-reliability branch on `ExPlEco_ML_Desk`. This is a release-candidate test, not approval of scientific model quality.

## Derived Cross-Site and Tracking Fixtures

Do not rename or reorganize the 430-file baseline corpus. Build disposable,
traceable test copies on the Windows workstation instead:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\prepare_windows_acceptance_data.ps1 `
  -SourceRoot 'C:\Users\ExPlEco_ML_Desk\Downloads\RootDetector_Tests\Images\root scans'
```

The script refuses to overwrite an existing `test-derived` directory, hashes
all source TIFFs, verifies every byte-for-byte copy, and records provenance in
`mapping.csv`. All renamed dates and sites are synthetic and explicitly marked
`scientific_valid=false`. The fixtures qualify upload, detection, chronological
pairing, tracking mechanics, malformed-input isolation, and export; they do not
qualify biological tracking accuracy. That still requires genuine repeated
scans of the same roots on different dates.

Before and after a derived-fixture qualification run, verify both the unchanged
baseline and the derived-file hashes:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_windows_acceptance_data.ps1 `
  -SourceRoot 'C:\Users\ExPlEco_ML_Desk\Downloads\RootDetector_Tests\Images\root scans'
```

## Genuine Rhizotron Temporal Dataset

Use a traceable download from the private Eldena CKAN dataset for scientific
tracking qualification. The Rhizotron carriage scans from the top toward the
bottom. Eldena's short tubes normally yield three levels; long tubes can yield
as many as ten because the physical bottom sensor determines the run length.

Future acquisitions use the RootDetector-compatible name
`04_L001_28.08.2026_145304_IMG_0001.JPG`: the tube/site and physical level stay
before the dotted observation date, so RootDetector groups each depth across
time. `L001` is the top scan and subsequent levels continue downward. Existing
CKAN resources such as `04_20260821_110358_IMG_0001.JPG` remain immutable; make
derived test copies, add `L001`-style level labels from capture order, and keep a
mapping with source URL/name and SHA-256. Do not commit or redistribute the
private, license-unspecified images.

Run these gates in order:

1. Pilot 21-22 August 2026: 3 levels x 2 dates = 6 images and exactly 3 pairs.
2. Qualification 21-25 August 2026: 3 levels x 5 dates = 15 images and exactly
   12 consecutive-date pairs.
3. Preview the proposals and confirm every pair has the same tube and level,
   observation 2 is later than observation 1, and no cross-depth pair exists.
4. Run detection, tracking, and both exports; record review-required/failure
   counts, diagnostics, resource high-water marks, and ZIP integrity.
5. Have an ecological reviewer inspect alignment and biological plausibility.
   Mechanical completion alone does not validate scientific accuracy.

### 15 September 2026 Eldena evidence

The six-image pilot passed mechanically: 6/6 detections and all three expected
pairs completed. The 15-image qualification then completed 15/15 detections
and 10/12 tracking pairs on the RTX 3080. It correctly continued after both
failures and a retry targeted only the two failed pairs. The tracking export
contained 52 files, 10 `OK` CSV rows, and a schema-2 manifest.

Both failures involved `L003` on 23-24 and 24-25 August. The 24 August source
is 5152 x 4752 pixels while the other scans are 5152 x 4768. The released
tracker reaches a boolean operation on the two segmentation arrays and cannot
broadcast the unequal shapes. This is a source-grid compatibility failure, not
a GPU, filename-pairing, or pipeline-continuation failure. The source fix now
rejects unequal grids before matching with an actionable message; rebuild and
repeat these two pairs to qualify it in the portable application.

Do not silently crop production data. The December 2024 guide uses random
1000 x 1000 crops only for manual evaluation/ground truth and says training
images should preferably be uncropped; it gives no tracking crop/alignment
rule. Any future alignment/crop option therefore needs an explicit anchor,
preserved originals, a transformation manifest, and ecological validation.

During this run private memory was effectively flat from the earlier baseline
(about 12.47 to 12.49 GB), working set rose from about 4.33 to 5.54 GB, GPU
allocation fell from about 2.30 to 1.04 GB, and free disk fell about 1.98 GB.
This does not demonstrate an unbounded leak, but a second same-process run and
post-cleanup measurement are still required.

Evidence identifies build commit `0bcd70b`, Actions run `34896288600`, and
pipeline `06fe26e372da40f0a1889a9aad76bc60`. The diagnostics ZIP SHA-256 is
`e788ed07f73e818c919ba14c4ab682c232f2ab471e489a237dc02e5d2f9a8b4b`; the
tracking export SHA-256 is
`f5b0e0dd482b36aac72852b05a4324a3658b277a77ac2729160b97e1edc8f19a`.
Both archives passed integrity checks. The qualification detection archive was
not captured and remains a retest item. Browser-controller transfer through an
SSH tunnel took about 23.6 minutes; measure native Windows selection/upload
separately before treating that as application performance.

Images from manual or third-party scanners may also be tested. Detection does
not require a Rhizotron origin, but every input must use a supported, decodable
image format and resemble the imagery on which the selected model was trained.
Scientific tracking additionally requires comparable views of the same physical
location on different dates and a consistent prefix/date naming contract. Treat
cross-device, changed-scale, changed-orientation, or synthetic-date results as
mechanical tests until scientifically reviewed.

## Protect the Existing Installation

1. Keep the previous tested folder unchanged.
2. Extract the new ZIP into a new folder such as `RootDetector-Windows-batch-rc2`.
3. Record the ZIP SHA-256 (`Get-FileHash <zip> -Algorithm SHA256`) and the commit and Actions run in `BUILD-INFO.txt`.
4. Start only with `Start RootDetector.bat`; keep its console open.
5. On an NVIDIA workstation, confirm the first-launch console selects the CUDA
   PyTorch wheel and diagnostics report `effective_inference_device` as `cuda`.
   Current Windows 11 installations may not include deprecated `wmic`; RC2 probes
   `nvidia-smi` first and PowerShell CIM before retaining WMIC as a final fallback.

## Primary 86-Image Run

1. Load the established 86-image TIFF folder.
2. Confirm that the Detection tab lists 86 distinct files and Tracking shows the expected consecutive pairs.
3. Enable the NVIDIA GPU and select the same models/settings used for the failed run.
4. Select **Run Analysis** once. Record whether the modal clearly changes from Upload to Detection and then Tracking.
5. During upload, confirm that each row shows its filename and status. The former ambiguous 81%/`[object Object]` state must not occur.
6. Let the complete analysis finish. Record completed, failed, skipped, and review-required counts and download all detection/tracking results.

If an upload fails, take a screenshot, select **Run Analysis** again without reloading the files, and verify that acknowledged rows say **Already uploaded in this session**. If analysis fails, record the diagnostic ID and use **Download diagnostics** before closing the app.

## Recovery and Resource Checks

- Confirm **Cancel** can stop input preparation and that a new run reuses already prepared files.
- If a CUDA allocation failure occurs, verify that the affected image shows two attempts at most. RootDetector must not silently change from GPU to CPU.
- Record `nvidia-smi` memory before the run, near peak use, and after completion. Also record Task Manager private/working-set memory and free disk space.
- Without restarting RootDetector, run the same 86-image dataset a second time and export results again. Memory must not grow without settling, and both exports must be complete.
- Turn off only the display or lock the screen for a short interval during a run. Do not deliberately sleep/hibernate yet; Windows sleep prevention remains a separate planned feature.

## Mixed-Batch Isolation Check

1. Load `test-derived\cross-site-smoke\mixed` (17 files).
2. Run analysis once. The known malformed HH TIFF must show **Upload / Failed**
   with conversion guidance, while the other 16 images continue through
   detection.
3. The terminal summary must reach 100%, retain the single upload failure, and
   state that completed results are ready.
4. Export detection results and verify that the ZIP opens and contains exactly
   16 top-level image folders plus the aggregate statistics file.
5. Run analysis again without reloading. The 16 accepted files must be reused;
   only the malformed file should be retried.

The 15 September hot-patch exercise passed all five steps against a separately
labelled RC2 test copy. The repeat run issued only one `/file_upload` request—
for the known malformed TIFF—and reused the 16 accepted images before completing
again. A newly built portable ZIP must repeat all five steps; the hot-patched
extraction is implementation evidence, not a release artifact.

## Controlled Training Check

Keep this check separate from batch-reliability and scientific-tracking
acceptance. Do not use an automatically generated detection segmentation as a
training label. Until RootDetector distinguishes reviewed ground truth from its
own predictions, the UI training path is not approved for scientific model
creation; the earlier Stop/Retry test qualifies mechanics only.

After the provenance safeguard is implemented:

1. Prepare a small dedicated set of original images and same-sized,
   independently reviewed segmentation masks. Record their source and hashes.
2. Reserve unseen images by tube/site and date as a holdout set; do not split
   patches from one observation between training and evaluation.
3. Record the starting model, learning rate, epochs, device, and dataset IDs.
4. Complete training, save the model under a unique name, select it in Settings,
   restart RootDetector, and confirm that the selection persists.
5. Reprocess one training image only as an inference smoke test. Clear or reload
   its old result first so the new output is actually generated.
6. Process the untouched holdout set and compare reviewed metrics and visible
   errors with the starting model. Only this step contributes quality evidence.
7. Separately cancel one disposable run and verify that no partial model can be
   saved and the previous model is restored.

Passing on training images alone does not demonstrate generalization. A model
may be released only with a model card, dataset split, held-out results, intended
image conditions, limitations, application version, and model checksum.

## Evidence to Return

Provide the ZIP hash, `BUILD-INFO.txt`, screenshots of each phase and final summary, result counts, timings, CPU/GPU/RAM/disk observations, browser console errors if any, and `RootDetector-diagnostics.zip`. Do not include research images unless separately authorized.

Acceptance is **PASS** only if both full runs terminate truthfully, all expected exports open, failures are actionable and correlated to logs, retry does not repeat confirmed uploads, and no unbounded resource growth is observed. Otherwise report **FAIL** or **BLOCKED** with the exact failed step.

## RC1 Observation

RC1 completed 86/86 automated detections. T034 and T047 had failed only in the preceding manual **Process All** path and then completed on the automated pipeline's first attempt. Because this dataset produced zero tracking pairs, the observation is a detection-only partial PASS. RC2 must confirm that long error notifications wrap, transient result retrieval is retried, and any browser-side failure appears in diagnostics with an ID.

The zero-pair result is expected for this dataset: all 86 files have different prefixes before their dates, so none represents a later observation of the same site. A non-scientific smoke pair (`T093` to `T104`) was submitted directly to exercise the engine. Tracking finished in 12.88 seconds with zero matches and `review_required`; this is a mechanical PASS but must not be interpreted as a growth result. Full tracking acceptance still requires two or more dates for the same tube/site prefix.

Do not load a detection-results ZIP as new input images. Keep the original images loaded and use **Load Annotations** only when intentionally restoring compatible annotations. A valid training acceptance set must contain independently reviewed ground-truth segmentation images; automated predictions alone are not training labels. Until the revised RC2 gate is implemented, limit training to a small disposable set, monitor free disk space, and stop if the system drive approaches 10 GB free.

## 10 September Diagnostics Follow-up

The 43-image `HH` detection run completed 32 items and rejected 11 at processing time with libtiff `LZWDecode` errors. A live four-file reproduction confirmed that one known-good TIFF processes while three affected TIFFs fail at scanline 0. Current Pillow/libtiff on macOS fails on the same files, although Windows' permissive image decoder opens them. Treat these as malformed/non-standard LZW inputs, not GPU or tracking failures. RC2 must reject them during upload/input preparation, before inference, with conversion guidance; acceptance must include one valid image, one truncated/corrupt image, and one affected HH image converted to a standards-compliant TIFF or PNG.

The archived tracking exercise is not scientific tracking evidence. It loaded six detection-result folders as 12 new segmentation/skeleton images and paired each segmentation with its skeleton. The resulting six pairs are generated artifacts from the same observation, not consecutive dates. Repeat tracking with original images from the same tube/site prefix at two or more dates, verify the proposed pair names and order before starting, and inspect the tracking-specific export.

Before RC2 approval, also switch between two extracted builds that use the same loopback port. A restored/stale browser tab must show an explicit version-mismatch or missing-assets recovery message rather than `RootSecurity is not defined`. Verify the Settings close button remains inside the modal and long failure notifications wrap without clipping at 100% and 125% display scaling.

## Available Cross-Site Test Collection

The `root scans` directory contains 430 TIFFs (about 4.42 GiB) across 11 folders. All names contain parseable dates and no exact filenames are duplicated. Native metadata inspection found 428 images at 2550 x 2273 and two portrait images in `NZ` at 2273 x 2550. A strict Python 3.7/Pillow 7 decode passed 16 representative files covering every folder, both orientations, spaces/semicolons, and two dates; only the deliberately included known-bad `HH` TIFF failed.

| Folder | Files | Observation date(s) | Primary acceptance use |
|---|---:|---|---|
| BH | 42 | 2026-04-02 | Detection batch and `BH-R` naming |
| DE | 33 | 2026-04-13 | Same-day duplicate warning; must not auto-track |
| FS | 40 | 2026-04-14 | Detection batch |
| GR | 44 | 2026-04-12 | Largest folder/batch |
| HH | 43 | 2026-03-30 | Malformed-LZW rejection and converted-file retry |
| KA1 / KA2 | 39 / 43 | 2026-04-10 | Spaces and semicolons in filenames |
| KA3 | 40 | 2026-04-10 and 2026-04-11 | Multi-date but zero-valid-pair check |
| KO | 43 | 2026-04-09 | Detection batch |
| NZ | 25 | 2026-03-31 | Portrait-orientation coverage |
| WE | 38 | 2026-04-08 and 2026-04-09 | Multi-date but zero-valid-pair check |

None of these folders contains the same exact observation prefix at two distinct dates, even when all folders are combined. They can qualify detection, input handling, orientation, batching, failure isolation, disk use, and zero-pair guidance, but not scientific tracking. `DE` contains duplicate same-day scans for `Ref_T019_L001_` and `Ref_T021_L001_`. RC2 now rejects both ambiguous groups, creates zero pairs, and identifies the affected date and filenames. Dependency-free Node regression tests and a real-browser test with the four DE filenames confirm this behavior. Run folders separately first, then a controlled combined stress test after disk preflight and cleanup behavior pass.
