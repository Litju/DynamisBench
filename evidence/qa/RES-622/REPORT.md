# RES-622 — Scientific QA performance and Julia numerical-oracle pilot: report and decision

Unchanged-main code reference: protected `main` `3eda5c60717af360566fa3f5792eb5bc8e38670e`. Experimental, nonblocking; no production,
physics, scientific-contract, VM Workbench or required-CI change. Details: [`PROFILE.md`](PROFILE.md) (Gate A),
[`julia/`](julia/) (Gate B). All measurements are from one Windows 11 laptop (4C/8T, 7.4 GB) plus a WSL2 Ubuntu
guest on the same machine; **no hosted-runner data**, so absolute times do not transfer to `windows-2025` / `ubuntu-24.04`.

## DECISION

**Decision: keep Python, do not promote Julia or xdist, and leave prewarming opt-in.** Julia is not promoted
for speed (`NO_MEASURED_BENEFIT`); scientific verification comes from the invariant, not the language.
Prewarming remains opt-in because the experiment does not establish a reliable benefit over unchanged main.

* Optionally keep the Julia oracle under `evidence/qa/RES-622/julia/` as a nonblocking cross-check; do not add it
  to required CI, the installer or `uv`/`pnpm` lockfiles without a separate ADR.
* If an independent impulse–momentum check is wanted in the suite, the stdlib-Python implementation of the same
  frozen spec (`julia/compare_python.py`, 0.24 s, 31 MB, bitwise-identical output) delivers it without a
  second runtime. Its independence rests on the spec and its closed-form qualification, which are language-neutral.

## Gate A — measured bottlenecks and scheduling experiments

Clean A suite (A-r3; pytest serial with a one-worker eager-prewarm pool, 401 s): `tests/api` 34 %
(real sidecar subprocesses), `tests/execution/mujoco_squat`
15 % (MuJoCo mode runs + negative controls), Hypothesis properties 12–16 %, MuJoCo worker adversarial tests 10 %.
Phase split: call 86 %, fixture setup 11 %, teardown ≈ 0. Interpreter/import start-up is small (0.08 s bare, ≤ 0.9 s
with the app imports); **Python numerical computation is not a bottleneck**, the engine's simulation and process
creation are.

| Condition (full suite, assertions unchanged) | Median wall | vs A | Outcome |
| --- | ---: | ---: | --- |
| A pytest serial; one-worker eager prewarm (matrix comparison baseline, not unchanged main) | 464 s (403–525, n=3) | — | 3/3 pass |
| B pytest serial; four-worker squat prewarm (**opt-in only**) | 429 s (318–520, n=3) | −7.6 % vs A | 3/3 pass; inside ±13 % host noise |
| C xdist `-n 4 --dist loadfile` | 211 s (171–251, n=2 passing) | −54 % | 2 of 4 attempts passed (1 collection error, fixed; 1 intermittent failure) |
| D xdist `-n 4` + prewarm | 309 s (passing run) | −33 % | 1 of 2 passed (intermittent failure) |

* Matrix A is the historical one-worker eager-prewarm condition, not unchanged-main behavior. The original
  main fixtures ran modes synchronously on demand. No matched unchanged-main timing is in these receipts.
* Stable parametrized node ids are kept. Bounded concurrent prewarming is available only by explicitly setting
  `DYNAMISBENCH_QA_SQUAT_PARALLEL`; unset preserves the original synchronous on-demand behavior. The A/B median
  difference (−7.6 %) is inside host noise and is not evidence of a speed improvement over unchanged main.
* **Not adopted: xdist.** Passing xdist runs had lower observed wall times, but the small, uneven sample and
  intermittent failures do not qualify a reliable speed improvement. It exposed two failures, neither observed
  under the non-xdist A/B conditions: the worker reported `machine=''` on Windows (admission refused for the
  wrong reason), and Windows raised `PermissionError` in the concurrent-materialization test. Those need
  root-cause issues first; they are findings,
  not something to hide with retries or timeouts.
* Earlier runs overlapping my own setup (A-r1, B-r1) are retained and excluded from medians.

## Gate B — independent oracle (vertical impulse–momentum, M = 95 kg, g = 9.80665)

Equation, assumptions, units, method and tolerances: [`julia/SPEC.md`](julia/SPEC.md), frozen before any real-data
residual existed. Two spec errata were found by the oracle's own closed-form tests and fixed before real data
(a sign in the Euler–Maclaurin reference value; a quadrature allowance that masked its own spike).

