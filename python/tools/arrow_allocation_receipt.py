"""Measure the bounded Arrow preflight on the RES-566 expansion fixtures.

The script never invokes PyArrow's table reader on either hostile fixture. It records the
serialized/declared dimensions, refusal reason, elapsed wall/CPU time, Python allocation peak
and current process RSS delta for the preflight-only path.
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import json
import os
import platform
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any

from dynamisbench.transport.arrow import ArrowTransportError, read_ipc_stream
from dynamisbench.transport.arrow_limits import (
    MAX_ARROW_DECODED_BYTES,
    MAX_ARROW_IPC_BYTES,
    MAX_ARROW_LOGICAL_VALUES,
    MAX_ARROW_ROWS,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIRECTORY = REPOSITORY_ROOT / "apps" / "workbench" / "src" / "test" / "fixtures" / "arrow"
FIXTURES = (
    {
        "name": "expanded-null-columns",
        "path": "expanded-null-columns.arrow.b64",
        "expected": "too_many_values",
        "declared_rows": 100_000,
        "declared_columns": 256,
        "declared_logical_values": 25_600_000,
        "declared_decoded_buffer_bytes": 0,
    },
    {
        "name": "compressed-buffer-expansion",
        "path": "compressed-buffer-expansion.arrow.b64",
        "expected": "too_large_decoded",
        "declared_rows": 8,
        "declared_columns": 1,
        "declared_logical_values": 8,
        "declared_decoded_buffer_bytes": 8_640_000,
    },
)


def _working_set_bytes() -> int:
    if sys.platform == "win32":

        class ProcessMemoryCountersEx(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCountersEx()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32")  # type: ignore[attr-defined]
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi = ctypes.WinDLL("psapi")  # type: ignore[attr-defined]
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ProcessMemoryCountersEx),
            ctypes.c_ulong,
        ]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        process = kernel32.GetCurrentProcess()
        ok = psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb)
        if not ok:
            raise OSError("GetProcessMemoryInfo failed")
        return int(counters.WorkingSetSize)
    if sys.platform.startswith("linux"):
        resident_pages = int(Path("/proc/self/statm").read_text(encoding="ascii").split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE")
    raise RuntimeError(f"unsupported allocation receipt platform: {sys.platform}")


def _measure(fixture: dict[str, Any]) -> dict[str, Any]:
    path = FIXTURE_DIRECTORY / fixture["path"]
    payload = base64.b64decode(path.read_text(encoding="ascii").strip())
    if len(payload) > MAX_ARROW_IPC_BYTES:
        raise RuntimeError(
            f"fixture unexpectedly exceeds the serialized byte cap: {fixture['name']}"
        )

    before_rss = _working_set_bytes()
    tracemalloc.start()
    start_wall = time.perf_counter()
    start_cpu = time.process_time()
    iterations = 8
    reasons: set[str] = set()
    for _ in range(iterations):
        try:
            read_ipc_stream(payload)
            reasons.add("accepted")
        except ArrowTransportError as error:
            reasons.add(error.reason.value)
    wall_ms = (time.perf_counter() - start_wall) * 1000
    cpu_ms = (time.process_time() - start_cpu) * 1000
    _current, peak_python_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    after_rss = _working_set_bytes()

    if reasons != {fixture["expected"]}:
        raise RuntimeError(
            f"{fixture['name']} refusals were {sorted(reasons)}, expected {fixture['expected']}"
        )
    if "pyarrow" in sys.modules:
        raise RuntimeError("preflight imported PyArrow before refusing the hostile fixture")
    if wall_ms > 5_000 or cpu_ms > 5_000:
        raise RuntimeError(f"preflight exceeded its 5 s processing budget: {fixture['name']}")
    if peak_python_bytes > 16 * 1024 * 1024:
        raise RuntimeError(f"preflight exceeded its Python heap budget: {fixture['name']}")
    rss_delta = after_rss - before_rss
    if rss_delta > 32 * 1024 * 1024:
        raise RuntimeError(f"preflight exceeded its RSS growth budget: {fixture['name']}")

    return {
        **fixture,
        "serialized_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "refusal": next(iter(reasons)),
        "iterations": iterations,
        "wall_ms": round(wall_ms, 3),
        "cpu_ms": round(cpu_ms, 3),
        "cpu_us": round(cpu_ms * 1_000, 3),
        "wall_ms_per_iteration": round(wall_ms / iterations, 4),
        "cpu_ms_per_iteration": round(cpu_ms / iterations, 4),
        "python_heap_peak_bytes": peak_python_bytes,
        "rss_before_bytes": before_rss,
        "rss_after_bytes": after_rss,
        "rss_delta_bytes": rss_delta,
        "pyarrow_loaded": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=("windows-x64", "linux-x64"))
    parser.add_argument("--tested-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--image-os", required=True)
    parser.add_argument("--image-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = {
        "authority": "RES-566",
        "source": "bounded pre-table Arrow IPC preflight",
        "target": args.target,
        "tested_sha": args.tested_sha,
        "head_sha": args.head_sha,
        "ref": args.ref,
        "image_os": args.image_os,
        "image_version": args.image_version,
        "python": platform.python_version(),
        "limits": {
            "serialized_bytes": MAX_ARROW_IPC_BYTES,
            "rows": MAX_ARROW_ROWS,
            "logical_values": MAX_ARROW_LOGICAL_VALUES,
            "decoded_buffer_bytes": MAX_ARROW_DECODED_BYTES,
            "wall_ms": 5_000,
            "cpu_ms": 5_000,
            "python_heap_peak_bytes": 16 * 1024 * 1024,
            "rss_growth_bytes": 32 * 1024 * 1024,
        },
        "measurements": [_measure(fixture) for fixture in FIXTURES],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
