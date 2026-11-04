"""Publish I source and compact evidence; all large artifacts stay on the server."""
import fcntl, os, shutil, subprocess
from pathlib import Path
from i_common import *


def publish(stage):
    with (ROOT/'runtime/pi-bct-publication.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        RESULTS.mkdir(parents=True,exist_ok=True)
        for source_root,destination_root in ((CAMPAIGN,RESULTS),(COLLECTION,ROOT/'results/piper-color-v1/pi0-held-rotation-20261104')):
            for current,dirs,files in os.walk(source_root):
                dirs[:]=[d for d in dirs if d not in ('checkpoints','assets','scene','logs')]
                for name in files:
                    source=Path(current)/name
                    if source.suffix not in ('.json','.jsonl','.txt','.md','.exit'):
                        continue
                    destination=destination_root/source.relative_to(source_root)
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(source,destination)
        paths=[str(RESULTS.relative_to(ROOT)),'results/piper-color-v1/pi0-held-rotation-20261104',
          'results/piper-color-v1/pi0-h-numeric-review-20261104','AGENTS.md',
          'docs/PI0_H500_REVIEW_NEXT_PLAN_20261104.md','docs/PI0_I500_ROTATION_EXECUTION_20261104.md',
          'tasks/piper_color_v1/i_common.py','tasks/piper_color_v1/collect_pi0_i_rotation.py',
          'tasks/piper_color_v1/analyze_pi0_h_numeric_windows.py','tasks/piper_color_v1/analyze_pi0_i_rotation.py',
          'tasks/piper_color_v1/explain_pi0_h_failure_timing.py','scripts/run_pi0_i_d57.sh','scripts/run_pi0_i_collection_d57.sh']
        paths += [str(p.relative_to(ROOT)) for p in (ROOT/'tasks/piper_color_v1').glob('*pi0_i.py')]
        git('add','--',*paths)
        if git('diff','--cached','--name-only','--',*paths):
            git('commit','-m','Record I500 teacher rotation contrast: '+stage,'--only','--',*paths)
        commit=git('rev-parse','HEAD')
        try:
            env=gh_env()
            proc=subprocess.run(['git','-C',str(ROOT),'-c','http.proxy='+env['https_proxy'],
              '-c','http.version=HTTP/1.1','push','origin','HEAD:refs/heads/'+BRANCH],
              env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=90)
            receipt=dict(stage=stage,commit=commit,at_utc=now(),status='pushed' if proc.returncode==0 else 'pending',
                output=proc.stdout[-1500:],branch=BRANCH,transport='autodl_academic_only')
        except Exception as exc:
            receipt=dict(stage=stage,commit=commit,at_utc=now(),status='pending',error=str(exc),branch=BRANCH,
                         transport='autodl_academic_only')
        save(CAMPAIGN/'publication_delivery.json',receipt)
        print('I_GIT_PUBLICATION',receipt['status'],commit,stage,flush=True)
        return receipt['status']=='pushed'
