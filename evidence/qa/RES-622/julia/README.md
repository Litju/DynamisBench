# Julia impulse–momentum oracle (RES-622, experimental, nonblocking)

A separately versioned, one-shot command-line QA tool. It is **not** part of the application, the installer,
the MuJoCo worker, the scientific core or any required CI gate. Standard library only (`SHA`).
Specification: [`SPEC.md`](SPEC.md) (frozen before any real-data residual was computed; two errata are
recorded there, both found with closed-form tests).

| Item | Value |
| --- | --- |
| Julia | 1.13.3, pinned. Windows zip `1fae8fc95e6199b3d8f6d7a3791810e45e1b3c480eb4b9f5bb211789badfc729`, Linux tarball `5c61cb4b40332cb5a3504e7779e2f5dac093caa4a1116ded19f01413f85c63e4` (official `julialang-s3` archives) |
| Environment | `Project.toml` + `Manifest.toml` (only the `SHA` stdlib) |
| Input | `fixtures/squat-repetition/repetition_timeseries.csv` (551 samples, 100 Hz, sha256 `57bbbd95…ac1c`), exported from the unchanged worker by `python/tools/mujoco_squat_repetition.py` |
| Output | one JSON object, schema `dynamisbench.qa.impulse-oracle/1`; exit 0 all windows pass, 1 a window fails, 2 input rejected |

```text
# from this directory, with the pinned julia on PATH
julia --project=. -e "using Pkg; Pkg.instantiate()"
julia --project=. test/runtests.jl                                   # 34 checks: closed forms, adversarial, rejection
julia --project=. src/impulse_oracle.jl --input fixtures/squat-repetition/repetition_timeseries.csv --output out.json
python compare_python.py --input fixtures/squat-repetition/repetition_timeseries.csv      # Python reference (comparison only)
uv run --no-project --with psutil python evaluate_oracle.py --julia <path-to-julia> --out results/eval-<tag>.json
# regenerate the input (repo root's python/ directory, isolated worker provisioned):
uv run --frozen python tools/mujoco_squat_repetition.py --output ../evidence/qa/RES-622/julia/fixtures/squat-repetition
```

`results/` holds the raw output of every command above on Windows x64 and on Linux x64 (WSL2). The
`compare_python.py` reference re-implements the same specification, so it shares its assumptions with the Julia
tool by construction; it exists to compare speed and bitwise agreement, not to provide independence.
