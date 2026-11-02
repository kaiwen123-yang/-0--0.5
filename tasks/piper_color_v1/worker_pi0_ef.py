"""Real autonomous episodes, frozen-input probes and train-only teacher work."""
import argparse
import collections
import sys
import time
import imageio.v2 as imageio
import numpy as np
from ef_common import *
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
    import evaluate_pi0_ef as evaluator
    from publish_pi0_ef import publish
    tasks=read(roster_path)
    assert len({key(r) for r in tasks})==len(tasks)
    directory=CAMPAIGN/'evaluations'/label
    directory.mkdir(parents=True,exist_ok=True)
    rows=[]
    for task in tasks:
        unit=directory/trial_id(task)
        done=unit/'completed.json'
        was_completed=done.exists()
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
                    '--layout-seeds',str(task['layout']),'--targets',task['target'],'--data',str(CAMPAIGN/'evaluation_layouts'),
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
        if was_completed:
            continue  # Resume only new work; do not republish every historical 15-trial boundary.
        save(directory/'trials.json',rows)
        save(CAMPAIGN/'evaluation_progress.json',dict(label=label,completed=len(rows),expected=len(tasks),at_utc=now(),last=task))
        if len(rows)%15==0: publish(CAMPAIGN,f'{label}-{len(rows)}-episodes')
    result=summarize([metrics(r) for r in rows])
    save(directory/'summary.json',result)

