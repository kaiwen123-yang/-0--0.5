"""One parent publisher: H code and small records only, no binary queue."""
import fcntl, os, shutil, subprocess
from pathlib import Path
from h_common import *


def publish(stage):
    with (ROOT / 'runtime/pi-bct-publication.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        RESULTS.mkdir(parents=True, exist_ok=True)
        for current, dirs, files in os.walk(CAMPAIGN):
            dirs[:] = [d for d in dirs if d not in ('checkpoints', 'assets', 'scene', 'logs')]
            for name in files:
                source = Path(current) / name
                if source.suffix not in ('.json', '.jsonl', '.txt', '.md', '.exit'):
                    continue
                destination = RESULTS / source.relative_to(CAMPAIGN)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
        paths = [str(RESULTS.relative_to(ROOT)), 'AGENTS.md', 'docs/PI0_H500_PLAN_20261103.md',
                 'tasks/piper_color_v1/h_common.py', 'scripts/run_pi0_h_d57.sh']
        paths += [str(p.relative_to(ROOT)) for p in (ROOT / 'tasks/piper_color_v1').glob('*pi0_h.py')]
        git('add', '--', *paths)
        if git('diff', '--cached', '--name-only', '--', *paths):
            git('commit', '-m', 'Record H500 recovery data contrast: ' + stage, '--only', '--', *paths)
        commit = git('rev-parse', 'HEAD')
        try:
            env = gh_env()
            proc = subprocess.run(['git', '-C', str(ROOT), '-c', 'http.proxy=' + env['https_proxy'],
                '-c', 'http.version=HTTP/1.1', 'push', 'origin', 'HEAD:refs/heads/' + BRANCH],
                env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
            receipt = dict(stage=stage, commit=commit, at_utc=now(),
                status='pushed' if proc.returncode == 0 else 'pending', output=proc.stdout[-1500:],
                branch=BRANCH, transport='autodl_academic_only')
        except Exception as exc:
            receipt = dict(stage=stage, commit=commit, at_utc=now(), status='pending',
                           error=str(exc), branch=BRANCH, transport='autodl_academic_only')
        save(CAMPAIGN / 'publication_delivery.json', receipt)
        print('H_GIT_PUBLICATION', receipt['status'], commit, stage, flush=True)
        return receipt['status'] == 'pushed'
