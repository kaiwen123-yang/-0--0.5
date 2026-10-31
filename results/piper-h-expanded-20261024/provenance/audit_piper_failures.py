"""Reconstruct recorded Piper trajectories and measure failure evidence, without GPU."""
import argparse
import json
from pathlib import Path
import numpy as np
import mujoco
from scipy.spatial.transform import Rotation


def original_rotvec(q):
    # Original OpenPI LIBERO helper, q is xyzw; unlike SciPy this keeps angles > pi.
    q=q.copy();q[3]=np.clip(q[3],-1,1);den=np.sqrt(1-q[3]**2)
    return np.zeros(3) if den<1e-8 else q[:3]*2*np.arccos(q[3])/den


def main():
    p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path,required=True);args=p.parse_args()
    run=args.run_dir.resolve();out=run/'diagnostics';out.mkdir(exist_ok=True)
    rows=[json.loads(x) for x in (run/'episodes.jsonl').read_text().splitlines()]
    reports=[]
    for row in rows:
        directory=(run/row['trajectory']).parent
        m=mujoco.MjModel.from_xml_path(str(directory/'scene.xml'));d=mujoco.MjData(m)
        saved=np.load(directory/'trajectory.npz')
        target=m.body('akita_black_bowl_1_main').id;plate=m.body('plate_1_main').id
        tcp=m.site('gripper0_grip_site').id;hand=m.body('robot0_right_hand').id
        finger_ids=[m.geom('gripper0_gripper_link1_collision').id,m.geom('gripper0_gripper_link2_collision').id]
        arm_ids=[m.joint(f'robot0_joint{i}').id for i in range(1,7)]
        joints=m.jnt_qposadr[arm_ids];limits=m.jnt_range[arm_ids]
        traces={'eef':[],'bowl':[],'plate':[],'gripper':[],'joint_margin':[],'contact_fingers':[],'rotvec_difference':[],'orientation':[]}
        for q,v in zip(saved['qpos'],saved['qvel']):
            d.qpos[:]=q;d.qvel[:]=v;mujoco.mj_forward(m,d)
            traces['eef'].append(d.site_xpos[tcp].copy());traces['bowl'].append(d.xpos[target].copy());traces['plate'].append(d.xpos[plate].copy())
            traces['orientation'].append(d.xquat[hand].copy())
            traces['gripper'].append(q[m.jnt_qposadr[m.joint('gripper0_gripper_joint1').id]]-q[m.jnt_qposadr[m.joint('gripper0_gripper_joint2').id]])
            traces['joint_margin'].append(np.minimum(q[joints]-limits[:,0],limits[:,1]-q[joints]))
            quat=d.xquat[hand][[1,2,3,0]]
            traces['rotvec_difference'].append(np.linalg.norm(original_rotvec(quat)-Rotation.from_quat(quat).as_rotvec()))
            touches=[False,False]
            for contact in d.contact[:d.ncon]:
                for i,fg in enumerate(finger_ids):
                    other=contact.geom2 if contact.geom1==fg else contact.geom1 if contact.geom2==fg else None
                    if other is not None and m.geom_bodyid[other]==target:touches[i]=True
            traces['contact_fingers'].append(touches)
        a={k:np.asarray(v) for k,v in traces.items()}
        contact=np.all(a['contact_fingers'],axis=1)
        start=row['wait_steps'];nearest=int(np.argmin(np.linalg.norm(a['eef']-a['bowl'],axis=1)))
        report={'model':row['model'],'task_id':row['task_id'],'trial_index':row['trial_index'],
                'policy_success':row['success'],'adapter_version':row.get('adapter_version','original'),
                'target_initial_xyz':a['bowl'][start].tolist(),'plate_initial_xyz':a['plate'][start].tolist(),
                'target_lift_m':float(a['bowl'][start:,2].max()-a['bowl'][start,2]),'target_final_xyz':a['bowl'][-1].tolist(),
                'target_plate_final_xy_m':float(np.linalg.norm(a['bowl'][-1,:2]-a['plate'][-1,:2])),
                'bilateral_contact_frames':int(contact.sum()),'one_finger_contact_frames':int(np.any(a['contact_fingers'],axis=1).sum()),
                'nearest_eef_frame':nearest,'nearest_eef_distance_m':float(np.linalg.norm(a['eef'][nearest]-a['bowl'][nearest])),
                'nearest_eef_xyz':a['eef'][nearest].tolist(),'gripper_width_at_nearest_m':float(a['gripper'][nearest]),
                'joint_limit_frames_within_1_degree':(a['joint_margin']<np.deg2rad(1)).sum(axis=0).tolist(),
                'original_scipy_rotvec_disagreement_frames':int((a['rotvec_difference']>1).sum()),
                'rotvec_comparison_note':'Historical raw quaternion diagnostic only; not an error count for the v2 positive-x hemisphere adapter.',
                'action_clipped_by_axis':(np.abs(saved['raw_actions'])>1.001).sum(axis=0).tolist()}
        np.savez_compressed(out/f"{row['model']}-task{row['task_id']}-trial{row['trial_index']}-diagnostics.npz",**a)
        reports.append(report);print(json.dumps(report),flush=True)
    (out/'failure-audit.json').write_text(json.dumps(reports,indent=2)+'\n')


if __name__=='__main__':main()
