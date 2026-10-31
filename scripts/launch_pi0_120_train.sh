#!/usr/bin/env bash
set -uo pipefail
ROOT=/root/autodl-tmp/robot-repro/pi-reproduction
RUN="$ROOT/outputs/pi0-120-demo-v2-20261101"
/root/miniconda3/bin/python -u "$ROOT/tasks/piper_color_v1/run_pi0_120.py" --run "$RUN" > "$RUN/logs/supervisor.log" 2>&1
rc=$?
printf '%s\n' "$rc" > "$RUN/supervisor.exit"
exit "$rc"
