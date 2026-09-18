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

Candidate commit `96e9956` and Actions run `34972004393` passed that packaged
retest on 15 September. All three affected observations completed CUDA
detection, then both unequal pairs failed in about 0.09 seconds with the exact
4768 x 5152 / 4752 x 5152 dimensions and a diagnostic ID. Retry incremented
only the two pair attempts; detections remained at one attempt. A separate
same-grid 23-25 August pair cancelled truthfully and then completed on retry in
24.8 seconds with 2,883 matches. Its tracking export passed ZIP integrity and
contained an `OK` schema-2 statistics row and manifest.

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

The GitHub artifact digest is
`9b9e7d38063dd8842b04a6f27c45cb962d0eda25aaaa0299144307ce43bd6536`;
its single nested portable ZIP is
`5d4f7bfb80ff7cce86f790778f9e0a8b2aaf3430b6949e461b61cb4d9f2a468c`.
Both ZIP layers passed integrity checks and `BUILD-INFO.txt` identifies the
expected commit and run. The focused candidate diagnostics digest is
`e8ee8501b235caf5f56e63fc34de59f31f178ffc3ac038e1eef979db03c62418`;
it reports CUDA on the RTX 3080. The recovered tracking export digest is
`cbafa7f07e4fd0cd52b78c198a1649de39c1a8660c69fdd4b5515a4efa914ffe`.
Post-run private memory was about 11.65 GiB and working set about 5.04 GiB,
consistent with the earlier run but not a substitute for the planned repeated
full-batch settling check.

The rebuilt mixed-batch replay on the same candidate also passed. Pipeline
`284f02a18e8d428399faa637ffed245f` attempted all 17 cross-site fixtures,
reported the known malformed TIFF as one actionable HTTP 415 upload failure,
and completed all 16 accepted detections. The detection archive contains 16
top-level image folders, their segmentation/skeleton/statistics files, and the
aggregate statistics file (65 ZIP entries); its SHA-256 is
`044c269af70a41f59b7794e0ddf7b91749e937f51795f8a30c417618e3f0d667`.
Two additional same-process runs (`c453dbd2ca8449ab9f1192c85149afef`
and `98bd7f6c7d4d4c0ea3a581afa858d248`) each retried only the malformed upload,
reused all 16 accepted inputs, reached 100%, and finished in 19.9 and 19.8
seconds. Between those repeats private memory remained exactly 11,056,029,696
bytes, working set changed by only 12,288 bytes, and thread count remained 69.
This representative repeat found no per-run memory growth. The system-wide
free-disk delta was about 16.3 MB and is not precise enough to attribute solely
to RootDetector. This left the repeated 86-image run as the final large-batch
resource gate; the later evidence below closes it.

Commit `e0617c9` then corrected the Settings layout found during scaled-browser
inspection by keeping Save/Cancel outside the scrollable form. Actions run
`34977475649` completed in 4m16s and produced the portable ZIP with SHA-256
`c0962fe88bd6aaa31572d790f88d6f200d93aa087544c191ca77f2007be921d1`.
The unmodified package kept the Settings dialog, close button, long failure
toast, and toast close control inside the viewport with no measured text
overflow at 1920x1080, 1536x864, and 1280x720 CSS viewport equivalents. These
represent 100%, 125%, and 150% layout geometry; they do not replace manual
native Windows DPI switching. A clean packaged CUDA smoke run
`40a4ddc944b242319c071ea10e682d6f` completed one detection in 5.1 seconds and
reached 100%. Diagnostics report the RTX 3080 as the effective CUDA device and
have SHA-256
`a38f05ef2c6ba9d6b6cf5fe2b2738e75121c9e7fe17cad9f526cb25755671530`.

### 15 September 2026 final large-batch evidence

The final gate used a separate byte-identical, hash-mapped fixture containing
all 42 `BH` and 44 `GR` TIFFs (86 files, 941,159,876 bytes). The baseline corpus
was not renamed or changed and the fixture is explicitly
`scientific_valid=false`; it has no temporal pairs.
The mapping, both exports, and diagnostics remain under
`C:\Users\ExPlEco_ML_Desk\Downloads\RootDetector_Tests\acceptance-evidence`
and `test-derived\large-batch-86` on the qualification workstation.

