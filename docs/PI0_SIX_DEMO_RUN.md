# Pi0 six-demonstration development run

Authorized on 2026-10-31. This executes step 1 of `PI0_FIRST_PLAN.md` and stops after its evaluations. It does not start full-dataset training, Pi0.5 training, or hardware actions.

Configuration: official `pi0_base`, JAX LoRA on both Gemma modules, `pi05=False`, continuous state (`discrete_state_input=False`), upstream PI0 mean/std normalization. The six demonstrations are train layouts 100 and 101 × red/green/blue, 1,608 observation starts. Only this subset supplies state and action normalization statistics. Six joints use deltas from measured state; gripper opening remains absolute metres. Horizon 10, two RGB cameras, 20 Hz control, and five actions per replanning call are unchanged.

The fixed budget is batch 4 × 2,010 updates. Five saved permutations each visit all 1,608 starts once, using NumPy PCG64 seeds 42–46. Initialization/training seed is 42; the learning rate has 100 warmup updates, peak 3e-5, final 3e-6, and a fixed 2,010-step cosine schedule. OpenPI's initialization, optimizer, training step, transforms, and checkpoint format are used from commit `215abfb217dbac7d5f1273282331b9b1866c0479`.

Checkpoints at exactly 500, 1,000, 1,500, 2,000 and 2,010 **completed updates** retain parameters, optimizer/train state, normalization assets, sampling offset and RNG metadata. The directory name is the completed update count, unlike the historical zero-based iteration directories. Saved sample order and the RNG fold-in rule support continuation without silently restarting the sampler. Actual resume execution has not yet been qualified.

After training exits, all five checkpoints are evaluated on all six training tasks with base seed 42. The final checkpoint is also evaluated with base seed 43. Per-episode seed = base seed + layout seed × 3 + color index. Success retains the original full-task conditions continuously for two seconds: correct block in box, no wrong block in box, open gripper, distractor displacement below 2.5 cm, and joint violation below 0.01 rad. Videos and physical/action trajectories are retained. Stage observations do not replace task success. Evaluation pauses the physics clock during inference and does not measure real-time hardware readiness.

The Pi0 environment is isolated from Pi0.5, SuperMimic and MPC-RL. CPU affinity is eight cores for training/inference and four for simulation. JAX preallocation is disabled, with a 0.50 allocator memory fraction. GPU compute remains shared, so throughput can vary. Training and evaluation run sequentially to avoid loading both Pi0 processes together.

## Launch and inspect

Server workspace: `/root/autodl-tmp/robot-repro/pi-reproduction`.

```bash
cd /root/autodl-tmp/robot-repro/pi-reproduction
tmux new-session -d -s pi0-six-demo-20261031 \
  'set -o pipefail; /root/miniconda3/bin/python -u tasks/piper_color_v1/run_pi0_six.py --run outputs/pi0-six-demo-20261031 2>&1 | tee outputs/pi0-six-demo-20261031.tmux.log'

tmux attach -t pi0-six-demo-20261031
tail -n 20 outputs/pi0-six-demo-20261031/logs/train.log
cat outputs/pi0-six-demo-20261031/training_progress.json
cat outputs/pi0-six-demo-20261031/training_eta.json
cat outputs/pi0-six-demo-20261031/run.json
```

Use a new run directory for a new experiment. The runner refuses to overwrite one and uses an exclusive project lock. A failed evaluation or publication is recorded and stops the pipeline; there is no automatic extension of the training budget.

## Logs and GitHub cadence

`lora_metrics.jsonl` records **every update**, including step, loss, gradient norm, parameter norm, timestamp, compute duration, sample count and equivalent start epochs. At 500/1000/1500/2000, and additionally at 2010, compact logs, exact configuration, normalization, data selection, and local checkpoint inventories are committed and pushed to `codex/pi0-six-demo-20261031`. Completion of all evaluations triggers a final push. Failures trigger one bounded publication attempt.

GitHub snapshots are under `results/piper-color-v1/pi0-six-demo-20261031`. Full checkpoints, MP4 videos and NPZ trajectories stay on D57; this log-publication task does not claim those large files have been uploaded. `publication_receipts.jsonl` records actual push commits. A run is successful only when the final checkpoint completes 6/6 under both fixed evaluation seeds. Failure records remain in the report.
