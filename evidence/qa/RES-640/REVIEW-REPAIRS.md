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
