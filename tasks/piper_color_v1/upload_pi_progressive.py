"""Low-priority copies only. Never invoke the cancelled backup/restore/cleanup pipeline."""
import fcntl
import math
import re
import shutil
import tarfile
import threading
import time
import urllib.parse
from bct_common import *

REPO='kaiwen123-yang/-0--0.5'
TAG='pi-complete-backup-20261101'
RATE=4*1024**2
CHUNK=1024**3

def gh(*args,timeout=40):
    return subprocess.check_output(['gh',*args],env=gh_env(),text=True,timeout=timeout,stderr=subprocess.PIPE)

def release(tag):
    obj=json.loads(gh('release','view',tag,'--repo',REPO,'--json','databaseId,assets'))
    return obj['databaseId'],{r['name']:r for r in obj['assets']}

def source_file(group,entry):
    return Path(group['source_workspace'])/entry['path']

def eligible(path):
    # Research outputs only: no papers, source archives, caches or installed environments.
    p=str(path)
    return '/pi-reproduction/outputs/' in p or '/pi-reproduction/results/' in p

def plan():
    catalog=read(ROOT/'runtime/pi-complete-backup-20261101/catalog-working.json')
    index=read(ROOT/'publication/pi-complete-backup-20261101/index.json')
    refs={g['id']:g for g in index['groups']}
    release_cache={}; jobs=[]; reused=[]; excluded=[]; unresolved=[]; mapped_sources=set()
    for group in catalog['groups']:
        gid=group['id']
        if gid.startswith('official-'):
            excluded.append(dict(group=gid,reason='Official base weights excluded; existing assets left intact')); continue
        files=[e for e in group['entries'] if e['type']=='file']
        selected=[e for e in files if eligible(source_file(group,e))]
        if not selected:
            excluded.append(dict(group=gid,reason='Outside experiment data/checkpoint/log/trajectory/video scope')); continue
        if group['tag'] not in release_cache: release_cache[group['tag']]=release(group['tag'])
        _,assets=release_cache[group['tag']]
        parts=refs.get(gid,{}).get('parts') or group.get('parts',[])
        missing_parts=[p for p in parts if p['name'] not in assets or assets[p['name']]['size']!=p['bytes'] or assets[p['name']]['state']!='uploaded']
        if parts and not missing_parts:
            # Source-to-part correspondence comes from the existing catalog, without rereading payloads.
            changed=[e['path'] for e in selected if not source_file(group,e).is_file() or source_file(group,e).stat().st_size!=e['bytes']]
            if changed: unresolved.append(dict(group=gid,reason='Existing source size/path differs from catalog',paths=changed)); continue
            reused.append(dict(group=gid,tag=group['tag'],source_files=len(selected),source_bytes=sum(e['bytes'] for e in selected),
                parts=[dict(name=p['name'],bytes=p['bytes'],state=assets[p['name']]['state']) for p in parts],
                source_mapping='runtime/pi-complete-backup-20261101/catalog-working.json',payload_reread=False))
            mapped_sources.update(str(source_file(group,e)) for e in selected)
            continue
        if parts:
            unresolved.append(dict(group=gid,reason='Partial legacy volume set; preserve existing volumes, no duplicate repack',missing_parts=missing_parts)); continue
        small=[]; total=0
        def bundle():
            nonlocal small,total
            if not small: return
            identity=hashlib.sha256(json.dumps([(e['source'],e['bytes']) for e in small]).encode()).hexdigest()[:16]
            jobs.append(dict(name=f'progressive-{gid}-records-{identity}.tar',kind='small_records_bundle',members=small,
                source_bytes=total,group=gid,status='queued',attempts=0))
            small=[]; total=0
        for e in sorted(selected,key=lambda e:e['path']):
            path=source_file(group,e)
            if str(path) in mapped_sources: continue
            mapped_sources.add(str(path))
            if not path.is_file() or path.stat().st_size!=e['bytes']:
                unresolved.append(dict(source=str(path),reason='Catalog source missing or size changed')); continue
            member=dict(source=str(path),archive_path=e.get('archive_path',e['path']),bytes=e['bytes'],mtime_ns=path.stat().st_mtime_ns,
                existing_sha256=e.get('sha256'))
            if e['bytes']<=8*1024**2:
                if total+e['bytes']>64*1024**2: bundle()
                small.append(member); total+=e['bytes']
            else:
                identity=hashlib.sha256(str(path).encode()).hexdigest()[:16]
                stem=re.sub('[^a-zA-Z0-9._-]','_',path.name)[:60]
                parts_count=math.ceil(e['bytes']/CHUNK) if e['bytes']>=2*1024**3 else 1
                for part in range(parts_count):
                    offset=part*CHUNK if parts_count>1 else 0
                    size=min(CHUNK,e['bytes']-offset) if parts_count>1 else e['bytes']
                    name=f'progressive-{gid}-{identity}-{stem}'+(f'.part-{part:03d}' if parts_count>1 else '')
                    jobs.append(dict(name=name,kind='raw_file_range',members=[member],source_bytes=size,bytes=size,
                        offset=offset,part=part,parts=parts_count,group=gid,status='queued',attempts=0))
        bundle()
    group_order={g['id']:i for i,g in enumerate(catalog['groups'])}
    jobs.sort(key=lambda j:(group_order[j['group']],j['kind']!='small_records_bundle',j['name']))
    save(TRANSFER/'reused_groups.json',reused); save(TRANSFER/'excluded.json',excluded)
    mapping=dict(created_at=now(),release_tag=TAG,scope='previous completed pi experiment outputs; source data retained',jobs=jobs,unresolved=unresolved,
        source_mapping_reference=str(ROOT/'runtime/pi-complete-backup-20261101/catalog-working.json'),source_deletion=False,
        no_restore_or_redownload=True,no_new_payload_hash_scan=True,rate_limit_bytes_per_second=RATE)
    save(TRANSFER/'mapping.json',mapping)
    return mapping

