#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
ENV="$ROOT/runtime/d57-color-sim"
UV=/root/autodl-tmp/tools/uv-env/bin/uv
export UV_CACHE_DIR="$ROOT/runtime/uv-color-cache" UV_LINK_MODE=copy
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2
if [[ ! -x "$ENV/bin/python" ]]; then
  "$UV" venv --python "$ROOT/../pi05/openpi/.venv/bin/python" "$ENV"
fi
if [[ -f "$ROOT/deployment/d57/color-sim.freeze.txt" ]]; then
  "$UV" pip install --python "$ENV/bin/python" --index-url https://mirrors.aliyun.com/pypi/simple \
    --link-mode copy -r "$ROOT/deployment/d57/color-sim.freeze.txt"
else
  "$UV" pip install --python "$ENV/bin/python" --index-url https://mirrors.aliyun.com/pypi/simple \
    --link-mode copy -r "$ROOT/deployment/d57/color-sim-requirements.txt" \
    "$ROOT/../pi05/openpi/packages/openpi-client"
fi
"$UV" pip check --python "$ENV/bin/python"
"$UV" pip freeze --python "$ENV/bin/python" > "$ROOT/deployment/d57/color-sim.freeze.txt"
