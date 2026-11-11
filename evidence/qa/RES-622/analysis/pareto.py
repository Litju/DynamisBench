"""Aggregate a `pytest --durations=0` text log into a ranked bottleneck table (RES-622).

    python pareto.py <pytest-log.txt> <tests-root> [--json out.json]

Durations below pytest's 5 ms display floor are hidden by pytest; their count is reported
and bounded above by count*5ms. Each test file is classified by what its source imports/calls
(static, documented heuristic - not a measurement of the numerical share).
"""
from __future__ import annotations
import argparse, collections, json, re, sys
from pathlib import Path

LINE = re.compile(r"^\s*([0-9.]+)s (setup|call|teardown)\s+(\S+)")
SUMMARY = re.compile(r"(\d+) passed.* in ([0-9.]+)s")

def classify(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    tags = []
    if "hypothesis" in text: tags.append("property")
    if re.search(r"run_mode|mujoco_squat|DYNAMISBENCH_MUJOCO_PYTHON|real_worker|run_worker", text) or "/mujoco" in str(path).replace("\\", "/"):
        tags.append("mujoco-worker")
    if re.search(r"subprocess|Popen|sys\.executable", text): tags.append("subprocess")
    if re.search(r"TestClient|fastapi", text): tags.append("api")
    if re.search(r"tmp_path|write_text|write_bytes|mkdir", text): tags.append("filesystem")
    return tags or ["unit"]

def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("log"); ap.add_argument("tests")
    ap.add_argument("--json"); a = ap.parse_args()
    shown = collections.defaultdict(float); phase = collections.defaultdict(float)
    by_dir = collections.defaultdict(float); by_file_phase = collections.defaultdict(lambda: collections.defaultdict(float))
    total = None; hidden = 0
    for line in Path(a.log).read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE.match(line)
        if m:
            sec, ph, node = float(m[1]), m[2], m[3].replace("\\", "/")
            f = node.split("::")[0]
            shown[f] += sec; phase[ph] += sec
            by_file_phase[f][ph] += sec
            by_dir["/".join(f.split("/")[:3] if "execution" in f else f.split("/")[:2])] += sec
        h = re.search(r"\((\d+) durations < ([0-9.]+)s hidden", line)
        if h: hidden = int(h[1]); floor = float(h[2])
        s = SUMMARY.search(line)
        if s: total = float(s[2])
    root = Path(a.tests).parent
    rows = []
    for f, sec in sorted(shown.items(), key=lambda kv: -kv[1]):
        p = root / f
        rows.append({"file": f, "seconds": round(sec, 2), "setup": round(by_file_phase[f]["setup"], 2),
                     "call": round(by_file_phase[f]["call"], 2), "teardown": round(by_file_phase[f]["teardown"], 2),
                     "class": classify(p) if p.exists() else ["?"]})
    cls = collections.defaultdict(float)
    for r in rows:
        cls["+".join(r["class"])] += r["seconds"]
    out = {"wall_seconds": total, "attributed_shown_seconds": round(sum(shown.values()), 2),
           "hidden_under_floor": {"count": hidden, "max_seconds_bound": round(hidden * floor, 1)},
           "phase_seconds": {k: round(v, 2) for k, v in phase.items()},
           "by_directory": {k: round(v, 2) for k, v in sorted(by_dir.items(), key=lambda kv: -kv[1])},
           "by_class": {k: round(v, 2) for k, v in sorted(cls.items(), key=lambda kv: -kv[1])},
           "files": rows[:25]}
    print(json.dumps(out, indent=1))
    if a.json: Path(a.json).write_text(json.dumps(out, indent=1))
    return 0
sys.exit(main())
