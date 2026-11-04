"""Numerical record of the three real revised suffixes at the H training starts."""
import json
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from analyze_pi0_h_numeric_windows import ROOT, OUT, summary, read, save


def main():
    source = ROOT/'outputs/pi0-held-rotation-20261104/dataset'
    original = ROOT/'outputs/pi0-held-recovery-20261103/dataset'
    stats = read(OUT/'B_normalization.json')['norm_stats']
    mean = np.asarray(stats['actions']['mean']); std = np.asarray(stats['actions']['std'])
    sm = np.asarray(stats['state']['mean']); ss = np.asarray(stats['state']['std'])
    sampler = read(ROOT/'results/piper-color-v1/pi0-h500-recovery-20261103/H/sampler.json')
    windows = []
    for entry in read(source/'index.json'):
        name=entry['directory']; stem=source/name
        state=np.load(stem/'state.npy',mmap_mode='r'); action=np.load(stem/'action.npy',mmap_mode='r')
        with np.load(stem.with_suffix('.npz'),allow_pickle=False) as z:
            targets=z['teacher_rotation_target']; errors=z['diagnostic_orientation_error_deg']; tcps=z['diagnostic_tcp']
            timestamps=z['timestamp']; frame0=entry['intervention_frame']
            for repl in [r for r in sampler['replacements'] if r['suffix']==name]:
                f=repl['relative_frame']; frames=np.arange(f,f+10)
                s=np.asarray(state[f],dtype=np.float32); a=np.asarray(action[frames],dtype=np.float32)
                d=a.copy();d[:,:6]-=s[:6]
                norm=(d-mean)/(std+1e-6)
                old_s=np.load(original/name/'state.npy',mmap_mode='r')[f]
                old_a=np.load(original/name/'action.npy',mmap_mode='r')[frames].copy(); old_a[:,:6]-=old_s[:6]
                old_n=(old_a-mean)/(std+1e-6)
                q=frame0+f
                row=dict(directory=name,layout=entry['layout_seed'],target=entry['target'],
                    relative_frame=f,full_frames=(frame0+frames).tolist(),replacement=repl,
                    state_measured_start=s.tolist(),state_normalized=((s-sm)/(ss+1e-6)).tolist(),
                    absolute_commands=a.tolist(),delta_from_start_with_absolute_gripper=d.tolist(),
                    action_normalized=norm.tolist(),normalized_action_summary=summary(norm),
                    original_normalized_action_summary=summary(old_n),
                    measured_start_max_difference_from_H=float(np.max(abs(s-old_s))),
                    npz_state_max_difference=float(np.max(abs(state[frames]-z['state'][frame0+frames]))),
                    npz_action_max_difference_after_float32=float(np.max(abs(a-z['executed_command'][frame0+frames].astype(np.float32)))),
                    timestamp=timestamps[frame0+frames].tolist(),stage=z['stage'][frame0+frames].tolist(),
                    reset_orientation_error_deg=errors[frame0+frames].tolist(),
                    teacher_rotation_target=targets[frame0+frames].tolist(),
                    target_rotation_offset_from_takeover_deg=Rotation.from_matrix(targets[frame0+frames] @ z['diagnostic_tcp_rotation'][frame0].T).magnitude().__mul__(180/np.pi).tolist())
                windows.append(row)
                if f==0:
                    print(json.dumps(dict(layout=entry['layout_seed'],state_j4=float(s[3]),
                        zstate_j4=float((s[3]-sm[3])/(ss[3]+1e-6)),
                        command_j4=a[:,3].tolist(),delta_j4=d[:,3].tolist(),z_action_j4=norm[:,3].tolist(),
                        old_max=float(np.max(abs(old_n))),new_max=float(np.max(abs(norm))),
                        old_j4_rms=summary(old_n)['per_dimension_rms'][3],new_j4_rms=summary(norm)['per_dimension_rms'][3],
                        target_rot_change_deg=row['target_rotation_offset_from_takeover_deg'],
                        start_state_diff=row['measured_start_max_difference_from_H'])),flush=True)
    save(OUT/'revised_training_windows.json',dict(only_change='teacher rotation during original 30-frame lift',
        sampled_recovery_windows_replaced=len(windows),window_order_reused='H exact sampler',windows=windows))

if __name__=='__main__':
    main()
