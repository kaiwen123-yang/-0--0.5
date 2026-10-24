#!/usr/bin/env bash
set -euo pipefail
PIPER_SOURCE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source /root/autodl-tmp/pi05/env.sh
export PIPER_OPENPI=/root/autodl-tmp/pi05/openpi
export PIPER_COLOR_RUN=/root/autodl-fs/pi05/piper-color-v1
export PIPER_COLOR_DATA="$PIPER_COLOR_RUN/dataset"
export PIPER_BASE_PARAMS=/root/autodl-fs/pi05/models/openpi-assets/checkpoints/pi05_base/params
export PYTHONPATH="$PIPER_SOURCE:/root/autodl-tmp/piper-color-v1/sim_deps"
export MUJOCO_GL=egl
export OMP_NUM_THREADS=8 OPENBLAS_NUM_THREADS=8 MKL_NUM_THREADS=8
export XLA_PYTHON_CLIENT_MEM_FRACTION=0.85
export WANDB_MODE=disabled
unset LD_LIBRARY_PATH
mkdir -p "$PIPER_COLOR_RUN/logs"
exec 9>"$PIPER_COLOR_RUN/pipeline.lock"
flock -n 9 || { echo 'Piper pipeline already running'; exit 3; }
trap 'code=$?; printf "%s\n" "$code" > "$PIPER_COLOR_RUN/logs/pipeline.exit"; if [ "$code" -ne 0 ]; then printf "FAILED\n" > "$PIPER_COLOR_RUN/logs/status"; fi' EXIT
stage() {
  local piper_stage="$1"; shift
  printf '%s\n' "$piper_stage" > "$PIPER_COLOR_RUN/logs/status"
  printf '%s %s\n' "$(date -Iseconds)" "$piper_stage"
  timeout --signal=TERM --kill-after=60s 3h "$@" > "$PIPER_COLOR_RUN/logs/$piper_stage.log" 2>&1
  printf '0\n' > "$PIPER_COLOR_RUN/logs/$piper_stage.exit"
}
cd "$PIPER_SOURCE"
stage dataset-audit python -u dataset.py "$PIPER_COLOR_DATA"
stage norm-stats python -u train_task.py prepare
stage teacher-cloud-check python -u sim.py --output "$PIPER_COLOR_RUN/cloud_teacher_check" --seed 2000 --target blue --video
python -c 'import json,os; from pathlib import Path; assert json.loads((Path(os.environ["PIPER_COLOR_RUN"])/"cloud_teacher_check/result.json").read_text())["success"]'
stage base-validation python -u evaluate.py --mode base --split validation
stage train-lora python -u train_task.py lora --steps 1500 --batch 4
stage lora-validation python -u evaluate.py --mode lora --split validation
stage train-full python -u train_task.py full --steps 1500 --batch 4
stage full-validation python -u evaluate.py --mode full --split validation
stage lora-test python -u evaluate.py --mode lora --split test
stage full-test python -u evaluate.py --mode full --split test
stage report python -u report.py
printf 'COMPLETE\n' > "$PIPER_COLOR_RUN/logs/status"
# No shutdown / reboot command: user explicitly requested the rented instance stay on.
