# 单相机：复用 H0 记录、现场显示与接收时间关联

本模块只处理真实观测。`associate_h0.py` 是已录数据分析；`live_view.py` 订阅一个已经存在的 ROS RGB 话题并读取 H0 已落盘反馈。两者均不创建相机驱动管线、不打开 CAN、不导入机械臂 SDK、不使能、不发送目标，也不运行策略。

代码准备不代表现场运行完成。**本次硬件执行：NOT_RUN；模型推理：NOT_RUN。** 下面命令供现场执行端使用，不能把命令存在写成实测成功。

## 1. 固定源格式与相机身份

已按 [dog-and-arm@284c1f3](https://github.com/kaiwen123-yang/dog-and-arm/tree/284c1f3f1bb9d5096003433f6153a9c5e95d6189) 的实际源码编写：

- `scripts/h0_record_camera.py` 写入 `stream_timing.csv`、`sample_index.jsonl`、原始 RGB PNG 和深度 NPY、CameraInfo、`camera_live.json`/`camera_summary.json`。
- `scripts/h0_record_arm.py` 写入真实接收组的 `joints.csv`、0x2A8 反馈的 `gripper.csv`、`arm_live.json`/`arm_summary.json`。约 10 Hz 的缓存快照不作为本模块关节反馈来源。
- 六关节是 `q1_rad` 至 `q6_rad`，夹爪是实测总开口 `width_m`。没有夹爪反馈时明确缺失，不能拿目标值补齐。
- 单相机规范字段名为 `camera_rgb`。`--mount external_fixed` 或 `--mount wrist` 必须显式给出；没有历史默认。当前外部固定方案使用前者，但必须与现场实际安装一致。
- H0 的历史 ROS 命名空间是 `/wrist_camera`。沿用该话题名不证明相机仍在腕部；安装改变应另记真实安装与待标定状态，不能由话题名推断外参。

## 2. 复用现有记录器

先确认现有相机节点与 H0 接收器是否已经运行；存在活动会话时使用它，不启动重复驱动或重复接收器。本模块不会自动启动它们。

下面路径变量中的“实际”内容须换成现场路径。`PI_DATA` 是原始数据目录，不能指向 Git 已跟踪的成果目录；每次用新的会话名。原始数据留原机，不另建归档或上传队列。

```bash
H0_ROOT=/home/kaiwen/research/dog-and-arm
PI_ROOT=/实际的π仓库绝对路径
PI_DATA=/实际的原始数据绝对目录
PI_SESSION="$PI_DATA/precalib_20261120_session01"
PI_RAW="$PI_DATA/precalib_20261120_session01_raw"
```

若尚无记录器，在各自终端复用原 H0 入口。它们只订阅或接收，图像与机械臂采集仍分进程。下例的 `wrist_camera` 是已存在的话题命名空间，现场有改名时使用实际命名空间。

```bash
bash "$H0_ROOT/scripts/h0_ros_env.sh" /usr/bin/python3 \
  "$H0_ROOT/scripts/h0_record_camera.py" "$PI_SESSION" \
  --raw-directory "$PI_RAW" --seconds 180 --bag-seconds 0 --sample-period 0 \
  --camera-name wrist_camera
```

```bash
env -u LD_LIBRARY_PATH \
  /home/kaiwen/research/OSCBF-research/envs/piper-sdk/bin/python -I \
  "$H0_ROOT/scripts/h0_record_arm.py" "$PI_SESSION" \
  --raw-directory "$PI_RAW" --seconds 180
```

相机/机械臂硬件、接口名、固件配置与 USB-CAN 身份沿用 H0 已确认现场配置；这些命令不会配置 CAN 或使能电机。若接口没有就绪，应由执行端按当前事实处理，不能把旧会话姿态复制为运动目标。

本轮命令用 `--sample-period 0` 逐帧保存原始RGB PNG和深度NPY，`--bag-seconds 0` 不再重复保存全量bag；时间表和原CameraInfo仍保留。先查看实际数据目录剩余空间，连续原始帧会产生数GB数据。180秒是这次明确的记录窗口，不是后台强制kill。新写盘负载下的实际帧数、队列丢帧与写入错误据本轮日志报告，不能照搬旧H0无丢帧结论。若已在运行的记录符合需求，直接复用，不因示例参数重复采集。已有完整bag也可保留其原始帧，现场按实际接口导出，不把只有10秒的bag说成完整180秒。

## 3. 现场只读显示

等待已启动 H0 接收器产生有效 `arm_live.json` 后，从与相机相同的 ROS/DDS 环境启动。相机 ID 使用本轮真实身份；H0 历史 DC1 序列号是 `CC16762023M`，只有现场仍为这台设备时才使用该值。

```bash
bash "$H0_ROOT/scripts/h0_ros_env.sh" /usr/bin/python3 \
  "$PI_ROOT/tasks/piper_real_single_v1/live_view.py" \
  --topic /wrist_camera/color/image_raw \
  --camera-id 实际相机序列号 --mount external_fixed \
  --arm-dir "$PI_SESSION"
```

只看相机而未连接机械臂反馈时省略 `--arm-dir`；界面明确显示测量状态缺失。`--seconds 180` 可指定本次显示会话长度；默认由 `q`、Esc 或 Ctrl+C 结束，不添加后台强制时限。

画面同时显示当前收到的 RGB、RGB 回调年龄、原 ROS header、已落盘的六关节与夹爪反馈、各反馈的原接收时间年龄。**相机画面与已落盘反馈分开显示，不声称它们已经同步构成实时模型输入。** 缺失状态不填零；当前不显示伪造的预测动作。

H0 臂记录器源码的显式 CSV flush 间隔是 **2 秒**，缓冲区满时可能提前写入。因此：

- 反馈“recorded-event age”从 CSV 原 `host_monotonic_ns` 算到显示时刻。
- “age when read from file”还包含写盘可见性与 viewer 调度，首次读取旧行时也包含其历史年龄。
- 两者都不是传感器内部延迟或 CAN 网络延迟；不能通过文件修改时间将旧反馈伪装成新反馈。
- Viewer 不适合作为后续模型实时控制的状态通道。未来需要实时通道时，应在已验证接收器的接收事件上显式发布，而非让 viewer 新开 CAN 或刷新旧时间戳；此模块没有实施该改动。

Viewer 要求臂元信息 boot_id 等于运行主机当前 Linux boot_id；跨重启旧文件不能被标作本机 live。文件被替换、截断或接收时间倒退时会直接指出问题，不自动跳转到另一个会话。

## 4. 已录数据离线关联

正常结束本次记录器后，使用原始会话数据执行：

```bash
/usr/bin/python3 "$PI_ROOT/tasks/piper_real_single_v1/associate_h0.py" \
  --camera-dir "$PI_SESSION" --arm-dir "$PI_SESSION" \
  --camera-id 实际相机序列号 --mount external_fixed \
  --max-joint-age-ms 100 --max-gripper-age-ms 100 \
  --output "$PI_DATA/precalib_20261120_session01_association"
```

输出目录必须是新的；原 H0 数据不改动。100 ms 是本次关联可接受样本年龄的显式配置，供判断“能否组装完整观测”，不是已经验证的硬件时延指标。报告保留实际年龄分布，不隐藏超出值。

如果使用 H0 导出的 `evidence/motion_success` 窗口，其元信息文件名不同，显式指定：

```bash
/usr/bin/python3 "$PI_ROOT/tasks/piper_real_single_v1/associate_h0.py" \
  --camera-dir "$H0_WINDOW" --arm-dir "$H0_WINDOW" \
  --camera-metadata "$H0_WINDOW/full_run_camera_summary.json" \
  --arm-metadata "$H0_WINDOW/full_run_arm_summary.json" \
  --sample-manifest "$H0_WINDOW/window_manifest.json" \
  --camera-id CC16762023M --mount wrist \
  --output "$PI_DATA/historical_h0_window_association"
```

这里 `wrist` 只描述 11 月 16 日真实历史样本，不修改当前外部安装选择。原生记录自动读取本目录 `sample_index.jsonl`；导出窗口接受 `window_manifest.json` 的真实 samples。没有样本清单时只输出接收时间索引，不猜 PNG 文件名，不把带标注的 `preview.avi` 左半屏当作原始 RGB。

只有相机数据时可以省略 `--arm-dir`，生成 `state=null` 的相机观测索引。给出了臂目录时必须同时具有真实 boot_id 元信息；跨 boot 或缺失时钟身份时拒绝比较其单调时钟，不能用“最近数值”跨重启拼接。

### 输出语义

`observations.jsonl` 对每个真实 color 接收事件保留：

- `camera_rgb`：对应原始 PNG 路径与存在性、原 ROS header、同机接收时间、尺寸、源色序和 frame_id；无对应样本清单项则 path 为 null，清单有记录但本地 PNG 不存在则保留路径并标记 available=false。新导出器用 Pillow 直接解码为 RGB；若另用 OpenCV 读图，则将 BGR 转换一次为 RGB，不能对已经是 RGB 的数组再交换通道。
- `joint_feedback` / `gripper_feedback`：该 RGB 接收时刻之前最近一条实测反馈；没有插值，没有未来状态。源 CAN/SDK 时间作为独立字段保存。
- `state`：仅在六关节和夹爪反馈完整、有限且满足关联年龄时组合为 7D；否则为 null，但已有真实测量及缺失原因保留。
- `action=null`、`data_kind=observation_only`、`training_eligible=false`。工具没有把测量反馈、预测或历史动作事件生成监督标签。

`model_observation_complete=true` 只表示原始 PNG 文件存在并有完整关联状态；不表示 FK/零位、标定、输入分布或策略已验证。

`association_report.json` 分别报告全部 RGB 时序行、实测状态齐备行、实际保留 PNG 行和完整观测行，附接收间隔、先行反馈年龄 P50/P95/最大值。不同 CSV 的窗口长度可能不同，因此每个流的频率按自己的真实记录跨度计算。

所有关联只证明**同一主机、同一 boot 的软件接收时间关系**，不证明曝光同步、硬件同步或端到端实时性。相机原 ROS header 在 H0 中是驱动回调时间，不能重新命名为曝光时间。

## 5. 本次完成与未运行项

已完成源码准备和一段历史真实 H0 CSV 的离线关联分析：读取旧运动窗口前 240 条 timing 行与前 800 条关节/夹爪行，包含 65 个 RGB 接收事件；65 行都有先行实测关节与夹爪。该摘录未下载原始 PNG，所以完整图像观测数为 0，不能用于模型输入或训练。

此短摘录来自旧 DDS 运动窗口，RGB 接收存在成批到达；其数值不代表最终 240 秒静止窗口或当前部署性能。离线执行不包括相机启动、ROS 显示、CAN 接收、推理或机械臂动作。本次 `live_view.py` 的现场运行仍为 **NOT_RUN**。
