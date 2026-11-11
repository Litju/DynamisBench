"""Python reference implementation of SPEC.md, for performance/compatibility comparison ONLY.

It is not the scientific oracle: it re-implements the same frozen specification (so it shares
its assumptions with the Julia tool by construction) and uses no code from DynamisBench.
Standard library only (``math.fsum`` is exactly rounded).

    python compare_python.py --input repetition_timeseries.csv [--output out.json]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys

MASS_KG = 95.0
GRAVITY = 9.80665
EPS_REL = 1.0e-3
EPS_ABS = 1.0e-9
EPS_Q = 5.0e-3
REQUIRED = ("t_s", "grf_left_z_n", "grf_right_z_n", "com_vz_m_s", "phase")


class InputError(Exception):
    pass


def read_series(path: str):
    with open(path, "rb") as handle:
        raw = handle.read()
    digest = hashlib.sha256(raw).hexdigest()
    rows = list(csv.reader(raw.decode("utf-8").splitlines()))
    if not rows:
        raise InputError("empty input")
    header = rows[0]
    col = {name: i for i, name in enumerate(header)}
    for name in REQUIRED:
        if name not in col:
            raise InputError(f"missing column {name}")
    body = rows[1:]
    if len(body) < 3:
        raise InputError("fewer than 3 samples")
    t, fz, v, phase = [], [], [], []
    for r, row in enumerate(body, start=1):
        if len(row) != len(header):
            raise InputError(f"row {r} has {len(row)} fields")
        try:
            t.append(float(row[col["t_s"]]))
            fz.append(float(row[col["grf_left_z_n"]]) + float(row[col["grf_right_z_n"]]))
            v.append(float(row[col["com_vz_m_s"]]))
        except ValueError:
            raise InputError(f"row {r} holds a non-numeric value") from None
        if not (math.isfinite(t[-1]) and math.isfinite(fz[-1]) and math.isfinite(v[-1])):
            raise InputError(f"row {r} holds a non-finite value")
        phase.append(row[col["phase"]])
    n = len(t)
    h = (t[-1] - t[0]) / (n - 1)
    if h <= 0:
        raise InputError("time is not increasing")
    for r in range(1, n):
        if abs((t[r] - t[r - 1]) - h) > 1e-6 * h + 1e-9:
            raise InputError(f"time grid is not uniform at row {r + 1}")
    return t, fz, v, phase, digest, h


def windows_of(phase):
    n = len(phase)
    ws = [("whole-record", 0, n - 1)]
    a = 0
    for i in range(1, n + 1):
        if i == n or phase[i] != phase[a]:
            if i - 1 > a:
                ws.append((f"phase:{phase[a]}@{a + 1}", a, i - 1))
            a = i
    return ws


def trapezoid(y, h, i0, n, k):
    if n < 1:
        return 0.0
    inner = math.fsum(y[i0 + k * j] for j in range(1, n))
    return k * h * (0.5 * (y[i0] + y[i0 + n * k]) + inner)


def evaluate(series, mass=MASS_KG, gravity=GRAVITY):
    t, fz, v, phase, _digest, h = series
    net = [f - mass * gravity for f in fz]
    out = []
    for label, a, b in windows_of(phase):
        n = b - a
        impulse = trapezoid(net, h, a, n, 1)
        n_even = n - (n % 2)
        if n_even >= 2:
            u_q = abs(trapezoid(net, h, a, n_even, 1) - trapezoid(net, h, a, n_even // 2, 2)) * (
                n / n_even
            )
        else:
            u_q = 0.0
        dp = mass * (v[b] - v[a])
        residual = dp - impulse
        dt = t[b] - t[a]
        cap = EPS_Q * mass * gravity * dt
        tau = min(u_q, cap) + EPS_REL * mass * gravity * dt + EPS_ABS
        out.append(
            {
                "label": label,
                "t_start_s": t[a],
                "t_end_s": t[b],
                "samples": n + 1,
                "delta_momentum_n_s": dp,
                "net_impulse_n_s": impulse,
                "residual_n_s": residual,
                "u_quad_n_s": u_q,
                "tolerance_n_s": tau,
                "ratio": abs(residual) / tau,
                "pass": abs(residual) <= tau,
                "quadrature_limited": u_q > cap,
            }
        )
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output")
    parser.add_argument("--mass-kg", type=float, default=MASS_KG)
    parser.add_argument("--gravity", type=float, default=GRAVITY)
    arguments = parser.parse_args(argv)
    try:
        series = read_series(arguments.input)
    except (InputError, OSError) as error:
        sys.stderr.write(f"input rejected: {error}\n")
        return 2
    windows = evaluate(series, arguments.mass_kg, arguments.gravity)
    report = {
        "schema": "dynamisbench.qa.impulse-oracle/1",
        "implementation": "python-reference",
        "input_sha256": series[4],
        "all_pass": all(w["pass"] for w in windows),
        "windows": windows,
    }
    text = json.dumps(report, indent=1) + "\n"
    if arguments.output:
        with open(arguments.output, "w", encoding="utf-8") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)
    return 0 if report["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
