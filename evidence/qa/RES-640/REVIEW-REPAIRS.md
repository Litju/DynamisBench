# RES-640 independent review repairs

Baseline: 90e6cd61b12fc90210b950c759fcf63ac41daff0, unchanged PR #29 branch.
Two untracked RES-595 owner documents were preserved. Remote main remained
707f0dd45bccf71b1f07eafb61d7fc7eaf328f66. Main is protected by active ruleset
24680388 (classic protection endpoint returns 404): eight ADR-025 contexts,
strict status checks, resolved review threads, no deletion or force pushes.

## Review dispositions

- P1: Historical mechanism energy fields were default zeros with energy disabled.
  They are preserved for historical integrity and withdrawn as energy evidence.
  The replacement static energy qualification uses an isolated diagnostic model.
- P1: Removed the permanent stability diagnostic from quality.yml. Its exit status
  could fail the required Python job despite the non-gating description. On-demand
  tool, historical receipts, regression tests and eight required jobs remain.
  Workflow authority tests: 12 passed before the CI-only commit.
- P2: Removed lower bounds requiring last-bit instability. Upper bounds and
  constructed physical changes remain. Checker controls cover pelvis tilt/height,
  joint angles, three bar position axes, relative bar orientation and activations.
  Added finite-value refusal and quaternion validity checks, including zero-angle
  rotations. Quaternion norm bound 1e-10 follows ten-significant-digit asset
  serialization (four component absolute errors <=5e-11, Euclidean norm <=1e-10).
  This input validity budget does not change KEYFRAME_TOLERANCE=1e-6.
- P2: squat/pins.py ADAPTER_SOURCE_FILES has no current consumer beyond its export.
  Current identity.py and receipt comparison consume the separate pendulum inventory.
  The squat identity/native/worker integration is held for M2B in RES-595 source-map.
  Required integration change: add squat/reference.py to the sorted implementation
  manifest before activating the squat identity algorithm; include every transitive
  numerical source and packaged model, reject missing paths, independently recompute
  source hashes and implementation digest, and validate mutation sensitivity for
  reference.py before sealing evidence. Do not fabricate the missing modules or
  regenerate accepted pendulum/worker identities. Existing source-closure assertions
  must not be interpreted as a completed squat worker implementation.

## Scientific contract proposed for explicit owner adoption

Adopt pelvis heading zero (pelvis forward-axis projection along world +x) as the
representative of the generated standing state. Compare packaged and regenerated
qpos after a common rigid rotation of pelvis and barbell about the world vertical
through the pelvis origin, preserving relative poses, heights, joint angles and
activation. Retain horizontal pelvis coordinates and the 1e-6 component tolerance.
**Acceptance equivalence changes: comparison is modulo whole-system heading.**
The scalar tolerance remaining unchanged does not preserve the old acceptance set.

Applicability is the declared vertical gravity, infinite horizontal floor, isotropic
paired tangential friction, internal relative constraints and joint-space controller.
Mathematical symmetry maps trajectories by rotation; it does not assert bitwise
numerical equivariance or unchanged world-coordinate trajectory values. Finite
solver/contact anisotropy and floating-point residuals require numerical controls.
The projection preserves relative bar motion and contact geometry under that common
transformation; it does not excuse bar-only rotations, tilt, joint or activation changes.

This is coordinate selection and numerical verification, not empirical biomechanical
validation. No model bytes, MODEL_SHA256, controller, benchmark inputs, reference
values or tolerance were changed. Packaged-asset re-expression and dataset regeneration
are separate owner-gated work: their hashes/trajectories would change. No claim of a
complete accepted future squat source closure is made. Owner must explicitly adopt
this statement before it becomes accepted scientific authority. Keep PR draft;
RES-640 and RES-622 cannot be Done until authorized merge and protected-main gates.

## Independent verification record

A separate read-only review agent independently reproduced the disabled-energy
behavior, checked declared symmetry conditions, audited the revised diff, verified
all 49 recorded source/native hashes, and ran the 42 focused reference/energy tests.
Final verdict: no remaining blocking mathematical/code findings in repair scope.
This review is independent of the implementing agents; it is not owner acceptance.
Remaining limits: shared MuJoCo kinematics, static gravitational potential only,
conditional engineering arithmetic allowance rather than formal libm proof.

Local revised checks: 54 focused tests (reference, energy, workflow authority),
Ruff and formatting passed; both application and worker Pyright configurations
reported zero errors/warnings. JUnit suite properties are consumed locally but not uploaded. The energy test now
emits its complete receipt directly into the retained job log, with no new CI step
or artifact. The earlier artifact-retention claim is withdrawn.
Fresh Windows default/Haswell regeneration reproduces the historical mechanism:
Haswell pre-projection delta 3.8292216124695965e-06; canonical delta
1.7299170830795712e-08 (default 1.968016969139139e-09). No retry was used.
Full local suite and exact-head hosted qualification remain separate gates.

Final local full-suite observation: Windows CPython 3.12.13, pytest 9.1.1 /
Hypothesis 6.168.3: 2761 passed, 7 skipped in 516.63s. This invocation collected before
the eight final refusal cases were added; those cases and final JUnit receipt
recording were subsequently verified in focused checks (54 total across reference,
energy and workflow). No failed test was retried to claim numerical repair.
Skips are existing optional/platform cases (symlink/FIFO, optional pipeline module,
optional figure regeneration), not RES-640 energy/refusal checks. New hosted
exact-head qualification remains pending and is linked on PR #29/Linear RES-640.


Hosted qualification at 5fe849220784d5630402fc45cb638d02ae8bd6e4 passed all eight
required Windows/Linux checks plus MuJoCo receipt comparison in first-attempt run
43193480918. Artifact inspection exposed that pytest.xml is consumed but not
uploaded; its energy suite property was not retained. Corrected the existing
energy regression to emit the complete receipt into the job log through disabled
pytest capture. Focused test passes and output retention was checked. This is a
retention repair, not a numerical repair; new exact-head qualification is required.
