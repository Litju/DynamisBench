# RES-640 â€” Windows squat keyframe regeneration drift: root cause, repair and receipts

Issue: [RES-640](https://linear.app/alignerr-cmj/issue/RES-640/db-qa-03-root-cause-windows-squat-keyframe-regeneration-drift-on).
Branch and draft PR: `codex/res-640-keyframe-diagnostics`, [PR #29](https://github.com/Litju/DynamisBench/pull/29).
Protected-main baseline: `707f0dd45bccf71b1f07eafb61d7fc7eaf328f66` (postmerge run
[43023293371](https://github.com/Litju/DynamisBench/actions/runs/43023293371), Windows job failed:
`the keyframe qpos differs from the regenerated one by 3.829e-06`).

## Disposition

**RES640_REVIEW_FINDINGS_OPEN - MERGE_BLOCKED.**

[Review repairs and owner decision](REVIEW-REPAIRS.md) supersede the historical
qualification below. Energy computation was disabled in the old mechanism receipt;
its zero values were uncomputed defaults. Corrected diagnostic energy qualification:
baseline 1030.3403578290963 J; +0.125 m complete-system lift expected 116.45396875 J,
residual 7.11e-14 J. Eight yaw angles have maximum MuJoCo residual 2.28e-13 J within
predeclared conditional binary64 arithmetic budget 8.05e-9 J. See
[method](analysis/ENERGY_METHOD.md) and [receipt](raw/energy-windows-local.json).
This is gravitational potential energy; constraint energy is excluded. No exact
floating-point-zero claim is made. Owner adoption changes acceptance equivalence
(modulo heading), although KEYFRAME_TOLERANCE remains 1e-6. New exact-head hosted
qualification remains required; old green runs do not qualify the revised changes.


The failing comparison was not comparing the model. The standing reference contains one
coordinate that the model cannot determine â€” the athlete's heading about the world vertical â€”
and the contact settle sampled it from last-bit rounding. A controlled change of the
BLAS/LAPACK kernel dispatch on one Windows host reproduces the protected-main failure exactly
(`3.829e-06`), and the repaired comparison passes on every dispatch with a 58x margin while
the gauge-invariant physical state agrees to `4.9e-10`. The repair does not change the model,
the packaged asset, the tolerance or any physical quantity: it declares the representative of
an exact symmetry that the generator must write, and compares the reference in it.

The reference *definition* wording (heading is a gauge; the declared representative is zero
pelvis heading) and the follow-up asset re-expression are **owner-review items**; they are not
merged and RES-640 is not Done.

## 1. What the failing check compares

`tools/mujoco_squat_model.py --check` regenerates the standing keyframe in the isolated worker
and compares it elementwise with the packaged `stand` keyframe at `1e-6`. The keyframe is the
end state of: posture solve â†’ inverse-dynamics contact settle â†’ minimum-effort tonic torques â†’
30 s forward-dynamics relaxation.

The failure was in `qpos` entries 6 and 42 â€” the `z` quaternion components of the pelvis and
barbell free joints. Those two are not independent: the bar is welded to the shelf, so it
carries the pelvis's heading.

## 2. The mechanism

### 2.1 The model has an exact world-frame gauge

The floor is an infinite plane, gravity is vertical, every actuator is an internal joint
torque, and the sole contacts are friction contacts on that plane. Rotating the **entire**
system (athlete and barbell) about the world vertical axis is therefore a symmetry: it changes
no potential energy, no joint angle, no contact load, no trajectory. Translation in the floor
plane is the same kind of symmetry. The model's placement in the plane â€” two translations and
a heading â€” is a *gauge*, not physical content.

Measured on the packaged model (`raw/mechanism-windows-local.json`):

| whole-system rotation | potential-energy change |
| --- | --- |
| 1e-3 rad | withdrawn: energy disabled |
| 1e-1 rad | withdrawn: energy disabled |
| 1.0 rad | withdrawn: energy disabled |

and a 1 s closed-loop standing run started from the keyframe rotated by 1e-2 rad, un-rotated
afterwards, reproduces the unrotated run:

| quantity | difference |
| --- | --- |
| gauge-invariant physical state (joints, pelvis height/tilt, bar pose in pelvis) | `1.89e-15` |
| mechanical energy | withdrawn: energy disabled |
| heading kept minus heading injected | `-2.60e-17` rad |

### 2.2 The contact settle cannot determine the heading

The settle adjusts only the two free poses so that MuJoCo's inverse dynamics needs no force on
any unactuated coordinate. Its 12x12 finite-difference Jacobian at the settled state
(`raw/mechanism-windows-local.json`, dofs root `0-5` then bar `35-40`):

```
singular values: 1.138e7 1.136e7 1.123e7 1.051e6 4.00e5 3.82e5
                 3.91e4 1.66e4 1.30e3 | 1.71e-7 2.58e-10 2.45e-11
condition number: 4.64e17          gap above the third smallest: 1.32e-10
```

The three smallest directions are exactly the rigid placements. Their stiffness, measured as
the change of the inverse-dynamics residual per unit whole-system twist:

| rigid placement | stiffness (N or NÂ·m per unit) |
| --- | --- |
| translation x | 0.0034 |
| translation y | 0.0023 |
| **heading (yaw)** | **0.0785** |
| roll | 9.40e4 |
| pitch | 1.50e5 |
| translation z | 2.38e6 |

A whole-system heading is ~2e6 times softer than the softest physical rotation and ~3e7 times
softer than vertical translation; in the conservative dynamics it is *exactly* free. The
min-norm least-squares step therefore injects an arbitrary placement (the solve keeps the
components below `rcond = 1e-12` of the largest singular value, which truncates exactly these
three and nothing else).

### 2.3 Localisation: the settle injects it, the relaxation preserves it

| stage | pelvis heading (rad) |
| --- | --- |
| after posture solve | `4.96e-18` |
| after contact settle | `1.0216e-06` |
| after 30 s relaxation | `6.961e-07` |
| declared representative (after the repair) | `-6.87e-23` |

The posture solve is exactly symmetric (the hard foot-orientation rows and the symmetric
right-hand side give a zero heading to rounding). The settle injects ~1e-6 rad. The relaxation
does not amplify or remove it: the heading is neutral, so it is carried through the 30 s. This
is why the discrepancy "appears before forward-dynamics relaxation" â€” the existing RES-640
evidence was right about the stage, and the settle is the stage.

### 2.4 It is a rounding sample, not a model property

40 independent **one-ulp** perturbations of the posture solution, propagated through the
settle (`raw/mechanism-windows-local.json`):

| quantity | value |
| --- | --- |
| settle heading, min | `-5.61e-08` rad |
| settle heading, max | `1.355e-06` rad |
| settle heading, spread | `1.411e-06` rad |
| canonical `qpos` spread (translation gauge only) | `5.78e-09` |
| **physical-state spread** | **`1.44e-15`** |

A one-ulp input change moves the output heading by up to 9e-7 rad. Nothing physical moves at
all. So a pinned heading is not reproducible *in principle*: it is an arbitrary sample whose
scale is set by floating-point arithmetic, not by the model.

## 3. Accounting for the protected-main `3.829e-06`

### 3.1 The observed values

`qpos[6]` is the pelvis quaternion's `z` component; for this near-identity pelvis, the heading is
`â‰ˆ 2Â·qpos[6]`.

| generation | `qpos[6]` | heading (rad) |
| --- | --- | --- |
| packaged asset (Linux, RES-595) | `3.193249316e-07` | `6.383545323e-07` |
| hosted Linux, 43035751307 (pre-repair) | `-9.985680354e-08` | `-1.997e-07` |
| hosted Windows, 43035751307 (pre-repair) | `3.481756154e-07` | `6.961e-07` |
| local Windows, default dispatch | `3.481756154e-07` | `6.960955244e-07` |
| hosted Windows, 43049377562 (AMD Zen 5) | â€” | `6.960955244e-07` |
| hosted Linux, 43049377562 | â€” | `6.383545055e-07` |
| local Windows, `OPENBLAS_CORETYPE=Haswell` | `-3.509896681e-06` | `-7.025347869e-06` |
| local Windows, `OPENBLAS_CORETYPE=Nehalem` | `1.443262052e-06` | `2.887772426e-06` |
| local Windows, `OPENBLAS_CORETYPE=Sandybridge` | `1.192858e-08` | `2.3140e-08` |

Two facts matter here.

* The three independent Windows hosts â€” an Intel Tiger Lake laptop, an earlier hosted runner of
  unknown CPU, and a hosted **AMD Zen 5** runner â€” land on the same pre-projection heading
  (`6.96095524e-07`) to better than 1e-9. Within a compatible arithmetic path the sample is
  reproducible; the platform label is a proxy, not a cause.
* The hosted Linux runners are not mutually reproducible either: one lands at `-1.997e-07`, the
  other at `6.383545055e-07` â€” and the second differs from the *packaged* heading by only
  `2.7e-14` rad. The packaged reference and a later Linux generation differ by `4.19e-07` in
  `qpos[6]` (42 % of the tolerance) with no Windows involved.

Windows-minus-Linux for the pre-repair pair was `4.480e-07` in `qpos[6]`, i.e. `8.96e-07` rad â€”
the `~8.9668e-7 rad`, almost entirely yaw, that the earlier RES-640 evidence reported.

### 3.2 The controlled counterexample

`tools/mujoco_squat_reference_stability.py` regenerates the reference under several
`OPENBLAS_CORETYPE` values. Same machine, same CPython 3.12.13, same NumPy 2.5.4
(scipy-openblas 0.3.34 with `DYNAMIC_ARCH`), same MuJoCo 3.17.0, same model bytes, same code.
Only the BLAS/LAPACK kernel an `DYNAMIC_ARCH` OpenBLAS selects changes â€” which is exactly what
differs between two hosted runners of the same image on different physical CPUs.

Receipt: `raw/reference-stability-windows-local.json` (4 dispatches x 2 runs; the two runs of
every dispatch are identical, so within-host repeatability is bitwise).

| dispatch | pre-projection heading | pre-projection max `Î”qpos` vs packaged | pre-RES-640 criterion | repaired criterion | physical state |
| --- | --- | --- | --- | --- | --- |
| default (Skylake-X) | `6.961e-07` | `2.885e-08` | pass | `1.97e-09` pass | `4.87e-10` |
| `Haswell` | `-7.025e-06` | **`3.829222e-06`** | **FAIL** | `1.73e-08` pass | `4.87e-10` |
| `Nehalem` | `2.888e-06` | `1.123937e-06` | **FAIL** | `8.09e-09` pass | `4.87e-10` |
| `Sandybridge` | `2.314e-08` | `3.074e-07` | pass | `1.62e-09` pass | `4.87e-10` |

The pre-projection comparison is the state the old generator would have written, reconstructed
by rotating the canonical state back by the heading the generator reports
(`_pre_projection_difference`). Its Haswell value is `3.8292216124696e-06` â€” the protected-main
failure string, digit for digit.

This counterexample is not synthetic. On a later hosted run (Â§5.3) a **windows-2025 runner with
an AMD Family 25 CPU** produced pre-projection heading `-7.025347868663774e-06` and
pre-projection difference `3.8292216124695965e-06`: the Haswell arithmetic path, live, on a
genuine hosted runner, with the repaired comparison passing at `1.7299170830795712e-08`.

So the answer to "why could `3.829e-06` occur" is: the heading is a ~1e-5 rad range random
sample of an exactly free direction; the quaternion component is half the heading; the 1e-6
absolute tolerance is a ~2e-6 rad window; and two of the four arithmetic paths tested here
land outside it. The exact kernel of the failed runner was never recorded (the diagnostic
probe did not exist in the required workflow then), so that *sample* is not attributable to a
named kernel. The *mechanism*, the *magnitude* and the *variability* are established, one
occurrence of the exact failure magnitude has since been observed live on a hosted runner, and
the repair does not depend on which kernel it was.

## 4. The correction

`squat/reference.py` declares the representative and projects onto it; `engine.standing_reference`
applies it to the generated reference; `tools/mujoco_squat_model.check` applies it to **both**
the packaged and the regenerated `qpos` before the elementwise comparison.

* **Representative.** The whole system is rotated rigidly about the vertical axis through the
  pelvis until the pelvis heading is exactly zero. This is the same heading anchor the posture
  solver already declares (its pelvis-yaw soft row targets zero), so the reference is now
  consistent with its own declared stance instead of contradicting it by 1e-6 rad.
* **Why it is not a model change.** The rotation is an exact symmetry (Â§2.1). It changes no
  joint angle, energy, contact load, activation or trajectory; it changes only the world
  placement, and by â‰¤3.2e-7 in the quaternion components and â‰¤2e-8 m in positions.
* **Scalar tolerance unchanged; acceptance equivalence changes.** `KEYFRAME_TOLERANCE` remains `1e-6`, still applied
  elementwise to all 43 `qpos` entries and all 29 `act` entries. The repaired comparison is
  strictly *more* meaningful, not weaker: every physical coordinate is compared exactly as
  before, and the only coordinate that is no longer compared *as a number* is the one that is
  not a number of the model. Negative controls in
  `tests/execution/mujoco_squat/test_squat_reference_frame.py` perturb a pelvis height, a hinge
  angle, a bar coordinate and the pelvis pitch by `2e-6` and all four are still rejected.
* **Structural guard.** `check` also refuses a regenerated reference whose heading is not zero
  (`CANONICAL_HEADING_TOLERANCE = 1e-12` rad; measured `7e-23`), so a generator that stopped
  projecting cannot pass silently.
* **Diagnostics.** `--keyframe` additionally reports the heading the relaxation landed on
  before projection, and the probe reports raw, canonical and gauge-invariant comparisons side
  by side.

### Why not the alternatives

| candidate | verdict |
| --- | --- |
| raise the tolerance | rejected: the quantity is a random sample; no finite tolerance is a scientific bound |
| regenerate and repin the MJCF | rejected: matches one draw, leaves the gauge unaddressed, invalidates every receipt |
| retries / xfail / skip | rejected: violates the QA contract and hides the mechanism |
| better conditioning of the settle only | insufficient: the heading is free, so removing the settle's noise still leaves the relaxation's own 3e-7 sample, and nothing bounds it |
| explicit heading stiffness in the controller | rejected: adds a non-physical external anchor and changes the biomechanics |
| gauge-invariant acceptance criterion (compare physical state only) | not chosen: changes the acceptance criterion and discards a useful elementwise check; the projection retains component comparison but changes acceptance equivalence |

The projection is the smallest change that removes the mechanism rather than its symptom.

## 5. Verification

### 5.1 Analytical / numerical

| check | result | receipt |
| --- | --- | --- |
| potential energy invariant under 1 rad whole-body rotation | withdrawn: energy disabled; see new energy controls | `raw/energy-windows-local.json` |
| 1 s closed loop invariant under 1e-2 rad rotation | `1.89e-15` physical | same |
| rigid-mode stiffness: x / y / yaw vs roll / pitch / z | `0.003 / 0.002 / 0.079` vs `9.4e4 / 1.5e5 / 2.4e6` | same |
| settle Jacobian condition number | `4.64e17`, 10-order gap above the 3 null directions | same |
| 40 one-ulp trials: heading spread vs physical spread | `1.41e-06` rad vs `1.44e-15` | same |
| packaged vs regenerated, repaired comparison | raw `3.19e-07`, canonical `1.97e-09`, physical `4.87e-10` | `raw/keyframe-probe-windows-local.json` |
| four arithmetic paths, repaired comparison | worst canonical `1.73e-08`, worst physical `4.87e-10`, all pass | `raw/reference-stability-windows-local.json` |
| live hosted run of the pre-repair failure condition | Windows: pre-repair `3.829e-06` **FAIL**, repaired `1.73e-08` pass, physical `4.87e-10` | `raw/hosted-b20687e-windows.json` |
| negative control: four `2e-6` physical perturbations | all rejected at `1e-6` | `test_squat_reference_frame.py` |
| packaged asset re-expressed in the canonical frame (impact study) | 22/57 diagnostics bitwise unchanged; largest change in the rest is `6.4e-06` deg on the foot-vs-world toe-out check, then GRF `3.4e-11` N; trajectory hash changes | `raw/canonical-asset-impact-windows-local.json` |

### 5.2 Local suite

`python -m pytest` on Windows 11, CPython 3.12.13, MuJoCo 3.17.0: see Â§6 for the exact-head
result. The 93 tests of `tests/execution/mujoco_squat` pass, including the existing
`test_the_packaged_asset_is_the_regenerated_one` (which now exercises the repaired comparison)
and the new `test_squat_reference_frame.py`.

### 5.3 Hosted Windows/Linux

The repaired code passed the full required workflow twice, on two independent hosted runner
pairs:

| run | code | result |
| --- | --- | --- |
| [43049377562](https://github.com/Litju/DynamisBench/actions/runs/43049377562) | `3b6dfdf` | all eight gates pass on `windows-2025` and `ubuntu-24.04`; `mujoco-receipt-comparison` pass (after one infrastructure re-run, Â§6) |
| [43064795808](https://github.com/Litju/DynamisBench/actions/runs/43064795808) | `b20687e` | all eight gates pass, first attempt, no re-run; `mujoco-receipt-comparison` pass |

Both hosted `python` jobs report **2740 passed, 5 skipped** on each platform and run the
repaired `test_the_packaged_asset_is_the_regenerated_one` together with all of
`test_squat_reference_frame.py`. They also print the standing-reference stability receipt
(`raw/hosted-{3b6dfdf,b20687e}-{windows,linux}.json`, extracted verbatim from the job logs):

| run | host | pre-projection heading | pre-projection `Î”qpos` | pre-RES-640 criterion | canonical `Î”qpos` | physical difference |
| --- | --- | --- | --- | --- | --- | --- |
| 43049377562 | windows-2025, AMD Family 25 Model 17 | `6.960955244e-07` | `2.885e-08` | pass | `1.968e-09` | `4.868e-10` |
| 43049377562 | ubuntu-24.04, azure `7.0.0-1017` | `6.383545055e-07` | `4.868e-10` | pass | `4.868e-10` | `4.868e-10` |
| 43064795808 | windows-2025, **AMD Family 25 Model 1** | **`-7.025347869e-06`** | **`3.829221612e-06`** | **FAIL** | `1.730e-08` | `4.868e-10` |
| 43064795808 | ubuntu-24.04, azure `7.0.0-1017` | `6.383545055e-07` | `4.868e-10` | pass | `4.868e-10` | `4.868e-10` |

The third row is the whole issue in one line: a genuine hosted Windows runner regenerated the
standing reference at the same heading that broke protected main, the **pre-repair criterion
would have failed it with `3.829e-06`**, and the repaired criterion passed it at `1.73e-08`
while the gauge-invariant physical state was identical to every other host at `4.87e-10`. The
same run's Linux job passed by both criteria. The value matches the local `Haswell` replay to
every recorded digit, which is what makes that replay a faithful model of the mechanism rather
than a synthetic construction.

Across the two hosted platforms the headings differ by `5.77e-08` rad on one pair and by
`7.66e-06` rad on the other â€” the gauge â€” while the physical states agree to `4.868e-10`,
**2054 times inside** the unchanged `1e-6` tolerance, in every pair.

The `frontend (linux-x64)` and `desktop (linux-x64)` jobs failed on the first run only, before
running any test: `pnpm exec playwright install --with-deps chromium` and the Tauri
`apt-get install` could not resolve `azure.archive.ubuntu.com`
(`E: Failed to fetch ... Temporary failure resolving 'azure.archive.ubuntu.com'`, exit code
100). No frontend, desktop or Tauri file is touched by this branch. They were re-run on the
same SHA and passed; the second run needed no re-run at all.

## 6. Exact-head qualification

Two independent full runs of the repaired code:

* `3b6dfdfe4e1cb9990ed36840191091746a8344ae`, run
  [43049377562](https://github.com/Litju/DynamisBench/actions/runs/43049377562): all eight
  required ADR-025 gates plus `mujoco-receipt-comparison` pass on `windows-2025` and
  `ubuntu-24.04`.
* `b20687e2292b0ffff5d9c308bb6934647832bd31`, run
  [43064795808](https://github.com/Litju/DynamisBench/actions/runs/43064795808): the same nine
  jobs pass on the first attempt, and its Windows `python` job is the run in which the
  pre-repair criterion's `3.829e-06` failure condition occurred live (Â§5.3).

The first attempt at `3b6dfdf` failed only the two Linux jobs, both in their
*dependency-installation* step, both with the same hosted-runner network outage â€”
`E: Failed to fetch ... Temporary failure resolving 'azure.archive.ubuntu.com'`, exit code 100 â€”
before any repository test or build ran. They were re-run on the same SHA and passed. That is an
infrastructure incident, recorded here rather than treated as a code result: no scientific
step, threshold or test was skipped, relaxed, or retried around a numerical failure. (The
protected-main failure this issue diagnoses was a numerical failure and is *not* treated this
way; it is repaired, not retried.)

The last two commits on this branch (`b20687e` and its successor) touch only
`evidence/qa/RES-640/`; every file that participates in the model, the generator, the check,
the tests or the workflow is byte-identical to `3b6dfdf`, which is qualified above.

## 7. Residual uncertainty

1. **The failed runner's arithmetic path is not recorded.** The mechanism, magnitude and
   variability are demonstrated with a controlled kernel change; the specific sample is not
   attributable. This does not affect the repair, which removes the free coordinate rather than
   the sample.
2. **The horizontal translation is the same kind of gauge and is not canonicalised.** It is
   bounded much more tightly than the heading (`5.8e-09` m in x, `4.7e-08` m in y under one-ulp
   perturbation; `1.9e-08` across kernels), and the declared stance anchors it explicitly in
   the posture solve, so it is not an ambiguity in practice. Removing it too would require a
   stance-anchored projection that moves every world-frame coordinate of the packaged
   reference by ~1.6 mm and changes the pinned laboratory dataset â€” an owner decision, and not
   needed for `3.829e-06`.
3. **The packaged asset still carries a `6.38e-07` rad heading.** It is physically irrelevant
   and the check projects it; the byte identity, `MODEL_SHA256`, implementation digest and
   laboratory dataset are untouched. Re-expressing it is the follow-up proposal below.
4. **`keyframe.foot_orientation_error_deg` is a world-frame diagnostic** (feet against the
   world toe-out), so it moves by `6.4e-06` deg when the reference is rotated. Its threshold is
   1 deg. It is not part of the keyframe comparison.

## 8. Owner-review items (not merged, RES-640 not Done)

1. **Reference-definition clarification.** Record in the authority that the standing
   reference's heading is a gauge of the model's exact SO(2) symmetry, that the declared
   representative is zero pelvis heading, and that the keyframe comparison is made in that
   representative. This changes acceptance equivalence and requires explicit owner adoption.
2. **Asset re-expression (separate change).** `--write` now emits the canonical representative,
   so the next reviewed regeneration would store a heading-free keyframe. That changes
   `MODEL_SHA256`, the worker implementation digest, the authority pins, the laboratory
   dataset's trajectory hash and its world-frame columns. Â§5.1 quantifies the physical impact
   (none beyond world-frame coordinates); the dataset regeneration is the real cost and needs
   its own review.
3. **Temporary CI probe removed.** The branch-only `RES-640` step is deleted from
   `quality.yml`. The permanent mechanism is `tools/mujoco_squat_reference_stability.py`
   (on demand, read-only) plus projection tests in the required suite. Both temporary and
   permanent additional diagnostic CI steps are removed; the eight
   ADR-025 gates are unchanged.

## 9. Reproduce

From `python/`, with `uv sync --frozen --project worker-mujoco` done:

```text
# the production check (now in the declared representative)
uv run python tools/mujoco_squat_model.py --check

# the gauge-invariant receipt: raw / canonical / physical under several BLAS dispatches
uv run python -m tools.mujoco_squat_reference_stability --output receipt.json

# the read-only probe (raw and canonical comparisons per run)
uv run python -m tools.mujoco_squat_keyframe_probe --runs 3

# the mechanism and impact receipts (worker interpreter, PYTHONPATH=src)
PYTHONPATH=src worker-mujoco/.venv/bin/python ../evidence/qa/RES-640/analysis/mechanism.py
PYTHONPATH=src worker-mujoco/.venv/bin/python ../evidence/qa/RES-640/analysis/canonical_asset_impact.py

# the affected tests
uv run pytest tests/execution/mujoco_squat/test_squat_reference_frame.py \
              tests/execution/mujoco_squat/test_keyframe_probe.py \
              tests/execution/mujoco_squat/test_keyframe_metrics.py \
              tests/execution/mujoco_squat/test_squat_dynamics.py
```

## 10. Receipts

| file | content | source |
| --- | --- | --- |
| `raw/mechanism-windows-local.json` | stage headings, settle spectrum and rigid-mode stiffness, invalid disabled-energy fields (withdrawn), 40-trial one-ulp sweep, closed-loop invariance | Windows 11, Intel Family 6 Model 140, CPython 3.12.13, NumPy 2.5.4, MuJoCo 3.17.0 |
| `raw/reference-stability-windows-local.json` | four BLAS dispatches x two runs, raw / pre-projection / canonical / physical comparisons | same host |
| `raw/keyframe-probe-windows-local.json` | one regeneration, probe schema `dynamisbench.qa.squat-keyframe-probe/2` | same host |
| `raw/canonical-asset-impact-windows-local.json` | packaged vs canonicalised asset: 57 diagnostics, trajectory hash, digests | same host |
| `raw/hosted-run-43035751307-windows.json`, `raw/hosted-run-43035751307-linux.json` | the pre-repair hosted probe receipts extracted verbatim from the job logs | `windows-2025`, `ubuntu-24.04` |
| `raw/hosted-3b6dfdf-windows.json`, `raw/hosted-3b6dfdf-linux.json` | the repaired standing-reference stability receipt on the first qualified code, extracted verbatim from run 43049377562 | `windows-2025` (AMD Family 25 Model 17), `ubuntu-24.04` |
| `raw/hosted-b20687e-windows.json`, `raw/hosted-b20687e-linux.json` | the same receipt on the second qualified code, extracted verbatim from run 43064795808; the Windows row is the live `3.829221612e-06` pre-repair failure | `windows-2025` (AMD Family 25 Model 1), `ubuntu-24.04` |

Digests of every file are in `SHA256SUMS`.
