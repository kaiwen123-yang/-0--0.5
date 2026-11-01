"""Single-model, resumable three-stage experiment in an independent tmux session."""
import contextlib
import fcntl
import signal
import shutil
import socket
import threading
import time
from bct_common import *
from publish_pi0_bct import publish

ENTRY=ROOT/'scripts/run_pi0_bct_d57.sh'

def stop(proc):
    if proc.poll() is None:
        os.killpg(proc.pid,signal.SIGTERM)
        try: proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid,signal.SIGKILL); proc.wait(timeout=10)

def counts():
    completed=list((CAMPAIGN/'evaluations').glob('*/*/completed.json'))
    updates={}
    for g in ('C','D'):
        p=CAMPAIGN/g/'lora_metrics.jsonl'
        updates[g]=len(p.read_text().splitlines()) if p.exists() else 0
    correction=read(CAMPAIGN/'correction_manifest.json') if (CAMPAIGN/'correction_manifest.json').exists() else {}
    return dict(new_autonomous_evaluations=len(completed),reused_evaluations=42,
        new_optimizer_updates=sum(updates.values()),updates_by_group=updates,
        teacher_prefix_evaluations=len(list((CAMPAIGN/'prefix').glob('*.json'))),
        correction_attempts=len(correction.get('attempts',[])),accepted_corrections=len(correction.get('accepted',[])))

