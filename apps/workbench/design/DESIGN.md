# Codex — design specification of the DynamisBench biomechanics laboratory

Status: the specification the workbench implements (route `/laboratory`, source in
`src/laboratory/`; §8 maps the specification to the code). Scope: the frontend's visual language,
layout, interaction and its data contract with the local application API. It is a workbench
design document, not architecture authority: where it touches an architectural boundary it
cites the boundary it respects.

Plates (SVG, generated from the real model and recording by `tools/plates.py`; PNG previews in
`previews/`):

| Plate | File | Content |
| --- | --- | --- |
| 00 | `references/reference-study.svg` | reference study: paradigms adopted and rejected ([REFERENCE_STUDY.md](references/REFERENCE_STUDY.md)) |
| 01 | `mockups/01-design-language.svg` | Codex: pigments, letters, instruments, proportion, components |
| 02 | `mockups/02-laboratory-studiolo.svg` | Laboratory folio, dark ground (default) |
| 03 | `mockups/03-laboratory-vellum.svg` | Laboratory folio, light ground |
| 04 | `mockups/04-model-atlas.svg` | Model Atlas folio |
| 05 | `mockups/05-analysis.svg` | Analysis folio |
| 06 | `mockups/06-evidence.svg` | Evidence folio |

(The plates predate the Study & Runs folio, which now opens the numbering, and the anatomical
figure; the implementation and the screenshots captured from it are the current reference.)

Regenerate: `python/worker-mujoco/.venv/bin/python apps/workbench/design/tools/plate_data.py
/tmp/plate_data.json && python/worker-mujoco/.venv/bin/python apps/workbench/design/tools/plates.py
/tmp/plate_data.json apps/workbench/design/mockups`.

## 1. Principles

1. **Measured, not decorated.** Every Renaissance motif is a measuring device: graduated floor
   rings, a plumb line for the centre of mass, a dial for a joint within its range, a ledger
   that must balance, seals that state a check's outcome.
2. **One clock.** Playback time is global; the stage, plots, inspector, plantar map, HUD and
   phase strip are projections of it. Seeking anywhere seeks everywhere.
3. **One selection.** A joint or segment selected in the codex tree, the stage, a table or a
   legend is selected everywhere.
4. **Provenance is ambient.** The colophon ribbon always states the recording or run, trajectory
   hash, model hash and engine, and which of two things is on show: a packaged *diagnostic
   record, not sealed evidence*, or a *sealed run, re-verified on read*.
5. **Honest absence, honest refusal.** What the application cannot do is shown with its reason;
   what the run service refuses (an inadmissible value, a preflight refusal, a run whose seals do
   not verify) is shown with the service's reason, and nothing of a rejected run is drawn.
   Nothing is simulated in the browser and no number is invented: every value shown is read from
   the API.

## 2. Tokens

### 2.1 Pigments (semantic, both grounds)

| Token | Studiolo | Vellum | Meaning |
| --- | --- | --- | --- |
| `sanguine` | `#D0603F` | `#A4442A` | kinetics: forces, moments, GRF, power |
| `lapis` | `#7393E3` | `#2B4C9E` | kinematics: angles, velocities, references |
| `verdigris` | `#5FB39A` | `#2D7A63` | contact, balance, passing checks, ready |
| `gold` | `#D9AE55` | `#A77A1E` | centre of mass, barbell, selection, playhead, rubrics |
| `ochre` | `#D99A3E` | `#B2721D` | warnings, not connected |
| `vermilion` | `#E2604B` | `#B83A27` | errors, failed checks |

Phase pigments: standing and return `#7F786C`/`#9C9381`, descent = lapis, bottom = gold,
ascent = verdigris.

### 2.2 Grounds and ink

| Token | Studiolo | Vellum |
| --- | --- | --- |
| `ground` | `#0E0C0A` | `#EDE4D1` |
| `panel` / `panel2` / `raised` / `sunk` | `#15120F` / `#1B1814` / `#221E19` / `#0A0907` | `#F8F3E8` / `#F2EADA` / `#FFFCF5` / `#E6DCC7` |
| `stage` | `#110F0C` | `#F4EDDF` |
| `line` / `line2` / `hair` | `#2C2721` / `#3D362C` / `#221E19` | `#D6C8AB` / `#BFAE8C` / `#E6DBC5` |
| `ink` … `ink4` | `#EEE6D6` `#CDBFA6` `#A39479` `#7D705B` | `#231C13` `#4A3F31` `#6B5E46` `#8F8165` |
| `gold-ink` (gold as text) | `#D9AE55` | `#7A5610` |
| `bone` / `steel` | `#D8C7A6` / `#AEB2B8` | `#CDB893` / `#7F858D` |

