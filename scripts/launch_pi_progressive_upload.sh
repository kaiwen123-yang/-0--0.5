#!/usr/bin/env bash
set -uo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
mkdir -p runtime/pi-progressive-upload-20261101
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
taskset -c 8-9 ionice -c 3 /root/miniconda3/bin/python -u tasks/piper_color_v1/upload_pi_progressive.py >> runtime/pi-progressive-upload-20261101/queue.log 2>&1
rc=$?
printf '%s\n' "$rc" > runtime/pi-progressive-upload-20261101/queue.exit
exit "$rc"
