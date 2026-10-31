"""Measure contacts and object motion in saved Object trajectories, without a policy.

The diagnostic categories describe recorded geometry, not causal proof or a new
success criterion. All policy outcomes remain those returned during evaluation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

import mujoco
import numpy as np

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    args=parser.parse_args();run=args.run_dir.resolve();reports=[]
    rows=[json.loads(line) for line in (run/'episodes.jsonl').read_text().splitlines()]
    for row in rows:
        assert row['suite']=='libero_object'
        bddl=ROOT/'repos/openpi/third_party/libero/libero/libero/bddl_files/libero_object'/f"{row['task_name'].replace(' ','_')}.bddl"
        match=re.search(r'\(In\s+(\w+)\s+(\w+)_contain_region\)',bddl.read_text().split('(:goal')[1])
        assert match
        target_name,destination_name=match.groups()
        folder=(run/row['trajectory']).parent
        model=mujoco.MjModel.from_xml_path(str(folder/'scene.xml'));data=mujoco.MjData(model)
        saved=np.load(folder/'trajectory.npz',allow_pickle=False)
        target=model.body(target_name+'_main').id;destination=model.body(destination_name+'_main').id
        target_bodies={target}
        for body in range(target+1,model.nbody):
            if model.body_parentid[body] in target_bodies:target_bodies.add(body)
        finger_ids=[model.geom(f'gripper0_gripper_link{i}_collision').id for i in (1,2)]
        joint_ids=[model.joint(f'robot0_joint{i}').id for i in range(1,7)]
        traces={'target_xyz':[],'destination_xyz':[],'eef_xyz':[],'contact_fingers':[],'joint_margin':[]}
        for q,v in zip(saved['qpos'],saved['qvel']):
            data.qpos[:]=q;data.qvel[:]=v;mujoco.mj_forward(model,data)
            traces['target_xyz'].append(data.xpos[target].copy())
            traces['destination_xyz'].append(data.xpos[destination].copy())
            traces['eef_xyz'].append(data.site_xpos[model.site('gripper0_grip_site').id].copy())
            touches=[False,False]
            for contact in data.contact[:data.ncon]:
                for index,finger in enumerate(finger_ids):
                    other=contact.geom2 if contact.geom1==finger else contact.geom1 if contact.geom2==finger else None
                    if other is not None and model.geom_bodyid[other] in target_bodies:touches[index]=True
            traces['contact_fingers'].append(touches)
            joints=q[model.jnt_qposadr[joint_ids]];limits=model.jnt_range[joint_ids]
            traces['joint_margin'].append(np.minimum(joints-limits[:,0],limits[:,1]-joints))
        traces={name:np.asarray(values) for name,values in traces.items()}
        contact_frames=int(np.all(traces['contact_fingers'],axis=1).sum())
        lift=float(traces['target_xyz'][row['wait_steps']:,2].max()-traces['target_xyz'][row['wait_steps'],2])
        category='policy_success' if row['success'] else 'no_bilateral_target_contact' if contact_frames==0 else 'bilateral_contact_without_3cm_rise' if lift<.03 else 'target_rose_3cm_but_goal_not_reached'
        reports.append({'model':row['model'],'task_id':row['task_id'],'trial_index':row['trial_index'],
            'task_name':row['task_name'],'policy_success':row['success'],'target':target_name,
            'diagnostic_category':category,'category_note':'Descriptive contact/height thresholds only; not proof of grasp quality or failure cause.',
            'bilateral_target_contact_frames':contact_frames,'target_max_rise_m':lift,
            'target_initial_xyz':traces['target_xyz'][row['wait_steps']].tolist(),
            'target_final_xyz':traces['target_xyz'][-1].tolist(),
            'target_destination_final_xy_m':float(np.linalg.norm(traces['target_xyz'][-1,:2]-traces['destination_xyz'][-1,:2])),
            'joint_limit_frames_within_1_degree':(traces['joint_margin']<np.deg2rad(1)).sum(axis=0).tolist(),
            'goal_bddl_sha256':hashlib.sha256(bddl.read_bytes()).hexdigest()})
    out=run/'diagnostics';out.mkdir(exist_ok=True)
    (out/'object-audit.json').write_text(json.dumps(reports,indent=2)+'\n')
    print(json.dumps({category:sum(row['diagnostic_category']==category for row in reports) for category in sorted({row['diagnostic_category'] for row in reports})}))


if __name__=='__main__':main()
