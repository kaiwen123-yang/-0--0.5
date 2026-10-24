"""Restore policy terminal states, open gripper, retreat, and check stable placement.

This post-policy check is kept separate from policy success and cannot turn a
failed policy into a success. It never changes object states after restoration.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess

import numpy as np
from piper_h_sim_check import setup,make_env
from run_piper_h_trials import composite


def main():
    p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--render',action='store_true')
    p.add_argument('--only',nargs='+',help='Optional task_id:trial_index selection, preserving other saved checks')
    args=p.parse_args()
    run=args.run_dir.resolve();rows=[json.loads(x) for x in (run/'episodes.jsonl').read_text().splitlines()]
    if (run/'provenance/adapter.json').exists():
        os.environ['PIPER_SIM_CONFIG']=str(run/'provenance/adapter.json')
    setup(args.render)
    selected={tuple(map(int,item.split(':'))) for item in args.only} if args.only else None
    reports=json.loads((run/'release-check.json').read_text()) if selected and (run/'release-check.json').exists() else []
    if selected:reports=[r for r in reports if (r['task_id'],r['trial_index']) not in selected]
    for row in rows:
        if not row['success']:continue
        if selected and (row['task_id'],row['trial_index']) not in selected:continue
        folder=(run/row['trajectory']).parent
        saved=np.load(folder/'trajectory.npz')
        env,task=make_env(render=args.render,task_id=row['task_id'],suite=row['suite'])
        writer=None
        try:
            env.reset_from_xml_string((folder/'scene.xml').read_text())
            sim=env.env.sim;robot=env.env.robots[0]
            sim.data.qpos[:]=saved['qpos'][-1];sim.data.qvel[:]=saved['qvel'][-1];sim.forward()
            robot.controller.update_initial_joints(sim.data.qpos[robot._ref_joint_pos_indexes].copy())
            robot.controller.reset_goal();robot.gripper.current_action=np.array([-1.,1.])
            env.env._post_process();env.env._update_observables(force=True);obs=env.env._get_observations()
            # robosuite checks the final mj_step's cached contact/kinematic data.
            # Restoring qpos/qvel and forwarding recomputes these at the new qpos;
            # a marginal contact can differ. Keep that discrepancy explicit and
            # assess placement stability separately without changing policy score.
            terminal_success_after_forward=bool(env.check_success())
            checks=[];states=[]
            if args.render:
                import imageio.v2 as imageio
                from PIL import Image,ImageDraw,ImageFont
                writer=imageio.get_writer(folder/'release-check.mp4',fps=20,codec='libx264',quality=7,macro_block_size=None,ffmpeg_params=['-movflags','+faststart'])
                font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',18)
                def recorded_frame():
                    frame=Image.fromarray(obs['robot0_panorama_image'][::-1])
                    draw=ImageDraw.Draw(frame);draw.rectangle((0,0,1279,31),fill=(19,25,33))
                    draw.text((12,5),'POST-POLICY VALIDATION: open gripper, retreat, hold (fixed checks after policy success)',font=font,fill='white')
                    return np.asarray(frame)
            for i in range(100):
                if writer:writer.append_data(recorded_frame())
                a=np.zeros(7);a[-1]=-1
                if 20<=i<35:a[2]=0.08
                obs,_,_,_=env.step(a)
                sim.forward()
                checks.append(bool(env.check_success()));states.append(sim.data.qpos.copy())
                assert np.isfinite(sim.data.qpos).all()
            if writer:writer.append_data(recorded_frame());writer.close();writer=None
            passed=all(checks[-40:]) and float(obs['robot0_gripper_qpos'][0]-obs['robot0_gripper_qpos'][1])>0.09
            result={'model':row['model'],'task_id':row['task_id'],'trial_index':row['trial_index'],'policy_success':True,
                    'check_version':'v2_fresh_forward','terminal_success_after_forward':terminal_success_after_forward,
                    'release_check_passed':passed,'last_2s_success_frames':sum(checks[-40:]),'total_check_steps':100,
                    'final_gripper_width_m':float(obs['robot0_gripper_qpos'][0]-obs['robot0_gripper_qpos'][1]),
                    'method':'restore final qpos/qvel, record fresh-forward terminal predicate, 20 open steps, 15 small upward retreat steps, 65 hold-open steps; require fresh-forward success throughout final 2 seconds',
                    'source_trajectory':row['trajectory']}
            np.savez_compressed(folder/'release-check-states.npz',qpos=np.asarray(states),success=np.asarray(checks))
            if args.render:
                # Concatenation keeps the untouched policy rollout, followed by a
                # separately identified post-policy release validation segment.
                playlist=folder/'panorama-with-release.ffconcat'
                playlist.write_text("ffconcat version 1.0\nfile 'panorama.mp4'\nfile 'release-check.mp4'\n")
                subprocess.run(['ffmpeg','-v','error','-y','-safe','0','-f','concat','-i',str(playlist),'-c','copy','-movflags','+faststart',str(folder/'panorama-with-release.mp4')],check=True)
                result['video']=str((folder/'panorama-with-release.mp4').relative_to(run))
                result['policy_video_frames']=row['video_frames'];result['release_video_frames']=101
            reports.append(result);print(json.dumps(result),flush=True)
            (run/'release-check.json').write_text(json.dumps(reports,indent=2)+'\n')
        finally:
            if writer:writer.close()
            env.close()
    (run/'release-check.json').write_text(json.dumps(reports,indent=2)+'\n')


if __name__=='__main__':main()