def main():
    assert git('branch','--show-current')==BRANCH
    lock=(ROOT/'runtime'/f'{TASK}.lock').open('a'); fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    previous=read(CAMPAIGN/'run.json') if (CAMPAIGN/'run.json').exists() else {}
    if previous.get('completed'): print('EXPERIMENT_ALREADY_COMPLETE',flush=True); return
    status={**previous,'started_at':previous.get('started_at',now()),'pid':os.getpid(),'stage':'starting',
            'completed':False,'base_optimizer_updates':BASE,'source_commit':git('rev-parse','HEAD'),'hardware_execution':False}
    if 'error' in status:
        append(CAMPAIGN/'execution_events.jsonl',dict(at_utc=now(),event='resume_after_recorded_interruption',previous_error=status.pop('error')))
    status_lock=threading.RLock(); stopping=threading.Event()
    def update(**kwargs):
        with status_lock:
            status.update(kwargs,updated_at=now(),counts=counts())
            save(CAMPAIGN/'run.json',status)
    def monitor():
        while not stopping.wait(30):
            update()
            append(CAMPAIGN/'resources.jsonl',dict(at_utc=now(),stage=status['stage'],free_bytes=shutil.disk_usage(CAMPAIGN).free))
    threading.Thread(target=monitor,daemon=True).start()
    def execute(stage,*args,label=None,run=CAMPAIGN,timeout=14400):
        label=label or (str(args[0]) if args else stage)
        update(stage=label)
        log=CAMPAIGN/'logs'/f'{label}_{time.time_ns()}.log'
        command=['bash',str(ENTRY),stage,*map(str,args)]
        append(CAMPAIGN/'execution_events.jsonl',dict(at_utc=now(),event='start',command=command,label=label))
        with log.open('x') as stream:
            proc=subprocess.Popen(command,env=dict(os.environ,PIPER_COLOR_RUN=str(run)),stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
            update(child_pid=proc.pid,child_log=str(log))
            try:
                rc=proc.wait(timeout=timeout)
                append(CAMPAIGN/'execution_events.jsonl',dict(at_utc=now(),event='end',label=label,returncode=rc))
                if rc: raise RuntimeError(f'{label} exited {rc}: {log}')
            finally: stop(proc); update(child_pid=None)
    @contextlib.contextmanager
    def service(ckpt,label):
        if shutil.disk_usage(CAMPAIGN).free<20*1024**3: raise RuntimeError('Less than 20 GiB free; no cleanup permitted')
        free=int(subprocess.check_output(['nvidia-smi','--query-gpu=memory.free','--format=csv,noheader,nounits'],text=True).splitlines()[0])
        if free<45000: raise RuntimeError('Shared GPU capacity unavailable')
        with socket.socket() as sock: sock.bind(('127.0.0.1',PORT))
        log=CAMPAIGN/'logs'/f'serve_{label}_{time.time_ns()}.log'
        with log.open('x') as stream:
            proc=subprocess.Popen(['bash',str(ENTRY),'serve','--checkpoint',str(ckpt),'--norm-stats',str(OLD/f'assets/{ASSET}')],
                stdout=stream,stderr=subprocess.STDOUT,env=dict(os.environ,PIPER_COLOR_RUN=str(CAMPAIGN)),start_new_session=True)
            update(stage=f'loading_{label}',service_pid=proc.pid,service_log=str(log),active_checkpoint=str(ckpt))
            try:
                deadline=time.monotonic()+900
                while True:
                    if proc.poll() is not None: raise RuntimeError(f'Model loading failed: {log}')
                    if time.monotonic()>deadline: raise TimeoutError(f'Model loading timeout: {log}')
                    if 'MODEL_LOADED ' in log.read_text(errors='replace'):
                        try:
                            with socket.create_connection(('127.0.0.1',PORT),timeout=1): break
                        except OSError: pass
                    time.sleep(1)
                yield
            finally: stop(proc); update(service_pid=None)
    def evaluate(label,roster_path,ckpt):
        execute('worker','evaluate','--label',label,'--roster',roster_path,'--checkpoint',ckpt,label=label)
        publish(CAMPAIGN,f'{label}-complete')
    try:
        update(); publish(CAMPAIGN,'supervisor-started')
        freeze_path=CAMPAIGN/'candidate_freeze.json'
        if not freeze_path.exists():
            prefix_pending=not (CAMPAIGN/'prefix_summary.json').exists()
            if not prefix_pending and (CAMPAIGN/'failure_case_manifest.json').exists():
                prefix_pending=read(CAMPAIGN/'prefix_summary.json')['total']<2*len(read(CAMPAIGN/'failure_case_manifest.json')['cases'])
            if not (CAMPAIGN/'coverage_summary.json').exists() or prefix_pending:
                with service(OLD,'B'):
                    if not (CAMPAIGN/'coverage_summary.json').exists():
                        evaluate('B_coverage',CAMPAIGN/'phase1_roster.json',OLD)
                        execute('worker','coverage',label='B_coverage_analysis')
                        publish(CAMPAIGN,'phase1-complete')
                    if not (CAMPAIGN/'prefix_summary.json').exists() or read(CAMPAIGN/'prefix_summary.json')['total']<2*len(read(CAMPAIGN/'failure_case_manifest.json')['cases']):
                        execute('worker','prefix',label='B_teacher_prefix')
                        publish(CAMPAIGN,'prefix-diagnosis-complete')
            execute('worker','correction',label='correction_generation')
            correction=read(CAMPAIGN/'correction_manifest.json')
            publish(CAMPAIGN,'correction-generation-complete')
            if correction['outcome']=='qualified':
                if not (CAMPAIGN/'D/sample_order.npy').exists(): execute('worker','samplers',label='paired_C_D_samplers')
                dev=read(CAMPAIGN/'development_training_roster.json')
                node_roster=roster('validation',range(1000,1005),range(42,47))+dev
                save(CAMPAIGN/'node_roster.json',node_roster)
                for group in ('C','D'):
                    for local in (500,1000):
                        label=f'{group}_{local}'; ckpt=checkpoint(group,local)
                        if not (ckpt/'resume.json').exists():
                            latest=[p for p in ckpt.parent.glob('*/resume.json') if int(p.parent.name)<local]
                            execute('train','--until',local,*(['--resume'] if latest else []),label=f'train_{label}',run=CAMPAIGN/group)
                        assert read(ckpt/'resume.json')['optimizer_updates']==BASE+local
                        if not (CAMPAIGN/f'node_{label}.json').exists():
                            with service(ckpt,label):
                                evaluate(label,CAMPAIGN/'node_roster.json',ckpt)
                                execute('worker','fixed','--label',label,'--checkpoint',ckpt,label=f'fixed_{label}')
                                execute('worker','node','--label',label,label=f'node_{label}')
                            publish(CAMPAIGN,f'node-{label}-complete')
            coverage=read(CAMPAIGN/'coverage_summary.json')
            dev_keys={key(r) for r in read(CAMPAIGN/'development_training_roster.json')}
            b_counts=[coverage['validation']['by_seed'][str(s)]['successes'] for s in range(42,47)]
            b_prompt=read(AB/'B/node_2010.json')['prompt_matches']
            baseline=dict(candidate='B',score=[min(b_counts),sum(b_counts),sum(r['success'] for r in coverage['train']['episodes'] if key(r) in dev_keys),b_prompt],eligible=True,local_updates=0)
            candidates=[baseline]+[read(CAMPAIGN/f'node_{g}_{n}.json') for g in ('C','D') for n in (500,1000) if (CAMPAIGN/f'node_{g}_{n}.json').exists()]
            selected=baseline
            # Sort tie breaks before comparing score; original B wins all ties.
            for r in sorted(candidates[1:],key=lambda r:(r['local_updates'],r['candidate'])):
                if r['eligible'] and r['score']>selected['score']: selected=r
            selected_ckpt=OLD if selected['candidate']=='B' else checkpoint(*[int(x) if i else x for i,x in enumerate(selected['candidate'].split('_'))])
            comparison=dict(candidates=candidates,selected_before_coverage=selected['candidate'],selection_uses='development only',correction_outcome=correction['outcome'])
            if selected['candidate']!='B':
                existing=read(CAMPAIGN/'evaluations'/selected['candidate']/'summary.json')['episodes']
                known={key(r) for r in existing}
                missing=[r for r in roster('train',range(100,140),(42,43)) if key(r) not in known]
                assert len(missing)<=228
                save(CAMPAIGN/'candidate_coverage_roster.json',missing)
                with service(selected_ckpt,'candidate_coverage'):
                    evaluate('candidate_coverage',CAMPAIGN/'candidate_coverage_roster.json',selected_ckpt)
                full=[r for r in existing if r['split']=='train']+read(CAMPAIGN/'evaluations/candidate_coverage/summary.json')['episodes']
                assert len(full)==240 and len({key(r) for r in full})==240
                b={key(r):r for r in coverage['train']['episodes']}
                comparison['paired_training']=[dict(trial={k:r[k] for k in ('split','layout','target','base_seed')},B_success=b[key(r)]['success'],candidate_success=r['success']) for r in full]
                regressed=sum(r['success'] for r in full)<coverage['train']['successes'] or sum(r['success'] for r in full if r['layout'] in (100,101))<sum(r['success'] for r in b.values() if r['layout'] in (100,101))
                comparison['coverage_regression_revert']=regressed
                if regressed: selected=baseline; selected_ckpt=OLD
            comparison['selected']=selected['candidate']
            save(CAMPAIGN/'candidate_comparison.json',comparison)
            files=read(CAMPAIGN/'contract.json')['old_checkpoint_files'] if selected_ckpt==OLD else inventory(selected_ckpt,hashes=True)
            freeze=dict(frozen_at_utc=now(),candidate=selected['candidate'],checkpoint=str(selected_ckpt),checkpoint_files=files,
                optimizer_updates=BASE+selected['local_updates'],source_commit=git('rev-parse','HEAD'),
                source_sha256={p.name:sha(p) for p in (ROOT/'tasks/piper_color_v1').glob('*.py')},
                normalization=str(OLD/f'assets/{ASSET}/norm_stats.json'),normalization_sha256=sha(OLD/f'assets/{ASSET}/norm_stats.json'),
                scene_sha256=sha(V2/'scene/scene.xml'),protocol=read(CAMPAIGN/'contract.json')['protocol'],
                selection=comparison,test_roster=read(CAMPAIGN/'test_roster.json'),test_result_used=False)
            save(freeze_path,freeze)
        # Resume from immutable freeze; no training/selection is entered once this file exists.
        freeze=read(freeze_path); selected_ckpt=Path(freeze['checkpoint'])
        if not (CAMPAIGN/'freeze_publication.json').exists():
            if not publish(CAMPAIGN,'candidate-frozen-before-independent-test'):
                raise RuntimeError('Candidate frozen locally; Git publication pending before first test')
            save(CAMPAIGN/'freeze_publication.json',read(CAMPAIGN/'publication_delivery.json'))
        with service(selected_ckpt,'independent_test'):
            evaluate('independent_test',CAMPAIGN/'test_roster.json',selected_ckpt)
        test=read(CAMPAIGN/'evaluations/independent_test/summary.json')
        assert test['total']==60 and test['errors']==0
        save(CAMPAIGN/'test_summary.json',test)
        current=counts(); assert current['new_optimizer_updates']<=2000 and current['new_autonomous_evaluations']<=957
        transfer=read(TRANSFER/'progress.json') if (TRANSFER/'progress.json').exists() else {'status':'not_available'}
        coverage=read(CAMPAIGN/'coverage_summary.json'); correction=read(CAMPAIGN/'correction_manifest.json')
        report=f'''# π0 B 覆盖、纠偏与独立测试

实验完成时间（UTC）：{now()}。实验完成与上传完成单独记录。

B 训练覆盖：{coverage['train']['successes']}/240；五种子验证：{coverage['validation']['successes']}/75。
各布局、颜色、种子、失败阶段与全部失败视频见 coverage_summary.json。

纠偏：{correction['outcome']}。{correction['reason']}。
教师前缀结果单列于 prefix_summary.json，不计自主成功。
C/D 节点及开发选择依据见 candidate_comparison.json；每次更新见 C、D 的 lora_metrics.jsonl。

最终冻结候选：{freeze['candidate']}，累计优化器更新 {freeze['optimizer_updates']}。
独立测试：{test['successes']}/60；seed42={test['by_seed']['42']['successes']}/30，seed43={test['by_seed']['43']['successes']}/30。
逐布局结果和失败轨迹见 test_summary.json，测试没有用于重选候选、继续训练或调整成功标准。

实际计算：新增自主评测 {current['new_autonomous_evaluations']}，复用 42；新增优化器更新 {current['new_optimizer_updates']}；
教师前缀 {current['teacher_prefix_evaluations']}；纠偏尝试 {current['correction_attempts']}，合格示范 {current['accepted_corrections']}。

上传快照：{json.dumps(transfer,ensure_ascii=False)}。
实时传输状态在 runtime/pi-progressive-upload-20261101/progress.json，缺失项见 missing.json。
无论上传状态如何，服务器原始数据、所有检查点与开发环境均保留。未使用实机或 π0.5 新训练。
'''
        (CAMPAIGN/'final_report_zh.md').write_text(report)
        save(CAMPAIGN/'index.json',dict(experiment_complete=True,upload_complete=transfer.get('status')=='complete',counts=current,
            candidate=freeze['candidate'],test_successes=test['successes'],test_total=60,upload_snapshot=transfer,
            final_report='final_report_zh.md',source_deleted=False))
        update(stage='experiment_complete',completed=True,finished_at=now(),selected_candidate=freeze['candidate'],upload_status=transfer.get('status'))
        for attempt in range(3):
            if publish(CAMPAIGN,f'experiment-complete-{attempt+1}'): break
    except BaseException as exc:
        update(stage='failed_requires_inspection',error=repr(exc),completed=False)
        append(CAMPAIGN/'execution_events.jsonl',dict(at_utc=now(),event='failure',error=repr(exc)))
        publish(CAMPAIGN,'execution-interrupted'); raise
    finally: stopping.set(); update()

if __name__=='__main__': main()
