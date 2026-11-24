# 11/24 一次真实手拖示范 → 导出 → π0.5 / π0 全参训练

## 当前决定与完成边界

用户要把一次示教直接录成训练示范，今晚采完后启动正式训练。本页替代此前“teach 只录路径，再 empty → block → review”的新数据流程；旧记录不删除。当前提交实现了采集、动作标签、有效 chunk、各自 norm 和正式全参入口。云端只完成源码衔接检查；尚未在现场执行这个版本、导出新数据或启动 D57 训练。

固定配置：Piper H，官方夹爪，DC1 CC16762023M 随腕，只有 left_wrist_0_rgb；固定浅盘，蓝红白绿四个颜色，阶段 A 先蓝红。沿用已完成的标定和既有环境。J2 按用户现场反馈记为重启恢复，不重跑历史诊断。

## 现场执行提示词

~~~text
只负责 π0 / π0.5 单腕真机示范、全参训练及后续模型测试。执行本文件最新流程，不再把用户手拖录制当成只供重放的路径。

先读 AGENTS.md、PI_REAL_TEST_STATE.md、PI_DAILY_WORK_LOG.md 的最新条目及本文件。把本次明确变更整合到 /home/kaiwen/research/pi-single-live，保留现场未提交修改，不用旧仿真整树覆盖。复用相机、viewer、SDK、ROS 与 D57 两套 OpenPI 环境，不重装，不修改共享 SDK 或 dog-and-arm。接入时读取一次当前状态，随后进入实际采集，不另开试动、空场、测试矩阵或容量试跑。

1. 复用正式 T01/T02=train、V01=validation 会话和已测量的夹爪配置。T01 已建立；其他会话按实际 session.json/setup.json 判断是否需要 prepare-formal，由当前真实保持所属会话交接，不重复准备已完成会话。
2. 从真实零位用 next-teach 准备公共起点。teach 必须带唯一 target-color 和实际 scene-colors。等待程序 start 已记后手拖真实任务：到目标方块按 C 回车，实际闭合夹住；手拖到固定浅盘按 O 回车，实际张开放下；空爪抬离并停稳，成功抓对颜色按 E，失败按 F。E 本身就是操作者成功确认，不再要求 review、empty 或 block。
3. C/O 仅用当前唯一发送端发送官方夹爪 0x159；六关节仍在实体示教模式，不发送关节目标、不改六轴模式。第一次正常示范中的 C/O 直接读取新鲜夹爪反馈：闭合看实际缩小和稳定，不要求夹住方块后仍达到空夹闭合目标。若固件不执行示教期间的夹爪命令，必须报告真实反馈和阻塞，不写成功、不自动切换六轴到 CAN；从这一次正常采集查明，不另录空场。
4. 正常结束后退出实体示教、灯灭撤手，按终端交接提示自动单段回六轴零位，关节参考最高 3°/s，回程单独记录。不规划绕行，不插旧路点。换物体位置后继续 next-teach → teach；每条只做一次真实抓放。
5. 同布局分别采蓝、红目标，再交换两色位置；同时继续采白、绿和四色混摆。每色先一块，目标必须在腕图中能辨认。T01/T02 用训练布局，V01 重新独立摆放并真实示教；不可复制源或随机拆相邻帧到验证。条数按今晚实际时间推进，80 条不是训练门槛。
6. 同次保存原始 RGB、实测六轴/夹爪、真实 C/O 命令和来源时间。成功 teach 自动生成 review.json。失败照实保留；回零不混入任务。不要把旧 C/O 仅记点的数据改旗标冒充新示范。
7. 采完按本页命令 export 冻结全库、stage-a 筛蓝红。局部超出本次控制器回读范围或接收缺口，只排除受影响的完整 10 步 action chunk；原始值和时间序列保留，不整段因为个别坏点作废。使用每条 run 固定的 bounds，不读后续改变的 setup 范围。
8. 阶段 A 训练和验证都包含真实成功蓝、红目标后，用 rsync -aL 上传蓝红视图，解析相对链接；复用现有 D57 连接，不新建环境。将本次 tasks/piper_real_single_v1 代码同步至 D57 的 π 仓库。
9. 直接执行 night_train.sh：π0.5 自己的 train-only norm → 10,000 步正式全参训练 → π0 自己的 norm → 10,000 步正式全参训练。单卡依次运行，绝不换 LoRA，不把两模型 norm/权重混用，不新增预训练试跑。采用新实验名；在已有 GPU 任务旁不能自动杀进程或盲目启动两个全参进程。用实际正式日志报告速度、损失、检查点、剩余时间。
10. 用户仍在采集时继续协助完成真实示范；数据冻结后继续上传和正式训练，不停在“代码已准备”。只有现场输入、资源确实被占用或真实设备阻塞时具体报告。更新唯一 PI_DAILY_WORK_LOG.md、状态和紧凑证据并推送本轮明确文件，区分代码完成、现场成功和训练已启动。
~~~

