# 11/24 连续采集、直接回零与已有数据结论

## 当前执行决定

用户最新要求为本页最高优先级：连续逐组采集，每组正常结束后直接自动回六轴零位；回零关节参考速度最高 3°/s；删除非必要路径规划和自行附加的工作区限制，不新增防御性框架或测试。J2 状态按用户最新现场反馈记为“重启后恢复”，本次云端未重新读取硬件。代码已在本次提交准备，尚无该版本的真实动作回执。

旧的手动回起点、Z、回零前几何搜索、5°/s 回零和每次沿空场原路倒退，不再是当前正式采集入口。历史记录保留。

## 给现场 Codex 的执行提示词

~~~text
只负责 π0 / π0.5 的 Piper H 单腕真实采集与后续算法测试。

先读本文件、AGENTS.md、PI_REAL_TEST_STATE.md 和 PI_DAILY_WORK_LOG.md 的最新条目。保留 /home/kaiwen/research/pi-single-live 当前未提交工作；把本次提交对 demo_field.py、demo_home.py、demo_io.py、demo_path.py 的实际修改整合到现场，不拿历史整树覆盖现场。不要重装 SDK/ROS，不改共享 pyAgxArm 或 dog-and-arm。

用户已明确授权继续采集，反馈 J2 重启后恢复。只使用现场当前状态，不把 18:17 的历史告警当当前读数。接入时沿用一次 status 读取当前模式、六轴使能和故障；这是正常接入，不另做试动、测试矩阵、容量试跑或恢复演练。已有相机和 viewer 继续复用。

执行要求：
1. 正常 teach、empty、正式 block 完成后，程序自动单段关节插值回 [0,0,0,0,0,0]°，最高参考速度 3°/s，不运行 home_geometry，不插旧保持位路点、不原路倒放。SDK 百分比不是度每秒：回零 50% 档与 3°/s 参考各自记录。回零不改变当前夹爪开口，回程独立记录，不能混入任务标签。
2. 在现场完成灯灭、撤手交接后直接回程；正常完成不再要求另发 home。中断和故障不当成完成，也不自动继续运动。
3. 从已回零状态用 next-teach 准备下一组；上一源成功或被拒都可接续。该入口按本次控制器回读刷新 setup.bounds。每次只教本条指定颜色，保持单 DC1 CC16762023M，唯一有效图像槽 left_wrist_0_rgb。
4. 角度范围只用本次控制器实际回读，不再叠加 SDK 可选预设、URDF 或额外余量；本实例 SDK 可选模型夹限恢复官方默认关闭。不得写控制器角度/速度/电流阈值或关闭硬件保护。现有原始回执中 J5 控制器为 ±89.5°，不是人为增加的 82° 或其他余量。若本次回读不同，如实记录，别手填。
5. 先在 T01-RB01b 红蓝混摆中完成一条紧凑蓝源，放入固定浅盘、释放后少翻腕并抬离，停稳记录 E，退出示教后自动回零。源通过后 anchor-start → empty → 自动回零 → review → 复原布局 → anchor-start → block --formal → 自动回零 → review。同一来源重复实物运行无需重教或重做同源空场；新颜色/位置要记录相应真实来源。
6. 继续复原同一布局采红目标，再交换蓝红位置；随后采四色混摆。采蓝红白绿，训练先筛蓝红；沿用 T01/T02 train、V01 validation，布局和来源不跨 split。禁止复制动作换颜色标签。
7. 对已有 11/24 四个 teach 目录用真实 run/feedback/rgb/标记做小型来源清单，说明哪些可作仿真参考、哪些不能作正式动作示范。保留旧拒绝状态和原始数值，不夹平 J5 后伪称原始数据合格。不要重下载大数组，不做全库扫描。
8. 每条真实 block 审核记录实际抓取颜色、是否人工介入和成败。仅真实成功 block 进入正式训练；teach TX=0 不等于动作监督。回零也不算新的任务 episode。
9. 不中断现场采集去扩建仿真。仿真可复用 tasks/piper_color_v1 的 Piper H 模型，但另建当前单腕场景，用冻结 K/D/T_flange_camera、实际浅盘/方块及可用真实轨迹段；明确 simulation 域，不冒充 real_demonstrations。已有旧双相机数据不直接混入本次训练。
10. 直接推进真实任务。不要添加与本任务无关的框架、兜底、预检、mock/单元/导入/shape 测试或耗时路径搜索。每轮把实际成功数、问题处理、回零参考与实际记录、最终硬件状态写进唯一 PI_DAILY_WORK_LOG.md，更新状态并提交本轮明确文件。不要把代码准备写成现场验证。
~~~

