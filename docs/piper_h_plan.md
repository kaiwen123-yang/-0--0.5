# Piper H 接入 π0 / π0.5 的准备方案

更新日期：2026-10-24。已知实机型号为 **Piper H**，用户确认使用松灵官方夹爪，并同意先按官方默认 100 mm 行程建模；实机实际行程、固件和实机控制电脑仍待登记。当前沿用单臂；已确认腕部 DaBai DC1＋松灵官方支架，外部拟用 D435i，首个任务为按颜色选择物体入盒。已准备 SDK 并接通 MuJoCo 仿真；没有连接机械臂、配置 CAN、使能电机或修改基础 Conda/共享 ROS 依赖。

## 当前目标：对接 AutoDL，准备实机数据和接口

用户在 2026-10-24 明确后续以 Piper H 实机为目标。AutoDL 已有 96GB RTX PRO 6000，另一个对话的日志确认 π0.5 LoRA 与全参数微调各 20 步、保存、重载和推理均通过；使用的是 16 条 Panda LIBERO 示范。[已读取的云端状态](../results/autodl-context-20261024.json)。本地 150 次仿真结果继续作为接口回归基线；云端的流程验证与本地的抓取成功率分开记录。

下一阶段顺序：

1. 已确定颜色入盒任务和双 RGB 相机：DaBai DC1 腕部、D435i 外部。序列号与安装外参待实物核验，不把虚拟腕部相机视为实机标定结果。
2. 优先定义单臂 6 关节位置＋夹爪目标的实机数据接口，保存实际下发目标、反馈、时间戳与图像。当前 LIBERO 的 7 维末端增量和 Piper 的 7 维关节/夹爪目标含义不同，不能仅凭维度一致复用。若最终选择 EEF 控制，应另行核对型号运动学、坐标系与 TCP。
3. 使用公开 Piper 数据验证字段转换，并准备符合本机相机/动作约定的 Piper H 示范。先核验一条 episode 的读取、时间对齐、归一化和模型输入输出；后续采集与实机动作另按用户阶段推进。公开数据的机器人差异、许可和样本标签见 [数据集调研](public_datasets_piper_20261024.md)。
4. 在 AutoDL 以相同的数据拆分、相机和动作定义比较 π0.5 LoRA 与全参数微调，保留基础模型对照；训练步数与 batch 根据正式数据规模另定，不将 20 步 smoke checkpoint 当作部署候选。
5. 将候选权重取回 fy-5080，先进行离线推理和匹配接口的仿真回放；关节动作策略需要相应仿真执行器，不能直接接现有 OSC 增量评测脚本。再进入实机采集/控制阶段。

随后用户授权直接上传并微调，已建立 fy-5080 到现有 AutoDL 的专用 SSH 通道。新任务独立放在 `/root/autodl-tmp/piper-color-v1/source`，持久结果位于 `/root/autodl-fs/pi05/piper-color-v1`；不改已有 LIBERO 训练任务。用户指定通过 tmux 托管，并允许训练所需期间保持开机。具体任务、接口和复运行见 [颜色入盒任务](../tasks/piper_color_v1/README.md)。尚未访问机械臂或使能电机。

## 当前 v3：150 次扩展仿真

[完整全景对比页](../results/piper-h-expanded-20261024/index.html) · [逐次 CSV](../results/piper-h-expanded-20261024/episodes.csv) · [源码、初态与录像校验](../results/piper-h-expanded-20261024/validation.json)。以下均是官方 LIBERO checkpoint 在 Piper H 模型上的迁移测试，未连接实机、未训练，不能替代标准 Panda 基准。

| 范围 | π0 | π0.5 |
|---|---:|---:|
| Spatial：10 任务 × 5 初态 | 27/50，54.0% | 38/50，76.0% |
| Object：5 任务 × 5 初态 | 5/25，20.0% | 9/25，36.0% |
| 总计 | 32/75，42.7% | 47/75，62.7% |
| 排除适配调试用的 6 个场景 | 26/69，37.7% | 41/69，59.4% |
| 已成功轨迹的独立松爪复检 | 32/32 | 45/47 |

