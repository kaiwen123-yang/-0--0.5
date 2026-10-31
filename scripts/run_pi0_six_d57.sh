#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
STAGE=${1:?Usage: run_pi0_six_d57.sh prepare|train|serve|evaluate|summarize [args]}
shift
export PIPER_OPENPI="$ROOT/../pi0/openpi"
export PIPER_SOURCE_DATA="$ROOT/results/piper-color-v1/dataset-v1"
export PIPER_COLOR_RUN=${PIPER_COLOR_RUN:?Set a unique absolute run directory}
export PIPER_COLOR_DATA="$PIPER_COLOR_RUN/dataset"
export PIPER_BASE_PARAMS="$ROOT/../assets/openpi-assets/checkpoints/pi0_base/params"
case "$STAGE" in
  prepare|train|serve)
    source "$ROOT/../pi0/activate.sh"
    export JAX_COMPILATION_CACHE_DIR="$ROOT/runtime/jax-pi0-six-cache"
    export XLA_PYTHON_CLIENT_PREALLOCATE=false XLA_PYTHON_CLIENT_MEM_FRACTION=0.50
    export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2
    cd "$ROOT"
    if [[ "$STAGE" == serve ]]; then
      exec taskset -c 0-7 nice -n 10 python -u tasks/piper_color_v1/serve.py \
        --model-family pi0 --mode lora --port 18766 "$@"
    else
      exec taskset -c 0-7 nice -n 10 python -u tasks/piper_color_v1/train_pi0_six.py "$STAGE" "$@"
    fi
    ;;
  evaluate|summarize)
    source "$ROOT/runtime/d57-color-sim/bin/activate"
    unset PYTHONPATH PYTHONHOME LD_LIBRARY_PATH
    export PYTHONNOUSERSITE=1 MUJOCO_GL=egl PYOPENGL_PLATFORM=egl
    export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2
    cd "$ROOT"
    if [[ "$STAGE" == evaluate ]]; then
      exec taskset -c 0-3 nice -n 10 python -u tasks/piper_color_v1/evaluate.py \
        --model-family pi0 --mode lora --split train --layout-seeds 100 101 \
        --seed-scope episode --replan-steps 5 --steps 420 --data "$PIPER_COLOR_DATA" \
        --policy-host 127.0.0.1 --policy-port 18766 "$@"
    else
      exec nice -n 10 python -u tasks/piper_color_v1/summarize_pi0_six.py "$PIPER_COLOR_RUN"
    fi
    ;;
  *) printf 'Unknown stage: %s\n' "$STAGE" >&2; exit 2 ;;
esac
