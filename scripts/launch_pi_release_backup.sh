#!/usr/bin/env bash
set -uo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
STAGE="$ROOT/runtime/pi-complete-backup-20261101"
mkdir -p "$STAGE"
cd "$ROOT"
taskset -c 0-3 nice -n 10 /root/miniconda3/bin/python -u scripts/pi_release_backup.py all >> "$STAGE/supervisor.log" 2>&1
rc=$?
printf '%s\n' "$rc" > "$STAGE/supervisor.exit"
exit "$rc"
