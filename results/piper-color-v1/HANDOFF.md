# AutoDL 后台任务交接

## 23:18 恢复读访问后的已核实结果

用户确认普通开机提示空闲 CPU 不足，随后已用无卡模式开机，SSH 命令未变。原训练没有自动重启，也未在无卡模式启动训练。

- LoRA：1500/1500 更新完成，1499 检查点提交成功，重新加载后的 15 次验证完成，成功率 0/15。权重与优化器已保存。
- 全参数：日志到 22:00:20 的第 1456 次更新；最新提交成功检查点为目录 1000，按上游保存语义对应 optimizer step 1001。恢复到 1500 需 499 次更新，其中 455 次是中断前未写入后续检查点的更新。尚未在重启后实际加载优化器验证。
- LoRA 验证诊断：10/15 次指定物体最大抬升超过 5 cm，其他物体抬升低于 2 cm；所有 15 次最终均未满足入盒/松爪成功条件。不得把抬升指标改称成功率。
- 日志、指标、全部已完成的 30 个验证视频/轨迹已下载到 cloud-recovery-20261024。大权重在本地 tmux `piper-color-backup` 中复制（两模式推理参数、归一化与元数据；优化器状态保留在云端文件存储）。看 backup-logs/weights.status / weights.exit。
- 已启动本地 tmux `piper-color-diagnose`，等待 LoRA 备份完成和本地 GPU 空闲，再在 5080 对 54 个固定教师观测做离线阶段动作误差检查，不训练、不执行硬件动作。看 offline-diagnostic/status / diagnostic.exit。它只用训练/验证数据，不使用独立测试集。
- 后续恢复全参数训练应先验证检查点，再续跑；不要重新启动整个 run_cloud.sh，否则会重做已完成阶段并在已有 checkpoint 目录报错。原始中断日志应保留。

平台的旧定时关机已发生，未来开 GPU 前仍需核实新的定时设置。不要仅凭脚本没有 shutdown 就宣称控制台没有定时关机。GPU 不可用时可参考官方同地区克隆（保留系统盘并勾选数据盘）；文件存储可在同地区共享。目前没有新建 GPU 实例或追加云端训练。

## 23:10 状态更正：平台定时关机可能中断任务

2026-10-24 北京时间约 23:10，现有 SSH 端口持续返回 Connection refused。重新读取另一对话发现它明确保留了控制台的 22:00 自动关机设置。此前“没有自动关机”的结论仅覆盖任务脚本，漏查平台设置，已向用户更正。尚未读取实例关机状态及本轮最终日志，不能宣布 LoRA/全参数完成或检查点可用。

用户已授权训练期间保持开机；本对话缺少已登录的 AutoDL 控制台操作工具，已请用户检查并恢复原实例、清除旧定时关机、确认 SSH 命令。恢复 SSH 后先盘点日志/完整检查点，再从已完成阶段继续，保留原始日志和失败轨迹；不要直接重跑整个 run_cloud.sh。

最后直接核实的训练状态为 21:02:56 的 LoRA 124/1500；之后进度未知。详见 connection-incident-20261024-2310.json。

用户已授权直接微调，并指定 tmux 托管；不需要等待完整训练才结束当前对话。允许训练所需期间保持实例运行，未授权实际机械臂动作。不要将后台任务已启动写成训练或实机验收已完成。

## 两小时后检查

本地工作目录 `/home/fanyuan/projects/kaiwen-learning/pi-reproduction`：

```bash
bash scripts/check_piper_color_cloud.sh
```

AutoDL 入口 `root@connect.westd.seetacloud.com:47745`；专用密钥在本项目 `runtime/ssh/autodl_piper_color_ed25519`，不要打印或打包私钥。主机密钥保存在 `results/autodl-known-hosts`。

登录后：

```bash
tmux attach -t piper-color-v1
cat /root/autodl-fs/pi05/piper-color-v1/logs/status
tail -n 30 /root/autodl-fs/pi05/piper-color-v1/logs/train-lora.log
```

