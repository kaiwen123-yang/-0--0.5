
"""Continue existing Release queue; publish verified groups and remove only completed output copies."""
import collections,fcntl,math,shutil,time,subprocess,os,threading
from ef_common import ROOT,CAMPAIGN,OLD,V2,TRANSFER,read,save,now,gh_env
import upload_pi_progressive as upload
from publish_pi0_ef import publish
LEDGER=ROOT/'publication/pi-ef-cleanup-20261102'
HIST=ROOT/'outputs/pi0-b-coverage-correction-test-20261101'
def sync(stage):
    with (ROOT/'runtime/pi-bct-publication.lock').open('a') as f:
        fcntl.flock(f,fcntl.LOCK_EX)
        destination=ROOT/'publication/pi-progressive-upload-20261101'
        for name in ('mapping.json','progress.json','missing.json','reused_groups.json'):
            p=TRANSFER/name
            if p.exists():shutil.copyfile(p,destination/name)
        subprocess.run(['git','add','--',str(LEDGER.relative_to(ROOT)),str(destination.relative_to(ROOT))],check=True,stdout=subprocess.DEVNULL)
        changed=subprocess.check_output(['git','diff','--cached','--name-only'],text=True)
        if changed:subprocess.run(['git','commit','-m','Record verified pi artifact groups: '+stage],check=True,stdout=subprocess.DEVNULL)
        env=gh_env()
        r=subprocess.run(['git','-c','http.proxy='+env['https_proxy'],'push','origin','HEAD:codex/pi0-b-coverage-correction-test-20261101'],
            env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=45)
        return r.returncode==0
cleanup_lock=threading.RLock()
def cleanup():
    with cleanup_lock:return cleanup_groups()
def cleanup_groups():
    LEDGER.mkdir(parents=True,exist_ok=True)
    mapping=read(TRANSFER/'mapping.json')
    catalog=read(ROOT/'runtime/pi-complete-backup-20261101/catalog-working.json')
    catalogs={g['id']:g for g in catalog['groups']}
    groups=[]
    for g in read(TRANSFER/'reused_groups.json'):
        c=catalogs[g['group']]
        members=[dict(source=str(Path(c['source_workspace'])/e['path']),bytes=e['bytes']) for e in c['entries'] if e['type']=='file' and upload.eligible(Path(c['source_workspace'])/e['path'])]
        groups.append(dict(group=g['group'],tag=g['tag'],parts=g['parts'],members=members))
    grouped=collections.defaultdict(list)
    for j in mapping['jobs']:grouped[j['group']].append(j)
    for gid,jobs in grouped.items():
        if not all(j['status']=='uploaded' for j in jobs):continue
        members={m['source']:m for j in jobs for m in j['members']}
        groups.append(dict(group=gid,tag=upload.TAG,parts=[dict(name=j['name'],bytes=j['bytes']) for j in jobs],members=list(members.values())))
    done=(CAMPAIGN/'report_complete.json').exists()
    protected=[] if done else [str(OLD.parent.parent.parent.parent),str(V2),str(HIST),str(CAMPAIGN)]
    cache={};deleted=[]
    for group in groups:
        if group['group'].startswith('ef-') and not mapping.get('ef_registered'):continue
        record=LEDGER/(group['group']+'.json')
        if record.exists() and read(record).get('status')=='deleted':continue
        paths=[Path(m['source']) for m in group['members']]
        if any(any(str(p)==q or str(p).startswith(q+'/') for q in protected) for p in paths):continue
        # Exclude installed environments, upstreams, Git, source and shared weights by explicit output-root containment.
        eligible=all((p.is_relative_to(ROOT/'outputs') or p.is_relative_to(ROOT/'results')) and not p.is_symlink() and p.suffix not in ('.py','.sh') for p in paths)
        if not eligible:continue
        if group['tag'] not in cache:cache[group['tag']]=upload.release(group['tag'])[1]
        remote=cache[group['tag']]
        if any(p['name'] not in remote or remote[p['name']]['state']!='uploaded' or remote[p['name']]['size']!=p['bytes'] for p in group['parts']):continue
        if any(p.exists() and p.stat().st_size!=m['bytes'] for p,m in zip(paths,group['members'])):continue
        receipt=dict(at_utc=now(),status='verified_ready_to_delete',group=group['group'],release_tag=group['tag'],
            remote_assets=[dict(name=p['name'],size=remote[p['name']]['size'],state=remote[p['name']]['state']) for p in group['parts']],
            source_paths=[dict(path=str(p),bytes=m['bytes']) for p,m in zip(paths,group['members'])],
            active_dependencies_retained=protected,freed_bytes=0)
        save(record,receipt)
        if not sync(group['group']+'-indexed'):continue
        info=__import__('json').loads(upload.gh('release','view',group['tag'],'--repo',upload.REPO,'--json','isDraft'))
        if info['isDraft']:
            upload.gh('release','edit',group['tag'],'--repo',upload.REPO,'--draft=false')
        freed=0;removed=[]
        for p in paths:
            if p.is_file():
                freed+=p.stat().st_size;p.unlink();removed.append(str(p))
        receipt.update(status='deleted',deleted_at=now(),freed_bytes=freed,deleted_paths=removed)
        save(record,receipt);sync(group['group']+'-deleted')
        deleted.append(group['group'])
        print('GROUP_DELETED',group['group'],freed,flush=True)
    return deleted
