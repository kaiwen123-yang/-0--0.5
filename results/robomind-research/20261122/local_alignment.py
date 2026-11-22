"""Read saved H0 RGB, state and independent arm/gripper command logs; no robot I/O."""
import argparse
import bisect
import csv
import json
import math
import struct
from pathlib import Path
import cv2

def load_csv(path):
    with path.open() as file:
        return list(csv.DictReader(file))

def prior(rows, stamp):
    times = [int(r['host_monotonic_ns']) for r in rows]
    if times != sorted(times):
        raise ValueError('Out of order monotonic timestamps')
    idx = bisect.bisect_right(times, stamp) - 1
    return rows[idx] if idx >= 0 else None

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    root = args.directory
    boot = [json.loads((root/f'full_run_{component}_summary.json').read_text())['boot_id']
            for component in ('arm', 'camera')]
    if not boot[0] or boot[0] != boot[1]:
        raise ValueError('Image and arm have different boot clocks')
    images = {int(r['index']):r for r in load_csv(root/'stream_timing.csv') if r['stream']=='color'}
    joints = load_csv(root/'joints.csv')
    gripper = load_csv(root/'gripper.csv')
    high = load_csv(root/'motion_commands.csv')
    joint_calls = [r for r in high if r['command_type']=='move_j']
    gripper_calls = [r for r in high if r['command_type']=='gripper']
    by_id = {}
    for r in load_csv(root/'motion_sdk_tx.csv'):
        by_id.setdefault(int(r['id'],16),[]).append(r)
    result=[]
    for p in sorted((root/'samples').glob('color_*.png')):
        idx = int(p.stem.split('_')[-1])
        im = images[idx]
        rgb_bgr = cv2.imread(str(p),cv2.IMREAD_COLOR)
        if rgb_bgr is None or list(rgb_bgr.shape[:2])!=[int(im['height']),int(im['width'])]:
            raise ValueError(f'Image mismatch at {p}')
        stamp=int(im['host_monotonic_ns'])
        js,gs=prior(joints,stamp),prior(gripper,stamp)
        qcall,gcall=prior(joint_calls,stamp),prior(gripper_calls,stamp)
        row=dict(source_rgb=str(p),rgb_index=idx,image_receive_ns=stamp,image_header_ns=int(im['header_ns']),
                 host_receive_minus_ros_header_ms=(int(im['host_unix_ns'])-int(im['header_ns']))/1e6,
                 image_encoding=im['encoding'],state_joint_and_grip_age_ms=[(stamp-int(v['host_monotonic_ns']))/1e6 for v in (js,gs)],
                 measured_state_rad_m=[*[float(js[f'q{i}_rad']) for i in range(1,7)],float(gs['width_m'])],
                 latest_logged_setpoint_rad_m=None, sdk_wire_checked=False)
        if qcall and gcall:
            qt=int(qcall['host_monotonic_ns']); gt=int(gcall['host_monotonic_ns'])
            packets=[prior(by_id[i],qt) for i in (0x155,0x156,0x157)]
            gr=prior(by_id[0x159],gt)
            times=[int(v['host_monotonic_ns']) for v in packets]
            if times!=sorted(times) or qt-times[0]>5_000_000 or gt-int(gr['host_monotonic_ns'])>5_000_000:
                raise ValueError('No matching contiguous/recent SDK calls for the selected target')
            raw_angles=[math.radians(v*.001) for p0 in packets for v in struct.unpack('>ii',bytes.fromhex(p0['data_hex']))]
            wire_grip=struct.unpack('>i',bytes.fromhex(gr['data_hex'])[:4])[0]*1e-6
            logged=[*json.loads(qcall['values']),float(gcall['values'])]
            if max(abs(a-b) for a,b in zip(logged[:6],raw_angles))>math.radians(.0011) or abs(logged[6]-wire_grip)>1.1e-6:
                raise ValueError('High-level and wire command differ')
            row.update(latest_logged_setpoint_rad_m=logged,sdk_wire_checked=True,
                       rate_note='Latest separately issued arm and gripper setpoints at receipt, not a 20 Hz demonstration label.',
                       command_ages_at_image_reception_ms=[(stamp-qt)/1e6,(stamp-gt)/1e6],source_call_times_ns=[qt,gt])
        result.append(row)
    report=dict(source=str(root),boot_id=boot[0],task='H0 bench motion and gripper opening/closing',training_eligible=False,
                evidence='Logged SDK buffers and matching application calls, no per-frame bus delivery acknowledgement in this 11/16 format.',
                rgb_count=len(result),rows_with_complete_seven_targets=sum(r['sdk_wire_checked'] for r in result),rows=result)
    args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print('Local observed rows',len(result),'with both logged setpoints',report['rows_with_complete_seven_targets'],
          'image receive minus header ms',[round(x['host_receive_minus_ros_header_ms'],1) for x in result])
if __name__=='__main__':
    main()
