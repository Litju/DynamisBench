#!/usr/bin/env bash
# RES-622 Gate A matrix. Run from the repository root's python/ directory, on an otherwise idle host.
#   A  serial pytest, one-worker eager prewarm (historical matrix baseline, not unchanged main)
#   B  serial pytest, opt-in four-worker eager prewarm
#   C  pytest-xdist -n 4 --dist loadfile, one-worker eager prewarm per worker
#   D  pytest-xdist -n 4 --dist loadfile + opt-in four-worker prewarm (oversubscription probe)
# Usage: run_matrix.sh <cond> <rep> <outdir>
set -u
cond=$1; rep=$2; out=$3
export DYNAMISBENCH_MUJOCO_PYTHON="$PWD/worker-mujoco/.venv/Scripts/python.exe" DYNAMISBENCH_REQUIRE_MUJOCO=1 HYPOTHESIS_PROFILE=ci
M="uv run --no-project --with psutil python ../evidence/qa/RES-622/analysis/measure.py"
base="uv run --frozen"
case $cond in
  A) export DYNAMISBENCH_QA_SQUAT_PARALLEL=1; extra="" ;;
  B) export DYNAMISBENCH_QA_SQUAT_PARALLEL=4; extra="" ;;
  C) export DYNAMISBENCH_QA_SQUAT_PARALLEL=1; base="uv run --frozen --with pytest-xdist"; extra="-n 4 --dist loadfile" ;;
  D) export DYNAMISBENCH_QA_SQUAT_PARALLEL=4; base="uv run --frozen --with pytest-xdist"; extra="-n 4 --dist loadfile" ;;
esac
$M --label "$cond-r$rep" --out "$out/$cond-r$rep.receipt.json" -- \
  $base pytest -p no:cacheprovider -q --durations=0 $extra --junitxml="$out/$cond-r$rep.xml" \
  > "$out/$cond-r$rep.txt" 2>&1
