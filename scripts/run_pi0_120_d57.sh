#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
STAGE=${1:?Expected generate|prepare|train|serve|evaluate}
shift
export PIPER_OPENPI="$ROOT/../pi0/openpi"
export PIPER_COLOR_RUN=${PIPER_COLOR_RUN:?Set absolute run directory}
export PIPER_COLOR_DATA="$PIPER_COLOR_RUN/dataset"
export PIPER_BASE_PARAMS="$ROOT/../assets/openpi-assets/checkpoints/pi0_base/params"
if [[ "$STAGE" == generate || "$STAGE" == evaluate ]]; then
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
  generate) exec taskset -c 0-3 nice -n 10 python -u tasks/piper_color_v1/prepare_pi0_120.py "$@" ;;
  prepare|train) exec taskset -c 0-7 nice -n 10 python -u tasks/piper_color_v1/train_pi0_120.py "$STAGE" "$@" ;;
  serve) exec taskset -c 0-7 nice -n 10 python -u tasks/piper_color_v1/serve.py --model-family pi0 --mode lora --port 18767 "$@" ;;
  evaluate) exec taskset -c 0-3 nice -n 10 python -u tasks/piper_color_v1/evaluate_pi0_120.py \
      --model-family pi0 --mode lora --seed-scope episode --replan-steps 5 --steps 420 \
      --data "$PIPER_COLOR_DATA" --policy-host 127.0.0.1 --policy-port 18767 "$@" ;;
  *) exit 2 ;;
esac
