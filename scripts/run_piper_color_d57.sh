#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
MODE=${1:?Usage: run_piper_color_d57.sh serve|evaluate|sim [arguments]}
shift
export PIPER_OPENPI="$ROOT/../pi05/openpi"
export PIPER_COLOR_DATA="$ROOT/results/piper-color-v1/dataset-v1"
export PIPER_BASE_PARAMS="$ROOT/../assets/openpi-assets/checkpoints/pi05_base/params"
RECOVERY="$ROOT/results/piper-color-v1/cloud-recovery-20261024"
case "$MODE" in
  serve)
    source "$ROOT/../pi05/activate.sh"
    # The project environment remains unchanged. Only this process gets these settings.
    export JAX_COMPILATION_CACHE_DIR="$ROOT/runtime/jax-color-cache"
    export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2
    cd "$ROOT"
    exec nice -n 10 python -u tasks/piper_color_v1/serve.py --mode lora \
      --checkpoint "$RECOVERY/checkpoints/pi05_piper_color_lora/v1/1499" \
      --norm-stats "$RECOVERY/assets/piper_h_color_v1" --port 18765 "$@"
    ;;
  evaluate|sim)
    source "$ROOT/runtime/d57-color-sim/bin/activate"
    unset PYTHONPATH PYTHONHOME LD_LIBRARY_PATH
    export PYTHONNOUSERSITE=1 MUJOCO_GL=egl PYOPENGL_PLATFORM=egl
    export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2
    cd "$ROOT"
    if [[ "$MODE" == evaluate ]]; then
      exec nice -n 10 python -u tasks/piper_color_v1/evaluate.py --mode lora \
        --policy-host 127.0.0.1 --policy-port 18765 --data "$PIPER_COLOR_DATA" \
        --checkpoint "$RECOVERY/checkpoints/pi05_piper_color_lora/v1/1499" \
        --norm-stats "$RECOVERY/assets/piper_h_color_v1" "$@"
    else
      exec nice -n 10 python -u "$@"
    fi
    ;;
  *) printf 'Unknown entry: %s\n' "$MODE" >&2; exit 2 ;;
esac