The unmodified `e0617c9` package completed 86/86 CUDA detections twice in the
same process, with no failed, skipped, or review-required items. Run
`187789e736ec43279e1b595407e3494b` uploaded 86/86 files and finished in 208.7
seconds. Run `3a6f1eeb2ba64d7893e2aa859a48a517` reused every upload (zero
`/file_upload` requests) and finished in 106.8 seconds. Brief browser connection
timeouts were recovered automatically and did not alter the terminal result.

Each export is 5,783,710 bytes and contains 86 result folders, 259 files, 345
ZIP entries, and an aggregate CSV with one header plus 86 rows. Both archives
pass integrity checks and all extracted files compare byte-for-byte equal. The
archive SHA-256 values are
`0b477199532e61ad7f8fe327cd1912f19e3e822508245d4806839bf67cc5a7c7`
and `c1df0a85446ffe7868b2802270515992369b02dd87bc45e5a8dc43229795075d`;
ZIP container metadata accounts for the different archive hashes.

After run 1 settled, working/private memory was 3,846,807,552 / 11,058,442,240
bytes with 929 handles and 68 threads. After run 2 it was 3,847,127,040 /
11,058,671,616 bytes with 933 handles and 67 threads. The negligible settled
deltas do not indicate per-run growth. The diagnostics archive passes integrity,
identifies commit `e0617c9`, CUDA, and the RTX 3080, and has SHA-256
`86bed8d50bd244b2f6d00b6192fe5f2249039269ff7408060ba1a91ab5f47126`.

The same browser then switched from `e0617c9` to `96e9956` and back on port
5000. In both directions the stale token received HTTP 403 with explicit reload
guidance; after reload all critical assets revalidated, client/server schemas
and tokens matched, and no console or `RootSecurity` startup error remained.

Windows was configured at a native 150% scale (`AppliedDPI=144`) on its
3840 x 2160 display. An isolated Chrome launched in the logged-in desktop
reported DPR 1.5 and a 2560 x 1305 viewport. The Settings dialog, close button,
Save/Cancel controls, and long error toast all remained within the viewport,
with no horizontal text or document overflow. Native 100% and 125% switches
remain manual confirmations; their equivalent browser viewport checks already
pass. The 86-image resource gate and highest-risk native scaling check are now
closed for RC2 mechanics. Ecological review of Eldena results remains required
before scientific acceptance.

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

The rebuilt candidate at `96e9956` passed all five steps on 15 September. The
repeat run issued only one `/file_upload` request—for the known malformed TIFF—
and reused the 16 accepted images before completing again. The archive hash,
contents, pipeline IDs, timings, and settled resource measurements are recorded
above. The later `e0617c9` package changes only the Settings template/style and
passed the workflow's upload-isolation regressions plus a packaged CUDA smoke.

## Controlled Training Check

Keep this check separate from batch-reliability and scientific-tracking
acceptance. Do not use an automatically generated detection segmentation as a
training label. The reviewed-label gate separates imported annotations from
RootDetector predictions, but user confirmation alone does not establish
scientific ground truth; the earlier Stop/Retry test qualified mechanics only.

The browser now excludes automatically generated detections from training candidates, requires a separately imported label set and explicit review confirmation, and uploads labels sequentially. The server rejects requests without that confirmation. Both the packaged-Windows API path and one positive browser annotation-import path passed mechanics checks below; scientific label quality remains unverified.

The workstation's `RootDetector_Tests\RootImagesForTraining` folder was inspected on
2026-09-18. It contains 29 PNG masks (2550 × 2273, opaque, predominantly black
with white root traces) spanning different site/tube/level observations. Their
pixel encoding is suitable for a **detection-label candidate**. All 29 contain
GIMP 2.10 save-history metadata from October 2023, consistent with manual
preparation but not proof of annotation correctness. Matching originals were
subsequently located in `J:\ExPlEco\Beech_Training\New_Files\images`: 29 TIFFs
with the same stems and 2550 × 2273 dimensions. The J: masks in `Roots` are
SHA-256 identical to the 29 Downloads masks. Copies of all 29 source TIFFs are
in `RootDetector_Tests\TrainingSourceImages`, and their SHA-256 hashes match the
J: originals; the J: files were not changed. Before training, visually confirm
image/mask alignment and review provenance, then select a small pilot and a
site/tube-level holdout. Do not train by using a mask as both input and target,
or pair it with unrelated 2026 scans. These 29 distinct observations cannot
establish longitudinal tracking accuracy on their own.

### 2026-09-18 packaged training pilot

