"""Validate custom Piper H robot dynamics and cameras without any policy model."""
import argparse
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def setup(render=False):
    from libero_bootstrap import configure, allow_trusted_initial_states
    configure(cpu_only=not render)
    if render:
        for key in ("__EGL_VENDOR_LIBRARY_FILENAMES","LIBGL_ALWAYS_SOFTWARE","MESA_LOADER_DRIVER_OVERRIDE","GALLIUM_DRIVER"):
            os.environ.pop(key,None)
        os.environ.update(MUJOCO_GL="egl",PYOPENGL_PLATFORM="egl",MUJOCO_EGL_DEVICE_ID="0")
    allow_trusted_initial_states()
    import piper_h_sim


def make_env(robot="PiperH", render=False, task_id=0, suite="libero_spatial"):
    from libero.libero import benchmark,get_libero_path
    from libero.libero.envs.env_wrapper import ControlEnv
    task=benchmark.get_benchmark_dict()[suite]().get_task(task_id)
    env=ControlEnv(bddl_file_name=str(Path(get_libero_path("bddl_files"))/task.problem_folder/task.bddl_file),
                   robots=[robot],use_camera_obs=render,has_offscreen_renderer=render,
                   camera_names=["agentview","robot0_eye_in_hand","robot0_panorama"] if robot=="PiperH" else ["agentview","robot0_eye_in_hand"],
                   camera_heights=[256,256,720] if robot=="PiperH" else 256,
                   camera_widths=[256,256,1280] if robot=="PiperH" else 256,
                   initialization_noise=None,control_freq=20)
    env.seed(7)
    return env,task


def solve_home(env, target_pos=None, target_rot=None):
    import numpy as np
    from scipy.optimize import least_squares
    from scipy.spatial.transform import Rotation
    robot=env.env.robots[0]
    sim=env.env.sim
    idx=robot._ref_joint_pos_indexes
    site=robot.eef_site_id
    if target_pos is None: target_pos=np.array([-0.20,0,1.08])
    # A small yaw keeps joint 6 inside its official +/-170-degree limits while
    # starting near the Panda checkpoint's downward-facing tool convention.
    if target_rot is None: target_rot=Rotation.from_euler("xyz",[np.pi,0,0.35]).as_matrix()
    limits=sim.model.jnt_range[robot.joint_indexes]

    def residual(q):
        sim.data.qpos[idx]=q
        sim.forward()
        return np.r_[sim.data.site_xpos[site]-target_pos,
                     0.2*Rotation.from_matrix(target_rot@sim.data.site_xmat[site].reshape(3,3).T).as_rotvec()]
    solutions=[]
    rng=np.random.default_rng(7)
    seeds=[[0,1.0,-1.0,0,1.0,0],[0,1.8,-1.7,0,0.8,0],[0,0.6,-1.5,0,1.4,0]]
    seeds.extend(rng.uniform(limits[:,0]+0.01,limits[:,1]-0.01,size=(24,6)))
    for seed in seeds:
        sol=least_squares(residual,seed,bounds=(limits[:,0]+1e-4,limits[:,1]-1e-4),max_nfev=200)
        solutions.append(sol)
        if np.linalg.norm(sol.fun)<1e-6:break
    sol=min(solutions,key=lambda x:np.linalg.norm(x.fun))
    error=residual(sol.x)
    if np.linalg.norm(error)>0.005:
        raise RuntimeError(f"Home IK did not converge: {error}, q={sol.x}")
    robot.init_qpos=sol.x.copy()
    robot.controller.update_initial_joints(sol.x.copy())
    robot.controller.reset_goal()
    sim.data.qvel[:]=0
    sim.forward()
    return sol.x.copy(),error.copy()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render",action="store_true")
    args=parser.parse_args()
    setup(args.render)
    import numpy as np
    env,_=make_env(render=args.render)
    try:
        obs=env.reset()
        robot=env.env.robots[0]
        print('JOINTS',robot.robot_model.joints,'indices',robot.joint_indexes,flush=True)
        q,err=solve_home(env)
        env.env._update_observables(force=True)
        obs=env.env._get_observations()
        start=np.array(obs['robot0_eef_pos'])
        max_qvel=0.0
        for t in range(100):
            action=np.zeros(7);action[-1]=-1 if t<30 or t>=70 else 1
            obs,_,_,_=env.step(action)
            assert np.isfinite(env.env.sim.data.qpos).all()
            assert np.isfinite(env.env.sim.data.qvel).all()
            max_qvel=max(max_qvel,float(np.max(np.abs(env.env.sim.data.qvel))))
            if t in (29,69,99):print('STEP',t,'eef',obs['robot0_eef_pos'],'gripper',obs['robot0_gripper_qpos'],flush=True)
        report={"robot":"Piper H","gripper":"AgileX default 100 mm","home_qpos":q.tolist(),"ik_error":err.tolist(),
                "holding_position_error_m":float(np.linalg.norm(obs['robot0_eef_pos']-start)),"max_qvel":max_qvel,
                "final_gripper_qpos":obs['robot0_gripper_qpos'].tolist(),"nq":env.env.sim.model.nq,"nv":env.env.sim.model.nv}
        out=ROOT/'results/piper-h-sim-check';out.mkdir(parents=True,exist_ok=True)
        if args.render:
            import imageio.v2 as imageio
            for name in ('agentview','robot0_eye_in_hand','robot0_panorama'):
                img=obs[name+'_image'][::-1]
                imageio.imwrite(out/f'{name}.png',img)
                report[name]={"shape":list(img.shape),"std":float(img.std())}
        (out/'check.json').write_text(json.dumps(report,indent=2)+'\n')
        (ROOT/'models/piper_h/home.json').write_text(json.dumps({"qpos":q.tolist()},indent=2)+'\n')
        print(json.dumps(report,indent=2))
    finally:
        env.close()


if __name__=='__main__':main()
