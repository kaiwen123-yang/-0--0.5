# Q12 单腕标定下一轮精确提示词

更新于北京时间 2026-11-22。先读 AGENTS.md、PI_REAL_TEST_STATE.md、PI_DAILY_WORK_LOG.md 当日记录、[本轮复算](../results/calibration-audit/20261122/README.md)、[已冻结准则](../results/calibration-audit/20261122/comparison_rules.md)和[尺度表](../results/calibration-audit/20261122/board_measurement.md)。[11/21 原始提示词](https://github.com/kaiwen123-yang/-0--0.5/blob/5ce7e162bebeab4248aab675f4facfa2cd8c3c72/docs/PI_Q12_CALIBRATION_REVIEW_NEXT_PROMPT_20261121.md)保留历史。

## 最新接续结果

**14:21 第二开发平台实机续采。** 经 SSH 使用 pyAgxArm 及 CAN 低速 MOVE_J，取得 35 个训练、7 个开发和 9 个冻结后实拍独立姿态。采用名义格距 20 mm，固定 k3 重新求解 K、D 和 T_flange_camera。完整 640×480 接收网格逆映射通过。独立组逐姿态均值为 PnP 0.107 px、固定板全链 2.222 px、板位姿偏差 3.342 mm / 0.445°。结束时实测 q=[0.000, 0.000, 0.000, 0.000, 0.000, 0.000]°、全使能、CAN/MOVE_J。该结果是本次单腕安装、名义尺度与实测距离内的标定候选，绝对空间精度待计量核验。[14:21 实机标定报告](../results/calibration-audit/20261122/ssh_multiview/report_zh.md)。

新 K/D/X 与分组已冻结并已有独立验证。保留本轮原图和像素域。需要验证绝对几何时，再用独立实物基准测量格距与任务空间误差。

## 优先接续 11/22 现场新批次

**最新接续点（14:01）。** 用户已回零，本轮独立测得六轴均为 0.000°、全部使能、CAN/MOVE_J、motion_status=0。零位已有一张完整的 88 点原图和真实 q/G，与 13:54 的有板观测分别留存。[零位帧](../results/calibration-audit/20261122/recollection_home_board.json)。不要沿用更早的 J2 越界作为当前结论，也不需要再次执行物理回零。中断发生在多姿态运动前；接续时核对实际现场与控制状态，保留预分组，不以这两次诊断代替新手眼求解或盲验收。

用户已改为重新采集。先看[现场读取证据](../results/calibration-audit/20261122/recollection_status_01.json)和当日日志会话 2–4。13:41 本机查询范围为 J2 [0°,180°]、J3 [−170°,0°]。13:53–13:54 纯接收窗口末次读到六轴均已使能、ctrl_mode=2（示教）、teach_status=2（记录已结束），J2 −0.698°、J3 −34.653°。用户随后确认已退出示教，13:55:54 新读 300 组仍报告 ctrl_mode=2、teach_status=2，六轴均使能，J2/J3 相同。J2 仍越过零端，CAN 控制源尚待交接。13:54:24 已取得[首张 88 点候选静止观测](../results/calibration-audit/20261122/recollection_first_board.json)，正式训练与独立留出均为 0。现场状态有变化后再读。厂家手册 §1.2、§2.2.4、§4.8/4.9、§7.3 已核，见日志。新会话在 /home/kaiwen/research/pi-q12-data/20261122_q12_recollect_01，已有状态和可见性检查，合格姿态为 0。不要以重复读取同一静止姿态代替采集。

现场操作者完成针对当前读数的恢复后，重新核对实测关节和本机限位、状态、工作区及安装；通过静止腕图确认整板 88 点和固定的物理原点，再进行多姿态。给新批次单独编号，预设训练/开发/最终独立姿态与用途，最低 15/5，完整保留逐帧 received RGB、角点表、G/q/时间和来源，冻结后再评估最终独立组。若机械臂维持可靠固定，只移动棋盘的内参采集必须独立。保留旧结果，不把新批称为重新得到旧 27 训练视角，不为采集自动改限位、零点或到位/停止逻辑。

## 如找回旧输入，离线复现可沿用以下路径

继续 π0/π0.5 的 Piper H 单腕 DC1 离线标定。只动 π 项目，先查本项目工作树、修改、新提交差异与活动进程。现场数据固定为 field/pi-single-20261120@b3bb539109af287f7963fc750dc2dcb0b0549baa。沿用现场既有工作树，仅接入明确小模块与文档。不要合并整分支、覆盖 final_seven、上传录像、扫描全库或操作硬件。

1. 取原机目录 /home/kaiwen/Documents/Codex/2026-11-20/https-github-com-kaiwen123-yang-0/work/field/board_q12_20261121_01，或同一会话的只读副本。测试机上该绝对路径缺失。定向读 approved_seven_01/reviewed_seven_manifest.jsonl、approved_seven_01/supplemental_sources.json、detect_initial/detection.json、approved_seven_01/detect_supplement/detection.json，以及拟合文件实际引用的 approved_seven_01/fit/detection.json（如存在）。带回原 full-chain/外缘生成脚本或明确出处。若多个 detection 版本不同，追溯实际拟合用表。保留 34 视角的原始角点顺序、G/q、时间、帧号及回溯来源。11/22 的 selected_public_evidence.jsonl 是发布证据整理；五图重检坐标不能补作原检测表。
2. 取得原始输入后，用同一张经确认的角点表分别运行 27 训练组的 OpenCV calibrateCameraExtended，原五项 flags=0、候选 CALIB_FIX_K3=128。复用 tasks/piper_real_single_v1/calibration.py 的 intrinsics(..., fix_k3=True)、target_pose、Park handeye 与训练参考逻辑。CLI 的 intrinsics/handeye 会从图片重新检测，固定检测结果需在两次求解中复用已连接的记录。不得直接清零旧 k3 或沿用旧 X。旧五项先核对已发布解；每个版本分别保存真实 K/D/X、训练参考、板尺度与 flags。沿用名义 0.020 m，直到可靠实测表有结论。
3. 训练 27、正式 h01/h02/h03/h05、回溯 u06/u07/u08、合并 7 分别报告 PnP、全链、固定板 mm/°的 mean/P95/max 及异常姿态；从原 88 点计算。仍排除 h04/u09/u10，最低姿态配置 15/5。用逐像素脚本检查接收域与同 K 理想域的正反映射、Jacobian、中央分支和边界。旧模型的 593 个缺逆中心、5 原图和 34 组外缘已复核，不能记为新采样或盲验收。按已冻结规则比较，旧验证用于选型后转开发验证。当前训练角点最下 y=310.564，原点深度 0.553–0.724 m，实际任务距离、绝对空间精度及固件内部校正待证。
4. 若原始输入仍缺，报告缺项与对应路径；不借合成角点、少量图、外缘或发布 C 代替 27 组完整训练点。尺度需现场记录同平面长向 0→10、短向 0→77、铝板外宽外高，量具分辨率、重复读数、照片。197 mm 是既有粗读。可靠实测改变格距后重建物点并重求解。
5. 本轮保持离线。另有明确现场任务时由合适操作者按厂家流程核查实时状态、净空/接触/安装、到位状态与超时停止。最后记录 CAN/MOVE_J，六轴失能，J2/J3 超查询限位，重连后无目标/使能/回零。恢复验收后才规划约 8 个事先指定、争取至少 5 个有实质差异的新姿态，覆盖任务距离、更大侧向基线及安全可见的下部；冻结候选和通过条件，保留失败/遮挡。若腕部遮挡，另开 intrinsics_only：相机与机械臂可靠固定，仅移动棋盘，此组不得参与固定板手眼姿态集。
6. π 继续使用 CC16762023M 的 640×480 received RGB，唯一槽 left_wrist_0_rgb；保留固件校正 null，不向驱动、深度或 π 预处理插入 D。公开 RoboMIND 单臂示范优先，先核版本、动作/状态单位、单臂独立性及时序，从可信动作 train split 分别计算两套 norm。静止 180 s observation_only 无动作标签。无本轮训练、推理或运动授权，不修改共享 SDK/ROS/CUDA/JAX、缓存或基础权重。
7. 按北京时间真实发生日向唯一 PI_DAILY_WORK_LOG.md 同日追加，记录来源、版本、问题及证实程度、实际数值、边界、未执行项、硬件状态及下一步；同步状态页和接续词。仅提交推送明确小文件，保留现场分支和其他活动任务。
