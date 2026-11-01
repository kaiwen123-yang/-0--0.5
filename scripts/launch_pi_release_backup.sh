#!/usr/bin/env bash
set -uo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
STAGE="$ROOT/runtime/pi-complete-backup-20261101"
mkdir -p "$STAGE"
cd "$ROOT"
if [[ -f "$STAGE/supervisor.exit" ]]; then
  mv -- "$STAGE/supervisor.exit" "$STAGE/supervisor.previous-$(date -u +%Y%m%dT%H%M%S).exit"
fi
export PI_BACKUP_DOWNLOAD_PROXY=http://127.0.0.1:7890
taskset -c 0-3 nice -n 10 /root/miniconda3/bin/python -u scripts/pi_release_backup.py all >> "$STAGE/supervisor.log" 2>&1
rc=$?
printf '%s\n' "$rc" > "$STAGE/supervisor.exit"
exit "$rc"
