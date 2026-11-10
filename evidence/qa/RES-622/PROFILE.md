# RES-622 Gate A — Python QA test-suite profile

Baseline commit: `3eda5c60717af360566fa3f5792eb5bc8e38670e` (protected `main`, PR #27 merge).
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

## Where the time goes (clean serial run `A-r3`, 401 s wall; `analysis/pareto-A-r3.json`)

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

All conditions ran the full unmodified-assertion suite on this host (median of passing runs, wall seconds; A and B exclude the contaminated r1):

| Cond | Change | Valid runs | Median | Range | vs A | Peak RSS (tree) | Passed |
| --- | --- | ---: | ---: | --- | ---: | ---: | --- |
| A | serial; squat modes serial (= pre-change behaviour, `DYNAMISBENCH_QA_SQUAT_PARALLEL=1`) | 3 | 464 | 403–525 | — | 0.39 GB | 3/3 |
| B | serial; squat modes prewarmed concurrently in a bounded pool (≤ 4) | 3 | 429 | 318–520 | −7.6 % | 0.53 GB | 3/3 |
| C | pytest-xdist `-n 4 --dist loadfile`, squat modes serial per worker | 2 passing (+1 failing 296 s, +1 collection error) | 211 | 171–251 | −54 % | 1.1 GB | **2/4 attempts** |
| D | xdist `-n 4` + prewarm pool (up to 32 processes) | 1 passing (309 s) + 1 failing (206 s) | 309 | — | −33 % | 1.2 GB | **1/2** |

Reading the table:

* **B (kept, committed).** The squat-mode prewarm removes a measured ≈ 45–100 s of *serial* fixture setup
  from the critical path (the 8 independent mode runs now overlap, longest-first). Its whole-suite benefit
  (−7.6 % median) is **inside the ±13 % run-to-run noise** of this host; the isolated squat directory improved
  155 s → 54 s in a head-to-head (`tests/execution/mujoco_squat`, one run each). It is safe: same processes,
  same assertions, a failing mode fails only the tests that use it, `DYNAMISBENCH_QA_SQUAT_PARALLEL=1` restores
  serial behaviour. It is the part of the saving that also helps *without* xdist.
* **C/D (xdist) are not adopted.** xdist roughly halves the wall time, but: (1) it **could not run at all**
  until two parametrized tests stopped embedding per-process random values in their node ids
  (`tests/api/test_session.py`; fixed with explicit `ids=`, values and assertions unchanged — run C-r1 shows the
  collection failure); (2) under load it exposed **two intermittent failures**, both in tests that touch real
  processes/files: `test_a_direct_protocol_request_with_a_substituted_semantic_digest_is_refused[system_under_test…]`
  (C-r4: the worker reported `machine=''` from `platform.machine()` on Windows, so admission refused for the
  wrong reason) and `tests/materialization/test_store.py::test_concurrent_materializations_converge_on_one_manifest_and_object`
  (D-r1: Windows `PermissionError` during concurrent replace). Neither failure occurred in 4 serial runs.
  A QA speed-up that makes a required gate flaky is a loss; these need root-cause issues (the first is plausibly
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

1. `python/tests/execution/mujoco_squat/conftest.py` — bounded concurrent prewarm of exactly the squat modes the
   selected tests use (`DYNAMISBENCH_QA_SQUAT_PARALLEL`, default `min(4, CPUs)`).
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