def io_pressure():
    try:
        for line in Path('/proc/pressure/io').read_text().splitlines():
            if line.startswith('full '): return float(dict(x.split('=') for x in line.split()[1:])['avg10'])
    except (OSError,KeyError): pass
    return 0.

def pause_reason():
    if (TRANSFER/'PAUSE').exists(): return 'manual_pause'
    if shutil.disk_usage(ROOT).free<70*1024**3: return 'disk_reserve_for_experiments'
    if io_pressure()>10: return 'system_io_contention'
    return None

def write_status(mapping,status,current=None):
    jobs=mapping['jobs']; reused=read(TRANSFER/'reused_groups.json')
    missing=[dict(name=j['name'],status=j['status'],source_bytes=j['source_bytes'],attempts=j['attempts'],reason=j.get('error')) for j in jobs if j['status']!='uploaded']
    save(TRANSFER/'missing.json',dict(at_utc=now(),assets=missing,unresolved=mapping['unresolved']))
    progress=dict(at_utc=now(),status=status,current=current,pid=os.getpid(),concurrency=1,nice=19,ionice='idle',
        transport='autodl_academic_only',vpn_fallback=False,
        rate_limit_mib_s=4,reused_groups=len(reused),reused_assets=sum(len(g['parts']) for g in reused),
        reused_source_files=sum(g['source_files'] for g in reused),reused_source_bytes=sum(g['source_bytes'] for g in reused),
        planned_new_assets=len(jobs),uploaded_new_assets=sum(j['status']=='uploaded' for j in jobs),
        uploaded_new_bytes=sum(j.get('bytes',0) for j in jobs if j['status']=='uploaded'),pending_assets=len(missing),
        unresolved_groups=len(mapping['unresolved']),source_deleted=False,experiment_status='independent; see campaign run.json')
    save(TRANSFER/'progress.json',progress); save(TRANSFER/'mapping.json',mapping)
    return progress

def check_sources(job):
    for m in job['members']:
        p=Path(m['source']); st=p.stat()
        if st.st_size!=m['bytes'] or st.st_mtime_ns!=m['mtime_ns']: raise RuntimeError(f'Source changed: {p}')

def materialize(job):
    check_sources(job)
    if job['kind']=='raw_file_range': return Path(job['members'][0]['source']),job['offset'],job['bytes'],False
    staging=TRANSFER/'staging'; staging.mkdir(exist_ok=True)
    path=staging/job['name']
    # At most one <=64 MiB payload bundle exists; no full-run/checkpoint/repository archive.
    with tarfile.open(path,'w',format=tarfile.PAX_FORMAT) as tar:
        for member in job['members']: tar.add(member['source'],arcname=member['archive_path'],recursive=False)
    job['bytes']=path.stat().st_size
    return path,0,job['bytes'],True