Studiolo is the default ground (long sessions); Vellum is the light alternative. The choice is
held in memory only (the workbench persists nothing). The two lightest inks were darkened (Vellum)
and lightened (Studiolo) from the plates so secondary text keeps ≥ 4.5 : 1 contrast on panels;
gold used *as text* on Vellum is the deeper `gold-ink`. The existing workbench tokens
(`--color-*`) are remapped onto these grounds, so the workspace routes wear the same Codex.

### 2.3 Letters

| Voice | Family (bundled, OFL) | Use |
| --- | --- | --- |
| Display | EB Garamond 400/500/600, italic 400 | folio names, plate and pane titles, marginalia (italic) |
| Interface | IBM Plex Sans 400/500/600 | labels, controls; rubrics in 600, caps, +0.12 em |
| Data | IBM Plex Mono 400/500 | every number, unit, hash; tabular figures |

Scale (px): display 34 · plate title 26 · pane title 20 · body 13 · label 11.5 · rubric 10.5 ·
data 12 · axis 9.5. Fonts are bundled with the application (local-first; no CDN).

### 2.4 Proportion

8 px grid, 4 px baseline, 1 px hairlines, 3 px radii. Laboratory columns: codex rail 264 px,
inspector 336 px (232 / 304 px below 1440 px); within the centre column the stage and the dock
stand in the golden ratio (stage : dock = 1.618 : 1) around the timeline. Minimum window
1366 × 768. The codex rail collapses to a 40 px spine on request; below 1440 px the timeline's
track takes its own row.

## 3. Layout and views

Chrome (all folios): **title bar** (emblem, "DynamisBench / Biomechanics Laboratory", folios
I-V, recording selector grouped into *Packaged dataset* and *Workspace runs (sealed, verified)*,
session state, Studiolo/Vellum), **colophon ribbon** (provenance and the not-sealed / sealed
notice), **status bar** (frame, time, rates, renderer, selection, source).

The route is `/laboratory`; `/laboratory?workspace=<id>` (the opaque identifier the API minted
when the workspace was opened — never a path) binds it to that workspace's studies and runs. The
workspace route's *Simulation Laboratory* mode links there and summarizes the workspace's runs.

### Folio I · Study & Runs

* **Study & model**: the workspace's studies (the study selector), the realization it runs
  (label, identifier@version), environment and platform, whether it is executable on this host
  and why not, the research question and the study's scientific limitations.
