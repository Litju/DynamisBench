# RES-595 source transfer and qualification record

**State:** `BLOCKED_AUTHORITY` for RunSpec worker admission and native evidence. The fixed model, mechanics, qualification tests, and fixed-mode tools are transferred; the original RunSpec worker is held at the RES-555 boundary. This record does not mark RES-595 complete.

## Source authority and reconstruction limits

The source was reconstructed from Turn 4 plus the Turn 5 changed-files overlay:

- Turn 4 archive SHA-256: `b25c64b6396ce39b9801e202d15fb36a23c06bf89affe027d541af8ec63a0a9b`
- Turn 5 delta ZIP SHA-256: `7f1f8a5433cc2249ca0dd2567c15ac8a519c6965b8e7d0d9035e33bd9529455d`
- The recovery report identifies its result as `RECOVERED_SOURCE_CANDIDATE; EXACT_ORIGINAL_WORKSPACE_NOT_PROVABLE`: 594 source files and 278 scientific output files were recovered; 43 screenshots are unavailable; unknown ignored files or unreported deletions cannot be ruled out.
- The map covers all 35 M2-adjacent Turn 4/Turn 5 squat package, test, tool, pipeline, and MuJoCo worker type-stub paths found in the original archives. It validates each effective Turn 5 byte sequence against the recovered candidate. Each transfer is mapped to its official path and SHA-256 in [source-map.csv](source-map.csv).

Commit `2fce40eac7705c775b8fa2a4c7ff311393f518bd` transfers the 24 original model, tests, and tools. A follow-on commit transfers the original MuJoCo worker type stub. In the final map, 24 of the 25 transferred paths are byte-identical to the effective Turn 5 source; the README carries one compatibility note identifying the source RunSpec/native pipeline as not yet integrated. Ten paths are held with reasons in the source map: the worker/native/identity seam, the Laboratory dataset and visualization tools, and the M3 squat pipeline, its two tests, and qualification tool.

The Turn 4 and Turn 5 archive hashes match the values in RES-591. This validates the targeted squat files against those inputs; it does not elevate the recovery candidate to a complete image of the original VM.

## Transferred behavior and checks

The transferred source preserves the authored 75 kg, 1.75 m synthetic athlete, 20 kg barbell, 29 torque actuators, actual MuJoCo forward dynamics, the closed-loop standing/descent/bottom/ascent/standing repetition, contacts, ground reactions, bar coupling, work/energy accounting, and diagnostics. No physics source or expected scientific threshold was rewritten.

- Model SHA-256: `c91b2fa2ca1e04f920f4685bc23be2a99a64ad697dcd6a40cf5699dc5761a947`; source and integrated asset hashes match.
- Model settings: MuJoCo `3.17.0`; `implicitfast`; Newton solver; 100 iterations; tolerance `1e-10`; 10 no-slip iterations; nominal step `0.001 s`; float64.
- `mujoco_squat_model.py --check`: passed, no problems.
- `mujoco_squat_authority.py --check`: passed; benchmark, scenario, realization, SUT, and both platform environment pins matched; no stale pins.
- Worker Pyright initially exposed missing MuJoCo stub declarations. The exact Turn 5 worker stub was transferred; the worker Pyright configuration then passed with 0 errors, 0 warnings, and 0 informational diagnostics.
- Focused existing tests: **65 passed in 75.69 s**, covering model authority, squat dynamics, the full repetition, timestep comparison, repeated-process determinism, and negative controls. Negative controls confirmed soft sole friction permits slip, removing the dynamic internal model degrades/rejects the repetition, half-stiffness fails to recover the applied push, and zero excitation collapses the athlete.
- The checks establish software and numerical behavior of the synthetic model only. They do not establish empirical biomechanical validity or human-subject agreement.

## Windows/Linux trajectory investigation

The archived Linux RunSpec receipt and the new Windows fixed-mode replay use the same model hash, MuJoCo version, worker lock bytes, nominal timestep, and solver settings. Their environment identities and CPython patch versions differ.