tmux 会话 `piper-color-v1`，执行窗口 `pipeline`，设置 remain-on-exit 保留退出现场；默认展示的 `progress` 窗口跟踪顶层日志。检查任务是否存活请看 pipeline 窗口，progress 的 tail 进程存活不代表训练存活。顶层日志保存每阶段开始时间；详细日志按阶段单独存储，错误退出会记录 FAILED 和退出码。无需保持本地 SSH 连接。没有关机命令。

## 固定任务

代码：`/root/autodl-tmp/piper-color-v1/source`。
持久结果：`/root/autodl-fs/pi05/piper-color-v1`。
原有 LIBERO 任务仍在 `/root/autodl-tmp/pi05`，不要改动或删除。

流程：数据校验 → 训练集归一化 → 云端教师抓取复检 → 基础模型验证集 → LoRA 1500 步 batch 4 → LoRA 验证集 → 全参数 1500 步 batch 4 → 全参数验证集 → 两模式分别测试集 → 汇总及推理包导出。两模式训练互相独立，从官方 π0.5 base 初始化；根据验证集选择候选，不按测试集挑选。

165 条合成教师示范（120 训练、15 验证、30 测试），正式示范全部通过物理抓放/松爪稳定检查。教师使用物体真值；学习策略只用 RGB、反馈和文本。教师 165/165 不是 π0.5 成功率。

上传源码 SHA256：`a5e941a64cc30443f8a73b00424f27824caedd48e584a045908989c6a4b2c5c9`。
上传原始数据 tar SHA256：`5881a60612c4571c850f928cba7fbff4f0c0034b136659a7f0bcbd0e83a552e7`。
两份均已由远端 sha256sum 确认匹配。后续修复应保留新的源码和修订记录，不覆盖已用于比较的版本而不记录。

启动后唯一代码修订：`deployment_io.py` 的夹爪范围检查允许 1e-6 m 浮点舍入误差，并将建议值钳至 [0, 0.1] m；原因是 float32 的 0.1 实际为 0.10000000149。只影响未连接实机的部署建议函数，不改变数据、训练、仿真或评测。修订另存 `source-amendments.json`，源始 tar 保留。

## 结果和取回

完成后读取 `summary.json` / `summary.csv` / `index.html`。每个评测 episode 保留全景 MP4、JSON 和执行指令 NPZ。`deployment/` 包含按验证集选择的推理参数、归一化、配置与服务入口，不包含优化器。按需取回这些成果到本目录；不要把整个旧任务或私钥打包。

若阶段 FAILED，先读对应 `logs/<stage>.log` 和 pipeline.exit，再针对性修复；不要重新生成测试布局或把失败算作成功。训练有 500 步检查点，恢复要使用相同数据、种子、lr 总步数与 `--resume`，且不能并行启动第二份同任务。阶段超时上限 3 小时；需要续训时基于已有日志确定下一轮，而非无限重跑。

## 实机配置

Piper H 单臂，松灵官方夹爪先用默认 100 mm。DaBai DC1 腕部＋官方支架；外部计划 D435i。首任务为按红/绿/蓝语言指令将同形物体放入同一灰色盒子。当前没有实机数据，未实测相机序列号、外参、关节正负号/零位、固件和夹爪真实行程。任务包预留输入输出接口，但不得把合成数据微调当作即插即用的实机稳定性保证。

## 启动验收补充

2026-10-24 20:46:52 +08:00 启动 tmux pipeline，PID 19892；交接时仍在 dataset-audit，尚未验证到 optimizer update。数据展开到持久网络盘约 13 GB，阶段内不输出逐条日志；不能仅凭空日志判定卡死。可查本任务 Python 进程 /proc/<pid>/io 的 wchar 或 episode 子目录数判断进展。完整预处理已在本地通过。云端初次 EGL 检查发现缺少 libEGL.so.1，已安装 libegl1/Mesa 支持库并完成实际全景渲染与教师抓取复检，success=true，位于 startup_render_check/result.json。未改 Python 基础环境或已有 CUDA/JAX 版本。
