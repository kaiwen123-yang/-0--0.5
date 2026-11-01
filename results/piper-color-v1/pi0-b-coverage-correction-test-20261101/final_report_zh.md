# π0 B 覆盖、纠偏与独立测试

实验完成时间（UTC）：2026-11-01T16:18:22.577752+00:00。实验完成与上传完成单独记录。

B 训练覆盖：211/240；五种子验证：72/75。
各布局、颜色、种子、失败阶段与全部失败视频见 coverage_summary.json。

纠偏：qualified。20 full successful corrections from 20 bounded train-failure attempts。
教师前缀结果单列于 prefix_summary.json，不计自主成功。
C/D 节点及开发选择依据见 candidate_comparison.json；每次更新见 C、D 的 lora_metrics.jsonl。

最终冻结候选：B，累计优化器更新 4020。
独立测试：53/60；seed42=26/30，seed43=27/30。
逐布局结果和失败轨迹见 test_summary.json，测试没有用于重选候选、继续训练或调整成功标准。

实际计算：新增自主评测 721，复用 42；新增优化器更新 2000；
教师前缀 24；纠偏尝试 20，合格示范 20。

上传快照：{"at_utc": "2026-11-01T15:00:03.358357+00:00", "status": "paused_academic_proxy_unavailable", "current": "progressive-ab-a-checkpoint-1000-275469e093061e7b-3166f94f0061adde97cba653806ddc22.part-000", "pid": 16156, "concurrency": 1, "nice": 19, "ionice": "idle", "transport": "autodl_academic_only", "vpn_fallback": false, "rate_limit_mib_s": 4, "reused_groups": 8, "reused_assets": 55, "reused_source_files": 3493, "reused_source_bytes": 47084260578, "planned_new_assets": 320, "uploaded_new_assets": 18, "uploaded_new_bytes": 8078490356, "pending_assets": 302, "unresolved_groups": 0, "source_deleted": false, "experiment_status": "independent; see campaign run.json"}。
实时传输状态在 runtime/pi-progressive-upload-20261101/progress.json，缺失项见 missing.json。
无论上传状态如何，服务器原始数据、所有检查点与开发环境均保留。未使用实机或 π0.5 新训练。
