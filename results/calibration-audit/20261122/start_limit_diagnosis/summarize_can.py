from pathlib import Path
import csv,collections,json,math,struct
root=Path.home()/'research'
data=root/'pi-q12-data/20261122_q12_recollect_01'
diagnostic=root/'pi-q12-data/20261122_start_diagnosis'
recent=sorted(p for p in diagnostic.glob('live_baseline_*') if p.is_dir())[-1]
out={}
for key,folder in [('disabled',data/'status'),('next_disabled',data/'recheck_02/status'),('teach',data/'recheck_03/status'),('home',data/'after_reported_home_01/status'),('recent',recent)]:
    if folder.is_file():continue
    raw=collections.defaultdict(list)
    for row in csv.DictReader((folder/'raw/raw_can.csv').open()):
        if (row['is_rx'],row['is_error'],row['is_remote'])==('1','0','0'):
            raw[int(row['id'],16)].append(bytes.fromhex(row['data_hex']))
    summary=json.load((folder/'arm_summary.json').open())
    axes={}
    for axis,packet,pair in [(2,0x2a5,1),(3,0x2a6,0)]:
        joint=[.001*struct.unpack('>ii',b)[pair] for b in raw[packet]]
        motor=[math.degrees(.001*struct.unpack('>hhi',b)[2]) for b in raw[0x250+axis]]
        currents=[.001*struct.unpack('>hhi',b)[1] for b in raw[0x250+axis]]
        axes[f'J{axis}']=dict(joint_deg=[min(joint),max(joint)],motor_deg=[min(motor),max(motor)],motor_current_A=[min(currents),max(currents)],joint_packets=len(joint),motor_packets=len(motor))
    out[key]=dict(source=str(folder),axes=axes,drive_bytes={hex(k):dict(collections.Counter(str(hex(b[5])) for b in raw[k])) for k in range(0x261,0x267)},q_deg=summary['last_joint_deg'],sdk_arm_status=summary['last_snapshot']['arm']['data'],boot=summary['boot_id'],CAN_errors=summary['can_error_frames'],interface_delta=summary['interface_delta'])
out['queried_limits']=json.load((data/'current_limits.json').open())['controller_limits']
out['stop_event']=json.load((root/'pi-q12-field-source/results/piper-real-single-v1/20261121_q12_01/stop_event.json').open())
out['published_reconnect']=json.load((root/'pi-q12-field-source/results/piper-real-single-v1/20261121_q12_01/reconnect_state.json').open())['joint_deg']
out['host_stop_vs_joint_feedback']='The Nov 21 stop, later reconnect and Nov 22 disabled readings are separate timestamped windows; no physical fixture or continuous cross-machine record connects all intervening events.'
Path('can_evidence.json').write_text(json.dumps(out,indent=2,ensure_ascii=False)+'\n')
print(out['disabled']['axes'],len(out['disabled']['drive_bytes']),out['recent']['axes'])