两模型逐场景物体初态、完整机器人初始 qpos/qvel、随机种子相同。新增 69 个场景仅指未用于本轮适配调试，不声称未出现在模型训练数据中。参数在扩展评测前固定；全部 150 次结果保留，每条均有原始全景与三视角录像，共 300 个视频。

上一轮 3 个失败均修复：π0 任务 0 / 状态 0 的碗盘终态水平距离由 3.69 cm 降到 2.52 cm；π0 任务 1 / 状态 1 从没有双指接触变为 64 帧双指接触、成功放盘；π0.5 任务 0 / 状态 1 的距离由 4.09 cm 降到 1.99 cm。三条都通过后续松爪复检，原成功判据未修改。[逐条前后证据](../results/piper-h-expanded-20261024/original-three-regression.json)

修改分两步验证：

1. 利用平行夹爪的 180° 对称性，对策略工具坐标及对应虚拟腕部相机同步旋转；物理第 6 关节 home 从约 +160° 变为 −20°，官方几何与限位不变。只做这一步时，原 6 个场景 π0 为 4/6、π0.5 为 6/6。
2. 将夹爪归一化命令每个物理子步的变化量从 0.1 改为官方 PandaGripper 的 0.01。robosuite 在每个 2 ms 子步调用它，旧配置命令斜坡快了 10 倍；这不代表实机夹爪速度已标定。两项同时采用后，两模型各 6/6，随后冻结用于扩展评测。[阶段记录](../results/piper-v3-development-20261024/summary.json)

当前明确存在的限制：两模型在抽屉、炉台取碗上均为 0/5，Object 成功率也较低；v3 不构成通用适配。π0.5 Spatial 任务 0 / 状态 2、任务 2 / 状态 1 通过原任务判据，但未通过后续稳定放置检查。1 条 π0 Object 任务 1 / 状态 3 出现 0.0115 rad（约 0.66°）软关节限位超调，超过原 0.01 rad 阈值，动力学校验记为未通过，失败轨迹继续纳入统计。视频完整性检查与动力学检查分别报告。

Object 使用地面场景，增加 `OnTheGroundPiperH` 注册，base 高度为 0 m、TCP home 高度为 0.18 m；桌面分别为 0.9 m、1.08 m。两类场景使用同一关节 home、工具映射和夹爪参数，全景相机随地面安装下移 0.9 m。首次 Object 启动缺少注册，在任何策略轨迹开始前退出；原日志保留。Object 清单里沿用的桌面高度标签也已按全部保存的场景 XML 更正，原清单保留。[执行修订](../results/piper-h-expanded-20261024/protocol-amendments.json) · [元数据更正](../results/piper-h-expanded-20261024/metadata-corrections.json)

本轮稳定性检查版本为 `v2_fresh_forward`：恢复终态后重新计算接触，之后固定打开夹爪、微量退让并保持，要求最后 2 秒连续满足任务条件。6 条成功轨迹的恢复瞬间判据与原环境返回值不同，差异单独记录；复检不能将原失败升级为策略成功。代表性视频末尾追加有明确标签的检查阶段，原始 `panorama.mp4` 均保留。

最新配置与复运行（运行会创建新的结果目录，模型依次占用 GPU）：

```bash
cd /home/fanyuan/projects/kaiwen-learning/pi-reproduction
/home/fanyuan/miniconda3/envs/kaiwen-learn/bin/python scripts/run_piper_h_demo.py \
  --models pi0 pi05 --suite libero_spatial --task-ids 0 1 2 3 4 5 6 7 8 9 --trials 5 \
  --adapter-config models/piper_h/adapter_v3b.json
/home/fanyuan/miniconda3/envs/kaiwen-learn/bin/python scripts/run_piper_h_demo.py \
  --models pi0 pi05 --suite libero_object --task-ids 0 1 2 3 4 --trials 5 \
  --adapter-config models/piper_h/adapter_v3b.json
CUDA_VISIBLE_DEVICES='' scripts/run.sh libero scripts/report_piper_h_demo.py --run-dir /绝对路径/新的run目录
CUDA_VISIBLE_DEVICES='' scripts/run.sh libero scripts/check_piper_release.py --run-dir /绝对路径/新的run目录
```

