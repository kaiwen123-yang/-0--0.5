# E/F local-state adaptation

Execution follows PI0_NEXT_STAGE_PLAN_20261102.md. Source remains codex/pi0-b-coverage-correction-test-20261101, based on reviewed 9b30982. B full state is ab_old2010/2010 with cumulative optimizer 4020.

Campaign outputs/pi0-ef-local-20261102. tmux pi0-ef-local-20261102 runs E/F 500 first, validation 75 + training development 48 each, then conditionally both 1000. B development episodes reused. v2 20Hz/horizon10/replan5/420 steps/40 consecutive success unchanged. Local correction contains 24 completed teacher interventions; prefix counts toward 420, only expert suffix is supervised.

Entry scripts/launch_pi0_ef.sh; live run.json and E/F/training_progress.json. A separate pi-ef-upload-20261102 queue uses only academic acceleration. Experiment and upload status are separate. No hardware or pi0.5 training.

## Background handoff

User authorized closing the foreground once tmux is stable. Computation continues independently.

- Experiment: tmux pi0-ef-local-20261102; outputs/pi0-ef-local-20261102/run.json, evaluation_progress.json, E/F/training_progress.json.
- Transfer: tmux pi-ef-upload-resume-20261102; runtime/pi-progressive-upload-20261101/progress.json and missing.json. B full4020 and v2 data reuse existing Release assets. New correction/state assets are queued first.
- Delivery: tmux pi0-ef-delivery-final-20261102; logs/delivery.log, publication/pi-ef-cleanup-20261102. It waits for experiment completion, generates behavior tables and loss/paired trajectory figures, appends remaining new artifacts to the existing single upload queue, confirms remote names/states/sizes, publishes indexed groups, then deletes only their server output copies. Active dependencies remain until use ends. Environments/upstreams/shared weights/other projects remain untouched.
- Reports: results/piper-color-v1/pi0-ef-local-20261102/candidate_comparison.json, behavior_comparison.json, new_layout_comparison.json, final_report_zh.md (generated at completion).
- Network failure records pending uploads; never falls back to VPN. A failed execution is recorded as failed_requires_inspection; no automatic increase of the 500/1000 budget.