**Qualification of the oracle itself:** 34 Julia checks pass on Windows and Linux — rest, constant push, free
flight, and a sinusoid whose residual matches the analytic truncation term within 5 % at three step sizes; mass
+1 %, gravity 9.9, sign inversion, spike, drift and time-shift adversaries; 8 input-rejection cases.

**Real MuJoCo repetition (551 samples, sha256 `57bbbd95…ac1c`, byte-reproducible export):** all 6 windows pass,
worst `|R|/τ` = 0.020. Whole record `R = −0.005 N·s` (τ = 5.13); ascent `R = −0.018 N·s` against a momentum change
of −0.473 N·s (3.9 %), 7× its Richardson quadrature estimate — i.e. not purely quadrature; consistent with the
engine's documented first-order integration error and 100 Hz instantaneous sampling, not proven to be either.

**Perturbed real-data cases (17, Windows and Linux identical verdicts, Julia = Python to the last bit):**

| Case | Verdict (worst window ratio) |
| --- | --- |
| GRF ×0.9995 / ×1.0005 / +0.5 N offset | pass (0.50 / 0.52 / 0.55) |
| GRF ×1.002 / +5 N offset / ×1.01 | **fail** (2.0 / 5.4 / 10.0) |
| GRF sign inversion | **fail** (2000) |
| mass 95.1 kg (+0.105 %) / 96 kg / gravity 9.9 | **fail** (1.05 / 10.4 / 9.4) |
| gravity 9.81 (+0.0034 %) | pass (0.34) — below the floor, as predeclared |
| one-sample GRF spike +5000 N / +200 N | **fail** (7.5) / pass (0.65) |
| velocity tail offset +0.2 / +0.02 m/s | **fail** (17) / **fail** (1.7) |
| velocity shifted one sample | pass (0.07) — **undetectable** at this signal level |

All 9 predeclared expectations were met. Detection floor ≈ 0.1 % of the window's weight impulse.

**Limitations (stated, not tuned away):**

* The pre-registered tolerance is **coarse for this slow squat**: τ ≈ 1.4 N·s per phase while the whole phase's
  momentum change is ≈ 0.5 N·s, so actual agreement (ratios 0.001–0.02) is ~50–1000× tighter than the test can
  resolve. A tighter, physically argued budget should be pre-registered in a follow-up; I did not retune it after
  seeing the data.
* It verifies *internal consistency of two engine outputs against Newton's law*, sharing the engine, the exporter and
  the declared constants with the code under test. It is not independent of MuJoCo's contact model and does not
  prove biomechanical validity.
* Only the nominal repetition was exported (the worker offers no sampled export for other factor cases); perturbed
  physics is emulated on the exported series, not by re-simulating perturbed models.
* Linux = WSL2 on the same CPU, not a hosted runner; Python there is 3.14.4, not the pinned 3.12.

## Julia performance (real 551-sample workflow, 5 runs each, 1 Julia thread)

| Command (Windows x64) | Wall median | Peak RSS | CPU |
| --- | ---: | ---: | ---: |
| Python reference | 0.24 s | 31 MB | 0.19 s |
| Julia one-shot (script, JIT each run) | 1.09 s | 210 MB | 1.05 s |
| Julia one-shot (precompiled package) | 1.20 s | 202 MB | 1.16 s |
| Julia, empty depot, first ever run (compile + precompile) | 1.4–1.8 s | 211–330 MB | 1.2–1.7 s |
| floors: bare `python` / bare `julia -e nothing` | 0.08 s / 0.25 s | | |

Linux x64 (WSL2): Python 0.105 s / 29 MB; Julia 0.98 s / 291 MB. Compared with the full workflow (13 s MuJoCo
export + oracle), Julia adds ≈ 8–9 % wall time, Python ≈ 2 %; against the 200–460 s pytest suite either is < 0.6 %.
**Julia's best case never beat Python**: the data is tiny, so start-up and JIT dominate. At 10⁶ rows (71 MB CSV,
beyond anything the QA produces) my idiomatic, untuned Julia parser was 5–9× *slower* than Python's C `csv`
(51 s vs 5.9 s Windows; 28 s vs 4.0 s Linux); a tuned parser would likely win but there is no workload that needs it.
The ≥ 20 % critical-path threshold is not met by any Julia configuration.

Maintenance/installer cost of Julia: a ~300 MB toolchain per OS, a second dependency manifest, a second language
for reviewers (≈ 200 lines + 130 lines of tests), and nothing to ship in the installer (test-only).

## Reproduce

See [`PROFILE.md`](PROFILE.md) (Gate A) and [`julia/README.md`](julia/README.md) (Gate B); raw data under `raw/`,
`analysis/` and `julia/results/`. Home-directory paths were scrubbed from the logs.
