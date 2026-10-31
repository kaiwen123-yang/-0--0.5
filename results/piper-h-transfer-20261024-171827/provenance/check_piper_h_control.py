"""Small Cartesian tracking and collision checks of the custom simulation only."""
from pathlib import Path
import json
import numpy as np
from scipy.spatial.transform import Rotation
from piper_h_sim_check import setup,make_env


def main():
    setup()
    env,_=make_env()
    measurements=[]
    try:
        for axis in range(6):
            for sign in (-1,1):
                obs=env.reset()
                r=env.env.robots[0];sim=env.env.sim
                r.gripper.current_action=np.array([1.0,-1.0])
                start_pos=obs['robot0_eef_pos'].copy()
                start_rot=Rotation.from_quat(obs['robot0_eef_quat'])
                start_t=sim.data.time
                for t in range(20):
                    a=np.zeros(7);a[-1]=-1
                    if t<3:a[axis]=sign*0.08
                    obs,_,_,_=env.step(a)
                    assert np.isfinite(sim.data.qpos).all() and np.isfinite(sim.data.qvel).all()
                delta=np.r_[obs['robot0_eef_pos']-start_pos,(Rotation.from_quat(obs['robot0_eef_quat'])*start_rot.inv()).as_rotvec()]
                q=sim.data.qpos[r._ref_joint_pos_indexes]
                limits=sim.model.jnt_range[r.joint_indexes]
                violation=float(max(0,np.max(limits[:,0]-q),np.max(q-limits[:,1])))
                response=float(sign*delta[axis])
                assert response>1e-5,(axis,sign,delta)
                assert violation<0.005,(axis,sign,violation)
                assert abs(sim.data.time-start_t-1)<1e-8
                robot_contacts=[]
                for contact in sim.data.contact[:sim.data.ncon]:
                    names=[sim.model.geom_id2name(contact.geom1),sim.model.geom_id2name(contact.geom2)]
                    if any(n and n.startswith(('robot','gripper')) for n in names):
                        robot_contacts.append({'geoms':names,'distance_m':float(contact.dist)})
                assert all(c['distance_m']>-.002 for c in robot_contacts),robot_contacts
                measurements.append({'axis':axis,'sign':sign,'measured_delta':delta.tolist(),'joint_limit_violation_rad':violation,'robot_contacts':robot_contacts})
        result={'status':'passed','robot':'Piper H','cases':len(measurements),'checks':'sign of all six Cartesian axes in both directions, finite state, joint limits, no deep robot contact at home/micro-motions; 20 Hz control time',
                'limitations':'local small-displacement test; not hardware identification or global task-space validation','measurements':measurements}
        path=Path(__file__).resolve().parents[1]/'results/piper-h-sim-check/controller.json'
        path.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({k:v for k,v in result.items() if k!='measurements'}))
    finally:env.close()


if __name__=='__main__':main()