`--adapter-config` 是必要的复现参数；不传时入口保留 v2 默认行为。`models/piper_h/home.json` 是旧 home，v3 home 保存在 `adapter_v3b.json` 中。下方历史重建 / IK 检查命令属于 v2，不应被当作 v3 home 的生成命令。`--resume` 只恢复已有目录中未完成的轨迹，要求参数和执行源码哈希不变；已完成的失败不会重跑。

公开微调数据的可用性、机器人差异、动作映射、样本时间对齐和 5080 显存限制见 [数据调研](public_datasets_piper_20261024.md)。

## 历史：v2 的 Piper H 全景仿真

仿真资产在 `models/piper_h/`，由 `scripts/build_piper_h_mjcf.py` 读取固定 commit 的官方 H 型号 URDF、夹爪 URDF 和装配 Xacro 中的法兰连接生成。保留官方 link 位姿、惯性、关节轴、限位与 STL 几何；本体实际为 6 个转动关节，夹爪是 2 个滑动关节、1 个开合控制量。移除 URDF 中不具有质量的虚拟夹爪驱动 link，使用 `q_right=-q_left` 等式耦合物理手指；默认各指行程 50 mm。未将 Panda 的外观贴到原有七轴结构上。

`scripts/piper_h_sim.py` 在项目进程中注册 `MountedPiperH` 和 `AgileXGripper`，不修改 robosuite 安装目录或 LIBERO 上游源码。机器人固定在桌面 `[-0.46, 0, 0.90] m`。初始关节姿态经带官方关节限位的 IK 求解，TCP 初始位置为 `[-0.20, 0, 1.08] m`，保存在 `models/piper_h/home.json`。重建模型后，需重新运行检查生成相匹配的 home。

检查结果：夹爪开—合—开正常；12 组微运动覆盖笛卡尔位置/姿态的 6 个维度及正负方向，响应方向、有限状态、关节限位、控制时间和局部碰撞检查通过。证据在 `results/piper-h-sim-check/check.json`、`controller.json`。这只是局部仿真验收，不是全工作空间或硬件动力学标定。

上一轮 v2 接口已完成真实策略驱动的抓取与放盘。LIBERO-Spatial 的任务 0、1、2，各取官方初始状态 0、1，π0 **4/6 成功（66.7%）**，π0.5 **5/6 成功（83.3%）**。初始状态 0 用于排查，状态 1 在适配固定后新增；两部分各 3 次，π0 分别 2/3、2/3，π0.5 分别 3/3、2/3。每个模型只计完整扩展测试的一轮，未把消融/重复测试合并扩大样本。范围小、任务相近，不能据此声称完成通用 Piper 适配或复现论文成功率。

失败排查与修正：

- 旧代码使用 SciPy 最短旋转向量，而 OpenPI 官方 LIBERO `_quat2axisangle` 保留不同角度分支；Piper 与 Panda 的 MuJoCo 四元数乘积符号也不同。接近 π 的向下姿态中，等价姿态可能给策略相差约 2π 的状态输入。v2 先选取正 x 四元数半球，再调用官方转换。**此半球约定针对本轮向下抓取，不是任意工具方向的通用解。**
- 初始工具 yaw 从 π/2 改为 0.35 rad，减少与训练手部朝向及腕部视角的偏差，同时给 Piper 第 6 关节保留初始限位余量。重新求解带限位 IK，夹爪开合、静态保持、12 项局部控制方向检查通过；机器人模型、接触参数、checkpoint 和任务判据未改变。
- 首轮旧接口两者各 0/3；只换官方旋转向量转换，π0.5 仍为 0/3；再加入半球统一和 home 偏航，π0 为 2/3、π0.5 为 3/3。后两项同时修改，这组消融不能分别量化它们的贡献。
- 扩展测试剩余失败：π0 任务 0 / 状态 0 双指接触 39 帧、抬升 4.4 cm，但最后距盘心 3.7 cm；π0.5 任务 0 / 状态 1 双指接触 106 帧、抬升 6.2 cm，但距盘心 4.1 cm，均超出原成功判据的 3 cm 水平距离条件。π0 任务 1 / 状态 1 没有双指接触，抬升不足 1 cm。部分轨迹靠近第 6 关节限位，需要后续检查更大工作空间与姿态变化。

