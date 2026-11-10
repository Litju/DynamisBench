"""Run one command and record wall time, process-tree CPU time, peak tree RSS and host identity.

    uv run --no-project --with psutil python measure.py --label L --out receipt.json -- <cmd...>

The whole process tree is sampled every 0.25 s; CPU seconds are the sum of the per-process
maximum observed user+system time (processes shorter than the sampling interval can be missed,
so CPU is a lower bound). Peak RSS is the largest instantaneous sum over the tree.
"""
import argparse, json, os, platform, subprocess, sys, time, datetime
import psutil

def tree(p):
    try: return [p] + p.children(recursive=True)
    except psutil.Error: return []

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--label", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("cmd", nargs=argparse.REMAINDER); a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd and a.cmd[0] == "--" else a.cmd
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    t0 = time.perf_counter()
    proc = subprocess.Popen(cmd); root = psutil.Process(proc.pid)
    cpu = {}; peak_rss = 0; peak_procs = 0; load = []
    while proc.poll() is None:
        procs = tree(root); rss = 0
        for p in procs:
            try:
                rss += p.memory_info().rss; t = p.cpu_times(); cpu[(p.pid, p.create_time())] = t.user + t.system
            except psutil.Error: pass
        peak_rss = max(peak_rss, rss); peak_procs = max(peak_procs, len(procs))
        load.append(psutil.cpu_percent(interval=None))
        time.sleep(0.25)
    wall = time.perf_counter() - t0
    r = {"label": a.label, "command": cmd, "started_utc": started, "exit_code": proc.returncode,
         "wall_s": round(wall, 2), "cpu_s_lower_bound": round(sum(cpu.values()), 1),
         "peak_tree_rss_mb": round(peak_rss / 2**20, 1), "peak_processes": peak_procs,
         "mean_host_cpu_percent": round(sum(load) / max(1, len(load)), 1),
         "host": {"os": platform.platform(), "cpu": platform.processor(), "logical_cpus": os.cpu_count(),
                  "ram_gb": round(psutil.virtual_memory().total / 2**30, 1), "python": sys.version.split()[0]}}
    open(a.out, "w").write(json.dumps(r, indent=1)); print(json.dumps(r))
    return proc.returncode
sys.exit(main())