def correction():
    cases=read(CAMPAIGN/'correction_roster.json')
    directory=CAMPAIGN/'correction_dataset'; directory.mkdir(exist_ok=True)
    manifest=CAMPAIGN/'correction_manifest.json'
    report=read(manifest) if manifest.exists() else dict(attempts=[],accepted=[],train_only=True)
    if report.get('complete'): return
    env=ColorEnvV2(render=True)
    entries=[]
    if (directory/'index.json').exists(): entries=read(directory/'index.json')
    try:
        for index,case in enumerate(cases[:36]):
            if len(report['accepted'])>=24: break
            if index<len(report['attempts']): continue
            frame=case['intervention_frame']; stem=directory/f'correction_{index:03d}'
            env.reset(case['layout'],case['target'])
            writer=imageio.get_writer(str(stem.with_suffix('.mp4')),fps=20,codec='libx264',quality=7,macro_block_size=1,output_params=['-threads','2'])
            observations=[]; actual=[]; timestamps=[]; stages=[]; traces=[]
            row=dict(attempt=index,source_trial=case['trajectory'],layout=case['layout'],target=case['target'],
                slot=case['slot'],intervention_frame=frame,reason=case['intervention_reason'],success=False,
                video=str(stem.with_suffix('.mp4')),trajectory=str(stem.with_suffix('.npz')))
            consecutive=0; full=False
            def record(command,stage):
                nonlocal consecutive,full
                if env.steps>=420: return False
                observations.append(env.observe()); timestamps.append(float(env.data.time))
                traces.append(sample(env)); writer.append_data(env.panorama())
                actual.append(env.step(command)); stages.append(stage)
                consecutive=consecutive+1 if env.result()['success'] else 0
                full=consecutive>=40
                return not full and env.steps<420
            def move(stage,endpoint,width,n):
                start=env.data.site_xpos[env.site].copy(); w=env.command[6]
                previous=env.state()[:6].copy()
                for j in range(n):
                    t=(j+1)/n; b=t*t*(3-2*t)
                    previous=env.ik(start+b*(endpoint-start),previous)
                    if not record(np.r_[previous,w+b*(width-w)],stage): return False
                return True
            try:
                with np.load(case['trajectory']) as source:
                    for command in source['executed_command'][:frame]: record(command,'policy_prefix')
                    row['replay_qpos_max_error']=float(abs(env.data.qpos-source['qpos'][frame]).max())
                pos=env.positions()[env.target].copy(); tcp=env.data.site_xpos[env.site].copy()
                held=pos[2]>.05 and env.state()[6]<.06 and np.linalg.norm(pos-tcp)<.065
                row['held_at_takeover']=bool(held)
                plan=[]
                if not held:
                    width=float(env.state()[6]); xy=float(np.linalg.norm(tcp[:2]-pos[:2]))
                    # Reopening is conditional on a closed empty gripper; retreat only for a low lateral collision.
                    if width<.045: plan.append(('local_reopen',tcp.copy(),.10,12))
                    align_z=max(float(tcp[2]),.06) if xy>.025 else float(tcp[2])
                    endpoint=np.r_[pos[:2],align_z]
                    if np.linalg.norm(endpoint-tcp)>.002:
                        plan.append(('local_align',endpoint,.10,max(10,int(np.ceil(np.linalg.norm(endpoint-tcp)/.0047)))))
                    plan.append(('descend',np.r_[pos[:2],.020],.10,max(10,int(np.ceil(abs(align_z-.020)/.0047)))))
                    plan.append(('grasp',np.r_[pos[:2],.020],0.,20))
                    plan.append(('lift',np.r_[pos[:2],.17],0.,30))
                elif tcp[2]<.16:
                    plan.append(('lift',np.r_[tcp[:2],.17],0.,max(10,int(np.ceil(abs(.17-tcp[2])/.0047)))))
                plan += [('transfer',BOX+np.array([0,0,.17]),0.,40),
                    ('lower',BOX+np.array([0,0,.08]),0.,26),
                    ('release',BOX+np.array([0,0,.08]),.10,20),
                    ('retreat',BOX+np.array([0,0,.17]),.10,30),
                    ('settle',BOX+np.array([0,0,.17]),.10,40)]
                row['teacher_plan']=[dict(stage=s,endpoint=x.tolist(),width=w,steps=n) for s,x,w,n in plan]
                for stage,endpoint,width,n in plan:
                    if not move(stage,endpoint,width,n): break
                while not full and env.steps<420:
                    if not record(env.command.copy(),'success_hold'): break
                row.update(success=bool(full),terminal=env.result(),steps=env.steps,teacher_frames=len(actual)-frame,
                           continuous_success_steps=consecutive)
            except ValueError as exc:
                row['failure_reason']=str(exc)
            finally:
                writer.close()
                d=arrays(traces)
                np.savez_compressed(stem.with_suffix('.npz'),
                    state=np.stack([o['state'] for o in observations]),
                    executed_command=np.asarray(actual),timestamp=np.asarray(timestamps),stage=np.asarray(stages),
                    external_rgb=np.stack([o['external_rgb'] for o in observations]),
                    wrist_rgb=np.stack([o['wrist_rgb'] for o in observations]),
                    teacher_mask=np.arange(len(actual))>=frame,prompt=observations[0]['prompt'],
                    **{'diagnostic_'+k:v for k,v in d.items()})
            save(stem.with_suffix('.json'),row)
            report['attempts'].append(row)
            if row['success']:
                # Only expert suffix is a training episode. Full prefix and failures remain in NPZ/video.
                out=stem; out.mkdir(exist_ok=True)
                for name,arr in [('state',np.stack([o['state'] for o in observations])),
                    ('action',np.asarray(actual,dtype=np.float32)),
                    ('external_rgb',np.stack([o['external_rgb'] for o in observations])),
                    ('wrist_rgb',np.stack([o['wrist_rgb'] for o in observations]))]:
                    np.save(out/(name+'.npy'),arr[frame:],allow_pickle=False)
                np.save(out/'stage.npy',np.asarray(stages)[frame:],allow_pickle=False)
                entries.append(dict(directory=out.name,frames=len(actual)-frame,split='train',
                    layout_seed=case['layout'],target=case['target'],slot=case['slot'],prompt=observations[0]['prompt']))
                report['accepted'].append(row)
            save(directory/'index.json',entries); save(manifest,report)
            print('CORRECTION',index,case['layout'],case['target'],frame,row['success'],len(report['accepted']),flush=True)
    finally: env.close()
    report.update(complete=True,outcome='qualified' if entries else 'no_successful_local_corrections',
        attempted=len(report['attempts']),accepted_count=len(entries),maximum_attempts=36)
    save(manifest,report)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['correction','evaluate'])
    p.add_argument('--label');p.add_argument('--roster',type=Path);p.add_argument('--checkpoint',type=Path)
    a=p.parse_args()
    correction() if a.stage=='correction' else evaluate(a.label,a.roster,a.checkpoint)

