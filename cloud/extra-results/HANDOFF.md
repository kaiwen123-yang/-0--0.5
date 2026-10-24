# AutoDL 后台任务交接

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
