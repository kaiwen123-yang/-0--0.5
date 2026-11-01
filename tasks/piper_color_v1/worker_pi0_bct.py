"""Real autonomous episodes, frozen-input probes and train-only teacher work."""
import argparse
import collections
import sys
import time
import imageio.v2 as imageio
import numpy as np
from bct_common import *
from diagnose_pi0_failures import arrays, sample, describe
from sim import BOX, HZ
from sim_v2 import ColorEnvV2
from policy_client import PolicyClient

def metrics(row):
    from analyze_pi0_120_regression import analyze
    r=analyze(Path(row['trajectory']))
    r.update({k:row[k] for k in ('split','layout','target','base_seed')})
    if r['first_close_frame'] is None:
        for k in list(r):
            if k.startswith('close_'): r[k]=None
        if not r['success'] and not r['non_target_lifted_5cm']:
            r['failure_class']='no_closure' if not r['target_lifted_5cm'] else 'failure_after_target_lift'
    result=read(row['result_json'])
    r.update(correct_in_box=result['correct_in_box'],gripper_open=result['gripper_open'],
             timeout=not result['success'] and result['error'] is None and result['steps']==420,
             video=row['video'],result_json=row['result_json'],trajectory=row['trajectory'],
             reused_from=row.get('reused_from'))
    diag=result.get('diagnostics',{})
    r['over_box_frames']=diag.get('over_box_frames',0)
    if r['success']: stage='success'
    elif r['first_close_frame'] is None: stage='approach_no_closure'
    elif r['non_target_lifted_5cm']: stage='wrong_target'
    elif not r['target_lifted_5cm']: stage='approach_or_grasp'
    elif not r['over_box_frames']: stage='lift_or_transfer'
    elif not r['correct_in_box']: stage='lower_or_release'
    elif not r['gripper_open']: stage='release'
    else: stage='stability_or_distractor'
    r['failure_stage']=stage
    return r

def summarize(rows):
    out=dict(total=len(rows),successes=sum(r['success'] for r in rows),errors=sum(bool(r.get('error')) for r in rows))
    for label,field in [('by_seed','base_seed'),('by_layout','layout'),('by_color','target'),('by_failure_stage','failure_stage')]:
        out[label]={str(v):dict(total=sum(r[field]==v for r in rows),successes=sum(r[field]==v and r['success'] for r in rows)) for v in sorted({r[field] for r in rows})}
    out['timeouts']=sum(r.get('timeout',False) for r in rows)
    out['episodes']=rows
    return out

def evaluate(label, roster_path, checkpoint_path):
    import evaluate_pi0_120 as evaluator
    from publish_pi0_bct import publish
    tasks=read(roster_path)
    assert len({key(r) for r in tasks})==len(tasks)
    directory=CAMPAIGN/'evaluations'/label
    directory.mkdir(parents=True,exist_ok=True)
    rows=[]
    for task in tasks:
        unit=directory/trial_id(task)
        done=unit/'completed.json'
        if done.exists():
            row=read(done)
            assert Path(read(row['result_json'])['checkpoint'])==checkpoint_path
        else:
            unit.mkdir(parents=True,exist_ok=True)
            attempts=sorted(unit.glob('attempt*_seed*'))
            row=None
            # A process can stop after persisting the final result but before the supervisor marker.
            for previous in attempts:
                stem=previous/f"layout_{task['layout']:05d}_{task['target']}"
                if all(stem.with_suffix(s).exists() for s in ('.json','.npz','.mp4')):
                    result=read(stem.with_suffix('.json'))
                    if result.get('error') is None:
                        row={**task,'result_json':str(stem.with_suffix('.json')),'trajectory':str(stem.with_suffix('.npz')),
                             'video':str(stem.with_suffix('.mp4')),'success':result['success']}
                        break
                    raise RuntimeError(f'Recorded execution error requires repair: {stem}')
            if row is None:
                if len(attempts)>=3: raise RuntimeError(f'Infrastructure attempt cap: {unit}')
                output=unit/f"attempt{len(attempts):03d}_seed{task['base_seed']}"
                sys.argv=['evaluate_pi0_120.py','--mode','lora','--model-family','pi0','--split',task['split'],
                    '--steps','420','--replan-steps','5','--seed',str(task['base_seed']),'--seed-scope','episode',
                    '--layout-seeds',str(task['layout']),'--targets',task['target'],'--data',str(V2/'dataset'),
                    '--output',str(output),'--checkpoint',str(checkpoint_path),'--norm-stats',str(OLD/f'assets/{ASSET}'),
                    '--policy-host','127.0.0.1','--policy-port',str(PORT)]
                append(CAMPAIGN/'trial_attempts.jsonl',dict(at_utc=now(),label=label,trial=task,attempt=str(output)))
                evaluator.main()
                result=read(output/'summary.json')
                assert result['complete'] and result['total']==1 and result['errors']==0
                stem=output/f"layout_{task['layout']:05d}_{task['target']}"
                row={**task,'result_json':str(stem.with_suffix('.json')),'trajectory':str(stem.with_suffix('.npz')),
                     'video':str(stem.with_suffix('.mp4')),'success':result['episodes'][0]['success']}
            save(done,row)
        rows.append(row)
        save(directory/'trials.json',rows)
        save(CAMPAIGN/'evaluation_progress.json',dict(label=label,completed=len(rows),expected=len(tasks),at_utc=now(),last=task))
        if len(rows)%15==0: publish(CAMPAIGN,f'{label}-{len(rows)}-episodes')
    result=summarize([metrics(r) for r in rows])
    save(directory/'summary.json',result)

