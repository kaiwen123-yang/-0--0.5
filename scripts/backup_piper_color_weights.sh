#!/usr/bin/env bash
# Back up inference weights while AutoDL is in no-GPU mode. No training command.
set -euo pipefail
PIPER_PROJECT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PIPER_PROJECT"
PIPER_BACKUP="$PIPER_PROJECT/results/piper-color-v1/cloud-recovery-20261024"
mkdir -p "$PIPER_BACKUP/checkpoints" "$PIPER_BACKUP/backup-logs"
exec 9>"$PIPER_BACKUP/backup-logs/weights.lock"
flock -n 9 || { echo 'This weight backup is already running'; exit 3; }
trap 'code=$?; printf "%s\n" "$code" > "$PIPER_BACKUP/backup-logs/weights.exit"' EXIT
PIPER_SSH="ssh -i $PIPER_PROJECT/runtime/ssh/autodl_piper_color_ed25519 -p 47745 -c aes128-gcm@openssh.com -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=12 -o ConnectionAttempts=3 -o ServerAliveInterval=10 -o ServerAliveCountMax=2 -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$PIPER_PROJECT/results/autodl-known-hosts"
for piper_spec in pi05_piper_color_lora/v1/1499 pi05_piper_color_full/v1/1000; do
  printf '%s %s\n' "$(date -Iseconds)" "$piper_spec"
  printf '%s\n' "$piper_spec" > "$PIPER_BACKUP/backup-logs/weights.status"
  mkdir -p "$PIPER_BACKUP/checkpoints/$piper_spec"
  rsync -a --partial --stats --exclude='/train_state/' -e "$PIPER_SSH" \
    "root@connect.westd.seetacloud.com:/root/autodl-fs/pi05/piper-color-v1/checkpoints/$piper_spec/" \
    "$PIPER_BACKUP/checkpoints/$piper_spec/"
done
printf 'COMPLETE\n' > "$PIPER_BACKUP/backup-logs/weights.status"
printf '%s backup complete; inference params + normalization, optimizer remains on durable cloud storage\n' "$(date -Iseconds)"
