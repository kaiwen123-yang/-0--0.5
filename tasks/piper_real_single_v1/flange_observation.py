"""Recover a stationary RGB frame and its measured-joint flange FK from one H0 recording.

Uses offline math from the installed Piper SDK and the same session's passive CAN
log. With no pose group the output is a diagnostic, never a calibration capture.
"""
import argparse
import csv
import json
import math
from pathlib import Path
import struct

from pyAgxArm.utiles.mdh_kinematics import fk_from_mdh, get_mdh
from pyAgxArm.utiles.tf import pose6_to_T16


def matrix(pose):
    flat = pose6_to_T16(pose)
    return [flat[i:i + 4] for i in range(0, 16, 4)]


def controller_feedback(path, before, max_age_ms):
    # Discard interrupted/reordered cycles. A complete triplet must fit within
    # one 5 ms nominal Piper feedback period in kernel receive time.
    pending, latest = [], None
    ids = ('0x2a2', '0x2a3', '0x2a4')
    with path.open() as source:
        for row in csv.DictReader(source):
            timestamp = int(row['host_monotonic_ns'])
            if timestamp > before:
                break
            if row['is_rx'] != '1' or row['is_error'] != '0' or row['is_remote'] != '0':
                continue
            ident = row['id'].lower()
            if ident not in ids:
                continue
            if ident == ids[0]:
                pending = []
            if ident != ids[len(pending)]:
                pending = []
                continue
            pending.append(row)
            if len(pending) == 3:
                kernel_s = [float(r['can_timestamp_s']) for r in pending]
                if 0 <= kernel_s[-1] - kernel_s[0] < .005 and kernel_s == sorted(kernel_s):
                    latest = pending
                pending = []
    if latest is None:
        return None
    age = (before - int(latest[-1]['host_monotonic_ns'])) / 1e6
    if age > max_age_ms:
        return None
    wire = [v for r in latest for v in struct.unpack('>ii', bytes.fromhex(r['data_hex']))]
    pose = [v * 1e-6 for v in wire[:3]] + [math.radians(v * .001) for v in wire[3:]]
    return dict(pose_m_rad=pose, T_base_flange=matrix(pose), age_ms=age,
                host_monotonic_ns=[int(r['host_monotonic_ns']) for r in latest],
                can_timestamp_s=[r['can_timestamp_s'] for r in latest], ids=list(ids))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--session', required=True, type=Path)
    p.add_argument('--stream-index', type=int, help='Default: middle received RGB of this stationary recording')
    p.add_argument('--pose-group')
    p.add_argument('--split', choices=('train', 'heldout'))
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if bool(args.pose_group) != bool(args.split):
        p.error('--pose-group and --split belong together')
    session = args.session.resolve()
    with (session / 'association/observations.jsonl').open() as f:
        rows = [json.loads(line) for line in f]
    if not rows:
        raise ValueError('No recorded RGB')
    row = rows[len(rows) // 2] if args.stream_index is None else next(
        r for r in rows if r['camera_rgb']['stream_index'] == args.stream_index)
    rgb, joints = row['camera_rgb'], row['joint_feedback']
    if not rgb['available'] or not Path(rgb['path']).is_file() or joints['status'] != 'associated':
        raise ValueError('Missing source image or fresh measured joints')
    arm = json.loads((session / 'arm_summary.json').read_text())
    cam = json.loads((session / 'camera_summary.json').read_text())
    if row['boot_id'] != arm['boot_id'] or row['boot_id'] != cam['boot_id']:
        raise ValueError('Session clock mismatch')
    before = rgb['host_monotonic_ns']
    limits = json.loads((session / 'association/association_report.json').read_text())['association_limits_ms']
    controller = controller_feedback(session / 'raw/raw_can.csv', before, limits['joint'])
    q = joints['values']
    fk = matrix(fk_from_mdh(get_mdh('piper_h'), q))
    difference = None
    if controller:
        other = controller['T_base_flange']
        trace = sum(fk[i][j] * other[i][j] for i in range(3) for j in range(3))
        difference = dict(translation_mm=1000 * math.dist([r[3] for r in fk[:3]], [r[3] for r in other[:3]]),
                          rotation_deg=math.degrees(math.acos(min(1, max(-1, (trace - 1) / 2)))))
    # Report actual nearby joint ranges for review of stationarity, without
    # converting one software agreement or one short hold into physical acceptance.
    with (session / 'joints.csv').open() as f:
        window = [[float(r[f'q{i}_rad']) for i in range(1, 7)] for r in csv.DictReader(f)
                  if abs(int(r['host_monotonic_ns']) - before) <= 250_000_000]
    result = dict(kind='calibration_capture' if args.pose_group else 'preboard_pose_diagnostic',
                  session=str(session), camera_id=row['camera_id'], camera_mount=row['mount'],
                  camera_role={'wrist':'left_wrist_0_rgb','external_fixed':'base_0_rgb'}[row['mount']],
                  camera_frame=rgb['frame_id'], image_path=rgb['path'], stream_index=rgb['stream_index'],
                  image_size=[rgb['width'], rgb['height']], image_header_ns=rgb['header_ns'],
                  image_receive_monotonic_ns=before, boot_id=row['boot_id'],
                  base_frame='base_link', gripper_frame='flange_link', pose_source='pyAgxArm 1.0.0 piper_h MDH FK',
                  T_base_gripper=fk, pose_receive_monotonic_ns=joints['host_monotonic_ns'],
                  joint_feedback=joints, controller_flange_feedback=controller,
                  fk_controller_difference=difference, joint_rows_within_250ms=len(window),
                  joint_range_rad_within_250ms=[max(axis)-min(axis) for axis in zip(*window)],
                  transform_convention='flange coordinates to base, metres',
                  pose_verified=False, static_capture_verified=False, board_orientation_verified=False)
    if args.pose_group:
        result.update(sample_id=args.pose_group, pose_group=args.pose_group, split=args.split, corner_order='detected')
    with args.output.open('x') as out:
        json.dump(result, out, indent=2, allow_nan=False)
        out.write('\n')


if __name__ == '__main__':
    main()
