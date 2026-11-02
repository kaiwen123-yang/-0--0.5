"""Fixed scope and small atomic records for the B coverage/correction/test run."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
TASK = 'pi0-ef-local-20261102'
CAMPAIGN = ROOT / 'outputs' / TASK
BRANCH = 'codex/pi0-b-coverage-correction-test-20261101'
V2 = ROOT / 'outputs/pi0-120-demo-v2-20261101'
AB = ROOT / 'outputs/pi0-ab-old2010-20261101'
OLD = AB / 'B/checkpoints/pi0_piper_color_lora/ab_old2010/2010'
DIAG = ROOT / 'outputs/pi0-120-regression-diagnosis-20261101'
ASSET = 'piper_h_color_v1'
BASE, BUDGET, BATCH, PORT = 4020, 1000, 4, 18770
COLORS = ('red', 'green', 'blue')
TRANSFER = ROOT / 'runtime/pi-progressive-upload-20261101'

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def read(path):
    return json.loads(Path(path).read_text())

def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))
    tmp.replace(path)

def append(path, value):
    with Path(path).open('a') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + '\n')

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(8 << 20), b''):
            h.update(block)
    return h.hexdigest()

def gh_env():
    from bct_common import gh_env as active_transport_env
    return active_transport_env()

def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True, timeout=30).strip()

def roster(split, layouts, seeds):
    return [dict(split=split, layout=l, target=c, base_seed=s) for s in seeds for l in layouts for c in COLORS]

def key(row):
    return (row['split'], row['layout'], row['target'], row['base_seed'])

def trial_id(row):
    return f"{row['split']}_{row['layout']:05d}_{row['target']}_seed{row['base_seed']}"

def checkpoint(group, local):
    return CAMPAIGN / group / 'checkpoints/pi0_piper_color_lora/ef_local' / str(local)

def inventory(path, hashes=False):
    return [dict(path=str(p.relative_to(path)), bytes=p.stat().st_size,
                 **({'sha256': sha(p)} if hashes else {}))
            for p in sorted(Path(path).rglob('*')) if p.is_file()]