## 现场最短操作

使用可观察实机的终端。以下 Q、S 为既有路径；当前不在零位时先按当前实际状态完成已有回零交接，不把历史零位记录当现在状态。

~~~bash
D=/home/kaiwen/research/pi-single-live/tasks/piper_real_single_v1/pi_demo.sh
Q=/home/kaiwen/research/pi-q12-data
S=$Q/pickplace_20261124_T01

bash "$D" status
bash "$D" next-teach "$S"
bash "$D" teach "$S" T01-RB02 --target-color blue --scene-colors blue red
~~~

程序确认后，单击实体示教键，等 start。手拖抓取位 → C 回车实际闭合 → 手拖入盘 → O 回车实际张开 → 抬离停稳 → E 回车成功保存。F 表示本次失败；不将抓错颜色或另行救场记成功。E 后按提示结束实体示教、撤手，自动以最高 3°/s 参考回零。手拖示范本身是正常监督来源，不算“额外人工介入”。

复原同一布局采红，位置改变才更换 placement：

~~~bash
bash "$D" next-teach "$S"
bash "$D" teach "$S" T01-RB02 --target-color red --scene-colors blue red
~~~

四色混摆将 scene-colors 改成 blue red white green，target-color 分别选择本条指令的颜色。每组正常回零后继续下一条。新正式示范不执行 empty、block、review。这些旧命令保留供历史任务使用。

T02/V01 如果已有分配文件但没有 setup，从当前持有实际保持的会话交接，例如当前保持属于 T01 时：

~~~bash
bash "$D" prepare-formal "$Q/pickplace_20261124_V01" "$S"
~~~

不要直接把上述 T01 写死为任何时刻的保持来源；以现场 hold 及当前状态为准。之后对新会话使用 next-teach 和 teach。V01 独立摆放，placement 使用 V01 前缀，保持真实分组。

## 夹爪到底改了什么

旧 teach 的 C/O 只记时间点；新正式 teach 创建夹爪发送端，使用当前 open_m / close_m / force_N，记录实际 0x159 帧、提交时刻与反馈。现有配置约张开 40 mm、闭合目标 15 mm、力 1 N，最终以现场 setup.json 为准。这里是 SDK 宽度，不能等同卡尺净距。

- 起始张开命令在任务网格开始前记录，首行也有真实夹爪目标来源。
- C 后要求新鲜实测宽度实际缩小并稳定。夹住方块后反馈宽度大于闭合目标是接触结果，不再以“必须达到空夹目标”判失败。
- O 后等待实测张开；命令、反馈分别保存。
- 官方 SDK 固定版本的 move_gripper_m 只发送夹爪 0x159，不自动改变机械臂控制模式。官方公开接口没有保证本机固件在实体示教中接受该命令；本次第一次真实 C/O 才能确认，未确认前不能写“实机夹爪修复验收通过”。