Panda 与 Piper 的关节数量不同，因此仿真按名称复制场景中所有非机器人关节的 qpos/qvel，机器人使用 Piper 专属 home；没有直接加载 Panda 的完整状态向量。两个模型逐任务/初始状态的场景哈希、原始状态哈希及种子相同。固定种子并不保证跨进程接触仿真的每一步都逐位相同；本轮不声称统计显著或绝对可重复的单次动作序列。

采用现有官方 LIBERO checkpoint、JAX BF16、10 次 flow 去噪、每 5 步重新推理。Piper 接收世界坐标系 OSC_POSE 末端增量和夹爪标量；输入为 TCP 位置、按上述约定处理的法兰方向旋转向量、夹爪反馈。夹爪反馈乘 0.8，将 100 mm 满开映射到 Panda 训练输入的 80 mm 范围，这是明确记录的迁移假设。动作限制到 [-1,1]，原始动作与实际动作都保存在轨迹中。没有训练、加入脚本抓取动作、传送目标或放宽任务成功条件。

录像新增独立全景相机，不替换策略输入相机：

- `panorama.mp4`：1280×720，整条机械臂、夹爪、桌面和物体；20 FPS 原时间顺序。
- `multiview.mp4`：1280×1008，上方完整全景，下方外部近景、腕部相机与任务说明；20 FPS。
- 每条包含 10 个初始化等待步、策略执行和最后状态；保存完整 `scene.xml`、逐帧 qpos/qvel，以及原始/实际动作 `trajectory.npz`，便于后续重渲染。

[查看最新全部全景/三视角视频与诊断](../results/piper-h-adaptation-20261024/index.html) · [逐次结果](../results/piper-h-adaptation-20261024/episodes.csv) · [校验结果](../results/piper-h-adaptation-20261024/validation.json)。π0 原始运行保存在 `results/piper-h-transfer-20261024-174527`，π0.5 在 `results/piper-h-transfer-20261024-174003`；分别保留运行清单、脚本/模型快照、动作状态、原始视频和日志。原 Panda 的 400 条基线及成功率保持独立。

成功后的验证使用 `scripts/check_piper_release.py`：恢复策略成功时的终态，20 步打开夹爪、15 步微量上移、65 步保持，要求最后 40 步（2 秒）任务条件连续成立且夹爪开口大于 90 mm。本轮全部 9 条成功轨迹通过；汇总器还重建接触，确认最后 2 秒碗与机械臂/夹爪无接触。它只检查已经成功的策略，不更改成功率。`panorama-with-release.mp4` 保留原始策略片段并追加 5 秒检查，附加片段顶部有明确阶段文字；它不是全程由策略生成的视频。`panorama.mp4` 是未经追加的原始策略轨迹。

首轮旧接口运行在 6 条记录落盘后以 SIGTERM/143 终止，逐个校验后重建汇总，详见 [首轮执行记录](../results/piper-h-transfer-20261024-171827/execution-notes.json)。扩展 π0 测试第一次在第 4 条途中收到 SIGTERM；清理了该运行自己的模型服务，并在新目录完整重跑 6 条，最终退出码 0。中断来源未确认，残留输出原样保留、不纳入成功率，详见 [中断记录](../results/piper-h-transfer-20261024-174356/execution-notes.json)。

复运行命令（工作目录 `/home/fanyuan/projects/kaiwen-learning/pi-reproduction`，仍使用项目规定的 Python）：

