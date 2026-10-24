"""Run pi0 / pi0.5 Piper H transfer demos sequentially; own and clean up servers."""
import argparse
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import time
import urllib.request

from run_libero_comparison import stop
from run_libero_trials import MAX_STEPS

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path)
    parser.add_argument('--models',nargs='+',choices=['pi0','pi05'],default=['pi0','pi05'])
    parser.add_argument('--task-ids',type=int,nargs='+',default=[0,1,2])
    parser.add_argument('--trials',type=int,default=1)
    parser.add_argument('--trial-start',type=int,default=0)
    parser.add_argument('--suite',choices=list(MAX_STEPS),default='libero_spatial')
    parser.add_argument('--adapter-config',type=Path)
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args()
    if args.resume and not args.run_dir:raise ValueError('--resume requires --run-dir')
    if len(set(args.models))!=len(args.models) or len(set(args.task_ids))!=len(args.task_ids):raise ValueError('Duplicate models/tasks')
    if args.trials<1 or args.trial_start<0 or any(x<0 or x>9 for x in args.task_ids):raise ValueError('Invalid task/trial selection')
    if args.adapter_config:
        adapter=json.loads(args.adapter_config.read_text())
    else:
        adapter={'version':'v2_quaternion_hemisphere_and_home_yaw','tool_frame_z_rad':0.,
                 'home_qpos':json.loads((ROOT/'models/piper_h/home.json').read_text())['qpos'],
                 'replan_steps':5,'gripper_state_scale':.8}
    run=(args.run_dir or ROOT/'results'/datetime.now(ZoneInfo('Asia/Shanghai')).strftime('piper-h-transfer-%Y%m%d-%H%M%S')).resolve()
    previous=json.loads((run/'manifest.json').read_text()) if args.resume else None
    if previous:
        for field,value in [('models',args.models),('suite',args.suite),('task_ids',args.task_ids),('trials',args.trials),('trial_start',args.trial_start),('adapter',adapter)]:
            if previous[field]!=value:raise ValueError(f'Resume configuration changed: {field}')
        for name,expected in previous['script_sha256'].items():
            if hashlib.sha256((ROOT/'scripts'/name).read_bytes()).hexdigest()!=expected:raise ValueError(f'Resume source changed: {name}')
    run.mkdir(parents=True,exist_ok=args.resume)
    (run/'logs').mkdir(exist_ok=args.resume);(run/'provenance').mkdir(exist_ok=args.resume)
    files=['build_piper_h_mjcf.py','piper_h_sim.py','piper_h_sim_check.py','piper_adapter.py','run_piper_h_trials.py','run_piper_h_demo.py',
           'serve_eval_policy.py','serve_local.py','run_libero_trials.py','run_libero_comparison.py','libero_bootstrap.py','run.sh','isolated_python.py']
    snapshots={}
    for name in files:
        p=ROOT/'scripts'/name;shutil.copy2(p,run/'provenance'/name)
        snapshots[name]=hashlib.sha256(p.read_bytes()).hexdigest()
    shutil.copytree(ROOT/'models/piper_h',run/'provenance/piper_h',dirs_exist_ok=args.resume)
    (run/'provenance/adapter.json').write_text(json.dumps(adapter,indent=2)+'\n')
    manifest={'created_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'robot':'Piper H','gripper':'AgileX official 100 mm model',
              'models':args.models,'suite':args.suite,'task_ids':args.task_ids,'trials':args.trials,'trial_start':args.trial_start,
              'expected_episodes':len(args.models)*len(args.task_ids)*args.trials,
              'adapter_version':adapter['version'],'adapter':adapter,
              'home_orientation_yaw_rad':0.35,
              'home_orientation_frame':'policy-equivalent tool frame, including configured local-Z offset',
              'scope':'small-sample Piper H adapter validation with official Panda LIBERO checkpoints; not standard LIBERO benchmark or hardware-calibrated digital twin',
              'robot_dof':6,'policy_action':'world-frame OSC_POSE deltas plus scalar gripper command',
              'state_adapter':'TCP xyz + official OpenPI LIBERO _quat2axisangle(physical hand rotation * local Z tool offset, positive x quaternion hemisphere) + physical gripper qpos * configured scale',
              'scene_initialization':'same official non-robot joint positions/velocities copied by name; Piper uses collision-checked reachable home instead of Panda state',
              'base_position_m':[-0.46,0,0.0 if args.suite=='libero_object' else 0.9],
              'base_position_note':'Nominal arena mount; saved per-episode scene.xml is the authoritative resolved pose',
              'home_qpos':adapter['home_qpos'],
              'camera_policy':'original LIBERO agentview plus virtual Piper wrist; panorama is recording-only',
              'video':{'panorama':[1280,720],'multiview':[1280,1008],'fps':20,'includes_settling_and_final':True},
              'seed':7,'replan_steps':adapter['replan_steps'],'flow_steps':10,'wait_steps':10,'max_steps':MAX_STEPS[args.suite],
              'model_horizons':{'pi0':50,'pi05':10},'action_range':[-1,1],
              'source_commits':{'openpi':'215abfb217dbac7d5f1273282331b9b1866c0479','libero':'f78abd68ee283de9f9be3c8f7e2a9ad60246e95c','agx_arm_urdf':'680fa925cd00db7e2628563d2edc5540963045de'},
              'script_sha256':snapshots,'real_hardware_connected':False,'fine_tuning_performed':False}
    if previous:manifest=previous
    else:(run/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    with (run/'attempts.jsonl').open('a') as f:
        f.write(json.dumps({'started_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'resume':args.resume})+'\n')
    (ROOT/'results/current-piper-h-transfer.txt').write_text(str(run)+'\n')
    print('RUN_DIR='+str(run),flush=True)
    server=client=None
    def interrupted(signum,frame):
        raise KeyboardInterrupt(f'Received signal {signum}')
    signal.signal(signal.SIGTERM,interrupted)
    signal.signal(signal.SIGINT,interrupted)
    try:
        for model in args.models:
            active=subprocess.check_output(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader,nounits'],text=True).strip()
            if active:raise RuntimeError('GPU compute is occupied; no existing process will be interrupted')
            with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
            environment=dict(os.environ,CUDA_VISIBLE_DEVICES='0',JAX_PLATFORMS='cuda',PYTHONUNBUFFERED='1',
                             PIPER_SIM_CONFIG=str(run/'provenance/adapter.json'))
            with (run/'logs'/f'server-{model}.log').open('a') as log:
                server=subprocess.Popen([str(ROOT/'scripts/run.sh'),'openpi',str(ROOT/'scripts/serve_eval_policy.py'),
                                         '--model',model,'--run-dir',str(run),'--port',str(port)],cwd=ROOT,env=environment,
                                        stdout=log,stderr=log,start_new_session=True)
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                deadline=time.monotonic()+240
                while True:
                    if server.poll() is not None:raise RuntimeError('Model server exited; inspect logs')
                    try:
                        with opener.open(f'http://127.0.0.1:{port}/healthz',timeout=1) as response:
                            if response.read()==b'OK\n':break
                    except OSError:
                        if time.monotonic()>deadline:raise TimeoutError('Server not ready in 240 seconds')
                        time.sleep(1)
                print('EVALUATING '+model,flush=True)
                with (run/'logs'/f'{model}-trials.log').open('a') as log:
                    client=subprocess.Popen([str(ROOT/'scripts/run.sh'),'libero',str(ROOT/'scripts/run_piper_h_trials.py'),
                                             '--run-dir',str(run),'--model',model,'--port',str(port),'--trials',str(args.trials),
                                             '--suite',args.suite,'--trial-start',str(args.trial_start),
                                             '--task-ids',*map(str,args.task_ids),*(['--resume'] if args.resume else [])],cwd=ROOT,env=environment,
                                            stdout=log,stderr=log,start_new_session=True)
                    code=client.wait()
                if code:raise RuntimeError(f'{model} evaluator exited {code}; inspect logs')
                stop(server);server=None
        rows=[json.loads(x) for x in (run/'episodes.jsonl').read_text().splitlines()]
        assert len(rows)==manifest['expected_episodes'] and not any(x['error'] for x in rows)
        summary={model:{'successes':sum(x['success'] for x in rows if x['model']==model),'episodes':sum(x['model']==model for x in rows)} for model in args.models}
        (run/'summary.json').write_text(json.dumps({'status':'complete','results':summary,'scope':manifest['scope']},indent=2)+'\n')
        print(json.dumps(summary),flush=True)
    finally:
        stop(client);stop(server)


if __name__=='__main__':main()
