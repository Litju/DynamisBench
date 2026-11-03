# Verification — unified workbench, revision 1.2 (RES-575 v0.3)

Status proposed: **READY_FOR_OWNER_DESIGN_REVIEW** (owner decides). Not production acceptance.

Branch `prototype/res-575-three-concepts` at `ca8a381`; all work is untracked under `design-prototypes/`
plus `.claude/launch.json`. No production app, backend, CI, fixtures or ADRs were modified
(`git diff --stat` empty). Nothing committed. Third-party files: `public/assets/myosim/` (Apache-2.0, see NOTICE).

## Commands observed

| Command | Result |
|---|---|
| `tsc --noEmit -p design-prototypes --noUnusedLocals` | pass |
| `pnpm --dir design-prototypes build` | pass (three.js chunk-size advisory only) |
| `pnpm --dir design-prototypes test` | 2 passed (Edge, SwiftShader WebGL), 0 console errors |

## Interaction smoke journey (`smoke.spec.ts`) — v0.3 §7 items

| # | Behaviour | Observed |
|---|---|---|
| 1 | Mode switch keeps study, selection, time (Alt+3, URL `mode`/`t`, inspector) | PASS |
| 2 | Tree click / keyboard (↑ Enter) and 3D click select entities; inspector + linked plot update | PASS |
| 3 | Orbit drag, wheel zoom, view preset, reset view, overlay toggle | executed without error (camera pose not asserted) |
| 4 | Draft initial angle 45° → preflight REFUSED `worker_failed`; restore → READY | PASS |
| 5 | Lifecycle completed / failed / timed_out / canceled; log shows codes and "native evidence: not produced" | PASS |
| 6 | Slider, plot keyboard and table row click move one shared time cursor (readout, plot aria, table) ; playback moves only the cursor | PASS |
| 7 | Compare: default exceeds 1e-8; semi-implicit Euler within 0.01; verdict says "not a scientific PASS" | PASS |
| 8 | Validation "No experimental reference available"; UQ "not assessed" | PASS |
| 9 | Evidence ledger: sealed stage "Nothing … is sealed"; source stage shows the real model SHA-256 | PASS |
| 10 | LCMJ20: "No human physics result", playback disabled, signals "not produced", refusal `unsupported_capability` + `adapter_engine_mismatch`, UQ matrix 5×3 = 15 | PASS |
| — | 1280×800 and 1024×768: no horizontal document overflow | PASS |
| 1.1 | Phase-portrait click moves time; Side layout; F focus hides side panels; Esc restores; `[` collapses navigator to rail | PASS |
| 1.2 | MyoSim: banner names the external model; tree has mbody.tibia_r (3.8 kg); knee_angle_r range 0…2.0944; Coordinates sliders pose hip/knee/ankle; Schematic toggle and back | PASS |
| 1.1 | Dark theme toggle sets `data-theme=dark`; source legend dialog lists categories | PASS |

## Screenshots (actual browser captures)

`01-lab-pendulum-1600` · `02-lab-draft-refused-1600` · `03-lab-lifecycle-log-1600` ·
`04-analysis-verification-1600` · `05-analysis-compare-1600` · `06-evidence-1600` ·
`07-study-pendulum-1600` · `08-lab-human-myosim-1600` · `08b-lab-human-myosim-sagittal-1600` · `09-analysis-human-validation-1600` ·
`10-study-lcmj-fixture-1600` · `11-lab-1280` · `11-lab-1024` · `12-analysis-compare-1280` · `01b-lab-side-layout-1600` ·
`01c-lab-scene-focus-1600` · `13-dark-lab-human-1600` · `14-dark-analysis-compare-1600`

## NOT_TESTED

Screen-reader pass; forced WebGL-failure fallback; dock resize by keyboard; contrast measured with a
tool (palette chosen for ≥4.5:1 but not audited); Firefox/Chrome; high-DPI; 1920+ px layouts.
