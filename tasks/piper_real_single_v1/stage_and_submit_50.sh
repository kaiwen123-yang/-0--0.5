#!/usr/bin/env bash
# Run on the collection host. --wait waits for sealed, independent layout pairs.
set -euo pipefail

wait_for_pairs=false
case "$#:${1-}" in
    0:) ;;
    1:--wait) wait_for_pairs=true ;;
    *) echo "Usage: bash $0 [--wait]" >&2; exit 2 ;;
esac

task_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo=$(git -C "$task_dir" rev-parse --show-toplevel)
module=tasks/piper_real_single_v1
python=/usr/bin/python3
q=/home/kaiwen/research/pi-q12-data
train=("$q/pickplace_20261124_T01" "$q/pickplace_20261124_T02")
validation="$q/pickplace_20261124_V01"
master="$q/four_colors_direct_20261124_50_v1"
stage_name=blue_red_direct_20261124_50_v1
stage="$q/$stage_name"
experiment=dc1_wrist_direct_blue_red_20261124_50_v1
remote=autodl-dog-arm
remote_repo=/root/autodl-tmp/robot-repro/pi-reproduction
remote_root=/root/autodl-tmp/robot-repro/piper-real-single-v1
destination="$remote_root/data/$stage_name"
budget=("$python" -B "$task_dir/collection_budget.py")
export RSYNC_RSH='ssh -o BatchMode=yes'

previous=
while ! progress=$("${budget[@]}" --train "${train[@]}" --validation "$validation" --require-ready); do
    # Exceptions print a traceback on stderr. Only a valid incomplete budget is waitable.
    summary=$(echo "$progress" | "$python" -c '
import json, sys
r = json.load(sys.stdin)
if r["ready"] is not False:
    sys.exit("Unexpected budget response")
print("Sealed pairs: train %d/20, validation %d/5" % (r["paired_layouts"]["train"], r["paired_layouts"]["validation"]))
')
    if [[ "$previous" != "$summary" ]]; then
        echo "$summary"
        previous=$summary
    fi
    if [[ "$wait_for_pairs" != true ]]; then exit 1; fi
    sleep 30
done

exec 9>"$q/.upload-${experiment}.lock"
flock -n 9 || { echo "A submission is already active for $experiment" >&2; exit 1; }
# The training launcher and its quota checker must both be part of the deployed module.
git -C "$repo" ls-files --error-unmatch "$module/collection_budget.py" "$module/night_train.sh" >/dev/null
if [[ ! -e "$master" && ! -L "$master" ]]; then
    bash "$task_dir/pi_demo.sh" export "$master" --train "${train[@]}" --validation "$validation"
fi
"$python" -B - "$task_dir" "$master" "${train[@]}" "$validation" <<'PY'
import json
from pathlib import Path
import sys
task, master, t01, t02, v01 = map(Path, sys.argv[1:])
sys.path.insert(0, str(task))
from demo_export import freeze_attempts
if not master.is_dir() or master.is_symlink() or json.loads((master/"dataset.json").read_text()).get("collection_view") != "all_colors":
    raise ValueError(f"Unrecognized master dataset: {master}")
requested = freeze_attempts({"train": [t01,t02], "validation": [v01]})
frozen = json.loads((master/"attempts.json").read_text())
approved = {k:v for k,v in requested.items() if v["approved_episode"]}
if {r["run_id"]:r for r in frozen if r["approved_episode"]} != approved:
    raise ValueError(f"Frozen master differs from the approved sources in these sessions: {master}")
if {r["directory"] for r in json.loads((master/"index.json").read_text())} != set(approved):
    raise ValueError(f"Frozen master index differs from its source identities: {master}")
PY
if [[ ! -e "$stage" && ! -L "$stage" ]]; then
    bash "$task_dir/pi_demo.sh" stage-a "$master" "$stage"
fi
"$python" -B - "$master" "$stage" <<'PY'
import json
from pathlib import Path
import sys
master, stage = map(Path, sys.argv[1:])
meta = json.loads((stage/"dataset.json").read_text())
if stage.is_symlink() or (stage/meta["master_directory"]).resolve() != master:
    raise ValueError(f"Stage A belongs to a different freeze: {stage}")
expected = [r for r in json.loads((master/"index.json").read_text()) if r["target_color"] in ("blue","red")]
actual = json.loads((stage/"index.json").read_text())
if actual != expected or any((stage/r["directory"]).resolve() != master/r["directory"] for r in actual):
    raise ValueError("Stage A episode identities or links differ from the master")
PY
"${budget[@]}" --frozen "$stage" --require-ready
digest=$(cd "$stage" && sha256sum dataset.json index.json alignment_manifest.json | sha256sum | cut -d' ' -f1)

# A private marker binds an interrupted transfer to its source. Never adopt a pre-existing unmarked path.
target=$(ssh -o BatchMode=yes "$remote" bash -s -- "$destination" "$digest" "$remote_repo" <<'REMOTE'
set -euo pipefail
dest=$1; digest=$2; repo=$3
[[ $(git -C "$repo" rev-parse --show-toplevel) == "$repo" ]]
mkdir -p "$(dirname "$dest")"
if [[ -e "$dest" || -L "$dest" ]]; then
    target=$dest
else
    target=$dest.incoming
    if mkdir "$target" 2>/dev/null; then printf '%s\n' "$digest" >"$target/.pi-stage-identity"; fi
fi
[[ -d "$target" && ! -L "$target" && -f "$target/.pi-stage-identity" && ! -L "$target/.pi-stage-identity" ]]
[[ $(cat "$target/.pi-stage-identity") == "$digest" ]]
[[ -z $(find "$target" -type l -print -quit) ]]
printf '%s\n' "$target"
REMOTE
)
if [[ "$target" == "$destination.incoming" ]]; then
    rsync -aLz --partial-dir=.rsync-partial --info=stats2 "$stage/" "$remote:$target/"
elif [[ "$target" != "$destination" ]]; then
    echo "Unexpected D57 staging path: $target" >&2; exit 1
fi

# Compare names, sizes and mtimes without retransferring payloads. --delete is dry-run only.
differences=$(rsync -rniL --delete --omit-dir-times --exclude='/.pi-stage-identity' "$stage/" "$remote:$target/")
if [[ -n "$differences" ]]; then printf 'D57 differs from the frozen view:\n%s\n' "$differences" >&2; exit 1; fi

# No training code is replaced if the same experiment was already launched.
phase=$(ssh -o BatchMode=yes "$remote" bash -s -- "$target" "$destination" "$digest" "$experiment" "$remote_root" <<'REMOTE'
set -euo pipefail
target=$1; dest=$2; digest=$3; exp=$4; base=$5
[[ -z $(find "$target" -type l -print -quit) ]]
[[ $(cd "$target" && sha256sum dataset.json index.json alignment_manifest.json | sha256sum | cut -d' ' -f1) == "$digest" ]]
if [[ "$target" != "$dest" ]]; then
    mv -Tn -- "$target" "$dest"
    [[ ! -e "$target" && $(cat "$dest/.pi-stage-identity") == "$digest" ]]
fi
receipt="$base/outputs/launches/$exp"
if [[ -e "$receipt/identity" ]]; then
    [[ $(cat "$receipt/identity") == "$digest" ]]
    if tmux has-session -t "=$exp" 2>/dev/null; then echo running; exit; fi
    if [[ -e "$receipt/exit-code" && $(cat "$receipt/exit-code") == 0 ]]; then echo completed; exit; fi
    if [[ -e "$receipt/started" ]]; then
        echo "Previous launch stopped. Inspect $receipt/train.log and $receipt/exit-code" >&2
        exit 1
    fi
fi
echo ready
REMOTE
)
case "$phase" in
    running|completed) echo "$experiment: $phase"; exit 0 ;;
    ready) ;;
    *) echo "Unexpected experiment status: $phase" >&2; exit 1 ;;