On `ExPlEco_ML_Desk` (RTX 3080), the isolated `f8cebee` RC2 package rejected an
unconfirmed training request (HTTP 400). With the beech detection model selected
and GPU enabled, it accepted two matched source/mask pairs (`BH-C_T011_L002` and
`DE-SR_T022_L003`) and completed one detection-training epoch at learning rate
`0.0001` in about 9 seconds. The test-only model
`RC2_training_pilot_20260918_2pairs.pt.zip` was saved (SHA-256
`ed986a4b16e8978fc6ac567f8616e2308aec3ec0f4d11891255895a03e2e7ef7`),
selected, reloaded after restart, and used to detect one untouched-by-this-pilot
`HH-R_T144_L002` image. The holdout detection completed. Against its PNG mask,
using a pixel threshold of 128, the original beech model had precision 0.471,
recall 0.244, and IoU 0.191; the pilot had 0.452, 0.306, and 0.223. This one
image is not a scientific quality result; overlap with the original pretrained
model's training data is unknown.

A separate ten-epoch disposable run was cancelled after two seconds, before
first-epoch progress. It ended `cancelled`, restored the selected beech model,
and rejected saving partial weights (HTTP 409; no file created). This does not
measure mid-epoch cancellation latency. The diagnostics archive is
`RC2-f8cebee-training-gate\RC2-training-pilot-diagnostics.zip` (SHA-256
`cd92487ecd0e669f226967b00ecf61ede9ccfaff80faf4abd0513110f2b8d4f3`).
The test app's original defaults (WM detection, WM exclusion mask, tracking,
GPU off) were verified after restart; its server was stopped. During cleanup,
a partial `POST /settings` persisted only the submitted detection entry and
silently dropped the exclusion-mask and tracking entries. A subsequent full
settings request returned HTTP 400 because validation recognized only loaded
model types. The test-created `settings.json` was moved recoverably to
`RC2-f8cebee-training-gate\training-test-settings.json`, restoring the original
no-settings-file state. The source fix and its restart regression are described
below; the frozen `f8cebee` package still contains this defect and must be
rebuilt before broad release.

### 2026-09-18 follow-up: browser, cancellation, and multiple holdouts

Through a localhost-only SSH tunnel to the isolated `f8cebee` Windows package,
the browser loaded a matching original TIFF and prepared PNG mask. The Training
tab showed one imported label; Start Training stayed disabled until the review
confirmation was checked. With the beech model, RTX 3080, learning rate
`0.0001`, and one epoch, browser-initiated training reached **Training finished**
at 100%. This proves the positive import/UI path, not the mask's scientific
correctness. A separate 100-epoch disposable run was cancelled while progress
was between 11% and 18.25%; it ended `cancelled` at 18.25%, showed the
interrupted/retry UI, and restored the beech model. The earlier save-gate test
already rejected partial weights. No model from these browser tests was saved.

A wider disposable pilot trained on five source/mask pairs from `BH`, `DE`,
`FS`, `KA1`, and `GR` (three epochs, GPU). Three images from sites not included
in that pilot (`HH`, `NS`, `WE`) were detected before and after training. Binary
pixel metrics against the supplied masks (threshold 128) were:

| Held-out site | Baseline precision / recall / IoU | Pilot precision / recall / IoU |
| --- | --- | --- |
| HH | 0.471 / 0.244 / 0.191 | 0.485 / 0.499 / 0.326 |
| NS | 0.373 / 0.758 / 0.333 | 0.276 / 0.740 / 0.252 |
| WE | 0.133 / 0.532 / 0.119 | 0.135 / 0.495 / 0.119 |

The mixed result is **not** evidence that this new model generalizes or should
be released. Labels and original pretrained-model overlap need ecological
review; the 29 images are not a longitudinal tracking validation set. The
unsaved pilot weights were discarded when the server stopped. Diagnostics are
at `RC2-f8cebee-training-gate\RC2-browser-multisite-diagnostics.zip` (SHA-256
`1d379a6d3fcf0c6f2d5f1e998b8a16f0b47b9ab732974fc534b47fcbb66b9a0e`).
The generated settings file was moved, without overwriting earlier evidence,
to `RC2-browser-multisite-settings.json`; port 5000 is free and the app folder
again has no `settings.json`.

In the source branch, partial settings updates now merge model selections
against defaults/current state, and startup restores omitted model types from
older partial files. A restart/recovery regression is in the fast Docker suite:
**110 passed**; released-model smoke: **2 passed**; all four workflow Node
checks passed.

