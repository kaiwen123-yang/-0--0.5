"""Record raw RGB and receive-only joint/gripper feedback on dev2 into a new episode."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time

ROOT = Path.home() / 'research'
TOOLS = ROOT / 'dog-and-arm/scripts'
SDK = ROOT / 'OSCBF-research/envs/piper-sdk/bin/python'
ROS = ['bash', str(TOOLS/'h0_ros_env.sh')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out', type=Path)
    parser.add_argument('--seconds', type=float, required=True)
    args = parser.parse_args()
    if not 0 < args.seconds < float('inf'):
        parser.error('Supply a positive finite recording duration')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    camera = arm = None
    with (out/'driver.log').open('w') as log, (out/'arm.log').open('w') as arm_log:
        try:
            if subprocess.run(['pgrep', '-x', 'astra_camera_no'], stdout=subprocess.DEVNULL).returncode:
                camera = subprocess.Popen(['bash', str(TOOLS/'h0_camera.sh'), 'enable_depth:=false'],
                                          stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            info = subprocess.run([*ROS,'ros2','service','call','/wrist_camera/get_device_info',
                                   'astra_camera_msgs/srv/GetDeviceInfo','{}'],
                                  capture_output=True, text=True, timeout=20, check=True)
            if "serial_number='CC16762023M'" not in info.stdout or 'success=True' not in info.stdout:
                raise RuntimeError('Configured DC1 identity did not match')
            (out/'camera_identity.txt').write_text(info.stdout)
            arm = subprocess.Popen([str(SDK),'-I',str(TOOLS/'h0_record_arm.py'),str(out),
                                    '--raw-directory',str(out/'raw')], stdout=arm_log, stderr=subprocess.STDOUT)
            start = time.monotonic()
            while not (out/'arm_live.json').exists():
                if arm.poll() is not None or time.monotonic()-start > 8:
                    raise RuntimeError('Passive CAN receiver did not start')
                time.sleep(.05)
            with (out/'camera.log').open('w') as color_log:
                subprocess.run([*ROS,'/usr/bin/python3',str(TOOLS/'h0_record_camera.py'),str(out),
                                '--seconds',str(args.seconds),'--sample-period','0','--bag-seconds','0',
                                '--camera-name','wrist_camera'], stdout=color_log, stderr=subprocess.STDOUT,check=True)
            time.sleep(.25)
        finally:
            try:
                if arm is not None:
                    if arm.poll() is None:
                        arm.terminate()
                    if arm.wait(timeout=10) != 0:
                        raise RuntimeError('CAN receiver exited with an error; inspect arm.log')
            finally:
                if camera is not None:
                    try:
                        os.killpg(camera.pid, signal.SIGINT)
                        camera.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(camera.pid, signal.SIGTERM)
                        camera.wait(timeout=8)
                    except ProcessLookupError:
                        pass
    a = json.loads((out/'arm_summary.json').read_text())
    c = json.loads((out/'camera_summary.json').read_text())
    if a['error'] or a['can_error_frames'] or a['boot_id'] != c['boot_id']:
        raise RuntimeError('Invalid CAN recording or clocks')
    if c['worker_error'] or not c['frames'].get('color') or not a['joint_rows'] or not a['gripper_rows']:
        raise RuntimeError('Missing camera/arm rows or camera worker failure')
    print(out)
    print('CAN interface counters',a['interface_delta'])
    print('Role: observation only. No sender action log attached.')


if __name__ == '__main__':
    main()