def coverage():
    reused=read(CAMPAIGN/'B_reused_trials.json')
    new=read(CAMPAIGN/'evaluations/B_coverage/trials.json')
    rows=[metrics(r) for r in reused+new]
    assert len(rows)==315 and len({key(r) for r in rows})==315
    train=[r for r in rows if r['split']=='train']; val=[r for r in rows if r['split']=='validation']
    assert len(train)==240 and len(val)==75
    save(CAMPAIGN/'coverage_summary.json',dict(train=summarize(train),validation=summarize(val),new_autonomous=273,reused=42))
    failures=sorted([r for r in train if not r['success']],key=lambda r:(r['layout'],r['target'],r['base_seed']))
    chosen=[]
    known=[r for r in failures if r['layout']==100 and r['target']=='blue']
    if known: chosen.append(known[0])
    strata=sorted({r['failure_stage'] for r in failures})
    # First pass covers distinct layouts; second pass fills remaining failure strata deterministically.
    for unique_layout in (True,False):
        changed=True
        while changed and len(chosen)<12:
            changed=False
            for stage in strata:
                eligible=[r for r in failures if r['failure_stage']==stage and key(r) not in {key(x) for x in chosen}
                          and (not unique_layout or r['layout'] not in {x['layout'] for x in chosen})]
                if eligible and len(chosen)<12: chosen.append(eligible[0]); changed=True
    save(CAMPAIGN/'failure_case_manifest.json',dict(cases=chosen,selection='failure-stage round robin; unique layouts first; layout100 blue included; deterministic order',train_only=True))
    dev=roster('train',(100,101),(42,43))
    dev += [{k:r[k] for k in ('split','layout','target','base_seed')} for r in chosen if key(r) not in {key(x) for x in dev}]
    save(CAMPAIGN/'development_training_roster.json',dev)