源码来源：[官方 d90e234 夹爪驱动](https://github.com/agilexrobotics/pyAgxArm/blob/d90e234ba8e408cfa964b38aa9120b3131fc9f85/pyAgxArm/protocols/can_protocol/drivers/effector/agx_gripper/default/driver.py)。本项目实现：[demo_field.py](../tasks/piper_real_single_v1/demo_field.py)。

## 数据如何直接用于训练

新版本名为 kinesthetic_direct_v1 / real_kinesthetic_demonstrations。20 Hz 网格每行的 state 来自 t 时刻之前最近的实测六关节和夹爪宽度；图像同样取因果最近帧。arm action 明确重建为 t+50 ms 之前最近的未来实测关节位置，gripper action 为该动作时刻实际已提交并保持的夹爪目标。前者不是历史 CAN 关节命令，来源标为 future_measured_joint_positions；后者标为 actual_submitted_sdk_width_target。

采集保留完整原始 RGB/反馈/命令。导出保持原始 20 Hz 行序和数值，用 valid_action_starts.npy 选择完整有效 10 步 chunk。触及局部控制器越界、过旧样本或大于 100 ms 接收间隙的 chunk 不取样，不把两段跨缺口拼起来。每条的 quality.json、row_sources.jsonl 和 index 解释有效条数与排除原因。末端允许按既有合同重复最后一行；回零区间不进入任务。

按实际已有会话列出参数；若今晚只完成 T01，就不要把不存在或未准备的 T02 加进命令。验证会话至少有蓝、红真实成功示范。输出使用新目录，不覆盖历史集：

~~~bash
bash "$D" export "$Q/four_colors_direct_20261124_v1" \
  --train "$Q/pickplace_20261124_T01" \
  --validation "$Q/pickplace_20261124_V01"
bash "$D" stage-a "$Q/four_colors_direct_20261124_v1" "$Q/blue_red_direct_20261124_v1"
~~~

T02 完成后加入 --train 后的会话列表。全库可先包含当天已采颜色，白绿无需为凑齐数量阻塞蓝红正式训练；以后追加批次时用新冻结版本。两模型共享同一冻结 split，各自的 norm 只读取 train 的有效 chunk，验证集不进入 norm 或训练梯度。蓝红目标的图中可以有白绿干扰物。

## D57 正式训练

上传 blue_red_direct_20261124_v1 时使用 rsync -aL，将阶段 A 的相对目录链接解析成真实内容。目标可用 /root/autodl-tmp/robot-repro/piper-real-single-v1/data/blue_red_direct_20261124_v1。连接方式沿用现场已有配置，不在仓库放凭证。

在 D57 同步过本次代码的 π 仓库根目录：

~~~bash
bash tasks/piper_real_single_v1/night_train.sh \
  /root/autodl-tmp/robot-repro/piper-real-single-v1/data/blue_red_direct_20261124_v1 \
  dc1_wrist_direct_blue_red_20261124_v1
~~~

脚本先生成实际 spec，然后依次 π0.5 → π0。每个模型 batch=8、全参 10,000 steps、warmup=500、peak LR=1e-5、最终 LR=1e-6，每 1,000 步保存、每 50 步记录；EMA 明确关闭。这是本轮正式起步预算，不是效果保证。无需先跑容量/冒烟/几步试训。原有 D57 环境和权重路径来自此前实际记录，本轮未联网登入 D57 确认 GPU 当前占用；脚本记录启动时真实占用，不停止别人的任务。

每个模型自己的输出位于 outputs/{pi05,pi0}/实验名，night_specs/实验名 保存配置、GPU 占用、norm.log 和 train.log。训练入口记录真实总参数/可训练参数数目。先完成 π0.5 可优先进入其模型检查点推理和实机部署，π0 随后完成对照；实机新位置抓放结果仍要用真实模型评估，旧 SDK 路径重放不算策略成功。今晚目标是采完即启动正式训练；完成时间从实际每步耗时计算，不保证明早一定完成。

## 本轮交付与既有数据

变更涉及 demo_field、demo_export、dataset、train、两份 pickplace 全参配置和 night_train.sh，以及当前指南/状态/唯一日志。未更改控制器角度、电流或硬件保护，不新增额外工作区限位；正常回零复用既有单段 3°/s 实现。

此前真实成功 A01 和手拖记录保留。它们不因 TX=0 或 commissioning 标签天然失去训练价值，也不能只改 flag 冒充本次“真实 C/O”新合同。已有数据的来源适配可后续处理，今晚首先把新采的每条录成可训练真实成功，避免再花时间重复一次任务。