from pathlib import Path
def register_new():
    lock=(TRANSFER/'queue.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX)
    try:
        m=read(TRANSFER/'mapping.json')
        if m.get('ef_registered'):return
        mapped={x['source'] for j in m['jobs'] for x in j['members']}
        files=collections.defaultdict(list)
        for current,dirs,names in os.walk(CAMPAIGN,followlinks=False):
            dirs[:]=[d for d in dirs if not (Path(current)/d).is_symlink()]
            for name in sorted(names):
                p=Path(current)/name
                if str(p) in mapped:continue
                if 'checkpoints' in p.parts:
                    rel=p.relative_to(CAMPAIGN)
                    if not (CAMPAIGN/Path(*rel.parts[:5])/'resume.json').exists():continue
                    gid='ef-'+rel.parts[0]+'-checkpoint-'+rel.parts[4]
                elif 'correction_dataset' in p.parts and p.suffix in ('.npz','.npy','.mp4'):gid='ef-local-corrections'
                elif 'evaluations' in p.parts and p.suffix in ('.npz','.mp4'):
                    if not (p.parent.parent/'completed.json').exists():continue
                    gid='ef-evaluation-'+p.relative_to(CAMPAIGN).parts[1]
                elif p.suffix=='.npy':gid='ef-samplers'
                else:continue
                st=p.stat();files[gid].append(dict(source=str(p),archive_path=str(p.relative_to(ROOT.parent)),bytes=st.st_size,mtime_ns=st.st_mtime_ns))
        jobs=[]
        for gid,members in files.items():
            small=[];total=0;serial=sum(j['group']==gid for j in m['jobs'])
            def bundle():
                nonlocal small,total,serial
                if small:
                    jobs.append(dict(name=f'{gid}-records-{serial:04d}.tar',group=gid,kind='small_records_bundle',members=small,source_bytes=total,status='queued',attempts=0))
                    small=[];total=0;serial+=1
            for member in members:
                size=member['bytes']
                if size<=8*1024**2:
                    if total+size>64*1024**2:bundle()
                    small.append(member);total+=size
                else:
                    parts=math.ceil(size/upload.CHUNK) if size>=2*1024**3 else 1
                    for part in range(parts):
                        offset=part*upload.CHUNK if parts>1 else 0;n=min(upload.CHUNK,size-offset) if parts>1 else size
                        jobs.append(dict(name=f'{gid}-file-{serial:04d}-part-{part:03d}',group=gid,kind='raw_file_range',
                            members=[member],source_bytes=n,bytes=n,offset=offset,part=part,parts=parts,status='queued',attempts=0))
                    serial+=1
            bundle()
        m['jobs']=jobs+m['jobs'];m['ef_registered']=(CAMPAIGN/'report_complete.json').exists()
        upload.write_status(m,'ef_artifacts_registered')
        print('NEW_ASSETS_REGISTERED',len(jobs),flush=True)
    finally:lock.close()
def main():
    LEDGER.mkdir(parents=True,exist_ok=True)
    state=LEDGER/'delivery_status.json'
    while True:
        run=read(CAMPAIGN/'run.json')
        if run.get('completed'):
            if not (CAMPAIGN/'report_complete.json').exists():
                r=subprocess.run(['/root/miniconda3/bin/python',str(ROOT/'tasks/piper_color_v1/finalize_pi0_ef.py')])
                if r.returncode:raise RuntimeError('Result report failed; original outputs retained')
            break
        if run.get('stage')=='failed_requires_inspection':
            save(state,dict(at_utc=now(),status='experiment_needs_inspection',run=run));return
        try:
            cleanup()
            save(state,dict(at_utc=now(),status='watching_experiment',experiment_stage=run.get('stage')))
        except Exception as exc:save(state,dict(at_utc=now(),status='cleanup_pending',error=repr(exc)))
        time.sleep(60)
    stop_cleanup=threading.Event()
    def cleanup_monitor():
        while not stop_cleanup.wait(60):
            try:cleanup()
            except Exception as exc:print('CLEANUP_PENDING',repr(exc),flush=True)
    threading.Thread(target=cleanup_monitor,daemon=True).start()
    save(state,dict(at_utc=now(),status='waiting_existing_single_upload_queue'))
    register_new() # Existing single-concurrency queue owns this lock until its current run ends.
    try:cleanup()
    except Exception as exc:print('CLEANUP_PENDING',repr(exc),flush=True)
    save(state,dict(at_utc=now(),status='uploading_ef_and_remaining'))
    upload.main()
    try:cleanup()
    except Exception as exc:print('CLEANUP_PENDING',repr(exc),flush=True)
    stop_cleanup.set()
    progress=read(TRANSFER/'progress.json')
    save(state,dict(at_utc=now(),status='complete' if progress.get('pending_assets')==0 else 'finished_with_pending',
        upload=progress,experiment_complete=True,
        freed_bytes=sum(read(p).get('freed_bytes',0) for p in LEDGER.glob('*.json') if p.name!='delivery_status.json')))
    sync('delivery-final')
if __name__=='__main__':main()