* **Configuration**: presets (nominal and the study's named cases) and one field per factor in
  its display unit (degrees for angles, ms for timesteps and time constants, s for durations)
  with its qualified domain and nominal; discrete factors (the timestep, which must divide the
  10 ms sample period) are chosen from their published values. Values are sent in canonical
  units exactly (typed 120° is the double of the domain's bound); nothing is clipped: a value
  outside its domain is marked and preflight is withheld.
* **Preflight & execution**: *Preflight* shows the decision and every identity the run would
  execute (study, benchmark, scenario, realization, system under test, environment with semantic
  digests; adapter, implementation digest, engine, CPython, platform, dependency closure;
  execution fingerprint; request digest; timeout) or the refusal with its reason. *Execute run*
  is offered only for the configuration that has just preflighted as ready; progress follows
  plan → materialize & preflight → start worker → forward dynamics → seal execution → normalize ·
  verify · assess → sealed & verified, with cancellation; on completion *Open in Laboratory* and
  *Inspect evidence*.
* **Runs of this workspace**: every sealed run with its read-back status (verified, failed,
  rejected, incomplete, or a progress state), configuration, verification / metrics / checks
  tallies and trajectory digest; *Play*, *Compare*, *Evidence*.

### Folio II · Laboratory (plates 02, 03)

* **Codex rail**: Recordings (nominal, timestep companion, two ablations; each with its check
  status) and, when bound to a workspace, its runs (a run that is not verified is listed with its
  status and opens its evidence instead of the stage), Model tree (bodies → joints; selecting sets the global selection), Layers (athlete,
  GRF vectors, CoM and plumb, loaded support polygon, plantar load discs, bar path, CoM path,
  joint axes, floor instrument).
* **Stage** (three.js, WebGL2): the athlete and bar posed per frame from recorded body poses,
  drawn as the **anatomical figure** (default) or the model's own segment geometry
  (**Scientific**), switched in the stage toolbar. The anatomical figure is a pinned asset derived
  from the model (`/laboratory/figure`; see the squat model's README), deformed on the CPU by
  dual-quaternion skinning with the recorded poses, coloured by its garment fields in the shader
  (straight hems, antialiased), the selected segment glowing by its skin weight; it is drawn only
  for the model whose skeleton it carries, otherwise the toolbar says why. Instruments inside the
  body (joint axes, the selected joint's ring, CoM and plumb) are drawn through the skin;
  floor instrument (graduated rings, centre at the balance point); per-foot GRF vectors from each
  foot's centre of pressure (sanguine, scaled 0.62 m per kN, labelled in N); CoM sphere and
  plumb; loaded support polygon (verdigris, hatched); plantar discs sized by √load; bar path
  (past solid, future dashed). View presets Oblique / Sagittal / Frontal / Plan; orbit, pan,
  zoom; armillary orientation instrument; HUD (time, phase, GRF/W, CoM z, CoP margin, loaded
  contacts); marginalia for the selected joint and its neighbours; scale bar.
* **Timeline**: transport (first, previous frame, play/pause, next frame, last), time and frame
  readout, phase strip (commanded phases, event ticks), graduated track with gold playhead,
  speeds ¼× ½× 1× 2×, loop.
* **Dock**: linked plots with the playhead and phase wash: Kinematics, Kinetics, Ground
  reaction (measured vs internal-model plan), Balance (CoP/XCoM margins), Contact (ten plantar
  loads), Energy (actuator power), Compare runs (this recording vs a companion). Clicking a plot
  seeks.
* **Inspector**: selected joint (dial within its range with reference tick, velocity, tracking
  error, actuator torque against capacity, activation, power), its segment (de Leva mass, CoM,
  inertia), plantar load map (two soles at true scale, ten discs with values), heel share and
  loaded-contact count.

### Folio III · Model Atlas (plate 04)

Lettered plate of the standing keyframe, frontal (with the Vitruvian circle and square of the
stature) and sagittal (measured heights, CoM plumb); legend table A-L with de Leva inertial
properties and the 95.0000 kg total; joint table (ROM bars, asymmetric capacity bars); contact,
coupling and actuation cards; sources.

### Folio IV · Analysis (plate 05)

Six summary cards (depth, measured tempo, peak moments, ground reaction, balance, contact); the
**Ledger of work and energy** (per phase: actuator +, actuator −, damping, ΔE, residual, seal;
Summa); commanded vs measured phase register; comparison plots against the chosen companion —
any playable packaged recording or verified run (*Compare* in the runs table), by default the
ablation for the nominal and the nominal for anything else: heel share, measured − planned GRF,
and either the timestep difference (nominal vs its dt/2 companion) or the knee-angle difference
this − compared.

### Folio V · Evidence (plate 06)

For a **workspace run** (the run on show, or any run chosen in *Inspect*), the folio shows what
the run service established when it re-verified the run for this request: the verdict (verified
/ failed / rejected / incomplete) with its reasons; the chain of provenance from the source
documents (with semantic digests) through the content-addressed inputs, RunSpec and preflight,
the isolated worker (adapter and implementation digest), the execution bundle and its native
files, the trajectory, the canonical series and the derived bundle; the register (independent
verification with value and tolerance, benchmark metrics with value and bound, the adapter's
checks); the claim and limitations; and both bundles file by file with sizes and SHA-256. A run
that is rejected shows its reasons and the seal that failed, and none of its data.

For a **packaged recording**:

(Plate 06's register is a layout study drawn before the criteria were final. The implementation
lists exactly the published criteria — 22, in the groups `criteria.py` declares: bar weld and
hand grip are separate checks, the ledger check reports the worst phase residual as a fraction
of its allowance, and cross-process determinism is a qualification test of the suite rather
than a per-recording criterion.)


Chain of provenance (model authority → asset → worker environment → recording → companions →
dataset → API → workbench, each with its identity); register of checks grouped by Mechanics,
Contact, Coupling & joints, Human-likeness, Numerics (value, bound, seal, PASS/FAIL); colophon
(claim, limitations, reproduction, and that the record is not sealed evidence).

## 4. Interaction

| Input | Action |
| --- | --- |
| Space | play / pause |
| ← / → | previous / next frame (⇧: ±10 frames) |
| Home / End | first / last frame |
| 1 2 3 4 | view preset Oblique, Sagittal, Frontal, Plan |
| [ / ] | previous / next phase boundary |
| click or drag on a plot or the track | seek (pauses playback) |
| on the focused track: ← → / PageUp PageDown / Home End | ±1 frame / ±10 frames / first, last |
| click segment on stage, tree row, plate letter or legend row | select joint/segment |
| drag / wheel on stage | orbit / zoom (⇧ drag or right drag: pan) |

Playback advances by wall clock × speed and samples the nearest recorded frame (frames are
100 Hz snapshots); it never interpolates new states. Focus is always visible; every control is
a real button or labelled control; plots expose a value table for assistive technology.

## 5. Data contract (`/api/v1/laboratory`, `/api/v1/workspaces/{id}/studies`, `…/runs`)

The laboratory publishes a **packaged, SHA-pinned dataset** generated offline in the isolated
worker (`python/tools/mujoco_squat_laboratory.py`). The laboratory routes read packaged bytes;
the API never imports MuJoCo and never executes a simulation itself (ADR-017) — runs are
delegated to the injected run service, which admits them and supervises the isolated worker. JSON carries metadata and small
records; bulk frame data travels as Arrow IPC streams (ADR-019 transport split).

| Route | Media type | Content |
| --- | --- | --- |
| `GET /laboratory` | JSON | dataset identity and claim; recordings (id, label, kind, timestep, frames, trajectory hash, checks passed/total) |
| `GET /laboratory/model` | JSON | bodies (parent, mass, CoM, inertia), geoms (body, type, size, local pose, role), joints (axis, range, capacity, damping), sole points, barbell, stance, sources |
| `GET /laboratory/recordings/{id}` | JSON | plan, command events, measured phases, summary, extrema, work ledger, checks, channel catalogue |
| `GET /laboratory/recordings/{id}/frames/{group}` | Arrow IPC stream | `pose` (body positions and quaternions), `kinematics`, `kinetics` (joint torques, per-foot GRF and centre of pressure, the ten plantar loads and their floor positions, margins, power); one row per 10 ms snapshot |

| `GET /laboratory/figure` | `application/vnd.dynamisbench.figure` | the anatomical figure stream (magic, JSON header with provenance, skeleton, bind pose, volumes, section table; aligned arrays: positions, normals, bone indices, weight bytes, garment fields, triangles) |

The model read model also carries the joint anchors, gravity, the subject (mass, stature, bar,
grip) and the contact parameters, so nothing the workbench labels is re-derived or hard-coded.

Runs of a workspace study go through the application's run service (the API adapts it; it plans,
admits, executes in the isolated worker, seals, normalizes, verifies and assesses; every read
re-verifies the seals):

| Route | Content |
| --- | --- |
| `GET /workspaces/{id}/studies` | studies, executability and reason, factors (canonical unit, domain, nominal, display, admissible values), presets, limitations |
| `POST /workspaces/{id}/runs/preflight` | decision, refusals, identities (study, definitions, adapter), fingerprint, request digest |
| `POST /workspaces/{id}/runs` (202) | the started run's progress |
| `GET /workspaces/{id}/runs/{run}/progress`, `POST …/cancel` | progress of a run this session started |
| `GET /workspaces/{id}/runs` | every sealed run re-verified, and this session's active runs |
| `GET /workspaces/{id}/runs/{run}/evidence` | both bundles' verification and files, run record, provenance, verification, assessment |
| `GET /workspaces/{id}/runs/{run}/recording`, `…/model`, `…/frames/{group}` | a *verified* run in the packaged recordings' shape (kind `run`), its own compiled model, Arrow frames; a run that does not verify answers 409 with its reasons |

A run's request carries exactly `{study_id, case_id, values}` in canonical units; the client
refuses any answer about another run, and a recording of kind `run` is accepted only from the
run routes.

**Display derivations.** The browser computes nothing scientific. The few transformations it
applies to published values are named where they are shown: extensor moment = −τ about a flexion
axis; vertical GRF = left + right over the published weight (total mass × gravity); unit
conversions (m → mm, fraction → %); a difference of two published series on the same 10 ms grid
(measured − planned GRF, dt 1 ms − dt 0.5 ms knee angle); the tracking error angle − reference;
the ledger residual (the arithmetic of the `ledger` criterion); and the convex hull of the
published load-bearing points drawn as the support polygon. Authoritative scalars — extrema,
check values and outcomes, the work record — are always the published ones.

## 6. Architecture boundaries respected

* HTTP through the one client (`src/api/client.ts`); typed decoders validate every response.
  The client's only writes are root selection and the run service's three commands (preflight,
  start, cancel); none of them carries a source document, and evidence is sealed by the service.
  Factor values are typed in one place (`folio-study.tsx`); `boundaries.test.ts` pins both.
* Nothing is persisted (no storage APIs); theme and selection live in memory.
* three.js (`three` 0.186.1, imported only by the stage) and the fonts (`@fontsource/*` 5.3.0,
  OFL) are reviewed additions to the allowed dependency list; Arrow is loaded lazily through
  `src/arrow/arrow.ts`, imported only by `src/laboratory/frames.ts`; the laboratory route itself
  is a lazily loaded chunk. `src/test/boundaries.test.ts` pins all three facts.
* No scientific computation in the browser: kinematics are the recorded poses; metrics and
  checks are read, not recomputed. Skinning the figure is presentation geometry over recorded
  poses, not a derived quantity.

## 7. Acceptance

* Typecheck, unit tests and build pass; new units cover decoders, playback clock, frame lookup,
  plot scaling, phase lookup and component rendering (WebGL-free fallback in jsdom).
* A Playwright test drives the production route tree against a real secured sidecar: the
  laboratory loads the dataset over HTTP, plays, seeks by plot and by keyboard, selects a joint,
  switches folios and theme, and shows the ablation's failed checks.
* Screenshots of every folio in both grounds are captured from the running application.

The researcher workflow adds `e2e/study-workflow.spec.ts` (a real squat workspace opened
through the landing form, its laboratory opened from the workspace, preflight, execution in the
isolated worker, playback, comparison, evidence, a damaged canonical series shown as rejected,
and a cancelled run) and Vitest suites for the run decoders and client, configuration, the
study workflow, the figure decoder and skinning, the stage's failure states and the plot layout.

Result at the first delivery: typecheck and build pass; Vitest 438 tests (82 new for the laboratory:
decoders, client binary reads, Arrow float columns, frame tables, clock and series helpers,
camera and engraving geometry, store, and the rendered route with a stubbed network); Playwright
36 specs against the real sidecar, including `e2e/laboratory.spec.ts`. Screenshots:
`DYNAMISBENCH_UX_SCREENSHOTS=<dir> pnpm exec playwright test e2e/laboratory.spec.ts`.

## 8. Implementation map

| Specification | Source |
| --- | --- |
| read models, decoders | `src/api/laboratory-types.ts`, `src/api/laboratory-decode.ts` |
| HTTP (JSON and the binary frame read) | `src/api/client.ts` (`laboratory*` methods) |
| query keys and options | `src/api/queries.ts`, `src/laboratory/frames.ts` (frames) |
| accepted data set per recording | `src/laboratory/data.tsx` |
| one clock, one selection, layers, pins | `src/laboratory/store.ts`, `src/laboratory/series.ts` |
| stage (three.js), camera, overlays, HUD | `src/laboratory/stage/scene.ts`, `camera.ts`, `stage.tsx` |
| timeline | `src/laboratory/timeline.tsx` |
| linked plots, dock | `src/laboratory/plot.tsx`, `src/laboratory/dock.tsx` |
| inspector (dial, capacity, plantar map) | `src/laboratory/inspector.tsx` |
| codex rail | `src/laboratory/rail.tsx` |
| Folio III engraving and tables | `src/laboratory/engraving.ts`, `src/laboratory/folio-atlas.tsx` |
| Folio IV | `src/laboratory/folio-analysis.tsx` |
| Folio V (packaged recording and run evidence) | `src/laboratory/folio-record.tsx` |
| Folio I (study, configuration, preflight, execution, runs) | `src/laboratory/folio-study.tsx`, `src/laboratory/configuration.ts` |
| run read models, decoders, sources | `src/api/run-types.ts`, `src/api/run-decode.ts`, `src/laboratory/sources.ts` |
| anatomical figure (decode, model check, skinning, material) | `src/laboratory/figure/figure.ts`, `skinning.ts`, `query.ts`; `FigureLayer` in `stage/scene.ts` |
| chrome (bar, ribbon, status, shortcuts) | `src/laboratory/laboratory-page.tsx`, `src/shell/app-shell.tsx` |
| tokens and letters | `src/styles.css`, `src/fonts.ts`, `src/laboratory/palette.ts` |
