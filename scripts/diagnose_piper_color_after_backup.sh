#!/usr/bin/env bash
set -euo pipefail
PIPER_PROJECT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PIPER_PROJECT"
PIPER_RECOVERY="$PIPER_PROJECT/results/piper-color-v1/cloud-recovery-20261024"
PIPER_DIAG="$PIPER_RECOVERY/offline-diagnostic"
mkdir -p "$PIPER_DIAG"
exec 9>"$PIPER_DIAG/diagnostic.lock"
flock -n 9 || exit 3
trap 'code=$?; printf "%s\n" "$code" > "$PIPER_DIAG/diagnostic.exit"; if [ "$code" -ne 0 ]; then printf "FAILED\n" > "$PIPER_DIAG/status"; fi' EXIT
printf 'WAITING_FOR_LORA_BACKUP\n' > "$PIPER_DIAG/status"
PIPER_READY=0
for ((piper_try=0; piper_try<360; piper_try++)); do
  piper_status="$(cat "$PIPER_RECOVERY/backup-logs/weights.status" 2>/dev/null || true)"
  if [[ "$piper_status" == 'pi05_piper_color_full/v1/1000' || "$piper_status" == 'COMPLETE' ]]; then
    PIPER_READY=1
    break
  fi
  if test -f "$PIPER_RECOVERY/backup-logs/weights.exit"; then
    echo 'Weight backup stopped before LoRA checkpoint became ready' >&2
    exit 4
  fi
  sleep 30
done
test "$PIPER_READY" = 1
printf 'WAITING_FOR_FREE_LOCAL_GPU\n' > "$PIPER_DIAG/status"
PIPER_READY=0
for ((piper_try=0; piper_try<240; piper_try++)); do
  piper_compute="$(nvidia-smi --query-compute-apps=pid --format=csv,noheader)"
  piper_free="$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -n 1 | tr -d ' ')"
  if [[ -z "$piper_compute" && "$piper_free" -ge 12000 ]]; then
    PIPER_READY=1
    break
  fi
  sleep 30
done
test "$PIPER_READY" = 1
export PIPER_COLOR_RUN="$PIPER_RECOVERY"
printf 'RUNNING_LOCAL_INFERENCE\n' > "$PIPER_DIAG/status"
timeout --signal=TERM --kill-after=30s 20m scripts/run.sh openpi tasks/piper_color_v1/audit_policy_offline.py \
  --checkpoint "$PIPER_RECOVERY/checkpoints/pi05_piper_color_lora/v1/1499" \
  --data "$PIPER_PROJECT/results/piper-color-v1/dataset-v1" --output "$PIPER_DIAG"
printf 'COMPLETE\n' > "$PIPER_DIAG/status"