def stream_upload(release_id,job,path,offset,size):
    endpoint=f'https://uploads.github.com/repos/{REPO}/releases/{release_id}/assets?name='+urllib.parse.quote(job['name'])
    log=TRANSFER/'transport.log'
    with path.open('rb') as source,log.open('a') as err:
        source.seek(offset)
        # gh reads --input - as a request body. The producer bounds disk reads and rate;
        # no payload staging is needed for checkpoint shards or necessary large-file parts.
        proc=subprocess.Popen(['gh','api','--method','POST',endpoint,'--input','-',
            '-H','Content-Type: application/octet-stream','-H',f'Content-Length: {size}'],
            env=gh_env(),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err)
        stop_watch=threading.Event(); reason=[]
        deadline=time.monotonic()+max(300,size/RATE*4+120)
        def watchdog():
            while not stop_watch.wait(5):
                why=pause_reason() or ('bounded_transport_timeout' if time.monotonic()>deadline else None)
                if why: reason.append(why); proc.terminate(); return
        threading.Thread(target=watchdog,daemon=True).start()
        try:
            remaining=size; start=time.monotonic(); sent=0
            while remaining:
                why=pause_reason()
                if why: reason.append(why); proc.terminate(); raise RuntimeError(why)
                block=source.read(min(256*1024,remaining))
                if not block: raise RuntimeError('Source ended early')
                proc.stdin.write(block); remaining-=len(block); sent+=len(block)
                target=sent/RATE-(time.monotonic()-start)
                if target>0: time.sleep(target)
            proc.stdin.close(); proc.stdin=None
            output,_=proc.communicate(timeout=90)
            if proc.returncode: raise RuntimeError(f'GitHub upload exit={proc.returncode}; {reason or "see transport.log"}')
            result=json.loads(output)
            if result['name']!=job['name'] or result['size']!=size or result['state']!='uploaded': raise RuntimeError('Upload receipt name/size/state mismatch')
            return {k:result.get(k) for k in ('id','name','size','state','browser_download_url')}
        finally:
            stop_watch.set()
            if proc.poll() is None: proc.kill(); proc.wait(timeout=10)

def register_completed_campaign(mapping):
    if mapping.get('campaign_registered') or not read(CAMPAIGN/'run.json').get('completed'):
        return False
    additions=[]; small=[]; total=0
    def add_bundle():
        nonlocal small,total
        if not small: return
        identity=hashlib.sha256(json.dumps([(m['source'],m['bytes']) for m in small]).encode()).hexdigest()[:16]
        additions.append(dict(name=f'progressive-bct-new-records-{identity}.tar',kind='small_records_bundle',members=small,
            source_bytes=total,group='bct-new-results',status='queued',attempts=0))
        small=[]; total=0
    for current,dirs,files in os.walk(CAMPAIGN,followlinks=False):
        dirs[:]=[d for d in dirs if not (Path(current)/d).is_symlink()]
        for name in sorted(files):
            path=Path(current)/name
            if 'checkpoints' not in path.parts and path.suffix not in ('.npz','.mp4','.npy'): continue
            st=path.stat(); member=dict(source=str(path),archive_path=str(path.relative_to(ROOT.parent)),bytes=st.st_size,mtime_ns=st.st_mtime_ns)
            if st.st_size<=8*1024**2:
                if total+st.st_size>64*1024**2: add_bundle()
                small.append(member); total+=st.st_size
            else:
                identity=hashlib.sha256(str(path).encode()).hexdigest()[:16]
                parts=math.ceil(st.st_size/CHUNK) if st.st_size>=2*1024**3 else 1
                for part in range(parts):
                    offset=part*CHUNK if parts>1 else 0; size=min(CHUNK,st.st_size-offset) if parts>1 else st.st_size
                    additions.append(dict(name=f'progressive-bct-new-{identity}-{name}'+(f'.part-{part:03d}' if parts>1 else ''),
                        kind='raw_file_range',members=[member],source_bytes=size,bytes=size,offset=offset,part=part,parts=parts,
                        group='bct-new-results',status='queued',attempts=0))
    add_bundle(); mapping['jobs'].extend(additions); mapping['campaign_registered']=True
    write_status(mapping,'new_experiment_artifacts_queued')
    return True


def reconcile_remote_receipts(mapping,assets):
    reconciled=[]
    for job in mapping['jobs']:
        asset=assets.get(job['name'])
        if asset and job.get('bytes') is not None and asset['size']==job['bytes'] and asset['state']=='uploaded':
            if job['status']!='uploaded':
                receipt={k:asset.get(k) for k in ('id','name','size','state')}
                record=dict(at_utc=now(),name=job['name'],previous_status=job['status'],receipt=receipt,metadata_only=True)
                reconciled.append(record)
                append(TRANSFER/'receipts.jsonl',record)
                job.update(status='uploaded',receipt=receipt,reconciled_at=now(),reused_on_resume=True)
    save(TRANSFER/'last_reconciliation.json',dict(at_utc=now(),entries=reconciled,verification='name/size/uploaded only; no download/hash rescan'))
    write_status(mapping,'ready_to_resume')
    return reconciled


