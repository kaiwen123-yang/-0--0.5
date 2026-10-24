# Piper H 颜色入盒任务 v1

使用官方 Piper H / 松灵夹爪几何，红绿蓝三块同形 35 mm 方块，按英文颜色指令抓取一块并放入灰色盒子。当前是仿真专项微调，尚无用户实机示范，尚未验证实机部署效果。旧 LIBERO 末端增量策略与本任务的关节目标策略不可互换。

## 数据、训练和验收

- MuJoCo 3.2.3；20 Hz 控制、2 ms 物理步。6 关节目标单位 rad，夹爪总开口单位 m，默认最大 0.10 m。
- 脚本 IK 教师使用物体真值，只负责生成示范。抓取靠双指碰撞与摩擦，不焊接、不传送物体。第一次开发预检查遇到路径不可达、抓取过浅，修改工作空间路径和夹持深度后冻结版本。
- 冻结版本 12 次预检查全部通过；正式 165 条示范全部通过。训练 40 布局×3 颜色＝120 条，验证 5×3＝15 条，测试 10×3＝30 条。按布局整体划分，无训练/验证/测试布局重叠。
- 数据保存动作下发前的 state / RGB，与真正下发的目标 action 配对，不能把下一帧反馈当作下发指令。保存每流时间戳；合成数据不声称是实机采集。
- 策略输入仅外部 RGB、腕部 RGB、7 维反馈和语言。没有物体坐标、阶段标签、目标位置信息。RGB 224×224；实机更大画面由 OpenPI resize-with-pad 转换，不能沿用 LIBERO 的图像翻转。
- π0.5 基础权重，horizon=10，执行前 5 步后重规划；关节使用相对于当前反馈的增量训练，输出还原为绝对关节目标；夹爪保持绝对开口。没有 ALOHA 符号或夹爪角度转换。
- 基础模型在验证集作对照；LoRA 和全参数初轮均 1500 步、batch=4、seed=42，训练集单独计算归一化。LoRA 使用官方 freeze filter，并不等价于只更新很小的 LoRA 矩阵。记录实际可训练参数量和显存。
- 成功要求指定颜色位于盒内、其他颜色不在盒内、夹爪打开、其他物体平移小于 25 mm、关节超限小于 0.01 rad，并保持 2 秒。学习策略评测没有脚本补救。每次保留 1280×720、20 FPS 全景视频。仿真在推理时暂停，推理时延另存，不能称已通过实机实时性验证。
- 根据验证集成功率选择候选，测试集只作独立报告。场景随机化仍有限、同一布局的三次颜色试验相关，不据此声称通用性或实机成功率。

## 本地复运行

从 `/home/fanyuan/projects/kaiwen-learning/pi-reproduction`：

```bash
scripts/run.sh libero tasks/piper_color_v1/generate.py --preflight --output results/color-new-preflight
scripts/run.sh libero tasks/piper_color_v1/generate.py --record --output results/color-new-data
scripts/run.sh libero tasks/piper_color_v1/dataset.py results/color-new-data
```

不运行真实机械臂 SDK 示例。`sim.py` 不导入 CAN / SDK。

## AutoDL

代码 `/root/autodl-tmp/piper-color-v1/source`；成果 `/root/autodl-fs/pi05/piper-color-v1`。复用原有 OpenPI 环境、权重，不改旧训练任务；仅通过独立 `sim_deps` 覆盖 MuJoCo 3.2.3。`run_cloud.sh` 持锁顺序运行，异常退出记录 FAILED；每阶段最多 3 小时。没有关机/重启命令。

结果入口 `index.html`、`summary.json`、`summary.csv`；`logs/status` 当前阶段；`lora_metrics.jsonl` / `full_metrics.jsonl` 每步损失；`deployment/` 只导出推理参数和归一化，不包含优化器状态。`deployment/manifest.json` 明确记录仿真来源和未完成的实机验证。

## 实机衔接

用户配置已记录在 `hardware.json`：Piper H 单臂、官方夹爪、DaBai DC1＋官方腕部支架、外部 D435i。序列号、实际 CAN、固件、内参、外参尚未读取，不填造数值。虚拟相机安装不是实机标定。

DaBai DC1 有[官方 Astra ROS2 launch](https://github.com/orbbec/ros2_astra_camera/blob/master/astra_camera/launch/dabai_dc1.launch.xml)，默认 RGB 640×480@30。不能仅凭 Orbbec 品牌使用 SDK v2：其[当前支持列表](https://github.com/orbbec/OrbbecSDK_v2)没有明确列出 DC1，[型号讨论](https://github.com/orbbec/OrbbecSDK_v2/issues/51)也指出这一差异。型号/序列号通过实物枚举核对，不硬编码不一致的 RGB PID，不更新相机固件。

D435i 使用[官方 librealsense](https://github.com/realsenseai/librealsense)。两个相机先用 RGB 输入；深度可单独记录，但不会自动成为 π0.5 输入。不声称跨相机硬同步。`deployment_io.observation` 检查时间戳和 RGB 数据格式；`sdk_command_proposal` 生成官方 SDK rad/m 单位调用建议，默认不发送动作。

加载导出包的推理服务：

```bash
# 在已安装固定 OpenPI 的 Python 环境，服务器只监听本机。
python serve.py --export /绝对路径/deployment --port 8002
```

服务不打开 CAN、不使能电机。实际控制电脑可用 OpenPI WebSocket 客户端送入 RGB/关节反馈，先记录预测与人工示范做离线对照。实机阶段需要核验关节零位/正负号/开口与实际相机视角，并采集同一任务、三个颜色和多种位置的实机示范后继续微调。训练脚本和归一化接口已统一，后续应为实机数据建立新的布局/日期隔离拆分，不能把合成测试通过当作实机验收。

本地 RTX 5080 用于推理与仿真回归；本轮微调在 96GB AutoDL 进行。此任务不构成 16GB 显存微调可用性的证明。
