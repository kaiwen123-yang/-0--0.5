"""Run official OpenPI checkpoints through the Piper H v2 adapter, saving panorama.

This is a different embodiment from the standard Panda LIBERO benchmark.
Full 1280x720 scenery and a 1280x1008 three-camera video are both retained.
"""
import argparse
import collections
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import time
import traceback

from piper_h_sim_check import setup,make_env
from run_libero_trials import connect_client,MAX_STEPS,atomic_json,load_upstream_main
from piper_adapter import configuration,policy_state

ROOT=Path(__file__).resolve().parents[1]


def transfer_scene(env, reference, initial_state):
    """Copy named non-robot joints; never load a 7-DOF robot state into 6-DOF Piper."""
    import numpy as np
    reference.set_init_state(initial_state)
    source=reference.env.sim
    target=env.env.sim
    scene={}
    for name in source.model.joint_names:
        if name.startswith(("robot", "gripper")):
            continue
        if name not in target.model.joint_names:
            raise ValueError(f"Scene joint missing from Piper environment: {name}")
        q=np.asarray(source.data.get_joint_qpos(name)).copy()
        v=np.asarray(source.data.get_joint_qvel(name)).copy()
        target.data.set_joint_qpos(name,q)
        target.data.set_joint_qvel(name,v)
        scene[name]={"qpos":q.tolist(),"qvel":v.tolist()}
    expected={n for n in target.model.joint_names if not n.startswith(("robot","gripper"))}
    assert set(scene)==expected
    target.forward()
    for name,value in scene.items():
        assert np.array_equal(target.data.get_joint_qpos(name),np.asarray(value['qpos']))
        assert np.array_equal(target.data.get_joint_qvel(name),np.asarray(value['qvel']))
    env.env._post_process()
    env.env._update_observables(force=True)
    encoded=json.dumps(scene,sort_keys=True,separators=(",",":"))
    return env.env._get_observations(),scene,hashlib.sha256(encoded.encode()).hexdigest()


