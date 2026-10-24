# RTX 5080 与后续微调

**2026-10-24 云端状态补充：** 已读取另一对话 [了解 AutoDL 租卡与企业套餐](codex://threads/01a16d34-479f-7911-9cd3-c44c5c8db349) 及其中的远端结果输出。用户已租 RTX PRO 6000 Blackwell Server Edition 96GB，按小时计费，并要求暂时保持开机。π0.5 的 LoRA 配置与全参数配置均完成 20 次更新、checkpoint 保存、重新加载和推理检查；结果摘要为 `COMPLETE`。两种输出均为有限的 10×7 动作块。这段记录对应前期 LIBERO 流程检查。后续用户已授权直接运行 Piper H 颜色入盒专项微调，并指定 tmux 托管；见 [新任务的完整配置](../tasks/piper_color_v1/README.md)。

这轮使用的是官方 `pi05_base`、16 条 Panda LIBERO 示范、batch=1；它验证训练流程，不证明抓取成功率改善，也不是 Piper H 专项微调。JAX 报告活跃内存峰值分别约 16.06 / 52.31 GiB，不能当作整个 GPU 进程峰值或据此证明 5080 能训练。完整摘录与范围见 [AutoDL 上下文记录](../results/autodl-context-20261024.json)。

后续按用户的实机目标分工：AutoDL 承担数据转换、归一化、π0.5 微调和权重导出；fy-5080 承担离线推理及仿真回归；机械臂附近的控制电脑承担相机采集、状态反馈与动作执行。先完成本地推理路径验证，再考虑部署形式。云端训练环境已可用于后续试验，下面的 16GB 限制仍专指本地 RTX 5080。

2026-10-23 核查：本机 RTX 5080 显存为 16,303 MiB，系统内存约 32 GiB。这里准备的是官方公开模型的推理、仿真评测与后续微调入口，不是从头重做两篇论文的大规模预训练。

| 工作 | 本机判断 |
|---|---|
| π0 / π0.5 推理、LIBERO、Piper H 接口开发 | 两种完整模型的 JAX GPU 推理、GPU EGL 全景录像、Panda 基线与 Piper H 抓放已实际运行。Piper H 扩展评测另存结果，不能视为实机标定。每次只运行一个模型服务。 |
| 官方 openpi JAX LoRA | 官方参考要求 >22.5GB；16GB 不满足该参考配置，不能承诺可直接运行。 |
| 官方全参数微调 | 官方参考要求 >70GB，按 80GB 级别 GPU 规划；本机不适合。 |
| 冻结 VLM、仅动作专家、PEFT/量化及 CPU offload 等改造 | 可做低显存研究，需先测 forward/backward/optimizer step 的峰值与速度；不是已验证的 16GB 方案。 |

来源：[OpenPI requirements](https://github.com/Physical-Intelligence/openpi#requirements)、[LeRobot hardware guide](https://huggingface.co/docs/lerobot/hardware_guide)。缩小 batch、梯度累积只能减少部分开销，不能消除权重、梯度与优化器状态的固定开销。

## 当前实现的边界

OpenPI 同时包含 JAX 和 PyTorch；当前 PyTorch 分支没有官方 LoRA/FSDP/混合精度训练支持，训练精度模式为整体 BF16 或 FP32。官方低内存示例 `pi0_libero_low_mem_finetune` 使用 JAX LoRA；当前没有现成同名 π0.5 low_mem 配置。`pi05_libero` 默认 batch=256，不能直接当作本机训练命令。[官方说明](https://github.com/Physical-Intelligence/openpi#pytorch-support)

后续优先研究新版 LeRobot 的 `train_expert_only=true`、`freeze_vision_encoder=true`、`gradient_checkpointing=true` 和 BF16，以及 PEFT。新版 LeRobot 与 OpenPI 固定的旧版 LeRobot 数据依赖必须分环境，不能在已验证的 openpi 环境中直接升级。[π0](https://huggingface.co/docs/lerobot/pi0)、[π0.5](https://huggingface.co/docs/lerobot/pi05)、[PEFT](https://huggingface.co/docs/lerobot/peft_training)

## 本机环境选择

- PyTorch 固定 `2.7.1+cu128`，因为官方说明 CUDA 12.8 构建支持 Blackwell；OpenPI 原始锁默认选择 CUDA 12.6，因此保存了本机的显式依赖覆盖。[PyTorch 2.7](https://pytorch.org/blog/pytorch-2-7/)
- 保留官方 JAX 0.5.3、Flax 0.10.2、transformers 4.53.2；已分别运行 PyTorch BF16 CUDA/卷积与 JAX BF16 JIT 检查，并用 JAX 加载两种完整模型进行推理。
- 项目启动脚本关闭 JAX 显存预分配；这不限制模型运行时的最终显存峰值。[JAX 显存说明](https://docs.jax.dev/en/latest/gpu_memory_allocation.html)
- CPU 检查不加载完整模型；另行 GPU 验收使用完整官方 LIBERO 权重、batch=1、默认 10 步 flow denoising，每个模型各预测两次。结果见 `results/pi0-gpu-inference.json` 和 `results/pi05-gpu-inference.json`。合成输入检查不等于任务成功率或严格延迟基准，记录的 JAX allocator 内存也不等于进程的全部显存峰值。没有训练；微调验收还需实际 backward 和 optimizer step。

## Piper H 微调前必须确定的数据

2026-10-24 的公开数据集调研与两份 Piper 样本实测见 [公开数据调研](public_datasets_piper_20261024.md)。已经找到仿真 Piper 与真实 Piper 示范；尚未确认与用户 Piper H 配置完全一致的公开数据。公开样本核查阶段未训练；后续新建的颜色入盒任务使用自建合成 Piper H 示范进行微调，不能视为这些公开数据或用户实机示范的训练结果。

参见 `piper_h_plan.md`：单/双臂、夹爪、相机；采样频率；joint position/EEF、绝对/增量动作；rad/m/夹爪单位；真实下发 action 与同步 state；按 episode/场景划分训练和验证。LIBERO 的末端增量动作不能直接当 Piper H 关节目标。

先采集并离线检查一条示范，再定义 Piper H 专用 Inputs/Outputs、LeRobot DataConfig 与 TrainConfig，计算本数据集归一化统计量。OpenPI 当前依赖较旧 LeRobot；新数据写入时要按锁定版本核对格式，不能默认新版 v3 数据直接兼容。

在有足够显存的机器上，官方 π0 LIBERO LoRA 的入口为 `repos/openpi/scripts/train.py pi0_libero_low_mem_finetune`，前置步骤是 `scripts/compute_norm_stats.py --config-name pi0_libero_low_mem_finetune`。这只是 LIBERO 示例，不是已经完成的 Piper H 训练配置；该命令属于原 LIBERO 准备记录；新任务有独立的 `tasks/piper_color_v1/train_task.py` 配置与数据。

## 复用本地基础权重

本次准备的基础权重路径分别是 `checkpoints/pi0_base/params` 和 `checkpoints/pi05_base/params`，完整校验结果见 `results/checkpoints-status.json`。它们用于初始化微调；直接运行 LIBERO 评测时使用 `pi0_libero` / `pi05_libero`，不能把基础模型当作已适配任务的策略。

OpenPI 自带训练配置默认指向 `gs://...`。后续启动训练时，π0 配置使用 `--weight-loader.params-path /home/fanyuan/projects/kaiwen-learning/pi-reproduction/checkpoints/pi0_base/params`，π0.5 使用相应 `pi05_base/params` 路径，从而复用本地已校验文件。此命令行参数已通过官方训练 CLI 的帮助入口核对，见 `results/pi0-lora-training-help.txt`；没有执行训练。

训练输出可指定 `--checkpoint-base-dir /home/fanyuan/projects/kaiwen-learning/pi-reproduction/results/training-checkpoints`，避免与下载的原始权重混放。数据归一化产物与训练使用相同的 `assets_base_dir`；所有 Python 入口仍通过 `scripts/run.sh openpi`，并在本项目目录启动。新任务的相机和动作约定、数据与资源验证完成后，再确定实际训练参数。

最新 π0.7 / π*0.6 的公开资料状态见 `latest_pi.md`。本页的 5080 显存判断针对现有公开 π0 / π0.5，不能外推为 π0.7 已能本地运行。

## 论文复现口径

π0（所附 v4，§IV–V）使用约 3.3B 参数模型及大规模自有机器人数据；π0.5（所附 v1，§IV）还包含离散动作预训练、多源数据和高低层联合训练。公开 OpenPI checkpoint 的任务微调与评测可复现部分公开流程；自有数据与全部家庭实验不在本次准备范围。公开版本的具体配置以固定 commit 为准，例如当前 `pi05_libero` 的 `discrete_state_input=False`，不能仅依据论文概述推定所有 checkpoint 配置相同。
