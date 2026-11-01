#!/usr/bin/env bash
set -uo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
CAMPAIGN="$ROOT/outputs/pi0-ab-old2010-20261101"
cd "$ROOT"
/root/miniconda3/bin/python -u tasks/piper_color_v1/run_pi0_ab.py --campaign "$CAMPAIGN" >> "$CAMPAIGN/logs/supervisor.log" 2>&1
rc=$?
printf '%s\n' "$rc" > "$CAMPAIGN/supervisor.exit"
/root/miniconda3/bin/python tasks/piper_color_v1/publish_pi0_ab.py "$CAMPAIGN" --stage "supervisor-exit-$rc" >> "$CAMPAIGN/logs/supervisor.log" 2>&1
exit "$rc"
