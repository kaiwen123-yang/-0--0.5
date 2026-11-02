
"""Bounded E/F campaign: full development tasks, conditional continuation, frozen comparison."""
import contextlib,signal,socket,time,fcntl
from ef_common import *
from publish_pi0_ef import publish
ENTRY=ROOT/'scripts/run_pi0_ef_d57.sh'
def stop(p):
    if p.poll() is None:
        os.killpg(p.pid,signal.SIGTERM)
        try:p.wait(timeout=15)
        except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
def count():
    return dict(updates={g:len((CAMPAIGN/g/'lora_metrics.jsonl').read_text().splitlines()) if (CAMPAIGN/g/'lora_metrics.jsonl').exists() else 0 for g in ('E','F')},
        autonomous_tasks=len(list((CAMPAIGN/'evaluations').glob('*/*/completed.json'))),
        baseline_reused=123)
def partition(rows):
    result={}
    for split in ('train','validation','test'):
        rr=[r for r in rows if r['split']==split]
        if not rr:continue
        result[split]=dict(total=len(rr),successes=sum(r['success'] for r in rr),
            back_successes=sum(r['success'] for r in rr if r['slot']=='back'),
            by_slot={s:dict(total=sum(r['slot']==s for r in rr),successes=sum(r['slot']==s and r['success'] for r in rr)) for s in ('back','front_left','front_right')},
            by_color={c:dict(total=sum(r['target']==c for r in rr),successes=sum(r['target']==c and r['success'] for r in rr)) for c in COLORS})
    return result
def enrich(rows):
    import numpy as np
    for r in rows:
        if 'slot' not in r:
            with np.load(r['trajectory']) as d:
                p=d['object_positions'][0,COLORS.index(r['target'])]
                r['slot']='back' if p[1]>-.09 else ('front_left' if p[0]<-.18 else 'front_right')
    return rows
