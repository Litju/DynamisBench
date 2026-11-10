"""Summarize the Gate A matrix receipts into one table (RES-622).

    python summarize_matrix.py <raw-dir> [--exclude A-r1,B-r1] [--json out.json]

Reads ``<cond>-r<N>.receipt.json`` (from measure.py) and the JUnit XML of every run, checks that
every passing run executed the same set of passed tests, and prints per-condition wall time
(all runs, median, min, max), CPU seconds, peak RSS and the change against condition A.
A-r1 has no receipt (it predates measure.py); its wall time is read from the pytest log.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import xml.etree.ElementTree as ET
from pathlib import Path


def passed_ids(xml: Path) -> set[str]:
    root = ET.parse(xml).getroot()
    out = set()
    for case in root.iter("testcase"):
        if case.find("failure") is None and case.find("error") is None and case.find("skipped") is None:
            out.add(f"{case.get('classname')}::{case.get('name')}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("raw")
    parser.add_argument("--exclude", default="")
    parser.add_argument("--json")
    arguments = parser.parse_args()
    raw = Path(arguments.raw)
    excluded = {x for x in arguments.exclude.split(",") if x}
    runs: dict[str, list[dict]] = {}
    for receipt in sorted(raw.glob("*.receipt.json")):
        data = json.loads(receipt.read_text())
        cond = data["label"].split("-")[0]
        runs.setdefault(cond, []).append(data)
    # A-r1 pre-dates measure.py: wall time from the pytest summary line.
    a1 = raw / "A-r1.txt"
    if a1.exists():
        m = re.search(r"in ([0-9.]+)s", a1.read_text(errors="replace").splitlines()[-6:].__str__())
        text = a1.read_text(errors="replace")
        m = re.findall(r"(\d+) passed.* in ([0-9.]+)s", text)
        if m:
            runs.setdefault("A", []).append(
                {"label": "A-r1", "wall_s": float(m[-1][1]), "exit_code": 0, "cpu_s_lower_bound": None,
                 "peak_tree_rss_mb": None, "peak_processes": None, "mean_host_cpu_percent": None}
            )
    table = {}
    for cond in sorted(runs):
        rows = sorted(runs[cond], key=lambda r: r["label"])
        kept = [r for r in rows if r["label"] not in excluded and r["exit_code"] == 0]
        walls = [r["wall_s"] for r in kept]
        entry = {
            "runs": [
                {"label": r["label"], "wall_s": r["wall_s"], "exit_code": r["exit_code"],
                 "cpu_s": r["cpu_s_lower_bound"], "peak_rss_mb": r["peak_tree_rss_mb"],
                 "peak_processes": r["peak_processes"], "host_cpu_pct": r["mean_host_cpu_percent"],
                 "excluded": r["label"] in excluded}
                for r in rows
            ],
            "n_used": len(kept),
            "median_wall_s": round(statistics.median(walls), 1) if walls else None,
            "min_wall_s": min(walls) if walls else None,
            "max_wall_s": max(walls) if walls else None,
        }
        cpu = [r["cpu_s_lower_bound"] for r in kept if r["cpu_s_lower_bound"]]
        rss = [r["peak_tree_rss_mb"] for r in kept if r["peak_tree_rss_mb"]]
        entry["median_cpu_s"] = round(statistics.median(cpu), 1) if cpu else None
        entry["median_peak_rss_mb"] = round(statistics.median(rss), 1) if rss else None
        table[cond] = entry
        # Node ids of two parametrized tests were random per process before RES-622 (A-r*, B-r*,
        # C-r1, D-r1), so outcomes are compared by count and by named failures, not by id set.
        for r in rows:
            xml = raw / f"{r['label']}.xml"
            if xml.exists():
                root = ET.parse(xml).getroot()
                cases = list(root.iter("testcase"))
                bad = [f"{c.get('classname')}::{c.get('name')}"[:200] for c in cases
                       if c.find("failure") is not None or c.find("error") is not None]
                skipped = sum(1 for c in cases if c.find("skipped") is not None)
                r_entry = next(x for x in entry["runs"] if x["label"] == r["label"])
                r_entry.update({"testcases": len(cases), "skipped": skipped, "failed": bad})
    base = table.get("A", {}).get("median_wall_s")
    for cond, entry in table.items():
        if base and entry["median_wall_s"]:
            entry["median_change_vs_A_pct"] = round(100 * (entry["median_wall_s"] - base) / base, 1)
    print(json.dumps(table, indent=1))
    if arguments.json:
        Path(arguments.json).write_text(json.dumps(table, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
