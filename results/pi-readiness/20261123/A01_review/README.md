# A01 仓库审查材料

北京时间 2026-11-23，来源固定为 `kaiwen123-yang/-0--0.5@0ee2d2ecc6783ffcfdec115079a83db3944caeb5`。

本目录为源代码、已发布现场回执和代表图片的分项审查。没有连接硬件、运行模型，或重新打开测试机全部原始图像/NPY。原始成功记录与元数据保留在相邻的 [local_commissioning](../local_commissioning/) 目录和现场原机。

- [data_audit.json](data_audit.json)：实际状态/动作来源、因果对齐、chunk、夹爪语义和分组要求。
- [control_audit.json](control_audit.json)：实际低速重放/保持/独立返回、当前 formal 门及首次重定位依赖。
- [visual_audit.json](visual_audit.json)：实际查看图片的观察、目录核查范围和未观看完整视频的限制。

统一结论与推进顺序以 [A01 审查报告](../../../../docs/PI_A01_RECORDING_REVIEW_20261123.md) 和 [新执行提示词](../../../../docs/PI_A01_NEXT_PROMPT_20261123.md) 为准。A01 认可为首条成功 commissioning，旧数据不直接改为正式训练；新合同和新终点的代码实现/现场验证仍待下一轮完成。分项文件中的数量建议是采集预算，不是额外数量审批门。