def main():
    TRANSFER.mkdir(parents=True,exist_ok=True)
    lock=(TRANSFER/'queue.lock').open('a'); fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    os.nice(19)
    # No GitHub networking is attempted through a different route if this proxy is down.
    for attempt in range(3):
        try: release_id,assets=release(TAG); break
        except Exception as exc:
            save(TRANSFER/'progress.json',dict(status='paused_academic_proxy_unavailable',at_utc=now(),error=str(exc),attempt=attempt+1,source_deleted=False,transport='autodl_academic_only',vpn_fallback=False))
            if attempt==2: return
            time.sleep(30)
    mapping=read(TRANSFER/'mapping.json') if (TRANSFER/'mapping.json').exists() else plan()
    register_completed_campaign(mapping)
    reconcile_remote_receipts(mapping,assets)
    for job in mapping['jobs']:
        if job['status']=='uploaded':
            old=assets.get(job['name'])
            if not old or old['size']!=job['bytes'] or old['state']!='uploaded':
                job.update(status='pending',error='Previously uploaded asset absent/mismatched; preserve remote state')
        if job['status']=='uploaded' or job['attempts']>=3: continue
        while pause_reason():
            write_status(mapping,'paused_'+pause_reason(),job['name']); time.sleep(30)
        path=None; temporary=False
        try:
            path,offset,size,temporary=materialize(job)
            old=assets.get(job['name'])
            if old:
                if old['size']==size and old['state']=='uploaded':
                    job.update(status='uploaded',receipt=old,reused_on_resume=True); write_status(mapping,'running'); continue
                job.update(status='pending',attempts=3,error='Remote asset name exists with mismatched size/state; no overwrite'); continue
            for attempt in range(job['attempts'],3):
                job.update(attempts=attempt+1,status='uploading')
                write_status(mapping,'running',job['name'])
                try:
                    receipt=stream_upload(release_id,job,path,offset,size)
                    job.update(status='uploaded',receipt=receipt,uploaded_at=now()); assets[job['name']]=receipt
                    append(TRANSFER/'receipts.jsonl',dict(at_utc=now(),name=job['name'],receipt=receipt)); break
                except Exception as exc:
                    job.update(status='pending',error=repr(exc)); write_status(mapping,'running',job['name'])
                    # A completed request may have lost its reply: inspect metadata before retrying.
                    try:
                        release_id,assets=release(TAG)
                        old=assets.get(job['name'])
                        if old and old['size']==size and old['state']=='uploaded': job.update(status='uploaded',receipt=old); break
                        if old: job.update(attempts=3,error='Partial asset exists; no deletion or duplicate upload'); break
                    except Exception as network:
                        job['error']='Official academic proxy/API unavailable; pending: '+repr(network)
                        write_status(mapping,'paused_academic_proxy_unavailable',job['name']); return False
                    if pause_reason():
                        write_status(mapping,'paused_'+pause_reason(),job['name']); return False
                    if attempt<2: time.sleep(10)
        except Exception as exc:
            job.update(status='pending',attempts=3,error=repr(exc))
        finally:
            # Only this queue's bounded temporary payload; originals are never removed.
            if temporary and path is not None and path.parent==TRANSFER/'staging' and path.exists(): path.unlink()
            save(TRANSFER/'mapping.json',mapping)
        if sum(j['status']=='uploaded' for j in mapping['jobs'])%10==0:
            from publish_pi0_bct import publish
            publish(CAMPAIGN,'progressive-upload-progress')
    if not mapping.get('campaign_registered'):
        while not read(CAMPAIGN/'run.json').get('completed'):
            write_status(mapping,'waiting_for_experiment_artifacts')
            time.sleep(30)
        register_completed_campaign(mapping)
        lock.close()
        return True
    complete=all(j['status']=='uploaded' for j in mapping['jobs']) and not mapping['unresolved']
    write_status(mapping,'complete' if complete else 'finished_with_pending')
    from publish_pi0_bct import publish
    publish(CAMPAIGN,'progressive-upload-finished')

if __name__=='__main__':
    while main(): pass
