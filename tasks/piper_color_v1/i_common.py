"""I500: only the evidenced teacher rotation-transition correction."""
from bct_common import ROOT, OLD, ASSET, COLORS, read, save, now, key, trial_id, gh_env, git
TASK = 'pi0-i500-rotation-20261104'
CAMPAIGN = ROOT / 'outputs' / TASK
RESULTS = ROOT / 'results/piper-color-v1' / TASK
HISTORY = ROOT / 'outputs/pi0-h500-recovery-20261103'
PREVIOUS = ROOT / 'results/piper-color-v1/pi0-ef-local-20261102'
COLLECTION = ROOT / 'outputs/pi0-held-rotation-20261104'
ORIGINAL_RECOVERY = ROOT / 'outputs/pi0-held-recovery-20261103/dataset'
RECOVERY = CAMPAIGN / 'recovery_dataset'
DATA = ROOT / 'outputs/pi0-120-demo-v2-20261101/dataset'
BRANCH = 'codex/' + TASK
CHECKPOINT = CAMPAIGN / 'I/checkpoints/pi0_piper_color_lora/i_rotation/500'
NORM = CAMPAIGN / 'I/assets' / ASSET
ENTRY = ROOT / 'scripts/run_pi0_i_d57.sh'
