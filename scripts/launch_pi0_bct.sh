#!/usr/bin/env bash
set -uo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
RUN="$ROOT/outputs/pi0-b-coverage-correction-test-20261101"
cd "$ROOT"
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
/root/miniconda3/bin/python -u tasks/piper_color_v1/run_pi0_bct.py >> "$RUN/logs/supervisor.log" 2>&1
rc=$?
printf '%s\n' "$rc" > "$RUN/supervisor.exit"
/root/miniconda3/bin/python tasks/piper_color_v1/publish_pi0_bct.py "supervisor-exit-$rc" >> "$RUN/logs/supervisor.log" 2>&1
exit "$rc"
