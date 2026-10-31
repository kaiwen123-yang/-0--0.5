#!/usr/bin/env bash
set -euo pipefail
PI_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PI_ENV="${1:?Usage: run.sh openpi|libero|piper SCRIPT.py or -m MODULE}"
shift
case "$PI_ENV" in openpi|libero|piper) ;; *) echo "Unknown environment: $PI_ENV" >&2; exit 2 ;; esac
export OPENPI_DATA_HOME="$PI_ROOT/cache/openpi"
export HF_HOME="$PI_ROOT/cache/huggingface"
export HF_LEROBOT_HOME="$PI_ROOT/data/lerobot"
export XDG_CACHE_HOME="$PI_ROOT/cache"
export NUMBA_CACHE_DIR="$PI_ROOT/cache/numba"
export MPLCONFIGDIR="$PI_ROOT/cache/matplotlib"
export TORCH_HOME="$PI_ROOT/cache/torch"
export WANDB_MODE="${WANDB_MODE:-disabled}"
export XLA_PYTHON_CLIENT_PREALLOCATE=false
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
export OPENBLAS_NUM_THREADS=4
export TOKENIZERS_PARALLELISM=false
export PYTHONNOUSERSITE=1
export LIBERO_CONFIG_PATH="$PI_ROOT/envs/libero/config"
unset PYTHONPATH PYTHONHOME
export PATH="$PI_ROOT/envs/$PI_ENV/bin:$PATH"
exec /home/fanyuan/miniconda3/envs/kaiwen-learn/bin/python -S "$PI_ROOT/scripts/isolated_python.py" "$PI_ENV" "$@"
