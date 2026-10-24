#!/usr/bin/env bash
set -euo pipefail
PI_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PI_PYTHON=/home/fanyuan/miniconda3/envs/kaiwen-learn/bin/python
PI_UV="$PI_ROOT/envs/tools/bin/uv"
export UV_CACHE_DIR="$PI_ROOT/cache/uv" UV_LINK_MODE=copy
if [[ ! -x "$PI_ROOT/envs/libero/bin/python" ]]; then
  "$PI_PYTHON" -m venv "$PI_ROOT/envs/libero"
fi
"$PI_UV" pip sync --python "$PI_ROOT/envs/libero/bin/python"   "$PI_ROOT/envs/libero/requirements.lock"   --extra-index-url https://download.pytorch.org/whl/cpu   --index-strategy unsafe-best-match
"$PI_UV" pip install --python "$PI_ROOT/envs/libero/bin/python" --no-deps   -e "$PI_ROOT/repos/openpi/third_party/libero"   -e "$PI_ROOT/repos/openpi/packages/openpi-client"
"$PI_UV" pip check --python "$PI_ROOT/envs/libero/bin/python"
