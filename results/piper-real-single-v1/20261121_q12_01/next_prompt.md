# Q12 腕部标定接续提示词

读取 AGENTS.md、docs/PI_REAL_TEST_STATE.md 以及本目录 final_seven/Q12_DC1_calibration.md。2026-11-21 的腕部标定已按用户确认的 27 个训练姿态、4 个正式预留姿态加 3 个 H0 补充姿态完成离线结算。使用 final_seven/Q12_DC1_calibration.yml 中的 K、D 和 T_flange_camera，项目原生结果、筛选与来源在同目录。相机序列号 CC16762023M、640×480 received、腕端安装、flange_link 与唯一槽 left_wrist_0_rgb 须匹配。

保留原始分组、运动与图像记录。理解短基线外缘尺寸最大偏差 13.3 mm 和图像覆盖范围后再判断结果是否满足具体应用。原始数据在本地，validation.json 的 local_session 指向本轮目录。原有 180 秒实录、历史 CAN 审计与本轮标定均已记录。

现场读数请重新查询。上次结束时 CAN 关节位置指令模式已接通、六轴均失能，J2/J3 实测超出控制器返回的工作范围。第二次回零及 50% 速度动作均未执行。后续仅在明确的新现场任务中由合适的现场操作者按厂家恢复流程处理。当前交付不触发任何实机动作、π 运行或新任务。
