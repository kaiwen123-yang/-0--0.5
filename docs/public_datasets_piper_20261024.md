# Piper H / π0 / π0.5 公开微调数据调研

核查日期：2026-10-24。目标是为当前单臂 Piper H 仿真及后续微调选择数据；本次没有启动训练或连接实机。

**有可用的公开数据，优先考虑 RoboTwin 的 Piper 仿真子集和小规模 Piper 实机示范。尚未在本次核查的来源中找到明确标注“Piper H＋用户同款夹爪与相机”的现成数据集。** Piper、Piper H、AgileX Cobot Magic 不能仅凭品牌或六轴结构视为同一机器人。

## 候选及适用范围

| 数据源 | 已核查内容 | 对当前项目的用途 | 许可与边界 |
|---|---|---|---|
| [Physical Intelligence / LIBERO](https://huggingface.co/datasets/physical-intelligence/libero) | 官方转换的 LeRobot v2.0；1,693 episodes、40 任务；8 维 state、7 维 action，两路图像，元数据 FPS=10 | 最适合先检查现有 OpenPI 数据加载、归一化和训练流程 | CC-BY-4.0；机器人是 Panda。训练它不会自动解决 Piper H 的夹爪、相机和动力学变化 |
| [RoboTwin 2.0 / Piper](https://huggingface.co/datasets/TianxingChen/RoboTwin2.0/tree/main/dataset/stack_bowls_two) | 官方仓库包含 `stack_bowls_two/piper_clean_50.zip`（385,710,961 bytes）和 `piper_randomized_500.zip`（7,288,272,946 bytes），也有其他 Piper 任务 | 优先用于仿真数据路线；可选单任务，再考虑用 H 型号与相机配置重新生成示范 | 数据卡 MIT；当前只核查发布文件及大小，没有解压核验内部条数。不是 Piper H；SAPIEN 数据不能直接作为 MuJoCo OSC 增量动作 |
| [aromanus / openpi_PiPER_demo_train_2](https://huggingface.co/datasets/aromanus/openpi_PiPER_demo_train_2) | 80 episodes、26,990 帧、一个搬运任务；LeRobot v2.1，30 FPS，双臂 14 维 state/action，3 路 640×480 视频 | 小规模真实 Piper 数据，适合先做样本转换与训练入口验证 | Apache-2.0，无访问门槛；没有确认 H 型号，关节/夹爪单位仍需核对采集代码 |
| [Ray0v0 / cl-piper-single-stack-bowls](https://huggingface.co/datasets/Ray0v0/cl-piper-single-stack-bowls) | 500 episodes；LeRobot v2.1、30 FPS、14 维 state/action、4 路 640×480 视频；任务是黄碗叠到绿碗上 | 与当前抓碗任务接近。[作者 ContinualVLA](https://github.com/Agentic-Intelligence-Lab/ContinualVLA) 提供基于 OpenPI 的 π0.5 数据配置和训练代码；另有挂杯、叠毛巾、按按钮数据 | 数据仓库没有 dataset card / LICENSE / license 标签，不能把代码许可证自动套给数据。正式训练使用前需确认数据许可。名称含 single，但存储保留双臂 14 维，不能按名字直接截断 |
| [RoboCOIN / Agilex_Cobot_Magic_close_drawer_upper](https://huggingface.co/datasets/RoboCOIN/Agilex_Cobot_Magic_close_drawer_upper) | 173 episodes、49,994 帧、LeRobot v2.1、30 FPS、3 相机；26 维字段混合左右关节、夹爪及 EEF 位姿，另有统一坐标系 EEF 字段 | 后续扩展接触/抽屉技能的候选，字段说明相对完整 | Apache-2.0；实际机器人标识是 Cobot Magic，不保证是 Piper H。数据卡有全局任务和子任务口径差异，使用时以对应字段和文件为准 |
| [RoboMIND](https://huggingface.co/datasets/x-humanoid-robomind/RoboMIND) | 数据卡介绍 107k 示范、多机器人，含 AgileX 双臂；HDF5 与语言标注；已链接 RoboMIND 2.0 的 ModelScope 发布页 | 多任务预训练或更大规模迁移的候选，当前不是最小起步方案 | 数据卡 Apache-2.0，但 Hugging Face 文件需要登录并接受访问条件。本次未访问受限文件，也未核验 2.0 全量包 |

RoboTwin 官方提供 [LeRobot v2.1/v3.0 转换与自定义采集说明](https://robotwin-platform.github.io/doc/usage/collect-data.html)。默认下载示例采用 Aloha-AgileX，选择 Piper 时应明确指定对应资产/子集；支持某机器人不代表每个任务都适合该机器人。当前不切换现有 MuJoCo 环境或安装 RoboTwin。

## 已实际下载并检查的样本

下载内容仅包括元数据、两份数据各一个 episode 的 Parquet、以及 aromanus episode 0 的三路视频，未下载整个训练集。文件在 `results/public-datasets-20261024/`，锁定了 HF revision，不使用浮动 main 作为检查依据。

| 检查 | aromanus episode 0 | Ray0v0 叠碗 episode 0 |
|---|---:|---:|
| 检查行数 | 548 | 382 |
| state/action 维度 | 14 / 14 | 14 / 14 |
| 空值、重复 episode/frame 键、非有限动作/状态 | 均未发现 | 均未发现 |
| 时间戳 | 单调，约 1/30 秒 | 单调，步长约 0.0316–0.0348 秒 |
| `action[t] == state[t+1]` | 547/547 对完全相同 | 381/381 对完全相同 |
| 视频检查 | 3 路完整解码，逐路 548 帧 | 本次未下载视频 |

这证明**所检查样本的 action 标签是下一帧记录状态**，不证明它记录了真实下发的控制命令。它可以用于“下一关节状态作为目标”的学习，但不能直接解释成 7 维 EEF 增量，也不能在读取时再无意偏移一帧。单条样本不能证明全库质量或全库只使用单臂。

夹爪字段也不能共用现有仿真里的缩放：aromanus 左夹爪样本范围约 0.277–0.872，Ray0v0 约 −0.0018–0.0995，两个数据源尺度明显不同；这里没有仅凭数值猜定单位。Ray0v0 样本右臂为固定状态，需结合全库及任务确认是否可采用单臂配置。

检查代码：[audit_public_robot_data.py](../scripts/audit_public_robot_data.py)；详细证据：[sample-quality.json](../results/public-datasets-20261024/sample-quality.json)。复查命令：

```bash
cd /home/fanyuan/projects/kaiwen-learning/pi-reproduction
CUDA_VISIBLE_DEVICES='' scripts/run.sh openpi scripts/audit_public_robot_data.py
```

## 建议的微调路线

1. **先验证训练数据链路。** 用官方 LIBERO 数据或上述小规模 Piper 样本，完成 episode 划分、时间对齐、图像解码、batch 和归一化检查。LIBERO 元数据 10 FPS 与本次仿真控制 20 Hz 不是同一个概念，不应只改 FPS 标签就当作动作重采样。
2. **明确学习的动作。** 真实 Piper 数据优先建立“6 关节位置＋1 夹爪”专用 Inputs/Outputs 与训练配置；双臂数据若取单臂，应确认另一臂不参与任务，选择对应图像和动作字段。需要 EEF 动作时，先用正确型号运动学、TCP、坐标系和采样间隔转换，不能把关节数值直接放入当前 LIBERO 7 维 action。
3. **按本项目接口准备 Piper H 示范。** 当前阶段更匹配的是同一个 H 模型、同一相机/TCP、同一控制约定的仿真成功示范。公开 Piper 数据可辅助学习，但真实相机与仿真图像、不同机器人几何之间仍有分布差异。当前策略成功录像可作为候选，训练前仍需保存策略输入帧、动作时序、成功检查和数据拆分；不能把所有录像直接当专家数据。
4. **独立划分训练与评测。** 按 episode、摆放/任务划分，不随机拆散相邻帧。现有用于适配调试的场景与新评测场景已分开记录；今后若把评测轨迹加入训练，必须另设新的评测集。
5. **选择基础权重与内存方案。** 真实 Piper 专项训练可从已下载的 `pi0_base` / `pi05_base` 开始；继续 MuJoCo LIBERO 场景实验时可比较 LIBERO 专家权重。公开数据存在不等于本机可直接全参数训练：截至本次核查，[OpenPI 官方参考](https://github.com/Physical-Intelligence/openpi#requirements) 仍为 LoRA >22.5 GB、全参数 >70 GB。本机 RTX 5080 约 16 GB，低显存方案仍需独立测一次 forward/backward/optimizer step；本次未进行该验收。

因此建议先做**一个 Piper H 仿真任务的数据闭环＋小批量训练可行性检查**，再决定使用公开 Piper 数据、生成匹配 H 型号的数据或混合两者。当前 OpenPI 固定版本与新版 LeRobot 的包和格式要求应分别处理，不能升级现有已验证环境来试错。

## 版本与核查边界

| 数据仓库 | 本次 API revision |
|---|---|
| physical-intelligence/libero | `a4336d589d589045d1c56423ffdf3b88a0e19b1f` |
| TianxingChen/RoboTwin2.0 | `3dc3b798668feb99ac61cc9086d84cbcc3d79186` |
| aromanus/openpi_PiPER_demo_train_2 | `e00910709205e98d515844659ef1fe8b4b847fc0` |
| Ray0v0/cl-piper-single-stack-bowls | `f81ff5e07c31053b39e64aa621882d6d17705d52` |
| RoboCOIN/Agilex_Cobot_Magic_close_drawer_upper | `7d09f0d619ca343b78d961e6cd099641fee8c0ba` |

原始 API、公开元数据、RoboTwin 叠碗文件清单、样本与检查结果均保存在上述 results 目录。API `usedStorage` 不等同于当前文件版本的精确下载量，因此未据此规划全量磁盘需求。访问失败的少量样本请求已重试成功；RoboMIND 受限文件没有绕过访问条件。
