# D57 放置与执行准备

本次已经把 fy-5080 的选定 π 项目文件迁入 D57，原机保留原件。主工作区为 `/root/autodl-tmp/robot-repro/pi-reproduction`；Git 远端为用户指定的 π 专用仓库。本次没有新训练、评测或实机动作。

## 已放在 D57 的内容

| 内容 | 本地位置 / 处理 |
|---|---|
| 适配、训练、评测源码与原始文档 | 本仓库 scripts、tasks、models、docs |
| 固定的上游源码与机器人资源快照 | repos；来源 commit 见 publication/upstream-provenance.json |
| 原始评测、视频与失败记录 | results；既有 Git 归档仍可恢复 |
| 合成示范与已展开 NPY | results/piper-color-v1/dataset-v1；原 120/15/30 划分 |
| 原数据 tar | results/piper-color-v1/dataset-v1.tar |
| LoRA / 全参本地参数备份 | results/piper-color-v1/cloud-recovery-20261024/checkpoints |
| 官方 π0 / π0.5 基础权重 | 复用 /root/autodl-tmp/robot-repro/assets/openpi-assets/checkpoints 中已校验的两套权重；本仓库 checkpoints 下有链接 |

LoRA 参数备份对应 1499，可作为后续推理/分析的输入，未在本轮重新加载；不含优化器。全参 1000 只有部分文件，本轮按原样保留并发布，不尝试补齐或宣称能够续训。

## 环境选择

```bash
# π0 模型环境
source /root/autodl-tmp/robot-repro/pi0/activate.sh

# π0.5 模型环境
source /root/autodl-tmp/robot-repro/pi05/activate.sh

# Piper H SDK / 轻量客户端
source /root/autodl-tmp/robot-repro/piper-h/activate.sh
```

每次只选择需要的环境，再进入本仓库。当前模型环境固定为 Python 3.11.18、Torch/TorchVision CUDA 12.8、JAX 0.5.3；完整声明与锁保存于 deployment/d57。

原 `scripts/run.sh` 使用 fy-5080 的 Conda 路径；原 `tasks/piper_color_v1/run_cloud.sh` 使用已经退出使用的云端路径。它们保留用于追溯，不能在 D57 直接照抄启动整条旧 pipeline。正式执行前，按要运行的任务绑定下面的现有数据和参数路径，并为新 run 单独指定输出目录。

颜色任务已有环境变量接口：`PIPER_OPENPI`、`PIPER_COLOR_DATA`、`PIPER_COLOR_RUN`、`PIPER_BASE_PARAMS`。真实位置记录在 deployment/d57/paths.json；新输出放在 outputs 下，历史 results 不覆盖。

## 尚需按后续任务准备的部分

- **LIBERO 评测**：单独重建与原锁一致的仿真环境（原 robosuite 1.4.1、MuJoCo 3.2.3），不要改模型环境的 MuJoCo。原锁与源码已经保存。
- **官方 LIBERO 权重**：fy-5080 原机保留 pi0_libero / pi05_libero；本轮不重复上传约 23 GiB 的官方权重，也未搬入 D57。需要重评时按 results 中的官方 GCS manifests 获取并校验。
- **训练**：本轮只迁入数据和现有参数。LoRA 旧 optimizer 未取回，全参备份不全；新的训练策略和预算应依据下一次指令确定。
- **实机**：Piper H 固件、CAN、双相机与动作/观测映射按硬件事实继续对齐。仿真结果不等于已经完成真机部署。

## 归档与复用

Git 保留代码、配置、紧凑结果和索引。2026-10-25 的 source/results 分卷继续复用；本轮新增训练数据、参数备份和补充资料置于新的 GitHub Release，详见 ARTIFACT_INDEX.json。

完整的已安装环境、下载缓存、原官方权重不再复制为 GitHub 资产；已有版本锁、补丁和官方权重清单提供重建入口。私钥和认证配置留在原机私有位置。临时服务器间传输密钥已移除。
