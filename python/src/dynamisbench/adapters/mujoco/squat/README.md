# Barbell back-squat model (MuJoCo)

A synthetic adult male athlete, **75 kg and 1.75 m**, holding an empty **20 kg men's Olympic
barbell** in the high-bar back-squat position. The model compiles, starts in a standing
configuration that is a rest state of its own forward dynamics, and is driven only by
muscle-like joint torque actuators under a feedback postural controller.

This is the first deliverable of the back-squat work. It has a **bounded claim**: mechanical
consistency and closed-loop forward-dynamics behaviour of a population-scaled model. It is not
validated against measured human motion, not subject-specific, not DynamisBench native,
canonical or assessment evidence, and not a benchmark execution (see
[Scope in DynamisBench](#scope-in-dynamisbench)).

## What is in the model

| Part | Content |
| --- | --- |
| Segments | 16 rigid bodies: pelvis, middle and upper trunk, head; upper arm, forearm, hand, thigh, shank and foot on each side. Mass, centre of mass and principal inertia from de Leva (1996) males; lengths from de Leva scaled to stature, with Drillis & Contini ankle height. The anatomical zero posture is exactly 1.750 m tall; athlete mass is exactly 75.000 kg. |
| Joints | 29 hinges, each with an anatomical range of motion: 3-axis lumbar, thoracic and neck; 3-axis hip (flexion, adduction, rotation), knee, ankle and subtalar; 3-axis shoulder (humerothoracic) and elbow. Positive angles are the named anatomical direction on both sides. Floating pelvis (6 DOF). |
| Actuators | 29 joint-torque actuators with first-order activation dynamics (30 ms). Control is a normalised neural excitation in [-1, 1]; torque is clamped to asymmetric peak capacities (e.g. knee 300 N m extension / 150 N m flexion). |
| Passive properties | Intrinsic viscosity of tonically active muscle (5 N m s/rad at the large sagittal joints), passive damping elsewhere; anatomical end-of-range stops. No armature (no non-physical inertia). |
| Foot-ground contact | Five plantar contact spheres per foot (two heel, first and fifth metatarsal heads, hallux), friction 0.9, elliptic cones, no-slip iterations. The sole contacts are explicit contact pairs whose friction directions use a 2 ms time constant (see [Contact friction](#contact-friction)). Body segments also collide with the floor (for falls); there is no self-collision. |
| Barbell | Free rigid body: IWF men's bar, 2.20 m, 28 mm shaft, 50 mm sleeves, 20 kg, inertia from its parts. Coupled by a near-rigid **weld** to the upper-trapezius shelf (high-bar) and a **connect** at each hand (0.96 m grip). Coupling forces are real constraint forces. |
| Solver | 1 ms step, `implicitfast`, Newton, standard gravity 9.80665 m/s^2. |

Every number and its source is in [`anthropometry.py`](anthropometry.py); the MJCF is rendered
from it by [`mjcf.py`](mjcf.py) and is never edited by hand. The asset
[`assets/barbell_back_squat.xml`](assets/barbell_back_squat.xml) is verified against a pinned
SHA-256 ([`contract.py`](contract.py)) every time it is loaded.

## How motion is produced

No trajectory, keyframe animation or kinematic playback is used anywhere.

1. **Posture solve.** [`stance.py`](stance.py) declares the task: feet flat, ankle centres 0.36 m
   apart with 20 deg toe-out; hands on the bar; whole-system (athlete + bar) centre of mass
   5 cm in front of the ankles, over the mid-foot. A constrained Gauss-Newton solve satisfies
   these exactly while preferring a neutral posture, inside every range of motion.
2. **Contact settle.** MuJoCo inverse dynamics adjusts only the floating-base and bar
   coordinates until the soft sole contacts and the bar couplings carry gravity.
3. **Tonic torques.** A minimum-effort static equilibrium (minimum sum of squared activations)
   gives the muscle torques that hold the posture. Standing needs about 24 N m of plantarflexor
   torque per ankle, as the statics of a body whose centre of mass is 5 cm in front of the
   ankles requires.
4. **Relaxation.** The closed-loop model is integrated for 30 s until it is at rest. The
   resulting state, with its activations, is the packaged keyframe `stand`.
5. **Forward dynamics.** [`control.py`](control.py) maps the *measured* joint state to
   excitations: tonic torque plus joint stiffness and damping feedback (the decentralised
   joint-impedance model of posture). MuJoCo integrates everything else.

Squat postures use the same pipeline with one extra hard constraint (knee flexion) and one
coordination preference: the trunk stays parallel to the shank, as in a well-executed high-bar
squat. They are static equilibria, not frames of an animation.

## Measured behaviour

All values come from the fixed-mode observations of the packaged model (MuJoCo 3.17.0, Linux
x86-64), and the test suite enforces them with independent thresholds.

| Observation | Result |
| --- | --- |
| Keyframe | 10/10 sole contacts at 0.5-0.9 mm compression; generalised force imbalance < 0.01 N; system CoM 50.6 mm in front of the ankles at 1.106 m; bar at 1.470 m (high-bar) |
| Quiet standing, 10 s | vertical ground reaction 931.63 N = (75 + 20) kg x g; CoM excursion < 0.01 mm; joint excursion < 0.01 deg; foot slip < 0.02 mm; peak activation 0.12 (ankle plantarflexors) |
| 15 N s push (forward / backward / lateral) | recovered: CoM excursion 26 / 27 / 10 mm, peak joint excursion 2.6 deg, settles in ~2 s, no actuator saturation, no foot lift-off beyond the toes unloading |
| Same push at half stiffness | falls (stability margin; nothing but the muscles holds the athlete up) |
| Zero excitation, 3 s | the athlete collapses to the floor; anatomical stops hold to within 1.9 deg |
| Flight under random excitation | momentum balance error halves with the timestep (3.63 -> 1.87 N s, first-order convergence): the error is integration error, not a modelling inconsistency |
| Static squat, knee 30 / 60 / 90 / 120 deg | hip 29 / 58 / 88 / 120 deg, ankle 11 / 21 / 29 / 34 deg, trunk 13 / 22 / 29 / 34 deg; thigh horizontal at 120 deg; knee extensor moment 21 / 52 / 74 / 86 N m and hip extensor 25 / 45 / 61 / 70 N m per leg; plantarflexor moment constant at ~24 N m; peak activation 0.31 |
| 90 deg squat hold, 5 s | stable under forward dynamics: CoM excursion 0.4 mm, foot slip 0.3 mm, all 10 contacts, ground reaction = body + bar weight |

## Reproduce

From `python/`, with the isolated worker environment provisioned
(`uv sync --frozen --project worker-mujoco`). `<worker-python>` is
`worker-mujoco/.venv/bin/python` on Linux and `worker-mujoco\.venv\Scripts\python.exe` on
Windows.

```text
# observations (one canonical JSON object each)
<worker-python> -I -m dynamisbench.adapters.mujoco.squat --report
<worker-python> -I -m dynamisbench.adapters.mujoco.squat --stand
<worker-python> -I -m dynamisbench.adapters.mujoco.squat --perturb
<worker-python> -I -m dynamisbench.adapters.mujoco.squat --passive
<worker-python> -I -m dynamisbench.adapters.mujoco.squat --flight
<worker-python> -I -m dynamisbench.adapters.mujoco.squat --squat
<worker-python> -I -m dynamisbench.adapters.mujoco.squat --repetition
<worker-python> -I -m dynamisbench.adapters.mujoco.squat --repetition-timestep

# the repetition as plain files: summary JSON, 100 Hz time-series CSV, qpos CSV, timestep study
uv run python tools/mujoco_squat_repetition.py --output <directory> --timestep-study

# the packaged laboratory dataset (nominal, dt/2 companion, two ablations; checks evaluated):
# --check regenerates it in the worker and compares; --write rewrites it (then pin the digest)
uv run python tools/mujoco_squat_laboratory.py --check
uv run python tools/mujoco_squat_laboratory.py --write

# the packaged asset is exactly the regenerated one (exit 1 otherwise)
uv run python tools/mujoco_squat_model.py --check
# regenerate it after a reviewed change to the authority, then pin its SHA-256 by hand
uv run python tools/mujoco_squat_model.py --write

# focused tests (set DYNAMISBENCH_MUJOCO_PYTHON and DYNAMISBENCH_REQUIRE_MUJOCO=1 as in CI)
uv run pytest tests/execution/mujoco_squat tests/test_simulator_isolation.py tests/laboratory \
  tests/pipeline tests/api/test_runs_api.py

# the study as workspace authority: its pinned digests, and a workspace holding it
uv run python tools/mujoco_squat_authority.py --check
uv run python tools/mujoco_squat_authority.py --workspace <directory>
```

To look at the model, open the asset in MuJoCo's viewer and load keyframe `stand`. The viewer
runs no controller, so with zero excitation the athlete relaxes and collapses, which is the
passive behaviour above.

## One controlled repetition

`--repetition` performs one back squat from the standing keyframe: **standing, descent,
bottom, ascent, return to standing**. The motion is integrated by MuJoCo from actuator torques;
no joint position, velocity or acceleration is ever written.

How the torques are produced (all in [`engine.py`](engine.py), [`movement.py`](movement.py),
[`control.py`](control.py)):

1. **Intent.** One scalar, the knee-flexion *depth*, follows a minimum-jerk profile (Flash &
   Hogan 1985): 5 deg to 120 deg in 1.5 s, a 0.3 s pause, back in 1.2 s
   ([`movement.REPETITION`](movement.py)).
2. **Measured-state phase machine.** Standing ends on the start command. The bottom is entered
   only when the *measured* knee has arrived and its speed has fallen below 3 deg/s, and standing
   again only when every measured sagittal joint is back within 3 deg. A repetition that does
   not get there within 1 s is declared failed.
3. **Synergy.** The depth selects a whole-body posture from the balanced posture family of the
   static squat analysis: feet fixed, hands on the bar, whole-system CoM over the mid-foot, trunk
   parallel to the shank, neutral spine. The family is solved at 60 depths and joined with a C2
   spline, blended from the standing keyframe over the first 40 deg.
4. **Internal model.** The planned posture, velocity and acceleration pass through the model's
   inverse dynamics (`M qacc + c - damping`), solved for minimum neural effort with the feet and
   bar as unknown contact and coupling forces. This is the feedforward torque, and it also
   predicts the ground reaction.
5. **Reflex feedback.** The declared postural stiffness and damping act on the deviation from
   the moving reference. Gains are the standing ones; nothing is retuned for the movement.
6. **Actuation.** Excitations pass through 30 ms activation dynamics and the torque capacities.

### Measured repetition (MuJoCo 3.17.0, Linux x86-64, 1 ms step)

| Quantity | Result |
| --- | --- |
| Phases (commanded, entered on measured state) | descent 1.00 s, bottom 2.50 s, ascent 2.80 s, standing 4.00 s |
| Phases (measured from hip height alone) | descent 1.32-2.41 s, bottom 2.41-2.88 s, ascent 2.88-3.76 s |
| Bottom position | knee 120.1 deg, hip 120.1 deg, ankle 33.5 deg dorsiflexion, trunk 33.6 deg from vertical, lumbar and thoracic within 0.4 deg of neutral, hip 0.455 m above the floor, thigh horizontal |
| Speed | peak knee flexion speed 144 deg/s down, 179 deg/s up; no velocity reversal within a phase |
| Peak extensor moments (per leg) | knee 118 N m (1.58 N m/kg), hip 104 N m (1.39 N m/kg), lumbar 133 N m, ankle 38 N m, all just after the bottom ("out of the hole"); peak activation 0.44, no saturation |
| Ground reaction | 0.76-1.31 x (body + bar) weight; mean over the repetition 1.000; internal-model plan vs simulation 1.0 % of weight RMS; left/right share 0.500 +/- 0.0001 |
| Balance | whole-system CoM within 47-53 mm of the ankle line (over the mid-foot) throughout; CoP >= 64 mm and extrapolated CoM >= 84 mm inside the support polygon |
| Feet | all 10 sole contacts load-bearing (> 5 N) throughout, the lightest point never below 31 N; on each foot the heel carries >= 38.4 % and the forefoot >= 37.7 % of that foot's load; the ten point loads sum to the total ground reaction (error 5e-13 N); friction use <= 31 % of each contact's cone; slip 0.6 mm; penetration <= 1.0 mm; shear <= 3 % of vertical load |
| Tracking | knee within 0.33 deg of its reference (RMS 0.10 deg), every sagittal joint within 0.33 deg |
| Momentum | impulse-momentum residual <= 0.029 N s over the whole repetition |
| Barbell | travel 0.54 m; forward excursion 7 cm at depth, always over the foot; tilt < 0.001 deg; shelf force 161-316 N around its 196 N weight; weld and grip errors < 0.1 mm |
| Work and energy | CoM drop 0.433 m (403 J); descent: actuators -320 J, damping 82 J; ascent: actuators +506 J, damping 102 J; work-energy residual < 0.6 J per phase; peak power 1.0 kW (13 W/kg) |
| Return | joints within 0.05 deg and CoM within 0.4 mm of the start, at rest |
| Timestep 1 ms vs 0.5 ms | identical phase times; knee angle <= 0.02 deg, bar <= 0.8 mm, CoM <= 0.7 mm, vertical GRF <= 0.2 % of weight, peak knee moment 0.05 % apart; impulse-momentum residual halves (0.0293 -> 0.0147 N s, first order); knee tracking error unchanged (0.330 vs 0.328 deg) |
| Determinism | identical trajectory hash in separate processes |

### Synchronized measurement

Every sample is one instant. Before each `mj_step` the state (`qpos`, `qvel`, `act`, `time`)
is snapshotted and the derived quantities of *that* state are read after `mj_forward`:
contact forces, ground reaction, centre of pressure, momentum, torques and energies all
describe time `t`, never a mixture of `t` and `t + dt`. Samples lie on the exact grid
`t = k x 10 ms` from `t = 0` through the last grid instant at or before the end of the run. The
final state always closes the last work interval, but it is a sample only when it falls on the
grid (at 1 ms the run ends at 5.500 s, which is a grid instant; at 0.5 ms it ends at 5.5005 s and
its last sample is 5.500 s). Work and energy are integrated per step interval, and the impulse-momentum residual compares the momentum change of each interval with
the impulse applied during it. The two timestep runs are compared sample by sample by index.
(An earlier draft mixed pre-step kinematics with post-step forces, which overstated the
momentum residual tenfold and the tracking error by half; the physics and its trajectory hash
were unaffected.) A plantar point counts as load-bearing only above 5 N of normal force;
geometric contact alone is reported separately.

The same acceptance bounds the tests apply reject the two defects found while building the
repetition: the earlier 15 ms sole friction time constant (9.4 mm of foot slip) and a controller
without the dynamic internal model (heels lift, the ground reaction departs 10.6 % of weight
from the plan, and the CoM leaves the mid-foot by 18 mm).

### Contact friction

MuJoCo friction is a velocity servo: the tangential reference acceleration is `-b v`, with `b`
set by the contact time constant, so a slip velocity decays with that lag and the drift it leaves
is never restored. No-slip iterations, the friction cone type and the integrator do not change
this. In quiet standing nothing drives it. In a squat the load sweeps continuously over the
soles, and with the 15 ms normal-contact time constant both feet slid 8.4 mm backwards in one
repetition while no contact used more than a quarter of its friction cone. The sole contacts are
therefore explicit pairs with a 2 ms friction time constant (two timesteps, MuJoCo's stability
floor), which leaves normal contact unchanged and reduces the slip to 0.6 mm.

## Known limitations

* **No sensorimotor delay.** Feedback is instantaneous apart from the 30 ms activation
  dynamics. With a 20 ms delay the current gains destabilise the light segments (head,
  forearms); representing how humans tolerate 50-150 ms delays needs muscle-level,
  operating-point-dependent short-range stiffness, not a retuned servo.
* **Torque actuators, not muscles.** Peak torque is constant: no torque-angle or
  torque-velocity relation, no biarticular muscles, no co-contraction model. Capacities are
  representative literature values, not a subject calibration.
* **Postural stiffness is higher than human estimates** (about 3 m g h at the ankle versus
  ~1.2-1.5 for human quiet stance): independent joint servos on a multi-segment chain are
  less efficient than coordinated control.
* **Simplified joints.** Pure-hinge knee, subtalar axis along the foot, rigid wrist and toes,
  no scapula (the shoulder is a humerothoracic joint, hence its 110 deg external-rotation
  range), spine in two 3-axis levels.
* **Contact and coupling compliance is numerical stabilisation**, not calibrated plantar or
  trapezius soft tissue. Fall-impact forces are outside the model's domain.
* **One repetition, one load.** The qualified repetition is one declared plan (parallel depth,
  1.5 s down, 0.3 s pause, 1.2 s up, empty bar). Through the study, depth (90-120 deg) and tempo
  (descent 1-2 s, ascent 0.8-1.6 s) are configurable inside those domains and every such run is
  verified and assessed, but only the nominal plan and the two ablations are qualified by the
  test suite. Other loads, multiple repetitions, fatigue and failed repetitions are not covered.
* **The knee cannot cave in.** With a pure-hinge knee and no tibial rotation, the knee axis
  stays perpendicular to the foot's long axis, so the knee always tracks over the toes; dynamic
  valgus, a real squat fault, cannot occur in this model. Hip abduction ("knees out") is free.
* **The internal model is exact.** The feedforward uses this model's own inverse dynamics; a
  human's internal model is approximate, so real tracking errors are larger.
* **Foot slip is not zero.** MuJoCo friction drifts slightly under changing load; with the 2 ms
  friction time constant one repetition slides 0.6 mm at the production timestep and converges
  to ~1.4 mm as the timestep shrinks (0.5 ms: 1.0 mm, 0.25 ms: 1.2 mm).

## The laboratory dataset and the workbench

`--laboratory` runs four repetitions in the worker — the nominal one, the same at half the
timestep, and the two ablations above (no dynamic internal model; the 15 ms sole friction) —
evaluates the 22 predeclared acceptance criteria of [`criteria.py`](criteria.py) on each, and
returns the compiled model as plain data ([`engine.describe_model`](engine.py)) with 100 Hz
frame columns: body poses, joint kinematics and references, CoM and bar, joint torques,
per-foot ground reaction and centre of pressure, the ten plantar loads and their positions,
balance margins and power. `tools/mujoco_squat_laboratory.py --write` packages it into
`dynamisbench.laboratory` (gzipped, every file pinned by a manifest whose SHA-256 is pinned in
`dataset.py`); the application API publishes it read-only under `/api/v1/laboratory`
(JSON read models; frames as Arrow IPC streams) and the workbench's **Laboratory** route draws
it. The laboratory routes read packaged bytes only: they never import MuJoCo and never run a
simulation (runs of the study go through the run routes and the isolated worker instead).

| Recording | Checks |
| --- | --- |
| nominal, dt 1 ms | 22 of 22 pass |
| dt 0.5 ms companion | 19 pass, 3 not evaluated (the cross-timestep checks belong to the nominal) |
| no dynamic internal model | 13 pass, 6 fail (plan vs GRF 10.6 % W, loaded contacts 6 of 10, lightest point 0 N, heel share 0 %, friction use 63 %, CoM 17.9 mm off the mid-foot), 3 not evaluated |
| 15 ms sole friction | 17 pass, 2 fail (foot slip 9.4 mm, CoM 10.9 mm off the mid-foot), 3 not evaluated |

## Scope in DynamisBench: a RunSpec-executable realization

The squat is executed through the accepted `RunSpec -> preflight -> supervisor -> worker`
boundary, by its own reviewed worker entry point `python -I -m
dynamisbench.adapters.mujoco.squat.worker` (protocol version 1). The fixed-mode entry point above
is unchanged and stays a qualification interface; the reference pendulum adapter, its identity
and the worker protocol are unchanged.

**Authority.** [`case.py`](case.py) defines the benchmark release `db.squat.back-squat` (45
canonical quantities with frames, units and sign conventions; 17 metrics with predeclared
criteria), the scenario `sc.squat.controlled-repetition`, the realization
`rl.mujoco.squat.torque-driven` (configuration, the model asset by digest, and the mapping of
every native column to a canonical quantity), the system under test, one environment per
platform, and the study `st.squat.configuration`. [`pins.py`](pins.py) pins their semantic
digests; `tools/mujoco_squat_authority.py --check` recomputes and compares them, and
`--workspace <dir>` writes them (and the model asset) into a new workspace.

**Configuration.** Six factors, each with the qualified domain the worker admits and nothing
outside it (no value is clipped or snapped):

| Factor | Domain | Nominal |
| --- | --- | --- |
| `f.squat.bottom-knee-flexion` | 90-120 deg (in rad) | 120 deg (parallel) |
| `f.squat.descent-duration` | 1.0-2.0 s | 1.5 s |
| `f.squat.ascent-duration` | 0.8-1.6 s | 1.2 s |
| `f.squat.integration-timestep` | 0.25-1 ms, dividing the 10 ms sample period | 1 ms |
| `f.squat.internal-model-gain` | 0-1 | 1 |
| `f.squat.sole-friction-time-constant` | 2-15 ms | 2 ms |

The nominal configuration reproduces the qualified repetition bit for bit (trajectory
`d3b4edafc090…`); gain 0 and a 15 ms friction time constant reproduce the two ablations.

**Worker.** [`worker.py`](worker.py) refuses a request whose adapter, capabilities, definition
identifiers, versions or semantic digests are not the pinned ones, whose seed or outcomes differ,
whose implementation digest is not the installed one ([`identity.py`](identity.py): the adapter
files, the model asset, the engine version, the CPython series and the locked dependency
closure), or whose configuration leaves the domain. It writes native output into the request's
output directory: `native/samples.parquet` (one row per 10 ms sample, schema in
[`native.py`](native.py)), `native/state.parquet` (raw `qpos`, `qvel`, `act`), `record.json`
(plan, events, checks, summary, work, extrema, trajectory digest), `model.json` (the compiled
model as run) and `index.json` (every file's digest). The supervisor verifies and harvests them
before the scratch directory is removed.

**Pipeline.** `dynamisbench.pipeline` normalizes the native samples to the benchmark's canonical
quantities, verifies them independently (`pipeline/squat.py`: exact time grid; canonical round
trip; contact closure; centre of pressure recomputed from the plantar loads; body orientation
and position re-derived by forward kinematics from joint angles; joint velocity against the
angle's finite difference; impulse-momentum; the energy ledger; sampled extrema), assesses the
17 metrics and seals both bundles (see the repository README). A run is shown only after its
seals and provenance chain verify on read.

**Deviation recorded.** The worker environment admits the CPython 3.12 series rather than one
exact patch version (the locked reference pins 3.12.13, which was not obtainable on the
qualification host; this host runs 3.12.3). The patch version is part of the implementation
digest, so a run records exactly which interpreter executed it.

## The anatomical figure

The workbench draws the athlete either with the model's own segment geometry (*Scientific*) or
as an **anatomical figure** (*Anatomical*): a closed, skinned surface generated by
`tools/mujoco_squat_figure.py` from the published model — its 16 bodies, parents and frames, its
landmarks (joint centres, sole contact points, segment geoms) and its segment masses, with each
segment's girth fitted so that its share of the enclosed volume equals its mass over Dempster's
segment density (all ten segments within 2 % of their mass; total enclosed volume 74.2 L
including the shoes). Each fist is shaped around the bar axis where the hand weld holds it (read
from the nominal recording), and the shoe's outsole lies on the plane of the five sole contact
spheres. The surface is the zero level set of smooth unions of analytic primitives, extracted by
surface nets as a closed 2-manifold (every edge has two faces), projected onto the exact
surface, refined at the face and hands, and bound to the bodies with skin weights restricted to
kinematic neighbours. The workbench deforms it with the *recorded* body poses by dual-quaternion
skinning; nothing about it is simulated, and it has no mass, inertia or contact. It is pinned by
digest (`dynamisbench/laboratory/figure.py`) and drawn only for the model whose skeleton it
carries.

```text
uv run python tools/mujoco_squat_figure.py --check   # regenerate (about 3 min) and compare
uv run python tools/mujoco_squat_figure.py --write   # then pin FIGURE_SHA256 by hand
```
