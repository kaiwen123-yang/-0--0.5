#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
STAGE=${1:?Expected train|serve|worker}
shift
export PIPER_OPENPI="$ROOT/../pi0/openpi"
export PIPER_COLOR_RUN=${PIPER_COLOR_RUN:-"$ROOT/outputs/pi0-g-fixed-vision-20261103"}
export PIPER_COLOR_DATA="$ROOT/outputs/pi0-120-demo-v2-20261101/dataset"
export PIPER_BASE_PARAMS="$ROOT/../assets/openpi-assets/checkpoints/pi0_base/params"
# Network settings are supplied only inside GitHub transport subprocesses.
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
if [[ "$STAGE" == worker ]]; then
  source "$ROOT/runtime/d57-color-sim/bin/activate"
  unset PYTHONPATH PYTHONHOME LD_LIBRARY_PATH
  export PYTHONNOUSERSITE=1 MUJOCO_GL=egl PYOPENGL_PLATFORM=egl
else
  source "$ROOT/../pi0/activate.sh"
  export JAX_COMPILATION_CACHE_DIR="$ROOT/runtime/jax-pi0-six-cache"
  export XLA_PYTHON_CLIENT_PREALLOCATE=false XLA_PYTHON_CLIENT_MEM_FRACTION=0.50
fi
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2
cd "$ROOT"
case "$STAGE" in
  train) exec taskset -c 0-7 python -u tasks/piper_color_v1/train_pi0_g.py "$@" ;;
  serve) exec taskset -c 0-7 python -u tasks/piper_color_v1/serve_pi0_g.py "$@" ;;
  worker) exec taskset -c 0-3 python -u tasks/piper_color_v1/worker_pi0_g.py "$@" ;;
  *) exit 2 ;;
esac
