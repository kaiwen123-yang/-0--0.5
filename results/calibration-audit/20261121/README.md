# 2026-11-21 Q12 / DC1 标定复核证据

对应 [审计报告](../../../docs/PI_Q12_CALIBRATION_AUDIT_20261121.md)。这是对既有真实结果的离线数值和来源核查；没有重新采图、重跑内参/Park 拟合或执行硬件命令。

## 文件

| 文件 | 内容 |
|---|---|
| [numeric_audit.json](numeric_audit.json) | 格式/参数一致性、真实关节 FK 链重建、旋转激励、基线、逐视角统计、包含切向项的 Brown 中央分支上界。 |
| [geometry_audit.json](geometry_audit.json) | 尺度条件敏感度、外缘基线/长度/像素偏差、图像和距离覆盖边界。其径向诊断的切向限制由 numeric_audit 中完整 Brown 推导补齐。 |
| [provenance_audit.json](provenance_audit.json) | 4正式＋3回溯来源、训练隔离、公开复现材料缺项、u11停止与最后硬件状态。 |
| [recompute_numeric_audit.py](recompute_numeric_audit.py) | 读取已存在源文件的实际算术复算入口，只 AST 读取 SDK 常量，不 import 机器人 SDK。 |

## 固定来源

现场源固定在 [`b3bb539109af287f7963fc750dc2dcb0b0549baa`](https://github.com/kaiwen123-yang/-0--0.5/tree/b3bb539109af287f7963fc750dc2dcb0b0549baa/results/piper-real-single-v1/20261121_q12_01)，分支 `field/pi-single-20261120`。

脚本需要已存在的这些小文件：

- `--session-dir` 下：`candidate_result.json`、`pose_review.json`。
- `--final-dir` 下：`intrinsics.json`、`handeye.json`、`validation.json`、`selection.json`、`Q12_DC1_calibration.yml`、`camera_info.yaml`。
- `--sdk-constants`：本次使用官方 pyAgxArm [`d90e234ba8e408cfa964b38aa9120b3131fc9f85/pyAgxArm/api/constants.py`](https://github.com/agilexrobotics/pyAgxArm/blob/d90e234ba8e408cfa964b38aa9120b3131fc9f85/pyAgxArm/api/constants.py) 的 `ROBOT_MDH_PRESET['piper_h']`。脚本不导入该模块，也不连接 CAN。

脚本专为本次固定数据复算，不是任意新相机/新 SDK 的通用验收器。不要换输入后仍把写入 JSON 的固定来源提交当成新来源。

## 调用方式

在已有 NumPy / PyYAML 环境中，将变量指向实际存在的现场源和 SDK 文件；main 的审计文档并不意味着现场数据目录已经合入 main。

```bash
# 三个变量由真实工作区位置填写，不使用占位路径直接运行。
Q12_SESSION=/absolute/path/to/existing/results/piper-real-single-v1/20261121_q12_01
Q12_SDK_CONSTANTS=/absolute/path/to/existing/pyAgxArm/api/constants.py
Q12_AUDIT_OUT=/absolute/path/to/new/numeric_audit.json

python results/calibration-audit/20261121/recompute_numeric_audit.py \
  --session-dir "$Q12_SESSION" \
  --final-dir "$Q12_SESSION/final_seven" \
  --sdk-constants "$Q12_SDK_CONSTANTS" \
  --output "$Q12_AUDIT_OUT"
```

本次已经对定向读取到的真实源文件执行该脚本，退出码 0；没有新增依赖。文件格式差值和冻结候选差值均为 0；重建固定板矩阵最大差约 `4.09e-15`；合并统计最大差约 `5.55e-17`。包含 p1/p2 后正常中央分支可达接收半径上界 `0.820528592`，原生底角为 `0.843801698` 与 `0.851651875`，均超过上界。

像素 RMS 由已发布逐视角标量汇总，未重新检测全部原图；三维固定板残差则由真实 q、SDK MDH、手眼和逐姿态 PnP 变换重新计算。本次没有运行 OpenCV 像素往返回环或生成逐像素有效掩码。当前证据不能称为完整原始数据重新求解。

几何/来源 JSON 记录的是本次定向审查的结果，完整生成最终七视角/外缘分析的现场脚本与有序角点输入仍需下一轮从本机补发布；不因此要求上传整段原始录像。
