"""Inspect downloaded public episode samples; no model training or robot I/O."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/public-datasets-20261024'


def main():
    reports = []
    for folder in sorted(OUT.glob('*__*')):
        samples = sorted(folder.glob('data/**/*.parquet'))
        if not samples:
            continue
        api = json.loads((folder / 'api.json').read_text())
        meta = json.loads((folder / 'meta/info.json').read_text())
        table = pq.read_table(samples[0])
        values = table.to_pydict()
        state = np.asarray(values['observation.state'])
        action = np.asarray(values['action'])
        stamp = np.asarray(values['timestamp']).ravel()
        dt = np.diff(stamp)
        ids = list(zip(values['episode_index'], values['frame_index']))
        videos = []
        for path in sorted(folder.glob('videos/**/*.mp4')):
            stream = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height,nb_frames,avg_frame_rate,codec_name', '-of', 'json', str(path)], text=True))['streams'][0]
            subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(path), '-f', 'null', '-'], check=True, timeout=60)
            videos.append({'file': str(path.relative_to(OUT)), 'stream': stream,
                           'matches_sample_rows': int(stream['nb_frames']) == len(table), 'full_decode': True})
        next_match = bool(np.array_equal(action[:-1], state[1:]))
        report = {'dataset_id': api['id'], 'revision': api['sha'], 'gated': api.get('gated'),
            'dataset_card_license': api.get('cardData', {}).get('license'),
            'metadata': {k: meta.get(k) for k in ('codebase_version', 'robot_type', 'total_episodes', 'total_frames', 'total_tasks', 'fps')},
            'sample_episode': 0, 'sample_rows': len(table), 'sample_columns': table.column_names,
            'sample_sha256': hashlib.sha256(samples[0].read_bytes()).hexdigest(),
            'sample_null_cells': sum(table[c].null_count for c in table.column_names),
            'duplicate_episode_frame_keys': len(ids) - len(set(ids)),
            'state_shape': list(state.shape), 'action_shape': list(action.shape),
            'numeric_finite': bool(np.isfinite(state).all() and np.isfinite(action).all()),
            'monotonic_timestamps': bool(np.all(dt > 0)),
            'timestamp_delta_s': {'min': float(dt.min()), 'median': float(np.median(dt)), 'max': float(dt.max())},
            'same_frame_action_state_mae': float(np.mean(abs(action-state))),
            'action_equals_next_state_except_terminal': next_match,
            'next_state_label_checked_transitions': len(state)-1,
            'per_dimension_state_range': np.ptp(state, axis=0).tolist(),
            'gripper_state_range': {str(i): [float(state[:,i].min()), float(state[:,i].max())] for i in (6,13)},
            'camera_keys': [k for k,v in meta['features'].items() if v['dtype'] == 'video'],
            'videos': videos,
            'interpretation': 'The checked action labels are exactly the next recorded state, not evidence of logged commanded EEF deltas. Preserve temporal alignment and verify collection code before converting action semantics.' if next_match else 'Action source needs review.',
            'scope_limit': 'Only episode 0 checked per dataset; not a full-corpus quality or hardware compatibility certification.'}
        reports.append(report)
    result = {'checked_at': datetime.now(timezone.utc).isoformat(), 'intended_use': 'Piper/Piper H fine-tuning data selection',
              'grain': 'one recorded transition per (episode_index, frame_index)', 'reports': reports}
    (OUT / 'sample-quality.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'samples': len(reports), 'rows': sum(r['sample_rows'] for r in reports),
                      'next_state_label_datasets': [r['dataset_id'] for r in reports if r['action_equals_next_state_except_terminal']],
                      'videos_checked': sum(len(r['videos']) for r in reports)}))


if __name__ == '__main__':
    main()
