# Validation Summary

This page records the scope of fork testing without publishing research images or workstation logs. A passed software check is not approval of ecological interpretation. Keep release candidates as prereleases until the exact packaged build passes its stated gates.

## Accepted software mechanics

| Scope | Evidence | Result |
| --- | --- | --- |
| Core automation and Windows recovery | Packaged tests through fork PR #3, including interruption/retry, export, and Settings keyboard access | Passed; model quality was not assessed. |
| Large GPU detection batch | Portable build `e0617c9` on an RTX 3080; the 86-image batch ran twice in one process | 86/86 on each run, with content-identical extracted exports and no repeat uploads. |
| Tracking grid validation | Portable build `96e9956`; unequal Eldena image dimensions | Failed pairs reported their exact dimensions promptly; retry did not redo successful detections. No automatic crop was applied. |
| Fork-main workflow | Build of `9b8de6c`, Actions run `35354845509`; nine Eldena images from 21–23 August 2026 | Nine CUDA detections and six same-level chronological tracking pairs completed; export and diagnostics ZIPs passed integrity checks. |

The released matcher is stochastic. Repeating one identical pair on the fork-main package changed matched points from 3,863 to 3,890 and changed turnover counts. Detection statistics matched. Treat historical single-run tracking counts as exploratory rather than exact repeatable measurements.

## Open qualification gates

1. For draft fork PR #6, build the exact `fix/deterministic-tracking` head. Verify `BUILD-INFO.txt`, the full ZIP hash, and the sole `StartRootDetector.bat` launcher.
2. On a fresh Windows extraction, enable seeded sampling and rerun the same valid pair in one process and after restart. Compare pair JSON, matched points, statistics, growth-map content, seed, model identities, and diagnostics. Compare contained results rather than ZIP bytes, which can include changing metadata. Test at least one CPU pair separately and investigate any device difference.
3. Review same-tube, same-level image alignment, matched correspondences, exclusions, and apparent growth/decay with an ecological reviewer. Record representative overlays and the review decision. The seeded mode remains opt-in until this passes.
4. Qualify any newly trained model on independently reviewed labels and site/tube-disjoint holdouts before making an accuracy claim. Training completion alone is not model validation.
5. Before a public release, repeat a short smoke test on the exact fork `main` package and record its commit, Action run, archive checksum, device, and remaining limitations.

The former detailed `WINDOWS-GPU-ACCEPTANCE.md` and completed `CORE-AUTOMATION-PLAN.md` are retained in Git history at commit `51e338a`. The detailed working copies are local-only and are not required to build or run RootDetector.
