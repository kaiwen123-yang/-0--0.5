#!/usr/bin/env bash
cd /root/autodl-tmp/robot-repro/pi-reproduction
export PIPER_COLOR_RUN="$PWD/outputs/pi0-ef-local-20261102"
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2
runtime/d57-color-sim/bin/python -u tasks/piper_color_v1/run_pi0_ef.py >> outputs/pi0-ef-local-20261102/logs/supervisor.log 2>&1
rc=$?
printf '%s\n' "$rc" > outputs/pi0-ef-local-20261102/supervisor.exit
exit "$rc"
