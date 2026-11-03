"""Paths and fixed scope for the single G500 contrast."""
from bct_common import ROOT, OLD, ASSET, COLORS, read, save, now, key, trial_id, roster, gh_env, git
TASK = "pi0-g-fixed-vision-20261103"
CAMPAIGN = ROOT / "outputs" / TASK
RESULTS = ROOT / "results/piper-color-v1" / TASK
PREVIOUS = ROOT / "results/piper-color-v1/pi0-ef-local-20261102"
BRANCH = "codex/" + TASK
PORT = 18771
CHECKPOINT = CAMPAIGN / "G/checkpoints/pi0_piper_color_lora/g_fixed_vision/500"
NORM = CAMPAIGN / "G/assets" / ASSET
