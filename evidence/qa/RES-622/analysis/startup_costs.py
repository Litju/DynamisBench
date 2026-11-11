"""Interpreter/import/solver start-up costs of the two Python environments (RES-622 Gate A).

    python startup_costs.py <app-python> <worker-python> [--json out.json]

Each command is run 5 times as a child process; min/median/max wall seconds are reported.
"""
import json, statistics, subprocess, sys, time

def timeit(cmd, n=5):
    ts = []
    for _ in range(n):
        t = time.perf_counter(); subprocess.run(cmd, capture_output=True, check=True); ts.append(time.perf_counter() - t)
    return {"cmd": [c if i else "<python>" for i, c in enumerate(cmd)], "min": round(min(ts), 3),
            "median": round(statistics.median(ts), 3), "max": round(max(ts), 3)}

app, worker = sys.argv[1], sys.argv[2]
rows = {
 "worker: interpreter only": timeit([worker, "-I", "-c", "pass"]),
 "worker: import numpy": timeit([worker, "-I", "-c", "import numpy"]),
 "worker: import mujoco": timeit([worker, "-I", "-c", "import mujoco"]),
 "worker: squat --stand": timeit([worker, "-I", "-m", "dynamisbench.adapters.mujoco.squat", "--stand"], 3),
 "app: interpreter only": timeit([app, "-I", "-c", "pass"]),
 "app: import numpy, pyarrow": timeit([app, "-I", "-c", "import numpy, pyarrow"]),
 "app: import fastapi, pydantic, numpy, pyarrow": timeit([app, "-I", "-c", "import fastapi, pydantic, numpy, pyarrow"]),
}
print(json.dumps(rows, indent=1))
if "--json" in sys.argv: open(sys.argv[sys.argv.index("--json") + 1], "w").write(json.dumps(rows, indent=1))