## 现场命令

工作树为 /home/kaiwen/research/pi-single-live，原始数据留 /home/kaiwen/research/pi-q12-data。以下命令逐条在可观察实机的现场终端执行；只有当前步骤正常完成才接下一步。

~~~bash
D=/home/kaiwen/research/pi-single-live/tasks/piper_real_single_v1/pi_demo.sh
S=/home/kaiwen/research/pi-q12-data/pickplace_20261124_T01

bash "$D" status
bash "$D" next-teach "$S"
bash "$D" teach "$S" T01-RB01b --target-color blue --scene-colors blue red
~~~

C 是抓取位，O 是释放位，E 是释放后抬离终点。按现有现场灯灭/撤手提示完成交接，自动回零。公共示教起点仍为 [0,2,−2,0,0,0]°；它是重复采集的起点，不是新增关节限位。回零目标始终为六轴 0°。

源通过后，移走任务方块：

~~~bash
bash "$D" anchor-start "$S"
bash "$D" empty "$S"
bash "$D" review "$S"
~~~

empty 正常结束也自动回零。审核通过后复原同一布局，再执行：

~~~bash
bash "$D" anchor-start "$S"
bash "$D" block "$S" --formal --target-color blue --scene-colors blue red
bash "$D" review "$S"
~~~

block 正常结束已自动回零。第二次同源重复用 anchor-start 后再次 block；换红目标或新布局时用 next-teach 后重新 teach。审核按实际结果填写，不能预填成功。四颜色主库、蓝红子集的导出命令继续使用[现场指南](PI_LOCAL_DEMONSTRATION_GUIDE_20261123.md)。

## 本次代码改了什么

| 部位 | 本次行为 |
| --- | --- |
| demo_field.py | teach、empty、正式 block 正常完成后接独立 home；next-teach 接上一组完成或重录；直接关节回零，最高参考 3°/s |
| demo_home.py | 删除几何子进程、20 mm 高度判据和旧保持位路点选择；闭式单段梯形速度，不运行路径搜索 |
| demo_io.py | 完整 CAN/MOVE_J/速度模式同帧发送；关闭本实例可选 SDK 模型夹限；目标范围仅取实际控制器回读 |
| demo_path.py | 分离真实源读取/标记与范围核对；teach 收尾不再运行自适应轨迹简化，真正重放时才生成其执行点 |

单段使用已有 8°/s² 起停参数。最长轴位移 D、最高速度 3°/s 时，一般行程参考时间为 D/3 + 3/8 秒；90° 约 30.4 秒（50 ms 网格）。短行程用三角速度。以上是代码参考，不包含模式交接/最终到位时间，也不是此次实测物理速度；实际响应保存在下一次真实回执。未执行测试套件或硬件运动。

## 哪些限位留下，为什么

官方 SDK d90e234 的模型软件夹限默认关闭，提供 set_joint_limits_enabled(False)；本次恢复本实例默认，不修改 SDK 源码。SDK 预设表保留为记录信息，不再与主控范围取交集。

本机 [11/23 两次原始参数查询](../results/pi-readiness/20261123/local_commissioning/field_checks.json) 的控制器字段确实返回：

| 关节 | 回读角度范围 |
| --- | --- |
| J1 | −150° ～ +150° |
| J2 | 0° ～ 180° |
| J3 | −170° ～ 0° |
| J4 | −135° ～ +135° |
| J5 | −89.5° ～ +89.5° |
| J6 | −170° ～ +170° |

运行时用新的回读，不把这张历史表硬编码成当前值。控制器过流、堵转和故障状态属于设备保护，保留。额外的 J5 提前 7.5° 提示、公共起点目标必须在 ±5° 内的附加判断、回零高度与几何检查已从当前路径移除。零位/源起点到位关系、唯一发送者和真实标签来源属于当前动作及数据合同。

