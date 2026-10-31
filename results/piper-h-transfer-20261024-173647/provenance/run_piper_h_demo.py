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

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path)
    parser.add_argument('--models',nargs='+',choices=['pi0','pi05'],default=['pi0','pi05'])
    parser.add_argument('--task-ids',type=int,nargs='+',default=[0,1,2])
    parser.add_argument('--trials',type=int,default=1)
    args=parser.parse_args()
    if len(set(args.models))!=len(args.models) or len(set(args.task_ids))!=len(args.task_ids):raise ValueError('Duplicate models/tasks')
    if args.trials<1 or any(x<0 or x>9 for x in args.task_ids):raise ValueError('Invalid task/trial selection')
    run=(args.run_dir or ROOT/'results'/datetime.now(ZoneInfo('Asia/Shanghai')).strftime('piper-h-transfer-%Y%m%d-%H%M%S')).resolve()
    run.mkdir(parents=True,exist_ok=False)
    (run/'logs').mkdir();(run/'provenance').mkdir()
    files=['build_piper_h_mjcf.py','piper_h_sim.py','piper_h_sim_check.py','run_piper_h_trials.py','run_piper_h_demo.py',
           'serve_eval_policy.py','serve_local.py','run_libero_trials.py','run_libero_comparison.py','libero_bootstrap.py','run.sh','isolated_python.py']
    snapshots={}
    for name in files:
        p=ROOT/'scripts'/name;shutil.copy2(p,run/'provenance'/name)
        snapshots[name]=hashlib.sha256(p.read_bytes()).hexdigest()
    shutil.copytree(ROOT/'models/piper_h',run/'provenance/piper_h')
    manifest={'created_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'robot':'Piper H','gripper':'AgileX official 100 mm model',
              'models':args.models,'suite':'libero_spatial','task_ids':args.task_ids,'trials':args.trials,
              'expected_episodes':len(args.models)*len(args.task_ids)*args.trials,
              'scope':'exploratory transfer of official Panda LIBERO checkpoints; not standard LIBERO benchmark or hardware-calibrated digital twin',
              'robot_dof':6,'policy_action':'world-frame OSC_POSE deltas plus scalar gripper command',
              'state_adapter':'TCP xyz + official OpenPI LIBERO _quat2axisangle(flange/right_hand xyzw, canonicalized to positive x hemisphere for downward tool tasks) + physical gripper qpos * 0.8',
              'scene_initialization':'same official non-robot joint positions/velocities copied by name; Piper uses collision-checked reachable home instead of Panda state',
              'base_position_m':[-0.46,0,0.9],'home_qpos':json.loads((ROOT/'models/piper_h/home.json').read_text())['qpos'],
              'camera_policy':'original LIBERO agentview plus virtual Piper wrist; panorama is recording-only',
              'video':{'panorama':[1280,720],'multiview':[1280,1008],'fps':20,'includes_settling_and_final':True},
              'seed':7,'replan_steps':5,'flow_steps':10,'wait_steps':10,'max_steps':220,
              'model_horizons':{'pi0':50,'pi05':10},'action_range':[-1,1],
              'source_commits':{'openpi':'215abfb217dbac7d5f1273282331b9b1866c0479','libero':'f78abd68ee283de9f9be3c8f7e2a9ad60246e95c','agx_arm_urdf':'680fa925cd00db7e2628563d2edc5540963045de'},
              'script_sha256':snapshots,'real_hardware_connected':False,'fine_tuning_performed':False}
    (run/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
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
            environment=dict(os.environ,CUDA_VISIBLE_DEVICES='0',JAX_PLATFORMS='cuda',PYTHONUNBUFFERED='1')
            with (run/'logs'/f'server-{model}.log').open('w') as log:
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
                with (run/'logs'/f'{model}-trials.log').open('w') as log:
                    client=subprocess.Popen([str(ROOT/'scripts/run.sh'),'libero',str(ROOT/'scripts/run_piper_h_trials.py'),
                                             '--run-dir',str(run),'--model',model,'--port',str(port),'--trials',str(args.trials),
                                             '--task-ids',*map(str,args.task_ids)],cwd=ROOT,env=environment,
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