def main():
    lock=(ROOT/'runtime/pi0-ef-local-20261102.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    status=read(CAMPAIGN/'run.json') if (CAMPAIGN/'run.json').exists() else dict(started_at=now(),completed=False)
    if status.get('completed'):return
    def update(**kw):
        status.update(kw,at_utc=now(),counts=count());save(CAMPAIGN/'run.json',status)
    def execute(stage,*args,label,run=CAMPAIGN):
        update(stage=label)
        log=CAMPAIGN/'logs'/f'{label}_{time.time_ns()}.log'
        with log.open('w') as f:
            p=subprocess.Popen(['bash',str(ENTRY),stage,*map(str,args)],env=dict(os.environ,PIPER_COLOR_RUN=str(run)),stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
            update(child_pid=p.pid,child_log=str(log))
            try:
                if p.wait()!=0:raise RuntimeError(f'{label} failed; {log}')
            finally:stop(p);update(child_pid=None)
    @contextlib.contextmanager
    def service(ckpt,label):
        log=CAMPAIGN/'logs'/f'serve_{label}_{time.time_ns()}.log'
        with log.open('w') as f:
            p=subprocess.Popen(['bash',str(ENTRY),'serve','--checkpoint',str(ckpt),'--norm-stats',str(OLD/f'assets/{ASSET}')],
                env=dict(os.environ,PIPER_COLOR_RUN=str(CAMPAIGN)),stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
            update(stage='loading_'+label,service_pid=p.pid,service_log=str(log))
            try:
                deadline=time.monotonic()+900
                while 'MODEL_LOADED ' not in log.read_text(errors='replace'):
                    if p.poll() is not None or time.monotonic()>deadline:raise RuntimeError(f'Model failed: {log}')
                    time.sleep(1)
                time.sleep(2)
                yield
            finally:stop(p);update(service_pid=None)
    def evaluate(label,rp,ckpt):
        if not (CAMPAIGN/'evaluations'/label/'summary.json').exists():
            execute('worker','evaluate','--label',label,'--roster',rp,'--checkpoint',ckpt,label=label)
        rows=enrich(read(CAMPAIGN/'evaluations'/label/'summary.json')['episodes'])
        save(CAMPAIGN/f'node_{label}.json',dict(label=label,summary=partition(rows),episodes=rows))
        publish(CAMPAIGN,label+'-complete')
        return rows
    try:
        update(stage='waiting_correction')
        while not (CAMPAIGN/'correction_manifest.json').exists() or not read(CAMPAIGN/'correction_manifest.json').get('complete'):
            exitfile=CAMPAIGN/'correction.exit'
            if exitfile.exists() and exitfile.read_text().strip()!='0':raise RuntimeError('Correction worker failed')
            time.sleep(10)
        report=read(CAMPAIGN/'correction_manifest.json')
        if not report['accepted']:raise RuntimeError('No qualified local correction; retain B, F cannot be formed')
        if not (CAMPAIGN/'F/sample_order.npy').exists():
            execute('prepare','samplers',label='matched_samplers')
        publish(CAMPAIGN,'corrections-and-samplers')
        baseline=read(CAMPAIGN/'B_development.json')
        base_rows=enrich(baseline['train']+baseline['validation']);base=partition(base_rows)
        save(CAMPAIGN/'node_B.json',dict(label='B',summary=base,episodes=base_rows))
        candidates=[]
        for local in (500,1000):
            if local==1000:
                permitted=any(x['summary']['validation']['successes']>=base['validation']['successes'] and x['summary']['train']['back_successes']>base['train']['back_successes'] for x in candidates)
                save(CAMPAIGN/'continuation_decision.json',dict(continue_to_1000=permitted,criterion='validation >= B and rear development success > B for at least one group',candidates=candidates))
                publish(CAMPAIGN,'500-comparison-and-budget-decision')
                if not permitted:break
            for group in ('E','F'):
                label=f'{group}_{local}';ckpt=checkpoint(group,local)
                if not (ckpt/'resume.json').exists():
                    execute('train','--until',local,*(['--resume'] if local==1000 else []),label='train_'+label,run=CAMPAIGN/group)
                with service(ckpt,label):
                    rows=evaluate(label,CAMPAIGN/'node_roster.json',ckpt)
                candidates.append(dict(label=label,local_updates=local,summary=partition(rows)))
        # Rank by complete validation, then rear developer success and complete training development.
        def score(x):
            s=x['summary'];return (s['validation']['successes'],s['train']['back_successes'],s['train']['successes'])
        selected=dict(label='B',local_updates=0,summary=base)
        for x in sorted(candidates,key=lambda x:(x['local_updates'],x['label'])):
            if x['summary']['validation']['successes']>=base['validation']['successes'] and score(x)>score(selected):selected=x
        selected_ckpt=OLD
        if selected['label']!='B':
            group,local=selected['label'].split('_');selected_ckpt=checkpoint(group,int(local))
            existing=read(CAMPAIGN/f"node_{selected['label']}.json")['episodes']
            seen={key(r) for r in existing}
            missing=[r for r in roster('train',range(100,140),(42,43)) if key(r) not in seen]
            save(CAMPAIGN/'candidate_coverage_roster.json',missing)
            with service(selected_ckpt,'candidate_coverage'):
                extra=evaluate('candidate_coverage',CAMPAIGN/'candidate_coverage_roster.json',selected_ckpt)
            full=[r for r in existing if r['split']=='train']+extra
            save(CAMPAIGN/'candidate_coverage.json',dict(summary=partition(full),episodes=full))
            if sum(r['success'] for r in full)<211:
                selected=dict(label='B',local_updates=0,summary=base,reason='candidate full training below 211/240');selected_ckpt=OLD
        freeze=dict(at_utc=now(),candidate=selected['label'],checkpoint=str(selected_ckpt),optimizer_updates=BASE+selected['local_updates'],
            selection='development only',new_layouts=list(range(3000,3010)),new_seeds=[42,43],old_test_untouched=True,candidates=candidates)
        save(CAMPAIGN/'candidate_freeze.json',freeze)
        publish(CAMPAIGN,'candidate-frozen')
        if selected['label']!='B':
            for label,ckpt in [('new_layout_candidate',selected_ckpt),('new_layout_B',OLD)]:
                with service(ckpt,label):evaluate(label,CAMPAIGN/'new_layout_roster.json',ckpt)
            save(CAMPAIGN/'new_layout_comparison.json',{label:read(CAMPAIGN/f'node_{label}.json') for label in ('new_layout_candidate','new_layout_B')})
        else:
            save(CAMPAIGN/'new_layout_comparison.json',dict(performed=False,reason='No candidate surpassed B; no new test launched'))
        save(CAMPAIGN/'candidate_comparison.json',dict(baseline=base,candidates=candidates,selected=selected['label']))
        update(stage='experiment_complete',completed=True,selected_candidate=selected['label'],finished_at=now())
        publish(CAMPAIGN,'experiment-complete')
    except BaseException as exc:
        update(stage='failed_requires_inspection',error=repr(exc));publish(CAMPAIGN,'interrupted');raise
if __name__=='__main__':main()

