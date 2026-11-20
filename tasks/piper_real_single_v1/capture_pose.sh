#!/usr/bin/env bash
# One manually positioned, stationary board pose; uses the already running H0 driver.
set -euo pipefail
if [[ $# != 3 || ! "$2" =~ ^(train|heldout)$ || ! "$3" =~ ^[[:alnum:]_-]+$ ]]; then
    echo 'Usage: bash capture_pose.sh CAL_DIRECTORY train|heldout UNIQUE_POSE_GROUP' >&2
    exit 2
fi
tools_dir=$(cd "$(dirname "$0")" && pwd)
cal=$(realpath "$1")
pose="$cal/poses/$3"
h0=/home/kaiwen/research/dog-and-arm
sdk=/home/kaiwen/research/OSCBF-research/envs/piper-sdk/bin/python
# This entry is for the photographed wrist DC1. Use its running driver's serial,
# not the ROS namespace, as the identity check.
bash "$h0/scripts/h0_ros_env.sh" ros2 service call /wrist_camera/get_device_info \
    astra_camera_msgs/srv/GetDeviceInfo '{}' | grep -F "serial_number='CC16762023M'"
mkdir -p "$cal/poses"
mkdir "$pose"
env -u LD_LIBRARY_PATH "$sdk" -I -B "$h0/scripts/h0_record_arm.py" "$pose" \
    --raw-directory "$pose/raw" >"$pose/arm.log" 2>&1 &
arm_pid=$!
stop_arm() {
    kill -TERM "$arm_pid" 2>/dev/null || true
    wait "$arm_pid"
}
trap stop_arm EXIT
while [[ ! -s "$pose/arm_live.json" ]]; do
    kill -0 "$arm_pid"
    sleep 0.2
done
bash "$h0/scripts/h0_ros_env.sh" env OPENCV_FOR_THREADS_NUM=1 /usr/bin/python3 -B \
    "$h0/scripts/h0_record_camera.py" "$pose" --seconds 3 --sample-period 0 --bag-seconds 0 --camera-name wrist_camera >"$pose/camera.log" 2>&1
trap - EXIT
stop_arm
/usr/bin/python3 "$tools_dir/associate_h0.py" --camera-dir "$pose" --arm-dir "$pose" \
    --camera-id CC16762023M --mount wrist --max-joint-age-ms 100 --max-gripper-age-ms 100 \
    --output "$pose/association" >"$pose/association.log"
env -u LD_LIBRARY_PATH "$sdk" -I -B "$tools_dir/flange_observation.py" --session "$pose" \
    --pose-group "$3" --split "$2" --output "$pose/capture.json"
echo "$pose/capture.json"
