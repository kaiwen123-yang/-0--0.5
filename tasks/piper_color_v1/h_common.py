"""The single authorized H500 recovery-data contrast."""
from bct_common import ROOT, OLD, ASSET, COLORS, read, save, now, key, trial_id, gh_env, git
TASK = 'pi0-h500-recovery-20261103'
CAMPAIGN = ROOT / 'outputs' / TASK
RESULTS = ROOT / 'results/piper-color-v1' / TASK
PREVIOUS = ROOT / 'results/piper-color-v1/pi0-ef-local-20261102'
RECOVERY = ROOT / 'outputs/pi0-held-recovery-20261103/dataset'
RECOVERY_RECORDS = ROOT / 'results/piper-color-v1/pi0-held-recovery-20261103'
DATA = ROOT / 'outputs/pi0-120-demo-v2-20261101/dataset'
BRANCH = 'codex/' + TASK
CHECKPOINT = CAMPAIGN / 'H/checkpoints/pi0_piper_color_lora/h_recovery/500'
NORM = CAMPAIGN / 'H/assets' / ASSET
ENTRY = ROOT / 'scripts/run_pi0_h_d57.sh'
