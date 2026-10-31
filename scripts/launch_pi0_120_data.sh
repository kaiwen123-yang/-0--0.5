#!/usr/bin/env bash
set -uo pipefail
ROOT=/root/autodl-tmp/robot-repro/pi-reproduction
export PIPER_COLOR_RUN="$ROOT/outputs/pi0-120-demo-v2-20261101"
mkdir -p "$PIPER_COLOR_RUN/logs"
bash "$ROOT/scripts/run_pi0_120_d57.sh" generate > "$PIPER_COLOR_RUN/logs/generate.log" 2>&1
rc=$?
printf '%s\n' "$rc" > "$PIPER_COLOR_RUN/generate.exit"
exit "$rc"