| Observation | Linux recovered RunSpec receipt | Windows replay in this task |
| --- | --- | --- |
| OS/architecture | Linux x86-64 | Windows 11 build 26300, AMD64 |
| CPU | Not recorded in recovered receipt | Intel Core i5-1135G7, 8 logical processors |
| CPython | 3.12.3 | 3.12.13 |
| MuJoCo | 3.17.0 | 3.17.0 |
| Model SHA-256 | `c91b2fa2…76a1` | `c91b2fa2…76a1` |
| 1 ms trajectory SHA-256 | `d3b4edafc090b1b1dca76f2af04343febdec9f9a0ff3d02b8e8d54d2aaef678b` | `6724404701cd6675a5d6b5daf7f7fa0bed000581d0d1d3dfe9f8a07efb3a1273` |
| Samples | 551 | 551 |
| RunSpec identity | fingerprint `49440369db4b76bb12e704b46e460bdfb152c10f59e5942ecce38aaa619a57f8`; environment `env.mujoco.squat.linux-x86-64` / `8a8c3416…`; implementation `491d0789…` | No RunSpec was created by this fixed-mode diagnostic replay |

The Windows and recovered Linux CSVs were aligned by their 551 shared sample rows; all 160 numeric columns were compared. Five columns were identical. The largest absolute cell difference was `0.0209892 deg/s` in left shoulder-flexion velocity. Selected maxima were: joint torques `0.00731 N·m`, GRF channels `0.01104 N`, plantar contact channels `0.00783 N`, bar channels `5.76e-6` in their declared units, and the compared hip/knee/ankle angle channels `3.90e-5 deg`.

The worker lock SHA-256 is identical in the recovered Turn 5 candidate and this repository: `f939e54b030cbd02c11a346867744340c1e1ccd8f9fbf74432640a0b0fcd4c99`. The installed Windows worker closure check passed with MuJoCo `3.17.0`, NumPy `2.5.4`, PyArrow `26.0.0`, and closure digest `6a2f7ad6b36c71ac3c17466934843666efe35d743502be64837bb322f8275d5c`. The recovered Linux record binds its run to an implementation digest, but its complete installed-package listing and CPU metadata are not present in the recovered receipt.

The source-defined Windows and Linux environment semantic digests are intentionally distinct (`2880abe8…` and `8a8c3416…`); a shared RunSpec fingerprint is not expected across those environments. The source Linux receipt records two repeat runs with the same `d3b4…` trajectory. The Windows tests also passed repeated-process bitwise determinism.

The task and accepted authority provide no predeclared cross-platform numerical tolerance for these squat channels. The comparison above is descriptive; cross-platform numerical equivalence remains **BLOCKED_NUMERICS** until an owner accepts a bound. No hash or acceptance threshold was changed. The observed difference is not attributed to OS, CPU, or CPython patch because those factors were not varied independently.

## Worker and evidence boundary requiring owner review

RES-555 authorizes materialization for `IN_PROCESS` SUTs but leaves native evidence extraction and its contract unapproved. The current official supervisor accepts the existing v1 worker response and bounded diagnostics; it does not harvest arbitrary worker-created native files. The Turn 4/5 squat worker imports its own `dynamisbench.execution.native` module and writes Parquet samples/state plus a native index. That module and output contract are absent from protected `main`.

Accordingly, this PR does not port `worker.py`, `identity.py`, `native.py`, the native laboratory dataset test, or its Laboratory generation tools. The source worker cannot be admitted through the existing official path while retaining its recorded time-series outputs without a RES-555 authority decision. The fixed-mode source remains isolated in the already-pinned MuJoCo environment and its qualification tests pass, but it is not a RunSpec execution route and its diagnostic output is not sealed evidence.

The scope also excludes unrelated Laboratory UI work and the broader pipeline/normalization/assessment code. The fixed RunSpec case declarations are retained from the VM source, but this PR does not activate API routes, normalization, assessment, or M3.

## Compatibility deviation

The only source-file deviation is the status note in the squat README. The original README described the VM's RunSpec worker and native pipeline as if they were active in the official repo. The note now labels those sections as recovered-source context and records the RES-555 hold. The exact original effective hash and official README hash are both in [source-map.csv](source-map.csv).