```bash
scripts/run.sh libero scripts/build_piper_h_mjcf.py
scripts/run.sh libero scripts/piper_h_sim_check.py --render
scripts/run.sh libero scripts/check_piper_h_control.py
# 模型依次运行，两个命令分别创建新目录并输出路径：
/home/fanyuan/miniconda3/envs/kaiwen-learn/bin/python scripts/run_piper_h_demo.py --models pi0 --task-ids 0 1 2 --trials 2
/home/fanyuan/miniconda3/envs/kaiwen-learn/bin/python scripts/run_piper_h_demo.py --models pi05 --task-ids 0 1 2 --trials 2
# 上条命令会输出并记录新的 run 目录；对该目录验收并生成视频页面：
CUDA_VISIBLE_DEVICES='' scripts/run.sh libero scripts/report_piper_h_demo.py --run-dir /绝对路径/新run目录
CUDA_VISIBLE_DEVICES='' scripts/run.sh libero scripts/audit_piper_failures.py --run-dir /绝对路径/新run目录
scripts/run.sh libero scripts/check_piper_release.py --run-dir /绝对路径/新run目录 --render
# 两个目录均完成上述验收后生成并排结果页：
CUDA_VISIBLE_DEVICES='' scripts/run.sh libero scripts/report_piper_adaptation.py \
  --pi0-run /绝对路径/pi0运行目录 --pi05-run /绝对路径/pi05运行目录 \
  --output /绝对路径/新汇总目录
```

**模型边界：**视觉使用官方 STL 形状及中性显示颜色，不复原 DAE 材质；碰撞使用每个 mesh 的凸包。驱动增益、armature、阻尼、摩擦和 TCP 为本次仿真配置，未按用户实机识别；TCP 在夹爪底座坐标系 `[0,0,0.125] m`，腕部相机是虚拟安装位姿。这里没有连接 pyAgxArm、ROS、CAN 或真实夹爪。

当前 SDK 状态：`envs/piper` 已安装 pyAgxArm 1.0.0、python-can 4.6.1，导入检查和依赖一致性检查通过。`ArmModel.PIPER_H` 的值确认为 `piper_h`（SDK 将其定义为字符串常量）。检查入口：`scripts/run.sh piper scripts/piper_smoke.py`；需从本项目目录运行，或传入脚本绝对路径。结果保存在 `results/piper_smoke.json`，依赖快照为 `results/piper_requirements.lock.txt`。该检查不创建机器人实例。

ROS2 状态：仅准备源码，不构建或启动节点。当前系统 ROS 使用 Python 3.10，项目指定解释器为 Python 3.11；其二进制 Python 扩展不能直接混用。后续实机部署需明确 ROS 所在电脑及其独立运行环境，当前 SDK 导入通过不能作为 ROS 节点兼容性已通过的证据。

源码已准备在 `repos/`，锁定记录为 `results/piper_sources.json`：

| 仓库 | 本次 commit |
|---|---|
| pyAgxArm | `d90e234ba8e408cfa964b38aa9120b3131fc9f85` |
| agx_arm_ros（ros2） | `286633e0d2edb038ee3a1047d9feb7f614a1c076` |
| agx_arm_urdf | `680fa925cd00db7e2628563d2edc5540963045de` |

URDF 大包首次传输中断，已用 Git partial clone + sparse checkout 成功下载 `piper_h/`、`agx_gripper/` 及根目录文档；ROS 仓库的模型子模块也准备为同一 commit。Piper H 本体及标准夹爪 Xacro 的 XML 和全部 mesh/include 路径检查通过，见 `results/piper_model_assets.json`。其他型号和 Revo2 灵巧手资源未下载；这不包含物理仿真、Xacro 展开或 ROS 编译验证。两个模型工作副本的 Git 代理仅在各自仓库中设为 `http://127.0.0.1:7897`，供 partial clone 按需取文件，未改变全局 Git 配置。

## 1. 型号与代码来源

