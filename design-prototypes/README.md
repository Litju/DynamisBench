# DynamisBench — Unified Scientific Workbench (design prototype, RES-575 v0.3, revision 1.1)

ONE integrated, browser-runnable design for owner review. It is not a production feature, it calls
no backend, worker or simulator, and it must not be used for scientific conclusions.

```
pnpm --dir design-prototypes install   # first time only
pnpm --dir design-prototypes dev       # http://localhost:5178/workbench
pnpm --dir design-prototypes build     # tsc --noEmit + vite build
pnpm --dir design-prototypes test      # Playwright smoke journey (Edge), writes evidence/*.png
```

Entry route: `/workbench`. Any other path redirects there. Deep links carry the scientific context,
e.g. `/workbench?study=pendulum-qual&mode=analysis&tab=compare&sel=joint.hinge&t=0.734`.

The rejected A/B/C concepts (revision 0.1) are preserved unchanged, outside the build, in
`archive/rejected-abc-v0.1/` (source, README, screenshots, verification note).

## One product, four contexts

One shell. The top bar always shows study, model/realization, scenario (and draft state), execution
lifecycle, capability and evidence status. The left **Navigator** (study context → model tree →
runs/series → references) and the right **Inspector** persist across all modes, so selection,
study and the shared time cursor survive every mode switch.

| Mode | Purpose |
|---|---|
| Study & Model | research question, intended use / non-use, claim ceiling, credibility hierarchy, assumptions, applicability, composition (benchmark/scenario/realization/SUT/environment), capability coverage, factors, planned comparisons, capability status map |
| **Simulation Laboratory** (primary) | run toolbar (scenario draft, preflight, demo outcome, execute, cancel, lifecycle stepper) · large interactive 3D scene · recorded-playback transport · resizable dock: linked signals, numerical table / coordinate pose editor, execution log, preflight report |
| Analysis & VVUQ | solution verification vs predeclared criteria, timestep refinement, error-over-time; SDI-style series comparison; validation workspace; uncertainty & sensitivity — each reported separately, with a linked 3D context view |
| Evidence & Provenance | 12-stage ledger source → plan → admission → execution → native → canonical → assessment → claim, stage detail, and a "distinctions kept separate" table |

Two studies are selectable:

* **Reference pendulum** — the real, qualified RES-550 MuJoCo fixed reference. Structure, constants,
  digests, tolerances and claim text are transcribed from the repository.
* **LCMJ20 contact-stiffness sensitivity** — the human-movement *target* UX, built from the
  schema test fixtures, rendered as a labelled design-only planar sagittal schematic. It cannot
  execute: preflight refuses with real refusal codes, and no trajectory, force or validation exists.

## Revision 1.1 (owner request: "the best design")

* **Laboratory layouts:** Bottom (plots in a 2×2 grid under the scene), Side (plots beside a tall
  scene, resizable width) and Scene-only focus (`F`, `Esc` restores). Navigator and Inspector
  collapse to rails (`[` / `]`). Layout preference is remembered per viewer.
* **3D:** the human schematic uses tapered anatomical proxy shapes (lathe limbs, rounded pelvis and
  feet, welded display-only arms) with shadows; still DESIGN_ONLY. Selecting a joint draws its
  hinge axis, the dashed reference direction and the swept pose angle; selected parts get an
  outline. Camera framing adapts to viewport aspect.
* **Signals:** phase portrait θ–ω (click the orbit to move time); energy shown as drift E − E₀
  so 1e-13 J numerical noise is not drawn as a large oscillation.
* **Provenance:** dense rows use a compact shape+colour glyph (with accessible name and tooltip);
  full tags remain in headers. A "Sources" legend explains all seven categories.
* **Dark theme** for long sessions (`Dark` / `Light` in the mode bar); all colours are tokens.

## Revision 1.2 — licensed human reference geometry

The LCMJ20 study now shows the **MyoSim MyoLegs + MyoTorso** model (MyoHub/myo_sim @ `93b0ca8f`,
Apache-2.0; derived from Rajagopal et al. 2016, MIT). 51 unmodified files (~6.1 MB) are in
`public/assets/myosim/` with `LICENSE` and `NOTICE`. `src/data/myosim.ts` parses the MJCF in the
browser; the navigator shows the real body tree (pelvis → femur → tibia → talus → calcn → toes,
sacrum → lumbar5…1 → torso), the inspector shows each body's mass/COM and each joint's axis and
range, and the Coordinates tab poses the 17 primary DOFs within the model's ranges. Everything from
MyoSim carries the **External reference model** tag. Not done: muscles, tendons, wrapping
surfaces, contacts, head, arms; coupled knee/patella DOFs are held at 0 (equalities not evaluated);
pelvis tx/tz/tilt are display-only. The design-only schematic stays available via the
MyoSim | Schematic toggle. No physics, trajectory or validation is implied.

## Reference interactions → design decisions

| Source | Adopted pattern | Where |
|---|---|---|
| COMSOL Model Builder | persistent model hierarchy → context Settings → Graphics → results; selecting a tree node (incl. Scenario, Solver) opens its settings; visible solver/execution log | Navigator + Inspector + Lab toolbar/log |
| OpenSim Creator | biomechanical entity vocabulary (bodies, joints, coordinates, contacts, actuators, sensors); coordinate panel that poses the model without simulating; simulated vs experimental data kept as distinct origins | Human tree, Coordinates dock tab, Validation legend |
| ParaView | linked views around an active object; 3D selection ↔ tree ↔ properties; view presets, camera reset, overlay toggles with explicit availability; the Analysis 3D context shows the comparison candidate as a ghost | Scene, overlays menu, Analysis context view |
| Simulink Data Inspector | signal catalog; baseline/candidate; abs/rel tolerance with max(abs, rel·\|base\|); time alignment and resampling stated; difference plot with tolerance band; linked cursors and zoom; result phrased as "within/exceeds tolerance", never PASS | Analysis → Compare series, linked Lab plots |
| WCAG 2.2 AA-inspired | native controls, visible focus, roving-tabindex tree, plots as keyboard sliders with `aria-valuetext`, table alternative to plots, text fallback if WebGL fails | throughout |