官方来源：[模型表](https://github.com/agilexrobotics/pyAgxArm/blob/d90e234ba8e408cfa964b38aa9120b3131fc9f85/pyAgxArm/api/constants.py)、[软件开关与默认值](https://github.com/agilexrobotics/pyAgxArm/blob/d90e234ba8e408cfa964b38aa9120b3131fc9f85/pyAgxArm/protocols/can_protocol/drivers/core/arm_driver_abstract.py)。

## 已采数据能否使用

依据 main@c9e7a52 的现场日志、A01 公开证据和当前代码。今日完整原始数据在现场，本次未逐帧重读。

| 记录 | 已记录质量 | 当前资格 |
| --- | --- | --- |
| 蓝一 164601 | 12,184 张原图；J2 最低 −2.62°，缺少正常 E，后期场景出现白绿 | 原始观察/轨迹参考，不能正式训练 |
| 蓝二 170803 | 6,754 张原图；任务 142.883 s；J3 +0.061°，J5 最高 89.903° | 示教源被拒，尚无对应正式实物 episode |
| 蓝三 174233 | 1,470 张原图；任务 49.05 s；J5 164 组超过 89.5°，最高 89.880° | 可作紧凑路径/仿真参考，不能直接作动作监督 |
| 红一 180201 | 983 张原图；任务 32.41 s；J5 170 组超过 89.5°，最高 90.027° | 同上 |
| 昨日 A01 | 一次真实成功抓放；11,553 原图，7,680 个 20 Hz 行 | commissioning，仍非正式训练 |

以上越界是实际反馈数值，原数据保留；不通过修改边界、删掉部分帧或将反馈复制成 action 制造成功。控制器范围与 SDK 表原本在这几轴相同，删除可选 SDK 交集不会自动使这些旧源合格。四个手拖源没有真实任务目标提交，它们的 TX=0 是正常被动示教事实。正式训练还需实际 block 的提交动作、成功抓放、颜色审核和独立验证来源。当前有证据的正式成功数仍为 0；新采结果按现场回执更新。

## 怎样用于仿真采集

可以使用上述数据提供相机视野、关节姿态、抓放阶段和实际工作区参考。复用现有 [piper_color_v1/sim.py](../tasks/piper_color_v1/sim.py) 的官方 Piper H 模型、物理接触和生成器，无需从零建机器人。

旧场景是双 RGB 224×224、35 mm 红绿蓝块和灰盒，不能直接当当前单腕实机数据。本任务另设单腕 RGB 640×480，使用[冻结标定](../results/calibration-audit/20261122/ssh_multiview/wrist_rgb_calibration.json)的完整 K、D 和 T_flange_camera，实测桌面、浅盘、方块及指垫参数；只有 left_wrist_0_rgb 有效。先以真实 q 和合法轨迹段比较视野/FK，再在新场景实际执行抓起、搬运和释放，产生新的模拟状态与提交动作。

新合成数据标 simulation，保留真实来源、布局与 split，不写成 real_demonstrations。先蓝红混摆、同布局换目标与交换位置，再扩四色。仿真可以辅助扩大位置与外观覆盖，但这些手拖源和旧双相机仿真不能替代本任务第一批正式真机成功示范。此轮只完成可行性与复用范围判断，没有生成新的单腕仿真 episode。

## J2 事件的结论边界

18:08 起点准备实际发送 move_mode=0xFF，健康判断随后发出 0x150 阻尼急停；这是已定位的软件指令问题。原修复只覆盖起点准备，本次把 home、return-start、empty/block 入口也统一为完整模式帧。官方 [set_speed_percent 源码](https://github.com/agilexrobotics/pyAgxArm/blob/d90e234ba8e408cfa964b38aa9120b3131fc9f85/pyAgxArm/protocols/can_protocol/drivers/piper/default/driver.py) 确实先把 mode 设为 255 再发送，且百分比不是 °/s。

18:09 记录还未报 J2 过流；Windows 操作后 18:14/18:17 的 A4 是过流、驱动错误、堵转并失能。缺少中间连续电流和 Windows TX，不能断言该软件问题就是随后过流的完整物理根因。用户最新反馈重启后已恢复，当前按此继续正常接入和采集，不额外扩大排障。本次没有清错、复位、使能或实际运动。[历史记录](PI_DAILY_WORK_LOG.md)