def composite(obs, model, task, step, phase):
    import numpy as np
    from PIL import Image,ImageDraw,ImageFont
    # robosuite's image observation requires a vertical flip for human display.
    # Policy preprocessing below remains the official LIBERO 180-degree rotation.
    panorama=np.ascontiguousarray(obs['robot0_panorama_image'][::-1])
    canvas=Image.new('RGB',(1280,1008),(19,25,33))
    canvas.paste(Image.fromarray(panorama),(0,32))
    canvas.paste(Image.fromarray(obs['agentview_image'][::-1]),(0,752))
    canvas.paste(Image.fromarray(obs['robot0_eye_in_hand_image'][::-1]),(256,752))
    draw=ImageDraw.Draw(canvas)
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',18)
    small=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',16)
    draw.text((12,5),f'Piper H + AgileX 100 mm gripper | {model} | {phase} | control step {step}',font=font,fill='white')
    draw.rectangle((0,752,255,774),fill=(19,25,33));draw.text((6,753),'External camera',font=small,fill='white')
    draw.rectangle((256,752,511,774),fill=(19,25,33));draw.text((262,753),'Wrist camera',font=small,fill='white')
    import textwrap
    draw.multiline_text((535,775),'Task:\n'+'\n'.join(textwrap.wrap(task,67))+'\n\nPiper H / official LIBERO checkpoint\n20 FPS | panorama + external + wrist\nNo real robot connected',font=small,fill='white',spacing=8)
    return panorama,np.asarray(canvas)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--model',choices=['pi0','pi05'],required=True)
    parser.add_argument('--suite',default='libero_spatial',choices=list(MAX_STEPS))
    parser.add_argument('--task-ids',type=int,nargs='+',default=[0,1,2])
    parser.add_argument('--trials',type=int,default=1)
    parser.add_argument('--trial-start',type=int,default=0)
    parser.add_argument('--port',type=int,required=True)
    args=parser.parse_args()
    adapter=configuration()
    run=args.run_dir.resolve()
    run.mkdir(parents=True,exist_ok=True)
    setup(render=True)
    import imageio.v2 as imageio
    import numpy as np
    from libero.libero import benchmark
    from openpi_client import image_tools
    upstream=load_upstream_main(ROOT)
    suite=benchmark.get_benchmark_dict()[args.suite]()
    client=connect_client('127.0.0.1',args.port)
    metadata=client.get_server_metadata()
    assert metadata['model']==args.model and metadata['run_id']==run.name
    records_path=run/'episodes.jsonl'
    existing=[json.loads(x) for x in records_path.read_text().splitlines()] if records_path.exists() else []
    keys={(r['model'],r['suite'],r['task_id'],r['trial_index']) for r in existing}
    try:
        for task_id in args.task_ids:
            reference=env=None
            try:
                np.random.seed(7)
                reference,_=make_env(robot='Panda',render=False,task_id=task_id,suite=args.suite)
                env,task=make_env(render=True,task_id=task_id,suite=args.suite)
                states=suite.get_task_init_states(task_id)
                for trial in range(args.trial_start,args.trial_start+args.trials):
                    key=(args.model,args.suite,task_id,trial)
                    if key in keys: raise RuntimeError(f'Refusing existing episode {key}')
                    episode=f'{args.suite}/{task_id}/{trial}'
                    directory=run/'videos'/args.model/args.suite/f'task_{task_id:02d}'/f'trial_{trial:03d}'
                    directory.mkdir(parents=True,exist_ok=False)
                    paths={kind:directory/f'{kind}.mp4' for kind in ('panorama','multiview')}
                    writers={kind:imageio.get_writer(path.with_suffix('.partial.mp4'),fps=20,codec='libx264',quality=7,
                                                     macro_block_size=None,ffmpeg_params=['-movflags','+faststart']) for kind,path in paths.items()}
                    started=time.monotonic(); actions=[]; raw_actions=[]; positions=[]; velocities=[]; frames=0; inference_calls=0
                    clipped_action_steps=0
                    success=False; error=None; steps=0; scene_hash=None; scene=None
                    policy_seed=7+list(MAX_STEPS).index(args.suite)*10000+task_id*100+trial
                    try:
                        np.random.seed(7);reference.seed(7);reference.reset()
                        np.random.seed(7);env.seed(7);env.reset()
                        obs,scene,scene_hash=transfer_scene(env,reference,states[trial])
                        robot=env.env.robots[0]
                        robot.gripper.current_action=np.array([1.0,-1.0])
                        robot.controller.reset_goal()
                        # Save the full instantiated scene for rerendering saved qpos/qvel.
                        (directory/'scene.xml').write_text(env.env.sim.model.get_xml())

                        def record_frame(phase):
                            nonlocal frames
                            pan,combined=composite(obs,args.model,task.language,steps,phase)
                            writers['panorama'].append_data(pan)
                            writers['multiview'].append_data(combined)
                            positions.append(env.env.sim.data.qpos.copy())
                            velocities.append(env.env.sim.data.qvel.copy())
                            frames+=1

                        for _ in range(10):
                            record_frame('settling')
                            obs,_,_,_=env.step([0,0,0,0,0,0,-1])
                        plan=collections.deque()
                        for t in range(MAX_STEPS[args.suite]):
                            record_frame('policy rollout')
                            if not plan:
                                policy_images=[image_tools.convert_to_uint8(image_tools.resize_with_pad(
                                    np.ascontiguousarray(obs[name][::-1,::-1]),224,224)) for name in ('agentview_image','robot0_eye_in_hand_image')]
                                # Keep physical qpos in saved sim state. Map full opening to the
                                # Panda checkpoint's +/-0.04 m input range as an explicit heuristic.
                                # MuJoCo's parent quaternion products can differ by sign
                                # across robot descriptions. Choose the same downward-tool
                                # hemisphere as the LIBERO Panda training states (positive x).
                                state=policy_state(obs,upstream._quat2axisangle,adapter)
                                answer=client.infer({'observation/image':policy_images[0],'observation/wrist_image':policy_images[1],
                                                     'observation/state':state,'prompt':task.language,
                                                     'evaluation/episode_id':episode,'evaluation/seed':policy_seed})
                                chunk=np.asarray(answer['actions'])
                                assert chunk.ndim==2 and chunk.shape[1]==7 and len(chunk)>=adapter['replan_steps'] and np.isfinite(chunk).all()
                                plan.extend(chunk[:adapter['replan_steps']]);inference_calls+=1
                            action=np.asarray(plan.popleft(),dtype=np.float64)
                            raw_actions.append(action.copy())
                            if np.any(np.abs(action)>1.001):
                                action=np.clip(action,-1,1)
                                clipped_action_steps+=1
                            previous_time=float(env.env.sim.data.time)
                            obs,_,success,_=env.step(action.tolist())
                            actions.append(action);steps=t+1
                            qpos=env.env.sim.data.qpos; qvel=env.env.sim.data.qvel
                            if not np.isfinite(qpos).all() or not np.isfinite(qvel).all(): raise RuntimeError('Nonfinite simulation state')
                            if abs(float(env.env.sim.data.time)-previous_time-0.05)>1e-6:raise RuntimeError('Simulation time reset or unexpected step duration')
                            if np.max(np.abs(qvel[robot._ref_joint_vel_indexes]))>30: raise RuntimeError('Arm joint velocity exceeded simulation sanity limit (30 rad/s)')
                            if success:break
                        record_frame('SUCCESS' if success else 'TIME LIMIT - not successful')
                    except BaseException as exc:
                        error=f'{type(exc).__name__}: {exc}'
                        traceback.print_exc()
                    finally:
                        for writer in writers.values():writer.close()
                    status='error' if error else 'success' if success else 'failure'
                    for path in paths.values():path.with_suffix('.partial.mp4').replace(path)
                    state_path=directory/'trajectory.npz'
                    np.savez_compressed(state_path,actions=np.asarray(actions),raw_actions=np.asarray(raw_actions),qpos=np.asarray(positions),qvel=np.asarray(velocities))
                    (directory/'initial_scene.json').write_text(json.dumps(scene,indent=2)+'\n')
                    row={'model':args.model,'robot':'Piper H','gripper':'AgileX 100 mm','suite':args.suite,'task_id':task_id,
                         'adapter_version':adapter['version'],
                         'trial_index':trial,'task_name':task.language,'success':bool(success) if not error else False,'status':status,
                         'steps':steps,'wait_steps':10,'video_frames':frames,'fps':20,'scene_sha256':scene_hash,
                         'source_initial_state_sha256':hashlib.sha256(np.asarray(states[trial]).tobytes()).hexdigest(),
                         'environment_seed':7,'policy_seed':policy_seed,'inference_calls':inference_calls,
                         'clipped_action_steps':clipped_action_steps,
                         'videos':{k:str(v.relative_to(run)) for k,v in paths.items()},'trajectory':str(state_path.relative_to(run)),
                         'server_metadata':metadata,'elapsed_seconds':time.monotonic()-started,'error':error,
                         'recorded_at':datetime.now(timezone.utc).isoformat()}
                    with records_path.open('a') as f:f.write(json.dumps(row)+'\n');f.flush()
                    print(json.dumps(row),flush=True)
                    atomic_json(run/'progress.json',{'model':args.model,'episode':episode,'status':status})
                    if error:raise RuntimeError(error)
            finally:
                if env is not None:env.close()
                if reference is not None:reference.close()
    finally:
        client._ws.close()


if __name__=='__main__':main()
