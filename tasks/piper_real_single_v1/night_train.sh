#!/usr/bin/env bash
# Run on D57 after copying a frozen blue/red dataset with rsync -aL.
# Each family computes its own norm, then starts its full 10,000-step training.
set -euo pipefail

if (( $# < 2 || $# > 3 )); then
    echo "Usage: bash tasks/piper_real_single_v1/night_train.sh DATASET_ROOT NEW_EXPERIMENT [RUN_ROOT]" >&2
    exit 2
fi

pi_night_task_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
pi_night_repo_root="$(cd -- "$pi_night_task_dir/../.." && pwd)"
pi_night_dataset="$1"
pi_night_experiment="$2"
pi_night_output="$(realpath -m -- "${3:-/root/autodl-tmp/robot-repro/piper-real-single-v1/outputs}")"
pi_night_specs="$pi_night_output/night_specs/$pi_night_experiment"

# These are the existing D57 environments, not new installations.
/root/robot-repro-envs/pi05/bin/python - "$pi_night_task_dir" "$pi_night_dataset" \
    "$pi_night_experiment" "$pi_night_output" "$pi_night_specs" <<'PY'
import json
from pathlib import Path
import sys

task, dataset, experiment, output, destination = sys.argv[1:]
dataset = Path(dataset).expanduser().resolve(strict=True)
output = Path(output).expanduser().resolve()
destination = Path(destination).expanduser().resolve()
specs = {}
for family in ("pi05", "pi0"):
    run = output/family/experiment
    if run.exists():
        raise FileExistsError(f"Existing output {run}; choose a new experiment name.")
    spec = json.loads((Path(task)/f"pickplace_{family}_full.json").read_text())
    spec.update(dataset_root=str(dataset), experiment_name=experiment, run_root=str(output))
    specs[family] = spec
destination.mkdir(parents=True, exist_ok=False)
for family, spec in specs.items():
    (destination/f"{family}.json").write_text(json.dumps(spec, indent=2) + "\n")
print(f"Formal full training, sequential order: pi05 -> pi0. Specs: {destination}")
PY

for pi_night_family in pi05 pi0; do
    (
        source "/root/autodl-tmp/robot-repro/$pi_night_family/activate.sh"
        cd -- "$pi_night_repo_root"
        pi_night_spec="$pi_night_specs/$pi_night_family.json"
        # Record actual occupancy; this script does not stop any existing job.
        nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu --format=csv \
            | tee "$pi_night_specs/$pi_night_family.gpu_before.log"
        nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv \
            | tee "$pi_night_specs/$pi_night_family.processes_before.log"
        python -u -m tasks.piper_real_single_v1.train --spec "$pi_night_spec" --stage prepare-stats \
            2>&1 | tee "$pi_night_specs/$pi_night_family.norm.log"
        python -u -m tasks.piper_real_single_v1.train --spec "$pi_night_spec" --stage train \
            2>&1 | tee "$pi_night_specs/$pi_night_family.train.log"
    )
done
