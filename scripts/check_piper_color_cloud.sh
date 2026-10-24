#!/usr/bin/env bash
set -euo pipefail
PIPER_PROJECT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec ssh -i "$PIPER_PROJECT/runtime/ssh/autodl_piper_color_ed25519" -p 47745 \
  -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=12 -o ConnectionAttempts=3 \
  -o ServerAliveInterval=10 -o ServerAliveCountMax=2 -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile="$PIPER_PROJECT/results/autodl-known-hosts" \
  root@connect.westd.seetacloud.com '
tmux list-panes -t piper-color-v1:pipeline -F "session=#{session_name} pid=#{pane_pid} exited=#{pane_dead} code=#{pane_dead_status}"
cat /root/autodl-fs/pi05/piper-color-v1/logs/status
tail -n 12 /root/autodl-fs/pi05/piper-color-v1/logs/pipeline.log
nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv
for mode in lora full; do
  if test -f "/root/autodl-fs/pi05/piper-color-v1/${mode}_metrics.jsonl"; then
    tail -n 2 "/root/autodl-fs/pi05/piper-color-v1/${mode}_metrics.jsonl"
  fi
done
if test -f /root/autodl-fs/pi05/piper-color-v1/logs/pipeline.exit; then
  cat /root/autodl-fs/pi05/piper-color-v1/logs/pipeline.exit
fi
'
