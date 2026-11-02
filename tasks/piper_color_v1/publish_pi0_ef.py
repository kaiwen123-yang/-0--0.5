"""Scoped text publication; proxy exists only in GitHub transport children."""
import fcntl
import shutil
import time
from ef_common import *

def publish(campaign, stage):
    campaign=Path(campaign)
    destination=ROOT/'results/piper-color-v1'/TASK
    destination.mkdir(parents=True,exist_ok=True)
    try:
        with (ROOT/'runtime/pi-bct-publication.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            assert git('branch','--show-current')==BRANCH
            staged=git('diff','--cached','--name-only').splitlines()
            if any(not p.startswith(str(destination.relative_to(ROOT))+'/') and not p.startswith('publication/pi-progressive-upload-20261101/') for p in staged):
                raise RuntimeError('Unrelated staged files; keep them intact')
            count=0
            for current,dirs,files in os.walk(campaign,followlinks=False):
                dirs[:]=[d for d in dirs if d not in ('checkpoints','dataset','correction_dataset','assets','scene') and not (Path(current)/d).is_symlink()]
                for name in files:
                    src=Path(current)/name
                    if src.suffix not in ('.json','.jsonl','.txt','.md','.log','.exit'): continue
                    dst=destination/src.relative_to(campaign)
                    dst.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(src,dst); count+=1
            if (campaign/'correction_dataset').exists():
                for src in (campaign/'correction_dataset').glob('*.json'):
                    dst=destination/'correction_dataset'/src.name; dst.parent.mkdir(exist_ok=True); shutil.copyfile(src,dst)
            upload_dest=ROOT/'publication/pi-progressive-upload-20261101'
            if TRANSFER.exists():
                upload_dest.mkdir(parents=True,exist_ok=True)
                for name in ('progress.json','missing.json','mapping.json','reused_groups.json','excluded.json','academic_probe.json','academic_upload_probe.json','transport_change.json'):
                    if (TRANSFER/name).exists(): shutil.copyfile(TRANSFER/name,upload_dest/name)
            save(destination/'publication_status.json',dict(stage=stage,at_utc=now(),text_files=count,
                large_files='Server originals retained; separate progressive upload queue',source_deleted=False))
            paths=[str(destination.relative_to(ROOT))]
            if upload_dest.exists(): paths.append(str(upload_dest.relative_to(ROOT)))
            git('add','--',*paths)
            if git('diff','--cached','--name-only'): git('commit','-m',f'Record pi0 E/F local adaptation: {stage}')
            commit=git('rev-parse','HEAD')
            for attempt in range(1,4):
                try:
                    transport_env=gh_env()
                    result=subprocess.run(['git','-C',str(ROOT),'-c','http.proxy='+transport_env['https_proxy'],'-c','http.version=HTTP/1.1',
                        'push','origin',f'HEAD:refs/heads/{BRANCH}'],env=transport_env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=25)
                    record=dict(stage=stage,at_utc=now(),attempt=attempt,commit=commit,returncode=result.returncode,output=result.stdout[-2500:])
                except subprocess.TimeoutExpired:
                    record=dict(stage=stage,at_utc=now(),attempt=attempt,commit=commit,returncode=124,output='25 second transport timeout')
                append(campaign/'publication_attempts.jsonl',record)
                if record['returncode']==0:
                    receipt=dict(stage=stage,at_utc=now(),commit=commit,status='pushed')
                    append(campaign/'publication_receipts.jsonl',receipt); save(campaign/'publication_delivery.json',receipt)
                    print('GITHUB_PUSHED',commit,stage,flush=True); return True
                time.sleep(attempt*2)
            save(campaign/'publication_delivery.json',dict(status='pending',commit=commit,stage=stage)); return False
    except Exception as exc:
        append(campaign/'publication_errors.jsonl',dict(at_utc=now(),stage=stage,error=repr(exc)))
        save(campaign/'publication_delivery.json',dict(status='pending',stage=stage,error=repr(exc)))
        print('PUBLICATION_PENDING',repr(exc),flush=True); return False

if __name__=='__main__':
    import sys
    raise SystemExit(0 if publish(CAMPAIGN,sys.argv[1]) else 1)
