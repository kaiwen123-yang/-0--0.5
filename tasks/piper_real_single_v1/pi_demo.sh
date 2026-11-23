#!/usr/bin/env bash
set -euo pipefail
here="$(cd -- "$(dirname -- "$0")" && pwd)"
case "${1:-}" in
    camera)
        shift
        h0=/home/kaiwen/research/dog-and-arm/scripts
        publishers=$(bash "$h0/h0_ros_env.sh" ros2 topic info /wrist_camera/color/image_raw 2>/dev/null || true)
        if [[ "$publishers" =~ Publisher\ count:\ ([1-9][0-9]*) ]]; then
            echo "腕图已有 ${BASH_REMATCH[1]} 个发布者；复用单个现有驱动。"
            [[ "${BASH_REMATCH[1]}" == 1 ]]
            exit
        fi
        exec bash "$h0/h0_camera.sh" serial_number:=CC16762023M "$@" ;;
    scene)
        shift
        mkdir -- "$1"
        exec bash /home/kaiwen/research/dog-and-arm/scripts/h0_ros_env.sh /usr/bin/python3 -B "$here/demo_rgb.py" "$1" --one ;;
    view)
        exec bash /home/kaiwen/research/dog-and-arm/scripts/h0_ros_env.sh ros2 run rqt_image_view rqt_image_view /wrist_camera/color/image_raw ;;
    review|export)
        exec /usr/bin/python3 -B "$here/demo_export.py" "$@" ;;
    play)
        shift
        exec ffplay -loglevel warning -autoexit -framerate 30 -i "$1/rgb/%07d.png" ;;
    *)
        exec env -u LD_LIBRARY_PATH /home/kaiwen/research/OSCBF-research/envs/piper-sdk/bin/python -EBs "$here/demo_field.py" "$@" ;;
esac