## Capability-to-UI map

Every value carries one of these tags in the UI: **Authority**, **Qualified**, **Test fixture**,
**Prototype computation**, **Design only**, **Not implemented**, **Not assessed**.
All data is centralised in `src/data/` (one demo adapter).

| UI element | Scientific concept | Source | Status | Integration dependency |
|---|---|---|---|---|
| Pendulum tree, inspector properties | MJCF bodies/joint/site/frames/solver | `adapters/mujoco/assets/reference_pendulum.xml`, `reference.py` | AUTHORITY | read-only model inspection API (none yet) |
| Identities and digests | semantic SHA-256 of definitions, raw model SHA-256 | `reference.py` pins, `reference_case.py` | AUTHORITY | workspace inspection API (M2 exists for workspaces) |
| Study page text | intended use, non-use, claim ceiling, assumptions… | `reference_case.py`; LCMJ20 `tests/fixtures/domain/valid/*.json` | AUTHORITY / FIXTURE | released benchmarks (none for humans) |
| Scenario draft + plan preview | local edit of initial angle, duration, Δt, integrator, seed | prototype state | DESIGN_ONLY — no RunSpec, no fingerprint | accepted RunSpec authoring endpoint (none; not added) |
| Preflight report | admission checks + RefusalCode | codes from `execution/contracts.py`, logic mirrors `preflight.py` / `worker.py` | DESIGN_ONLY deterministic demo | browser access to real preflight (pending) |
| Execute / cancel / lifecycle | RunLifecycleState incl. refused, failed, timed_out, canceled | `execution/contracts.py` | DESIGN_ONLY timer; explicit demo-outcome selector | production run/cancel API (not implemented) |
| 3D pendulum motion, signals, table | θ, ω, E, bob position on 1 ms grid | browser RK4 re-solve of I·θ'' + mgL sin θ = 0 from authority constants | RECOMPUTED — not MuJoCo output | sealed native evidence (RES-555) + canonical slices (M4) |
| Verification table | predeclared criteria; refinement Δt set | `qualification_criteria.py`, `qualification.py` | criteria AUTHORITY; observations RECOMPUTED; receipts QUALIFIED but not in repo | receipt/assessment artefact read path |
| Compare series | baseline vs candidate, tolerance, alignment | synthetic numerical series | RECOMPUTED, not runs | canonical cross-run query (M4, RES-569) |
| Validation | measured vs simulated, event alignment, metric | pendulum: none (synthetic ref); LCMJ20: fixture declares `r.baseline-0`, no data | NOT_ASSESSED / NOT_IMPLEMENTED | empirical data + M5 (RES-570) |
| UQ & sensitivity | factors, sampling draft, planned matrix | LCMJ20 fixture factors; pendulum `f.reference.gravity` | DESIGN_ONLY draft; outputs NOT_ASSESSED | ensemble execution, planner integration |
| Human schematic + pose editor | planar sagittal multi-segment subject | fixture conceptual model; geometry invented for legibility | DESIGN_ONLY; inertial/limit properties "not available" | licensed human model asset (none) |
| Evidence ledger | native / canonical / assessment separation | `evidence/*`, `diagnostics.py`, RES-555 docs | mixed, per stage | RES-555/561, M4 |

## Representative walkthrough (keyboard-capable)

1. Open `/workbench` → Laboratory with the qualified pendulum. Select `bob` in the tree (or click the
   bob in 3D): Inspector shows site properties; the dock swaps to bob x/z.
2. Scrub the transport slider, drag on a plot, or press ←/→: 3D, plot cursors, table row and
   Inspector live values move together. Space plays recorded samples (never solver steps).
3. Select **Scenario**, set the initial angle to 45° → draft badge; **Check preflight** → REFUSED
   `worker_failed` (pinned-digest authority). **Restore reference** → READY.
4. Choose a demo outcome and **Execute (demo)**: `starting → running → completed | failed |
   timed_out`, or **Cancel** → `canceled`. The log states that completion is a process fact only.
5. Alt+3 → Analysis: criteria vs observation, refinement ratio ≈ 16.8, error-over-time. **Compare
   series**: pick a candidate, set tolerance; verdict says within/exceeds, never PASS.
6. Validation and UQ show explicit not-assessed states. Alt+4 → Evidence ledger.
7. Switch study to LCMJ20 → design-only schematic, disabled playback, "not produced" signals, pose
   editor, refusal with `unsupported_capability`, `adapter_engine_mismatch`, `unstaged_asset`.

## Known limitations

* No backend: preflight, lifecycle and logs are deterministic demonstrations; nothing is executed.
* Trajectories are browser recomputations (RK4, Δt 1 ms vs Δt 10 µs reference) — they mirror the
  qualification procedure but are not the MuJoCo observations; receipt values are CI artefacts.
* "Energy reconstruction vs diagnostic" is not computable without the adapter diagnostic.
* Human geometry, segment lengths, coordinate ranges and sign conventions are display-only.
* No dark theme; no generic docking framework (dock resizes vertically only); tree is not
  virtualised; numeric table shows 10 ms rows plus the exact cursor sample.
* Charts are lightweight React/SVG; the long-term direction toward Plotly is not adopted here.
* Only the 1024–1920 px desktop range is designed; `min-width` 960 px, no phone layout.