esac

git -C "$repo" ls-files -z -- "$module/" |
    rsync -a --from0 --files-from=- "$repo/" "$remote:$remote_repo/"

ssh -o BatchMode=yes "$remote" bash -s -- "$remote_repo" "$destination" "$experiment" "$remote_root/outputs" "$digest" <<'REMOTE'
set -euo pipefail
repo=$1; dataset=$2; exp=$3; outputs=$4; digest=$5
receipt="$outputs/launches/$exp"
mkdir -p "$outputs/launches"
exec 8>"$outputs/launches/.$exp.lock"
flock -x 8
if mkdir "$receipt" 2>/dev/null; then
    printf '%s\n' "$digest" >"$receipt/identity"
fi
[[ ! -L "$receipt" && $(cat "$receipt/identity") == "$digest" ]]
if tmux has-session -t "=$exp" 2>/dev/null; then
    [[ -f "$receipt/started" ]] || { echo "Unrelated tmux session: $exp" >&2; exit 1; }
    echo "$exp is running"; exit
fi
if [[ -f "$receipt/exit-code" && $(cat "$receipt/exit-code") == 0 ]]; then echo "$exp completed"; exit; fi
for path in "$receipt/started" "$receipt/train.log" "$outputs/night_specs/$exp" "$outputs/pi05/$exp" "$outputs/pi0/$exp"; do
    [[ ! -e "$path" && ! -L "$path" ]] || { echo "Prior experiment output: $path" >&2; exit 1; }
done
code="$repo/tasks/piper_real_single_v1"
"/root/robot-repro-envs/pi05/bin/python" -B "$code/collection_budget.py" --frozen "$dataset" --require-ready >/dev/null
tmux new-session -d -s "$exp" -c "$repo" bash -c '
    set -u
    receipt=$1; code=$2; dataset=$3; exp=$4; outputs=$5
    date -Is >"$receipt/started"
    bash "$code/night_train.sh" "$dataset" "$exp" "$outputs" >>"$receipt/train.log" 2>&1
    rc=$?
    printf "%s\n" "$rc" >"$receipt/exit-code.tmp"
    mv "$receipt/exit-code.tmp" "$receipt/exit-code"
    exit "$rc"
' _ "$receipt" "$code" "$dataset" "$exp" "$outputs"
printf 'D57 night job submitted. tmux=%s log=%s/train.log specs=%s/night_specs/%s\n' "$exp" "$receipt" "$outputs" "$exp"
REMOTE