| 用途 | 官方来源 | 当前结论 |
|---|---|---|
| Python 驱动 | [pyAgxArm](https://github.com/agilexrobotics/pyAgxArm) | 新版官方 SDK，显式支持 `ArmModel.PIPER_H` / `robot="piper_h"`。 |
| 固件匹配 | [Piper firmware reference](https://github.com/agilexrobotics/pyAgxArm/blob/master/docs/piper/firmware_reference.md) | 按实机固件选择驱动；H 和 X 是不同型号参数。 |
| ROS2 驱动 | [agx_arm_ros / ros2](https://github.com/agilexrobotics/agx_arm_ros/tree/ros2) | 显式支持 `arm_type:=piper_h`，有 Humble/Jazzy 安装说明。 |
| 仿真模型 | [agx_arm_urdf](https://github.com/agilexrobotics/agx_arm_urdf) | 有独立的 `piper_h/` 模型及对应夹爪 Xacro。 |
| 历史 SDK | [piper_sdk](https://github.com/agilexrobotics/piper_sdk) | README 已引导新项目使用 pyAgxArm；历史教程需先核对 SDK/固件版本。 |
| VLA | [OpenPI](https://github.com/Physical-Intelligence/openpi) | 自定义机器人需要数据转换、输入输出映射和训练配置；已有 LIBERO/DROID/ALOHA 示例不等于 Piper H 即插即用。 |

**不能把 Piper、Piper H、Piper X 当作同一个机械臂。** 官方 SDK 中 H 复用 Piper 的固件驱动逻辑，但有独立型号标识；X 还有与固件相关的关节符号处理。驱动复用不证明几何、限位、负载和零位完全相同。仿真应选 H 的模型，核对实物末端和安装方式；本次没有核实用户这台机器的臂展、额定负载、机械版本或标定值。[依据：固件型号表](https://github.com/agilexrobotics/pyAgxArm/blob/master/docs/piper/firmware_reference.md)、[官方模型目录](https://github.com/agilexrobotics/agx_arm_urdf/tree/main/piper_h)。

## 2. 推荐接入方式

```text
Piper H + 相机 → 实机控制电脑（采集、时间对齐、动作执行）
                         ↕ OpenPI client / WebSocket
                fy-5080（π0 / π0.5 policy server）
```

模型推理和机械臂控制可以分进程、分机器；OpenPI 官方提供轻量客户端和远程推理接口。实机侧可先使用 pyAgxArm 直连，需要 ROS 的相机、TF、可视化和录包时再采用 ROS2。ROS2 不是 VLA 推理的必要前提。[OpenPI 远程推理文档](https://github.com/Physical-Intelligence/openpi/blob/main/docs/remote_inference.md)

本项目 Python 命令继续使用 `/home/fanyuan/miniconda3/envs/kaiwen-learn/bin/python`。后续若实机控制电脑采用 ROS2 原生 Python，需单独核对其 ABI 和部署位置；这里没有改变项目解释器，也没有执行官方文档中的系统级 pip/apt 安装命令。

## 3. 后续实机登记与连接检查

- [ ] 登记型号铭牌、序列号、单/双臂、夹爪型号、机械安装方向、固件版本、SDK commit。
- [ ] 登记 USB-CAN 型号、USB 物理路径、CAN 接口名和线路连接。官方 Linux 路线是 SocketCAN，示例速率为 1,000,000 bit/s；具体端口和适配器仍需现场核对。[官方 CAN 文档](https://github.com/agilexrobotics/pyAgxArm/blob/master/docs/can_user.md)
- [ ] 按实机固件匹配驱动：≤ S-V1.8-2 → `default`；S-V1.8-3～7 → `v183`；S-V1.8-8 → `v188`；≥ S-V1.8-9 → `v189`。实施时复核锁定 SDK 的版本表。[固件表](https://github.com/agilexrobotics/pyAgxArm/blob/master/docs/piper/firmware_reference.md)
- [ ] 先记录关节、夹爪和状态反馈的有效性、时间戳、频率和掉帧；再验证动作字段与实物方向。pyAgxArm 关节读数是 `[j1…j6]`，单位 rad；不要把旧 SDK 的整数协议单位直接套进新接口。[Piper API](https://github.com/agilexrobotics/pyAgxArm/blob/master/docs/piper/piper_api.md)
- [ ] 若采用 ROS2，使用 `arm_type:=piper_h` 和实际 `effector_type`。官方驱动启动默认 `auto_enable=true`，反馈验证阶段显式设为 false；RViz 仅显示反馈时设 `follow:=true, control:=false`。这只是启动配置，不能替代检查节点实际发送的命令。常用反馈话题为 `/feedback/joint_states`、`/feedback/gripper_status` 和 `/feedback/arm_status`。[ROS2 参数与接口](https://github.com/agilexrobotics/agx_arm_ros/blob/ros2/README.md)

## 4. 相机、数据与动作约定

下列是本项目建议，尚未作为实机配置验证：单臂先使用一台固定视角 RGB 相机和一台腕部 RGB 相机；相机具体型号不限，但采集到推理都要保持同一视角、颜色顺序和预处理。登记相机序列号、安装位姿、分辨率、帧率、曝光、时间戳来源；若做笛卡尔控制或几何估计，再登记内外参及 TCP 标定。

| 字段 | 建议的首版约定 | 必须验证 |
|---|---|---|
| `state` | 单臂 6 个关节角 rad + 1 个夹爪开度；双臂则明确左右拼接顺序 | 夹爪单位、开合方向、限位和有效反馈 |
| `action` | 与示范一致的关节目标 + 夹爪目标 | 绝对/增量、目标/实测值、控制模式；不能直接把 LIBERO 末端增量写到关节接口 |
| images | 固定视角 + 腕部 RGB，原始数据保留相机标识和时间戳 | 推理时与训练使用同一裁剪/缩放、uint8 RGB 和键名映射 |
| metadata | task/prompt、episode、timestamp、采样率、成功标签、机器人/相机配置版本 | 图像、状态、控制命令时间对齐；训练/验证按 episode 或场景拆分 |

关节目标可由 SDK 的位置接口执行，但 `move_j` 与 `move_js` 的平滑和响应方式不同，不能训练时一种、部署时随意切换另一种。控制频率和每次执行的动作块长度需由实机跟踪误差及推理延迟确定；论文的 50Hz 不应直接成为这台 Piper H 的默认值。[官方动作接口](https://github.com/agilexrobotics/pyAgxArm/blob/master/docs/piper/piper_api.md)

OpenPI 端需要新增 Piper H 的 `Inputs/Outputs` 映射、LeRobot 数据配置和训练配置，重新计算本数据集的归一化统计量。先完成一条示范的离线“采集 → LeRobot → batch → 模型输入/输出”检查，再扩大数据采集和微调。数据标签应保存实际下发目标，并保留反馈用于审计；没有下发目标时要明确说明如何构造 action，不能静默把同一时刻 state 当成 action。[OpenPI 自定义数据流程](https://github.com/Physical-Intelligence/openpi#fine-tuning-base-models-on-your-own-data)

## 5. 仿真到实机的验收顺序

1. **LIBERO 基线**：验证 π0/π0.5 checkpoint、推理与评测链路，保存成功率、种子和配置。它验证基准任务，不代表已经适配 Piper H。
2. **Piper H 仿真适配**：导入官方 H 模型及实际夹爪；补充与所选物理引擎匹配的驱动、碰撞、惯性、接触和相机配置。URDF 可视化正常不等于动力学已验证。
3. **离线实机数据检查**：只读反馈、同步 RGB、重放示范、检查动作单位与范围，记录从图像采样到动作可执行的延迟。
4. **实机跟踪验证**：验证经过限速的关节目标跟踪、夹爪开合以及指令超时后的行为；然后在一个固定桌面任务上验证整条 VLA 链路。执行器限位和动作变化率限制由适配层统一落实。
5. **Piper H 微调与复评**：按一致相机与动作约定采集示范，先做小规模参数高效微调试验；分别报告训练分布内表现、不同摆放/物体/视角表现和失败类型。

尚未验证：用户机械臂的固件、实际控制端的 ROS2 编译与运行兼容性、USB-CAN 与相机是否连接、实机关节/夹爪/动力学与相机标定。Piper H 仿真 v3 已完成上文 150 次迁移评测，π0 为 32/75、π0.5 为 47/75；跨物体、抽屉和炉台场景仍有明显失败，不能视为通用适配或实机能力。当前准备不应被描述为已完成实机控制或已复现论文家庭任务。
