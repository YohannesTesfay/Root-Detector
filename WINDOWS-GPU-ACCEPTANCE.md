# Windows GPU Release-Candidate Acceptance

Use this checklist for the portable ZIP built from `fix/windows-batch-reliability` on `ExPlEco_ML_Desk`. This is a release-candidate test, not approval of scientific model quality.

## Protect the Existing Installation

1. Keep the previous tested folder unchanged.
2. Extract the new ZIP into a new folder such as `RootDetector-Windows-batch-rc1`.
3. Record the ZIP SHA-256 (`Get-FileHash <zip> -Algorithm SHA256`) and the commit and Actions run in `BUILD-INFO.txt`.
4. Start only with `Start RootDetector.bat`; keep its console open.

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

## Evidence to Return

Provide the ZIP hash, `BUILD-INFO.txt`, screenshots of each phase and final summary, result counts, timings, CPU/GPU/RAM/disk observations, browser console errors if any, and `RootDetector-diagnostics.zip`. Do not include research images unless separately authorized.

Acceptance is **PASS** only if both full runs terminate truthfully, all expected exports open, failures are actionable and correlated to logs, retry does not repeat confirmed uploads, and no unbounded resource growth is observed. Otherwise report **FAIL** or **BLOCKED** with the exact failed step.
