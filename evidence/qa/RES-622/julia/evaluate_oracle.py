"""Gate B measurement harness: perturbed real-data cases, Julia/Python agreement, timing, memory.

    python evaluate_oracle.py --julia <julia> --out results/<tag>.json [--runs 5] [--scale-rows 1000000]
    (Windows needs psutil: ``uv run --no-project --with psutil python evaluate_oracle.py ...``)

Everything is run through the real command line contract (one process per invocation), which is the
workflow a QA job would use. Scratch inputs are written to a temporary directory and removed.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "squat-repetition" / "repetition_timeseries.csv"
PY_REF = HERE / "compare_python.py"


# ----------------------------------------------------------------------------- measurement
def run_measured(cmd: list[str], env: dict[str, str] | None = None) -> dict:
    """Run one command; return wall seconds, CPU seconds, peak RSS (MB) and exit code."""
    full_env = {**os.environ, **(env or {})}
    start = time.perf_counter()
    if os.name == "posix":
        proc = subprocess.Popen(cmd, env=full_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _, status, usage = os.wait4(proc.pid, 0)
        wall = time.perf_counter() - start
        code = os.waitstatus_to_exitcode(status)
        return {"wall_s": wall, "cpu_s": usage.ru_utime + usage.ru_stime,
                "peak_rss_mb": usage.ru_maxrss / 1024, "exit": code}
    import psutil  # noqa: PLC0415

    proc = subprocess.Popen(cmd, env=full_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    root = psutil.Process(proc.pid)
    cpu: dict = {}
    peak = 0
    while proc.poll() is None:
        try:
            members = [root, *root.children(recursive=True)]
        except psutil.Error:
            members = []
        rss = 0
        for member in members:
            try:
                rss += member.memory_info().rss
                times = member.cpu_times()
                cpu[(member.pid, member.create_time())] = times.user + times.system
            except psutil.Error:
                pass
        peak = max(peak, rss)
        time.sleep(0.01)
    wall = time.perf_counter() - start
    return {"wall_s": wall, "cpu_s": sum(cpu.values()), "peak_rss_mb": peak / 2**20, "exit": proc.returncode}


def summarize(samples: list[dict]) -> dict:
    out = {"runs": len(samples)}
    for key in ("wall_s", "cpu_s", "peak_rss_mb"):
        values = [s[key] for s in samples]
        out[key] = {"median": round(statistics.median(values), 3), "min": round(min(values), 3),
                    "max": round(max(values), 3)}
    out["exit_codes"] = sorted({s["exit"] for s in samples})
    return out


# ----------------------------------------------------------------------------- commands
def julia_script(julia, csv_path, out_json, extra=()):
    return [julia, "-t", "1", f"--project={HERE}", str(HERE / "src" / "impulse_oracle.jl"),
            "--input", str(csv_path), "--output", str(out_json), *extra]


def julia_package(julia, csv_path, out_json, extra=()):
    code = "using ImpulseOracle; exit(ImpulseOracle.main(ARGS))"
    return [julia, "-t", "1", f"--project={HERE}", "-e", code,
            "--", "--input", str(csv_path), "--output", str(out_json), *extra]


def python_ref(csv_path, out_json, extra=()):
    return [sys.executable, str(PY_REF), "--input", str(csv_path), "--output", str(out_json), *extra]


# ----------------------------------------------------------------------------- perturbations
def read_fixture():
    with FIXTURE.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    return rows[0], rows[1:]


def write_variant(path: Path, header, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def perturbed_cases():
    """(name, mutator(header, rows) -> rows, extra CLI args, pre-declared expectation or None)."""
    def col(header, name):
        return header.index(name)

    def scale_grf(factor):
        def mutate(header, rows):
            i, j = col(header, "grf_left_z_n"), col(header, "grf_right_z_n")
            out = []
            for r in rows:
                r = list(r)
                r[i], r[j] = repr(float(r[i]) * factor), repr(float(r[j]) * factor)
                out.append(r)
            return out
        return mutate

    def offset_grf(newtons):
        def mutate(header, rows):
            i = col(header, "grf_left_z_n")
            out = []
            for r in rows:
                r = list(r); r[i] = repr(float(r[i]) + newtons); out.append(r)
            return out
        return mutate

    def spike(index, newtons):
        def mutate(header, rows):
            i = col(header, "grf_left_z_n")
            out = [list(r) for r in rows]
            out[index][i] = repr(float(out[index][i]) + newtons)
            return out
        return mutate

    def shift_velocity(samples):
        def mutate(header, rows):
            k = col(header, "com_vz_m_s")
            values = [r[k] for r in rows]
            shifted = values[samples:] + [values[-1]] * samples
            return [[*r[:k], s, *r[k + 1:]] for r, s in zip(rows, shifted, strict=True)]
        return mutate

    def offset_velocity_tail(delta, from_index):
        def mutate(header, rows):
            k = col(header, "com_vz_m_s")
            out = [list(r) for r in rows]
            for r in out[from_index:]:
                r[k] = repr(float(r[k]) + delta)
            return out
        return mutate

    identity = lambda header, rows: rows  # noqa: E731
    return [
        ("real-unmodified", identity, (), "pass"),
        ("grf-scale-0.9995", scale_grf(0.9995), (), None),
        ("grf-scale-1.0005", scale_grf(1.0005), (), None),
        ("grf-scale-1.002", scale_grf(1.002), (), None),
        ("grf-scale-1.01", scale_grf(1.01), (), "fail"),
        ("grf-sign-inversion", scale_grf(-1.0), (), "fail"),
        ("grf-offset-+0.5N", offset_grf(0.5), (), None),
        ("grf-offset-+5N", offset_grf(5.0), (), "fail"),
        ("grf-spike-+5000N-one-sample", spike(300, 5000.0), (), "fail"),
        ("grf-spike-+200N-one-sample", spike(300, 200.0), (), None),
        ("velocity-shift-1-sample", shift_velocity(1), (), None),
        ("velocity-tail-offset-+0.02", offset_velocity_tail(0.02, 300), (), None),
        ("velocity-tail-offset-+0.2", offset_velocity_tail(0.2, 300), (), "fail"),
        ("mass-95.1kg-(+0.105%)", identity, ("--mass-kg", "95.1"), None),
        ("mass-96kg-(+1.05%)", identity, ("--mass-kg", "96.0"), "fail"),
        ("gravity-9.81-(+0.0034%)", identity, ("--gravity", "9.81"), "pass"),
        ("gravity-9.9", identity, ("--gravity", "9.9"), "fail"),
    ]


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def compare_reports(a, b):
    """Largest absolute and relative difference over every numeric window field."""
    keys = ("delta_momentum_n_s", "net_impulse_n_s", "residual_n_s", "u_quad_n_s", "tolerance_n_s", "ratio")
    worst_abs = worst_rel = 0.0
    same_verdict = a["all_pass"] == b["all_pass"]
    for wa, wb in zip(a["windows"], b["windows"], strict=True):
        same_verdict &= wa["pass"] == wb["pass"] and wa["quadrature_limited"] == wb["quadrature_limited"]
        for key in keys:
            d = abs(wa[key] - wb[key])
            worst_abs = max(worst_abs, d)
            worst_rel = max(worst_rel, d / max(abs(wa[key]), abs(wb[key]), 1e-300))
    return {"max_abs_diff": worst_abs, "max_rel_diff": worst_rel, "same_verdicts": bool(same_verdict)}


def synthetic_rows(path: Path, rows: int):
    """Tile the real repetition into ``rows`` samples on a uniform 100 Hz grid (scale test only).

    Only the five columns the oracle reads are written, so 10^6 rows stay under the 256 MiB input cap.
    """
    header, body = read_fixture()
    keep = [header.index(c) for c in ("t_s", "grf_left_z_n", "grf_right_z_n", "com_vz_m_s", "phase")]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([header[i] for i in keep])
        n = len(body)
        for k in range(rows):
            r = body[k % n]
            writer.writerow([repr(round(k * 0.01, 10)), r[keep[1]], r[keep[2]], r[keep[3]], r[keep[4]]])


# ----------------------------------------------------------------------------- main
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--julia", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--scale-rows", type=int, default=1_000_000)
    args = parser.parse_args()
    julia = args.julia
    report: dict = {
        "host": {"platform": platform.platform(), "machine": platform.machine(), "cpus": os.cpu_count(),
                 "python": platform.python_version(), "julia": subprocess.run(
                     [julia, "--version"], capture_output=True, text=True, check=True).stdout.strip(),
                 "julia_threads": 1},
        "fixture_sha256": None,
    }
    import hashlib
    report["fixture_sha256"] = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    scratch = Path(tempfile.mkdtemp(prefix="res622-oracle-"))
    try:
        # -- 1. precompile once so package-mode timings are warm-depot; time the cold paths first
        depot = scratch / "cold-depot"
        cold_env = {"JULIA_DEPOT_PATH": str(depot)}
        out = scratch / "o.json"
        report["cold_empty_depot_script_mode"] = run_measured(julia_script(julia, FIXTURE, out), cold_env)
        shutil.rmtree(depot, ignore_errors=True)
        report["cold_empty_depot_package_mode_first_run"] = run_measured(julia_package(julia, FIXTURE, out), cold_env)
        report["warm_depot_package_mode_second_run"] = run_measured(julia_package(julia, FIXTURE, out), cold_env)
        shutil.rmtree(depot, ignore_errors=True)

        # -- 2. workflow timing on the real 551-sample export, default depot, N runs each
        subprocess.run(julia_package(julia, FIXTURE, out), check=False, capture_output=True)  # precompile
        timing = {}
        for name, builder in (("julia_script_jit_each_run", lambda: julia_script(julia, FIXTURE, out)),
                              ("julia_package_precompiled", lambda: julia_package(julia, FIXTURE, out)),
                              ("python_reference", lambda: python_ref(FIXTURE, out))):
            timing[name] = summarize([run_measured(builder()) for _ in range(args.runs)])
        report["real_export_551_samples"] = timing
        interp = [run_measured([sys.executable, "-c", "pass"]) for _ in range(args.runs)]
        report["python_interpreter_floor"] = summarize(interp)
        julia_floor = [run_measured([julia, "-t", "1", "-e", "nothing"]) for _ in range(args.runs)]
        report["julia_runtime_floor"] = summarize(julia_floor)

        # -- 3. perturbed real-data cases, Julia vs Python agreement
        header, rows = read_fixture()
        cases = []
        for name, mutate, extra, expected in perturbed_cases():
            variant = scratch / f"{name}.csv"
            write_variant(variant, header, mutate(header, rows))
            jo, po = scratch / f"{name}.j.json", scratch / f"{name}.p.json"
            jr = run_measured(julia_package(julia, variant, jo, extra))
            pr = run_measured(python_ref(variant, po, extra))
            ja, pa = load(jo), load(po)
            worst = max(ja["windows"], key=lambda w: w["ratio"])
            cases.append({
                "case": name, "expected": expected, "julia_exit": jr["exit"], "python_exit": pr["exit"],
                "all_pass": ja["all_pass"], "worst_window": worst["label"],
                "worst_ratio": round(worst["ratio"], 4),
                "failing_windows": [w["label"] for w in ja["windows"] if not w["pass"]],
                "quadrature_limited_windows": [w["label"] for w in ja["windows"] if w["quadrature_limited"]],
                "julia_vs_python": compare_reports(ja, pa),
                "meets_predeclared_expectation": (None if expected is None else
                                                  (ja["all_pass"] == (expected == "pass"))),
            })
        report["perturbed_real_data_cases"] = cases

        # -- 4. scale test: where could Julia's kernel speed matter?
        scale = {}
        for rows_n in sorted({10_000, 100_000, args.scale_rows}):
            big = scratch / f"scale-{rows_n}.csv"
            synthetic_rows(big, rows_n)
            entry = {"csv_mb": round(big.stat().st_size / 2**20, 1)}
            for name, builder in (("julia_package_precompiled", lambda b=big: julia_package(julia, b, out)),
                                  ("python_reference", lambda b=big: python_ref(b, out))):
                entry[name] = summarize([run_measured(builder()) for _ in range(max(3, args.runs // 2))])
            scale[str(rows_n)] = entry
            big.unlink()
        report["synthetic_scale_rows"] = scale
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k in ("host", "real_export_551_samples")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
