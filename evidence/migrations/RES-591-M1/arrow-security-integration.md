# RES-591 M1 — RES-566 integration supplement

This file records a necessary post-transfer security change, not a reconstruction or rewrite of the selected VM Workbench.

The source-map.csv and 135-file source verification capture the original M1 migration as of `0a703594ce65d478380d11eb460f73945d3e4c94`: 113 byte-exact transfers, 20 compatibility adaptations and 2 M1-specific additions. Those historical hashes are intentionally preserved and must not be represented as hashes of the later combined security-integration tree.

The RES-566 independently qualified Arrow decoder repair from PR #26 is merged into the M1 integration for `apps/workbench/src/arrow/arrow.ts`, `python/src/dynamisbench/transport/arrow.py`, `python/tests/test_workflow_authority.py`, and `.github/workflows/quality.yml`. It preserves the VM float-column transport and cold-start loader while applying pre-materialization resource checks on *both* the generic Arrow decode path and the M1 numeric-frame decode path. The added numeric allocation regression tests reject adversarial metadata before Arrow materialization.

These intentional post-migration changes no longer match the corresponding original VM source hashes. Git history and the RES-566 PR/merge provide their provenance. All original VM renderer, source CSS, anatomical assets, and Study/Analysis/Evidence components are unaffected. No new live-run or scientific evidence authority is implied.

Final acceptance requires the exact merged PR head to pass the Windows/Linux quality matrix and review the desktop/security limitations honestly.
