#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
source "$ROOT/../pi0/activate.sh"
export PIPER_OPENPI="$ROOT/../pi0/openpi"
export PIPER_COLOR_RUN="$ROOT/outputs/pi0-ab-old2010-20261101/B"
export PIPER_COLOR_DATA="$ROOT/outputs/pi0-120-demo-v2-20261101/dataset"
export PIPER_BASE_PARAMS="$ROOT/../assets/openpi-assets/checkpoints/pi0_base/params"
export XLA_PYTHON_CLIENT_PREALLOCATE=false
cd "$ROOT"
exec taskset -c 0-7 nice -n 10 python -u tasks/piper_color_v1/verify_backup_state.py "$@"
