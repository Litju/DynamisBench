# RES-591 M1 — VM Workbench integration evidence

Status: draft for owner review. This branch is not merged or production-qualified.

## Source identity and transfer

The integration branch is based on protected `main` at `a24152305b60b7a7a6605666b95ba56149a4bc62`.
The Turn 4 archive SHA-256 is `b25c64b6396ce39b9801e202d15fb36a23c06bf89affe027d541af8ec63a0a9b`; the Turn 5 delta SHA-256 is `7f1f8a5433cc2249ca0dd2567c15ac8a519c6965b8e7d0d9035e33bd9529455d`. The reconstructed candidate ZIP SHA-256 is `8cbe5565537a9063e4c67f5f44b8388e9f4f0c3c1174ac3502f7fa6d7eccbfc8`; its 600-file manifest SHA-256 is `99a20394332f8c5301981b27806dac6c3b19a2dce49c90ef079ed67260d96ccd`.

All 600 reconstructed candidate files were independently rehashed against that manifest with zero mismatches. This M1 branch changes 135 repository paths: 113 match the candidate byte-for-byte, 20 are compatibility-modified, and 2 are M1-only boundary/test additions. `source-map.csv` records the candidate, protected-main, and integrated SHA-256 values for every changed path. `compatibility-diffs.patch` contains the candidate-to-integrated hunks for all 20 modified VM files; `compatibility-modifications.md` gives the reason for each change.

Turn 5 remains a delta over the complete Turn 4 archive. Its original VM workspace/commit provenance was not recovered; the M0 recovery report records the omitted binary recovery and the evidence used to rebuild the candidate. This branch preserves the input archives and candidate hashes and does not claim original-workspace provenance.

## Product surface preserved

The branch transfers the VM's actual React Workbench and Laboratory source, including the Three.js anatomical/scientific renderer and figure skinning, model inspection, Study & Runs, synchronized timeline, plots, quantitative analysis, comparison views, Evidence folio, CSS, fonts, API types/decoders, fixtures, design assets, and UI tests. The overview and existing workspace source-inspection routes remain available; the VM Laboratory is a real route in the official application router.

The `/laboratory` route runs the production router/provider/shell and the original VM components against the authenticated sidecar in Playwright. Only the Tauri IPC bootstrap is replaced in this browser harness. The packed recordings and figure are served from the SHA-pinned diagnostic package. No fake run or sealed-evidence result is substituted. The Study folio reports that workspace study/preflight/execute/cancel and sealed-run readback are unavailable in M1. The Evidence folio now states that it checks packaged files but does not rerun the MuJoCo worker; its old reproduction command pointed to M2 tools absent from this branch.

The 15 committed PNGs in `ui/` include the actual browser captures. Fourteen have M0 visual-reference counterparts: 9 are byte-identical; 3 Evidence images differ intentionally because the reproduction/provenance wording now reflects M1 limits; 2 WebGL captures are not byte-identical, but full-resolution inspection showed the same scene, layout, and labels. `05-study-runs-m1-unavailable.png` records the honest workspace-bound M1 state. The capture tests assert that session credentials are absent.

## Checks run

Local Windows results:

| Check | Result |
|---|---|
| `pnpm install --frozen-lockfile` | Pass |
| Workbench TypeScript typecheck | Pass |
| Vitest | 498 passed across 40 files |
| Workbench production build | Pass; Laboratory chunk 711.22 kB (187.15 kB gzip) |
| Full Playwright suite | 35 passed, 1 opt-in screenshot test skipped |
| Final Laboratory/workspace Playwright cases with screenshot capture | 3 passed |
| Focused Python Laboratory/columnar tests | 40 passed, 6 expected M2/opt-in skips |
| Python namespace/public-boundary/workflow-authority tests | 85 passed |
| Ruff check and format check | Pass; 218 Python files formatted |
| Pyright | 0 errors, 0 warnings |
| `uv sync --no-dev --locked` and `preload_columnar_stack()` | Pass; NumPy 2.5.4, PyArrow 26.0.0 |
| Tauri Rust tests | 103 passed (76 unit, 6 sidecar integration, 21 supervision) |
| Windows Tauri Rust build | Pass |

One intermediate full browser retry had an unexpected Windows sidecar exit (`3221226505`) in the existing session-replacement test. That test passed in isolation; a later complete suite passed, followed by the three final affected browser cases. No production-code change was made to conceal that transient failure.

These are local checks, not exact-head hosted Windows/Linux qualification. The native Tauri/WebView2 window was not launched or visually qualified; a Rust build is not RES-562 evidence. Linux qualification remains pending.

## Authority and merge blockers

1. **RES-566 — Arrow decoded-allocation boundary is still open.** The new GET-only frame route serves only files verified against a fixed package manifest, and the payload is byte-bounded. The browser nevertheless calls Arrow `tableFromIPC` before checking the decoded row count. RES-566 documents that a byte limit does not bound decoded allocation and says not to add an endpoint as part of that unresolved scope. Treat the new Laboratory frame endpoint and decoder as draft-only; do not merge until RES-566 is closed or the owner explicitly accepts a reviewed boundary disposition.
2. **Stack exception needs authority approval.** This PR directly reuses the VM's raw Three.js renderer and custom SVG plots. The accepted stack names React Three Fiber v9 and Plotly. No ADR or contract was edited; an explicit owner-approved exception/amendment is still needed before production adoption.
3. **Live scientific execution remains unavailable.** There is no RunSpec migration, worker/run service, preflight/start/cancel route, native evidence sealing, canonical normalization, or assessment in M1. RES-555/561/569 authority work remains for later phases. The VM code for the product workflows is preserved in the reconstructed candidate and frontend source, but the M1 capability gate is false.
4. **Native desktop and empirical qualification remain open.** RES-562 and RES-564 still govern real Windows WebView2 usability and CSP/session hardening. Numerical verification of synthetic recordings is not empirical biomechanical validation; RES-570 remains separate.

No ADR, scientific contract, protected branch, or Linear status was changed by this evidence package.

The narrow, unaccepted rendering-stack proposal is in `stack-exception-proposal.md`.