### 2026-09-18 exact-build Windows acceptance

Actions run `35352391140` passed at commit `fffb3f7` and published one full
portable ZIP. The GitHub artifact SHA-256 is
`5050341fd3c6851197333e9193fb9ef2f74a34372ad61c4e603dd527b2c6a3f3`;
its nested portable ZIP SHA-256 is
`e5fa375771d872593ac7881298c80a3fb158a2b6590a653aa12b930f69c67b1d`.
Both archives passed integrity checks and `BUILD-INFO.txt` identifies the exact
commit and run. On `ExPlEco_ML_Desk`, a fresh extraction started, saved a
partial Settings update that changed only the detection model and GPU flag,
preserved exclusion-mask and tracking selections in `settings.json`, and
restored all selections after process restart. This closes the packaged
settings-persistence gate.

The same package then processed nine hash-verified August 21–23 Eldena scans
and all six same-level consecutive-date pairs: pipeline
`3ec0abbb18784e32abd6a047f1173465` completed 15/15 work items with no
failures. Diagnostics report CUDA on the RTX 3080. The tracking ZIP passed
integrity, contains 32 entries and six `OK` schema-2 CSV rows, and has SHA-256
`c647ed94eb9aec057cf0a214d555c925454d2f0c59661f8c298a92813064a28c`.
The diagnostics ZIP passed integrity and has SHA-256
`b2c233693ecca8a6dfb3a91a4ebba5b3f00b68aac942ca516d06031752b789ae`.
Evidence remains in the isolated `RC2-fffb3f7-settings-gate` and
`Eldena-Pilot-2026-08-21-23` workstation folders. This was a packaged API
mechanics test, not a new browser-import test or scientific validation of
root turnover. Ecological interpretation can follow during supervised use;
no custom-model quality claim is established by these software tests.

### 2026-09-18 merged-fork-main replay and tracking repeatability

Fork PRs #4 and #5 were merged in order. The resulting `main` tree at
`9b8de6c` is identical to the qualified RC2 branch tree. Actions run
`35354845509` passed at that exact merge commit. The outer artifact SHA-256 is
`66951c3ac08335b2c74c1609133ef1cc38397263f06d72457e664d15d135968d`;
the full portable ZIP SHA-256 is
`7e08e79e78d94bef2ffa026d09e12f527c705ad3048854097b731e1f6d26d273`.
Both ZIP layers passed integrity checks and `BUILD-INFO.txt` names `9b8de6c`.
On a fresh Windows extraction, pipeline `0a72750b01f442d7a06ac86e89f1b321`
completed the same nine CUDA detections and six chronological pairs (15/15
items). Its tracking ZIP passed integrity, contains 32 entries and six `OK`
schema-2 rows (SHA-256
`59fde32473f171e7727f5728e1585f68cc982876e3ce813ef83d145c2d6c861d`).
Diagnostics report the RTX 3080 as the effective CUDA device; their ZIP
SHA-256 is
`0d22041a3f92bb3da716909708a1e8949d910d7d9d8de59d03907ef12275bbcb`.
The isolated Windows folder is `ForkMain-9b8de6c-gate`.

**Scientific reproducibility caveat:** all nine detection statistics matched
between the RC2 and merged-main runs, but tracking CSV counts did not. A repeat
of the identical L001 21–22 August pair in the *same running package* changed
matched points from 3,863 to 3,890 and same/decay/growth pixels from
39,802/17,059/13,458 to 39,858/17,161/13,402. The matcher deliberately uses
an unseeded `numpy.random.permutation` to sample root points, inherited from
the released algorithm. This confirms stochastic tracking rather than a
packaging, input, or model-hash difference. The workflow mechanics pass, but
tracking measurements are not repeatable enough to claim deterministic
scientific output. Preserve every run's export and settings; do not compare
single-run turnover counts as exact until a deterministic sampling rule is
implemented, versioned, and validated on representative data.

For a subsequent scientific qualification run:

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

Before stable approval, also switch between two extracted builds that use the same loopback port. A restored/stale browser tab must show an explicit version-mismatch or missing-assets recovery message rather than `RootSecurity is not defined`. Browser layout checks now pass for Settings and long failure notifications at the 100%, 125%, and 150% viewport equivalents; repeat the three checks with native Windows display scaling for final DPI acceptance.

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
