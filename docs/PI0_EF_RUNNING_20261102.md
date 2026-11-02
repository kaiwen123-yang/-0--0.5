# E/F local-state adaptation

Execution follows PI0_NEXT_STAGE_PLAN_20261102.md. Source remains codex/pi0-b-coverage-correction-test-20261101, based on reviewed 9b30982. B full state is ab_old2010/2010 with cumulative optimizer 4020.

Campaign outputs/pi0-ef-local-20261102. tmux pi0-ef-local-20261102 runs E/F 500 first, validation 75 + training development 48 each, then conditionally both 1000. B development episodes reused. v2 20Hz/horizon10/replan5/420 steps/40 consecutive success unchanged. Local correction contains 24 completed teacher interventions; prefix counts toward 420, only expert suffix is supervised.

Entry scripts/launch_pi0_ef.sh; live run.json and E/F/training_progress.json. A separate pi-ef-upload-20261102 queue uses only academic acceleration. Experiment and upload status are separate. No hardware or pi0.5 training.
