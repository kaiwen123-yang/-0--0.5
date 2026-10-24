#!/usr/bin/env bash
set -euo pipefail
PI_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PI_PYTHON=/home/fanyuan/miniconda3/envs/kaiwen-learn/bin/python
cd "$PI_ROOT"
mkdir -p logs cache envs results
if [[ ! -x envs/tools/bin/uv ]]; then
  "$PI_PYTHON" -m pip install --target "$PI_ROOT/envs/tools" uv==0.9.9
fi
if [[ ! -d envs/openpi/lib ]]; then
  "$PI_PYTHON" -m venv envs/openpi
fi
export GIT_LFS_SKIP_SMUDGE=1 UV_LINK_MODE=copy
export UV_CACHE_DIR="$PI_ROOT/cache/uv"
# Override the stale user-global Git proxy only in this process.
export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=http.proxy GIT_CONFIG_VALUE_0="${HTTPS_PROXY:-}"
envs/tools/bin/uv pip install --python envs/openpi/bin/python \
  --index https://download.pytorch.org/whl/cu128 \
  --default-index https://pypi.tuna.tsinghua.edu.cn/simple \
  --index-strategy unsafe-best-match -r envs/openpi-cu128-requirements.txt
envs/tools/bin/uv pip install --python envs/openpi/bin/python pytest==8.3.4 pynvml==12.0.0
scripts/run.sh openpi scripts/patch_transformers.py
envs/tools/bin/uv pip freeze --python envs/openpi/bin/python > envs/openpi-freeze.txt
envs/tools/bin/uv pip check --python envs/openpi/bin/python
