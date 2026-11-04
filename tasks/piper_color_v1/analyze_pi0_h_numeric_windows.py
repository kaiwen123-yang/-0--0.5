"""Read only the four specified H batches and their original E counterparts.

No model, simulation, dataset conversion, or broad data traversal is invoked.
The small numerical records are extracted from the existing NPY/NPZ files.
"""
import csv
import json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'results/piper-color-v1/pi0-h-numeric-review-20261104'
H = ROOT / 'results/piper-color-v1/pi0-h500-recovery-20261103/H'
DATA = ROOT / 'outputs/pi0-120-demo-v2-20261101/dataset'
REC = ROOT / 'outputs/pi0-held-recovery-20261103/dataset'
UPDATES = (19, 33, 48, 416)


def read(p):
    return json.loads(p.read_text())


def save(p, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def summary(x):
    x = np.asarray(x, dtype=np.float64)
    return dict(per_dimension_max_abs=np.max(abs(x), axis=0).tolist(),
                per_dimension_rms=np.sqrt(np.mean(x*x, axis=0)).tolist(),
                max_abs=float(np.max(abs(x))), rms=float(np.sqrt(np.mean(x*x))))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    norm_ref = read(H/'normalization.json')
    norm_source = Path(norm_ref['source'])
    norm = read(norm_source)['norm_stats']
    stats = {k: {n: np.asarray(v[n]) for n in ('mean', 'std')} for k, v in norm.items()}
    save(OUT/'B_normalization.json', dict(source=str(norm_source), norm_stats=norm,
         method='(x - mean) / (std + 1e-6); first six actions subtract window-start measured state; gripper remains absolute'))
    tables = {}
    for group, campaign in [('H','pi0-h500-recovery-20261103'),('E','pi0-ef-local-20261102'),('G','pi0-g-fixed-vision-20261103')]:
        p = ROOT/'results/piper-color-v1'/campaign/group/'lora_metrics.jsonl'
        tables[group] = {r['local_update']:r for r in map(json.loads, p.read_text().splitlines()) if r['local_update'] in UPDATES}
    save(OUT/'observed_training_batches.json', {g:list(rows.values()) for g,rows in tables.items()})
    original = [r for r in read(DATA/'index.json') if r['split']=='train']
    recovery = [r for r in read(REC/'index.json') if r['split']=='train']
    ends = np.cumsum([r['frames'] for r in original])
    rend = np.cumsum([r['frames'] for r in recovery])
    count = int(ends[-1])
    selected = sorted({i for g in ('H','E') for r in tables[g].values() for i in r['sample_indices']})
    windows, csv_rows = [], []
    for index in selected:
        is_rec = index >= count
        local_index = index-count if is_rec else index
        entries, cumulative, root = (recovery, rend, REC) if is_rec else (original, ends, DATA)
        ep = int(np.searchsorted(cumulative, local_index, side='right'))
        frame = int(local_index - (cumulative[ep-1] if ep else 0))
        entry = entries[ep]
        directory = root / entry['directory']
        frames = np.minimum(np.arange(frame,frame+10),entry['frames']-1)
        states = np.load(directory/'state.npy', mmap_mode='r')
        actions = np.load(directory/'action.npy', mmap_mode='r')
        state = np.asarray(states[frame],dtype=np.float32).copy()
        command = np.asarray(actions[frames],dtype=np.float32).copy()
        delta = command.copy()
        delta[:,:6] -= state[:6]
        ns = (state-stats['state']['mean'])/(stats['state']['std']+1e-6)
        na = (delta-stats['actions']['mean'])/(stats['actions']['std']+1e-6)
        roles = [dict(group=g, update=u, batch_slot=r['sample_indices'].index(index))
                 for g,rows in tables.items() for u,r in rows.items() if index in r['sample_indices']]
        row = dict(index=index, component='recovery' if is_rec else 'original',
            directory=str(directory), episode_index=ep, relative_frame=frame,
            window_frames=frames.tolist(), entry=entry, batch_memberships=roles,
            state_measured_start=state.tolist(), state_normalized=ns.tolist(),
            measured_states_in_window=np.asarray(states[frames]).tolist(),
            absolute_executed_commands_float32=command.tolist(),
            delta_from_window_start_with_absolute_gripper=delta.tolist(),
            actions_normalized=na.tolist(), delta_summary=summary(delta),
            normalized_action_summary=summary(na),
            normalized_action_squared_energy_in_padded32=float(np.sum(na*na)/(10*32)),
            normalized_state_max_abs=float(np.max(abs(ns))),
            source_npz=str(directory.with_suffix('.npz')))
        npz = directory.with_suffix('.npz')
        if npz.exists():
            offset = entry['intervention_frame'] if is_rec else 0
            full_frames = frames + offset
            command_key = 'executed_command' if is_rec else 'action'
            with np.load(npz,allow_pickle=False) as z:
                zs,za = z['state'][full_frames], z[command_key][full_frames]
                row['npz_correspondence'] = dict(full_frames_zero_based=full_frames.tolist(),
                    measured_state_max_abs_difference=float(np.max(abs(np.asarray(states[frames])-zs))),
                    command_max_abs_difference_after_float32_export=float(np.max(abs(command-za.astype(np.float32)))),
                    command_max_abs_difference_before_float32_export=float(np.max(abs(command.astype(np.float64)-za))),
                    npz_measured_states=zs.tolist(), npz_absolute_commands=za.tolist())
                if is_rec:
                    neighbor_frames = np.arange(max(0,offset+frame-2), min(offset+entry['frames'], offset+frame+11))
                    row['npz_correspondence']['timestamps_seconds'] = z['timestamp'][full_frames].tolist()
                    row['npz_correspondence']['stages'] = z['stage'][full_frames].tolist()
                    row['npz_correspondence']['teacher_mask'] = z['teacher_mask'][full_frames].tolist()
                    row['neighbor_frames'] = neighbor_frames.tolist()
                    row['neighbor_records'] = {k:z[k][neighbor_frames].tolist() for k in (
                        'state','executed_command','timestamp','stage','diagnostic_command_before',
                        'diagnostic_tcp','diagnostic_target_position','diagnostic_tcp_rotation',
                        'diagnostic_normal_force','diagnostic_orientation_error_deg')}
                    row['fourth_joint'] = dict(measured_start_rad=float(state[3]),
                        normalized_state=float(ns[3]), absolute_commands_rad=za[:,3].tolist(),
                        delta_rad=delta[:,3].tolist(), normalized_delta=na[:,3].tolist(),
                        measured_joint_rad=zs[:,3].tolist(),
                        command_before_start_rad=float(z['diagnostic_command_before'][offset+frame,3]),
                        orientation_error_deg=z['diagnostic_orientation_error_deg'][full_frames].tolist())
            row['collection_record'] = {k:v for k,v in read(directory.with_suffix('.json')).items()
                if k in ('prefix_qpos_max_difference','prefix_qvel_max_difference','prefix_command_max_difference',
                'takeover_clock_seconds','takeover_steps','teacher_frames','stage_frames','success','steps','teacher_plan')}
        else:
            row['npz_correspondence'] = dict(available=False,
                reason='Original v2 NPZ not retained at its indexed sibling path; actual restored NPY training inputs read. No download or recovery initiated.')
        windows.append(row)
        for k in range(10):
            for j in range(7):
                csv_rows.append(dict(index=index,component=row['component'],directory=entry['directory'],
                    start_frame=frame,chunk_step=k,frame=int(frames[k]),dimension=j+1,
                    state_measured_start=float(state[j]),state_normalized=float(ns[j]),
                    absolute_command=float(command[k,j]),delta_or_absolute_gripper=float(delta[k,j]),
                    action_normalized=float(na[k,j])))
        display = dict(index=index,directory=entry['directory'],frame=frame,
            state_j4=float(state[3]),z_state_j4=float(ns[3]),
            cmd_j4=[float(command[0,3]),float(command[-1,3])],
            delta_j4=[float(delta[0,3]),float(delta[-1,3])],
            z_action_max=float(np.max(abs(na))),z_action_dim_rms=row['normalized_action_summary']['per_dimension_rms'],
            npz_available=npz.exists())
        if is_rec: display['j4']=row['fourth_joint']
        print(json.dumps(display),flush=True)
    save(OUT/'numeric_windows.json',dict(selected_updates=list(UPDATES),selected_indices=selected,
        action_semantics='10 commands minus ONE measured start state in joint dimensions 1..6; width stays absolute',
        extraction='Read selected NPY slices and their retained NPZ values only; no model/simulator',windows=windows))
    with (OUT/'numeric_values.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(csv_rows[0])); writer.writeheader(); writer.writerows(csv_rows)
    save(OUT/'scope.json',dict(original_baseline='3dd547a169c7a821fabd278af3b86a1f3d099b95',
        main_plan_commit='71f927b1baa26cc5994ba9e9ee20231edb3dbfc6', updates=list(UPDATES),
        windows=len(windows), original_windows=sum(w['component']=='original' for w in windows),
        recovery_windows=sum(w['component']=='recovery' for w in windows),
        rows_csv=len(csv_rows), model_forwards=0, simulation_episodes=0, training_updates=0))

if __name__ == '__main__':
    main()
