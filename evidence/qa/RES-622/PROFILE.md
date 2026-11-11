# RES-622 Gate A — Python QA test-suite profile

Unchanged-main code reference: `3eda5c60717af360566fa3f5792eb5bc8e38670e` (protected `main`, PR #27 merge).

The recorded matrix A runs did not execute unchanged main. A is the experiment's comparison baseline: the
PR fixture code eagerly submits every selected squat mode to a one-worker pool when the first squat fixture
is requested. Unchanged main instead ran each mode synchronously when its own fixture was first requested.
The A/B figures compare one-worker eager prewarming with bounded concurrent eager prewarming; they do not
estimate a change versus unchanged main.
Reference CI figure from the issue: pytest/Hypothesis step 206 s (Windows) / 197 s (Linux), run 107.

## Environment (every row below ran on this one host; Linux was not measured here)

| Item | Value |
| --- | --- |
| Host | Windows 11 Pro 10.0.26300, Intel64 Family 6 Model 140 (4 cores / 8 logical), 7.4 GB RAM, laptop |
| Python / uv | CPython 3.12.13 (`python/.python-version`), uv 0.10.1 |
| Test stack | pytest 9.1.1, Hypothesis 6.168.3 (`HYPOTHESIS_PROFILE=ci`, 500 examples, derandomized), NumPy 2.5.4 |
| Worker | isolated MuJoCo 3.17.0 environment (`uv sync --frozen --project worker-mujoco`), `DYNAMISBENCH_REQUIRE_MUJOCO=1` |
| Selection | the full suite: 2717 test cases, 2710 pass, 7 skipped (hosts without symlink/FIFO support, a 3-minute opt-in figure regeneration, a missing future module) — identical in every passing run |
| State | `-p no:cacheprovider`, no result cache, uv/pyc caches warm; one run at a time on an otherwise idle host |

**This host is not the CI runner.** Serial wall time here is ~2× the CI figure and varies ±13 % between identical
runs (laptop power/thermal state; mean host CPU 28–48 % during serial runs, i.e. mostly one core busy). Only
*relative* statements within this dataset are supported; absolute numbers do not transfer to `windows-2025`.
Two early runs (`A-r1`, `B-r1`) overlapped with my own setup work (dependency installs, a collection probe,
a 300 MB download) and are kept in `raw/` but excluded from medians.

## Where the time goes (clean A run `A-r3`: pytest serial, one-worker eager prewarm; 401 s wall; `analysis/pareto-A-r3.json`)

`pytest --durations=0` attributes 94 % of the wall time to tests (phase split below); pytest hides durations
under 5 ms (6 800 items, ≤ 34 s combined). Collection is ~10–15 s (probe: `--collect-only` 29 s including `uv run`
resolution). Setup/teardown are almost entirely the session-scoped squat fixtures.

| Rank | Area | Seconds | Share | What it is |
| --- | --- | ---: | ---: | --- |
| 1 | `tests/api` | 136 | 34 % | real sidecar/uvicorn **subprocesses** (cold start ≈ 0.9 s of imports each), workspace/stream tests; `test_sidecar_process.py` alone 47 s |
| 2 | `tests/execution/mujoco_squat` | 61 | 15 % | 8 fixed-mode MuJoCo runs (4.6–6 s each *plus* up to ~40 s for the repetition/timestep modes), negative-control re-simulations |
| 3 | `tests/planning` | 47 | 12 % | Hypothesis properties (500 examples under the CI profile) |
| 4 | `tests/execution/mujoco` | 41 | 10 % | worker adversarial/authority tests, each spawning the real worker |
| 5 | `tests/evidence` | 20 | 5 % | Hypothesis + filesystem seal/bundle properties |
| 6 | everything else | 96 | 24 % | |

By phase: call 345 s (86 %), setup 45 s (11 %), teardown ≈ 0. By kind (file-level static classification, a
heuristic): subprocess-spawning 82 s, MuJoCo-worker 73 s, filesystem 58 s, Hypothesis 44 s.

Process initialisation is *not* the cost: a bare interpreter starts in 0.08 s, `import numpy` 0.4 s,
`import mujoco` 0.48 s, the app imports (FastAPI+pydantic+NumPy+PyArrow) 0.9 s (`startup-costs.json`). The
simulation itself dominates the MuJoCo tests (`--stand` 5.8 s end to end). **Python numerical computation is
not a bottleneck**: the Python-side NumPy work is milliseconds; the seconds are the engine, subprocess
creation, and the number of times tests deliberately start a fresh process (negative/security tests require it
and are not candidates for reuse).

## Remediations evaluated (matrix in `raw/`, summary `analysis/matrix-summary.json`)

All conditions ran the full unmodified-assertion suite on this host (median of passing runs, wall seconds; A and B exclude the contaminated r1). A is not an unchanged-main run.

| Cond | Change | Valid runs | Median | Range | Median delta vs A | Peak RSS (tree) | Passed |
| --- | --- | ---: | ---: | --- | ---: | ---: | --- |
| A | pytest serial; selected squat modes eagerly queued on a one-worker pool (`DYNAMISBENCH_QA_SQUAT_PARALLEL=1`; not unchanged-main scheduling) | 3 | 464 | 403–525 | — | 0.39 GB | 3/3 |
| B | pytest serial; selected squat modes prewarmed concurrently in a bounded pool (opt-in, `DYNAMISBENCH_QA_SQUAT_PARALLEL=4`) | 3 | 429 | 318–520 | −7.6 % | 0.53 GB | 3/3 |
| C | pytest-xdist `-n 4 --dist loadfile`, squat modes serial per worker | 2 passing (+1 failing 296 s, +1 collection error) | 211 | 171–251 | −54 % | 1.1 GB | **2/4 attempts** |
| D | xdist `-n 4` + prewarm pool (up to 32 processes) | 1 passing (309 s) + 1 failing (206 s) | 309 | — | −33 % | 1.2 GB | **1/2** |

Reading the table:

* **B (opt-in experiment only).** B changes fixture scheduling by eagerly submitting selected modes to a
  bounded pool. Its median was 7.6% lower than A, but this descriptive difference is within the reported
  ±13% run-to-run noise. It is not a controlled estimate against unchanged main, and no hosted Windows/Linux
  A/B qualification exists. The isolated-directory timings were 155 s for A and 54 s for B in one head-to-head;
  this descriptive observation does not establish a reliable speed benefit. Unset
  `DYNAMISBENCH_QA_SQUAT_PARALLEL` retains synchronous on-demand fixtures; setting it opts into eager
  prewarming.
* **C/D (xdist) are not adopted.** Passing C runs had shorter observed wall times, but the uneven samples and
  failures do not support a reliable speed claim: (1) xdist **could not run at all**
  until two parametrized tests stopped embedding per-process random values in their node ids
  (`tests/api/test_session.py`; fixed with explicit `ids=`, values and assertions unchanged — run C-r1 shows the
  collection failure); (2) under load it exposed **two intermittent failures**, both in tests that touch real
  processes/files: `test_a_direct_protocol_request_with_a_substituted_semantic_digest_is_refused[system_under_test…]`
  (C-r4: the worker reported `machine=''` from `platform.machine()` on Windows, so admission refused for the
  wrong reason) and `tests/materialization/test_store.py::test_concurrent_materializations_converge_on_one_manifest_and_object`
  (D-r1: Windows `PermissionError` during concurrent replace). Neither failure occurred in the four non-xdist A/B runs cited above.
  A shorter required gate that is flaky is a loss; these need root-cause issues (the first is plausibly
  a latent platform-detection fragility in the isolated worker's sanitized environment; the second a Windows
  atomic-replace race under CPU pressure) before xdist could be proposed for the required matrix.
* Oversubscription (D, 32 processes on 8 logical CPUs, 1.2 GB) is strictly worse than C.

## Isolation / resource findings for a future xdist pilot

* `--dist loadfile` keeps module-scoped fixtures intact; session fixtures are rebuilt per worker.
* Node ids must be identical across workers (fixed here); other random-id sources: none found in a collect-only
  comparison across two workers.
* Peak process-tree RSS 1.1–1.4 GB at `-n 4`, 25–32 processes: acceptable on a 7 GB host, to be re-checked on a
  4-vCPU hosted runner, where `-n 4` would also compete with the CI job's other steps.

## What changed in this commit (tests-only; no production code, assertion, timeout or reference touched)

1. `python/tests/execution/mujoco_squat/conftest.py` — synchronous on-demand fixtures by default. Setting
   `DYNAMISBENCH_QA_SQUAT_PARALLEL` opts into eager prewarming, capped at `min(4, CPUs)`; value `1`
   reproduces matrix A's one-worker eager condition, not unchanged-main scheduling.
2. `python/tests/api/test_session.py` — stable `ids=` for two randomly-valued parametrizations.
3. `evidence/qa/RES-622/{raw,analysis}` — raw logs/receipts (home paths scrubbed), measurement and analysis
   scripts, reproduction:

```text
cd python
uv sync --frozen && uv sync --frozen --project worker-mujoco
bash ../evidence/qa/RES-622/analysis/run_matrix.sh <A|B|C|D> <rep> <outdir>   # one measured full run
python ../evidence/qa/RES-622/analysis/summarize_matrix.py <raw-dir> --exclude A-r1,B-r1,C-r1,C-r4,D-r1
python ../evidence/qa/RES-622/analysis/pareto.py <raw-dir>/A-r3.txt tests
```

Receipt `exit_code` and the JUnit counts in `matrix-summary.json` show which runs failed; failed runs are
listed, not hidden (C-r1: collection error, fixed afterwards; C-r4, D-r1: the two intermittent failures above).
