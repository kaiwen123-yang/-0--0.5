# 单相机实机准备工具

此目录新增一个真实RGB输入的独立接口，不改变历史仿真模块、B配置或共享OpenPI。现场相机安装显式选择 external_fixed / wrist。当前用户意图是外部固定，历史H0为腕部；两者的记录不能混为同一安装。

**当前完成的是代码准备和有限历史数据离线处理。现场viewer、标定与两模型训练尚未执行。当前工具不发送机械臂指令。**

## 文件与职责

| 文件 | 用途 |
|---|---|
| associate_h0.py | 原始H0时间表、实际PNG索引、关节/夹爪反馈的接收时间关联 |
| live_view.py | 订阅已有ROS RGB，并显示H0已落盘反馈及年龄 |
| export_observation.py | 将一条真实完整观测导出为单相机NPZ，不生成动作标签 |
| policy_config.py | 单相机输入、绝对动作输出，以及π0/π0.5全参配置 |
| dataset.py | 有真实动作标签的完整episode读取；不将静止记录变示范 |
| train.py | 真实训练split统计量计算与正式全参入口；缺条件为NOT_RUN |
| infer.py | 从真实保存观测做一次只读推理；需要对应新checkpoint与资产 |
| calibration.py | 普通棋盘检测、内参、手眼和独立姿态评估 |
| calibration_spec.example.json | 待填写的真实板/图像/FK/安装信息，无假外参 |
| pi0_full.example.json / pi05_full.example.json | 两套准备配置；未确定项为空，不自动训练 |

## 1. 实录和显示

完整命令与H0源码格式见 [RECORDING_USAGE.md](RECORDING_USAGE.md)。

复用原H0记录器和现有ROS环境。保留唯一相机驱动，不让多个SDK pipeline争用设备。新viewer不打开CAN，不使能、不回零。

H0原相机记录器默认5秒抽样；预览视频有文字和拼接。需连续原始图时明确选择sample-period=0或全会话bag，并确认原始数据目录空间；不能以稀疏抽样声称得到30Hz完整训练图。

H0反馈CSV的显式flush为2秒。viewer显示的是已落盘测量值，其年龄包含写盘可见性与显示调度；它不是后续实时控制的状态通道。真正低时延模型控制需要接收事件通道，不能通过刷新文件时间戳伪造。

## 2. 一条真实观测的导出

先运行associate_h0.py，选择报告中原始PNG存在、7维反馈完整的真实stream index。从仓库根目录执行：

~~~bash
python tasks/piper_real_single_v1/export_observation.py \
  --index /实际路径/observations.jsonl \
  --stream-index 实际RGB索引 \
  --prompt "实际任务指令" \
  --output /实际新路径/observation.npz
~~~

导出键为camera_rgb、state、prompt。导出器用Pillow直接将PNG解码为RGB，不经过BGR，不缩放、不去畸变，不生成actions。伴随JSON保留源图、相机身份、安装与反馈年龄。历史H0来源应保留历史wrist标记，不能导出后冒充现在的外部视角。

原始图缺失或反馈不完整时不导出。该观测可用于已有匹配checkpoint的只读输入；文件存在不代表新单相机模型已训练。

## 3. 两个完整模型的准备

字段、数据目录与未来运行命令见 [MODEL_USAGE.md](MODEL_USAGE.md)。

两套配置必须分别填写已有π0/π0.5环境及基础参数路径。真实数据、norm和训练预算未落定时返回NOT_RUN，不做自动LoRA或容量试跑。本轮不执行prepare-stats或train，因为尚无本轮真实示范。

规范输入同为实测state7 + camera_rgb + prompt；监督为真实下发绝对关节/夹爪目标。π0/π0.5不同的状态表示和归一化由各自配置保持。模型内部action_dim保留32维padding，物理输出截取7维。

## 4. 周日使用的标定入口

先复制 calibration_spec.example.json 为本次实际配置并填写真实设备/板信息。图像域raw或rectified必须有现场依据；D=0或话题名image_raw不能自动证明是哪一种。

每行manifest表示一张真实接收图，必需字段：

- sample_id、image_path、split（train或heldout）、pose_group。
- 同一静止姿态的相邻帧属于同组，不能跨训练和验证。
- 手眼另需真实 T_base_gripper 与 pose_verified、static_capture_verified、board_orientation_verified。
- 保存真实图像/反馈时间、FK来源和帧名；没有实际位姿时不填单位矩阵。

T_A_B把B坐标变到A，平移m。外部固定模式需要板刚性随末端固定构件运动；腕部模式需要板相对基座固定。机器人基座全程固定。

~~~bash
python tasks/piper_real_single_v1/calibration.py detect \
  --spec /实际路径/calibration_spec.json \
  --manifest /实际路径/captures.jsonl \
  --out /实际新路径/detect

python tasks/piper_real_single_v1/calibration.py intrinsics \
  --spec /实际路径/calibration_spec.json \
  --manifest /实际路径/captures.jsonl \
  --out /实际新路径/intrinsics

python tasks/piper_real_single_v1/calibration.py handeye \
  --spec /实际路径/calibration_spec.json \
  --manifest /实际路径/captures.jsonl \
  --intrinsics /实际路径/intrinsics/intrinsics.json \
  --method park --out /实际新路径/handeye
~~~

raw拟合K与5项畸变；rectified固定D0并拟合当前流有效K。两者都使用真实图像，采集端不得再次缩放/去畸变后还沿用旧像素几何。

结果为FIT_REQUIRES_REVIEW，独立图像/姿态误差单独报告，不自动发布TF或宣称通过。无真实输入为NOT_RUN，不输出假外参。普通棋盘需要确认原点编号一致；实际板若是ChArUco/AprilGrid，按真实字典/ID补检测器。

## 5. 实际使用顺序

现在：现场身份/视野→真实接收与显示→时间关联→单帧导出→准备模型路径、FK与标定manifest。

到货：填板参数→多姿态真实采集→内参独立验证→手眼独立验证→接入同一session→真实空间一致性与连续动作联调。

训练：待真实动作监督数据与split落定后，计算各自norm，按明确预算启动两个全参任务。标定数据和静止记录不自动转成示范。

[本轮总计划](../../docs/PI_SINGLE_CAMERA_PRECALIB_PLAN_20261120.md)；
[现场Codex提示词](../../docs/PI_SINGLE_CAMERA_PRECALIB_PROMPT_20261120.md)；
[当前状态](../../docs/PI_REAL_TEST_STATE.md)。