def prefix():
    cases=read(CAMPAIGN/'failure_case_manifest.json')['cases']
    env=ColorEnvV2(render=True); policy=PolicyClient('127.0.0.1',PORT)
    assert Path(policy.metadata['checkpoint'])==OLD
    rows=[]
    try:
        for case in cases:
            assert 100<=case['layout']<140 and case['split']=='train'
            demo_path=V2/'dataset/train'/f"layout_{case['layout']:05d}_{case['target']}.npz"
            with np.load(demo_path,allow_pickle=False) as d:
                commands=d['executed_command'].copy(); states=d['state'].copy(); stages=d['stage'].copy()
            for length in (60,85):
                stem=CAMPAIGN/'prefix'/f"{trial_id(case)}_prefix{length}"
                if stem.with_suffix('.json').exists(): rows.append(read(stem.with_suffix('.json'))); continue
                stem.parent.mkdir(parents=True,exist_ok=True)
                env.reset(case['layout'],case['target'])
                writer=imageio.get_writer(str(stem.with_suffix('.mp4')),fps=20,codec='libx264',quality=7,macro_block_size=1,output_params=['-threads','2'])
                samples=[]; executed=[]; raw=[]; stable=False; consecutive=0
                try:
                    for command in commands[:length]: writer.append_data(env.panorama()); env.step(command)
                    error=float(abs(env.state()-states[length]).max())
                    if error>1e-6: raise RuntimeError(f'Teacher prefix replay differs: {error}')
                    policy.reset_seed(case['base_seed']+case['layout']*3+COLORS.index(case['target']))
                    obs=env.observe()
                    for _ in range(length//5): policy.infer(obs)
                    for step in range(length,420,5):
                        pred=np.asarray(policy.infer(env.observe())['actions'])
                        if pred.shape!=(10,7) or not np.isfinite(pred).all(): raise RuntimeError('Invalid prefix action')
                        for action in pred[:min(5,420-step)]:
                            writer.append_data(env.panorama()); samples.append(sample(env)); raw.append(action.copy()); executed.append(env.step(action))
                            consecutive=consecutive+1 if env.result()['success'] else 0
                            if env.max_joint_violation>.02: raise RuntimeError('Joint overshoot')
                            if consecutive>=40: stable=True; break
                        if stable: break
                finally: writer.close()
                trace=arrays(samples)
                row=dict(case={k:case[k] for k in ('layout','target','base_seed','split')},prefix=length,
                    handoff_stage=str(stages[length]),last_teacher_stage=str(stages[length-1]),handoff_state_max_error=error,
                    rng_advance_calls=length//5,source_trial=case['trajectory'],teacher_source=str(demo_path),
                    autonomous_success_rate_eligible=False,video=str(stem.with_suffix('.mp4')),
                    **describe(trace,{**env.result(),'success':stable},np.array(raw),np.array(executed)))
                np.savez_compressed(stem.with_suffix('.npz'),**trace,executed_command=executed,raw_action=raw)
                save(stem.with_suffix('.json'),row); rows.append(row)
                save(CAMPAIGN/'prefix_summary.json',dict(episodes=rows,total=len(rows),successes=sum(r['success'] for r in rows),intervention_only=True))
                print('PREFIX',trial_id(case),length,stages[length],stable,flush=True)
    finally: env.close(); policy.close()
    save(CAMPAIGN/'prefix_summary.json',dict(episodes=rows,total=len(rows),successes=sum(r['success'] for r in rows),intervention_only=True))

def correction():
    cases=read(CAMPAIGN/'failure_case_manifest.json')['cases']
    directory=CAMPAIGN/'correction_dataset'; directory.mkdir(exist_ok=True)
    manifest_path=CAMPAIGN/'correction_manifest.json'
    report=read(manifest_path) if manifest_path.exists() else dict(accepted=[],attempts=[],train_only=True,complete=False)
    if report.get('complete'): return
    if not cases:
        report.update(complete=True,outcome='correction_not_needed',reason='No failed training trial in B coverage')
        save(manifest_path,report); return
    env=ColorEnvV2(render=True)
    attempts=[]
    for delta in (0,-15,15,30):
        for case in cases:
            event=case['first_close_frame']
            if event is None: event=case['first_low_frame']
            frame=max(10,min(85,int(event if event is not None else 60)-5+delta))
            if (key(case),frame) not in [(key(c),f) for c,f in attempts]: attempts.append((case,frame))
    attempts=attempts[:40]
    try:
        for index,(case,frame) in enumerate(attempts):
            if len(report['accepted'])>=20: break
            if index<len(report['attempts']): continue
            stem=directory/f'correction_{index:03d}'
            row=dict(attempt=index,source_trial=case['trajectory'],source_case={k:case[k] for k in ('layout','target','split','base_seed')},
                intervention_frame=frame,environment_version='piper_h_color_contact_v2_impratio10',teacher_version='bct_reopen_retract_then_pose_ik_v1',
                success=False,video=str(stem.with_suffix('.mp4')))
            data=[]; commands=[]; timestamps=[]; stages=[]; diagnostics=[]; replay_errors=[]
            env.reset(case['layout'],case['target'])
            writer=imageio.get_writer(str(stem.with_suffix('.mp4')),fps=20,codec='libx264',quality=7,macro_block_size=1,output_params=['-threads','2'])
            fatal=None
            try:
                with np.load(case['trajectory'],allow_pickle=False) as source:
                    for i,command in enumerate(source['executed_command'][:frame]):
                        replay_errors.append(float(abs(env.data.qpos-source['qpos'][i]).max()))
                        replay_errors.append(float(abs(env.data.qvel-source['qvel'][i]).max()))
                        writer.append_data(env.panorama()); env.step(command)
                    replay_errors.append(float(abs(env.data.qpos-source['qpos'][frame]).max()))
                    replay_errors.append(float(abs(env.state()-source['state'][frame]).max()))
                    physics=sample(env)['physics_state']
                    replay_errors.append(float(abs(physics-source['diagnostic_physics_state'][frame]).max()))
                row['max_replay_error']=max(replay_errors)
                if row['max_replay_error']>1e-5: raise RuntimeError('Recorded actual-command replay mismatch')
                # No state assignment: retract/reopen from the actual contact history, then reacquire target.
                current=env.data.site_xpos[env.site].copy()
                plan=[('recover',np.r_[current[:2],.17],.10,20),
                    ('approach',None,.10,30),('descend',None,.10,32),('grasp',None,0.,20),
                    ('lift',None,0.,30),('transfer',BOX+np.array([0,0,.17]),0.,40),
                    ('lower',BOX+np.array([0,0,.08]),0.,26),('release',BOX+np.array([0,0,.08]),.10,20),
                    ('retreat',BOX+np.array([0,0,.17]),.10,30),('settle',BOX+np.array([0,0,.17]),.10,40)]
                previous=env.state()[:6].copy(); hold=[]
                def step_record(command,stage):
                    obs=env.observe(); timestamp=float(env.data.time); diagnostic=sample(env)
                    writer.append_data(env.panorama())
                    actual=env.step(command)
                    data.append(obs); timestamps.append(timestamp); commands.append(actual); stages.append(stage); diagnostics.append(diagnostic)
                    if env.max_joint_violation>.02: raise RuntimeError('Joint overshoot in correction')
                target=None
                for stage,endpoint,width,n in plan:
                    if stage=='approach': target=env.positions()[env.target].copy()
                    if endpoint is None: endpoint=np.r_[target[:2],.020 if stage in ('descend','grasp') else .17]
                    start=env.data.site_xpos[env.site].copy(); initial_width=env.command[6]
                    for j in range(n):
                        t=(j+1)/n; blend=t*t*(3-2*t)
                        previous=env.ik(start+blend*(endpoint-start),previous)
                        step_record(np.r_[previous,initial_width+blend*(width-initial_width)],stage)
                for _ in range(40): step_record(env.command.copy(),'success_hold'); hold.append(env.result()['success'])
                actual=np.asarray(commands)
                assert env.steps<=420 and np.isfinite(actual).all()
                assert np.max(abs(np.diff(actual[:,:6],axis=0)))<=.045001
                assert np.max(abs(np.diff(actual[:,6])))<=.010001
                assert np.allclose(np.diff(timestamps),.05,atol=1e-8)
                row.update(success=bool(all(hold) and env.result()['success']),terminal=env.result(),frames=len(actual),stable_2s=all(hold),
                    action_semantics='actual targets returned by env.step; observation captured before action',within_420_steps=True)
                if not row['success']: row['reason']='Teacher did not complete unchanged full-success criterion'
            except ValueError as exc:
                if 'Unreachable teacher waypoint' in str(exc): row['reason']=str(exc)
                else: fatal=exc; row['execution_error']=repr(exc)
            except Exception as exc:
                fatal=exc; row['execution_error']=repr(exc)
            finally:
                writer.close()
                if data:
                    np.savez_compressed(stem.with_suffix('.npz'),state=np.stack([x['state'] for x in data]),action=np.asarray(commands,dtype=np.float32),
                        executed_command=np.asarray(commands),external_rgb=np.stack([x['external_rgb'] for x in data]),
                        wrist_rgb=np.stack([x['wrist_rgb'] for x in data]),timestamp=timestamps,stage=stages,prompt=data[0]['prompt'],
                        **{'diagnostic_'+k:v for k,v in arrays(diagnostics).items()})
                    row.update(file=str(stem.with_suffix('.npz')),sha256=sha(stem.with_suffix('.npz')),frames=len(data))
                save(stem.with_suffix('.json'),row)
                report['attempts'].append(row)
                if row['success']: report['accepted'].append(row)
                save(manifest_path,report)
            print('CORRECTION',index,trial_id(case),frame,row['success'],row.get('reason'),flush=True)
            if fatal: raise fatal
    finally: env.close()
    entries=[]
    for row in report['accepted']:
        source=Path(row['file']); out=source.with_suffix(''); out.mkdir(exist_ok=True)
        with np.load(source,allow_pickle=False) as d:
            for k in ('state','action','external_rgb','wrist_rgb'): np.save(out/f'{k}.npy',d[k],allow_pickle=False)
            entries.append(dict(directory=out.name,frames=len(d['state']),split='train',layout_seed=row['source_case']['layout'],target=row['source_case']['target'],prompt=str(d['prompt'])))
    save(directory/'index.json',entries)
    report.update(complete=True,outcome='qualified' if len(entries)>=6 else 'correction_unavailable',
        reason=f'{len(entries)} full successful corrections from {len(report["attempts"])} bounded train-failure attempts')
    save(manifest_path,report)

def fixed(label,checkpoint_path):
    import probe_pi0_120_regression as original
    original.OUT=CAMPAIGN/'probes'; original.RUN=V2
    ref=original.OUT/'teacher_reference'
    ref.parent.mkdir(exist_ok=True)
    if not ref.exists(): ref.symlink_to(DIAG/'teacher_reference',target_is_directory=True)
    dest=original.OUT/'fixed'/label
    if (dest/'protocol.json').exists(): return
    if dest.exists(): dest.rename(dest.with_name(label+f'_incomplete_{time.time_ns()}'))
    policy=PolicyClient('127.0.0.1',PORT)
    try:
        assert Path(policy.metadata['checkpoint'])==checkpoint_path
        original.fixed(policy,label)
    finally: policy.close()

def node(label):
    summary=read(CAMPAIGN/'evaluations'/label/'summary.json')
    prompt=read(CAMPAIGN/'probes/fixed'/label/'prompt_swap.json')
    observations=read(CAMPAIGN/'probes/fixed'/label/'observations.json')
    assert len(prompt)==14 and len(observations)==588
    match=0
    for r in prompt:
        if r['layout']<1000: continue
        pred=np.asarray(r['endpoints'])[:,:2]; truth=np.asarray(r['teacher_endpoints'])[:,:2]
        match+=int((np.linalg.norm(pred[:,None]-truth[None],axis=-1).argmin(axis=1)==np.arange(3)).sum())
    rows=summary['episodes']; val=[r for r in rows if r['split']=='validation']; train=[r for r in rows if r['split']=='train']
    assert len(val)==75
    original=[r for r in val if r['base_seed'] in (42,43)]
    baseline=read(CAMPAIGN/'coverage_summary.json')['validation']
    counts=[sum(r['base_seed']==s and r['success'] for r in val) for s in range(42,47)]
    correct=sum(r['first_close_frame'] is not None and bool(r['close_nearest_is_target']) for r in original)
    wrong=sum(r['non_target_lifted_5cm'] for r in original)
    gates=dict(prompt_match=match>=24,correct_close=correct>=24,wrong_lifts=wrong<=2,
        every_validation_seed_at_least_B=all(n>=baseline['by_seed'][str(s)]['successes'] for n,s in zip(counts,range(42,47))))
    save(CAMPAIGN/f'node_{label}.json',dict(candidate=label,validation_counts=counts,correct_close=correct,non_target_lifts=wrong,
        prompt_matches=match,gates=gates,eligible=all(gates.values()),score=[min(counts),sum(counts),sum(r['success'] for r in train),match],
        local_updates=int(label.split('_')[1]),optimizer_updates=BASE+int(label.split('_')[1]),test_used=False))

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('stage',choices=['evaluate','coverage','prefix','correction','fixed','node','samplers'])
    p.add_argument('--label'); p.add_argument('--roster',type=Path); p.add_argument('--checkpoint',type=Path)
    a=p.parse_args()
    if a.stage=='evaluate': evaluate(a.label,a.roster,a.checkpoint)
    elif a.stage=='fixed': fixed(a.label,a.checkpoint)
    elif a.stage=='node': node(a.label)
    elif a.stage=='samplers':
        from prepare_pi0_bct import samplers
        samplers()
    else: globals()[a.stage]()
