# π0 / π0.5：Piper H 仿真、微调与复现资料

本仓库汇集保存在 **fy-5080** 上的 π 系列既有工作，并以 **AutoDL D57** 作为后续执行位置。2026-10-31 的发布在原源码/结果归档基础上，加入此前未上传的训练示范、本地参数备份和补充资料。原机文件保留，本轮没有重训、重评或实机动作。

**发布状态：源码与索引已就绪；新增 Release 资产上传中，尚未公开。**

主索引：[ARTIFACT_INDEX.json](ARTIFACT_INDEX.json)。原 2026-10-25 归档记录 [ARCHIVE_STATUS.json](ARCHIVE_STATUS.json) 保留原义，仅描述当时的源码、结果和视频范围。

## 已有结果

| 工作 | π0 | π0.5 | 范围 |
|---|---:|---:|---|
| 官方 LIBERO / Panda pilot | 183/200（91.5%） | 196/200（98.0%） | 每任务 5 个初态，不是官方默认 50 次规模 |
| Piper H 扩展迁移仿真 | 32/75（42.7%） | 47/75（62.7%） | 更换机器人与适配条件，不能与上一行当作同一基准 |
| Piper H 颜色入盒 LoRA | — | 完整任务验证 0/15 | 1500 updates；抬起物体不计为入盒、松爪与稳定成功 |

颜色任务使用 MuJoCo 合成示范 165 条、44,220 帧，按布局划分 train / validation / test = 120 / 15 / 30。教师示范全部完成任务，不代表学习策略成功率。全参数训练日志到 update 1456 后中断，未完成最终评测。

- [LIBERO 汇总](results/libero-comparison-20261023-212017/summary.json)
- [Piper H 迁移汇总](results/piper-h-expanded-20261024/summary.json)
- [颜色任务原恢复记录](results/piper-color-v1/cloud-recovery-20261024/recovery-status.json)
- [原项目说明](docs/PROJECT_README.md)

## 参数备份的实际状态

- **LoRA 1499**：本地保留完整的推理参数和归一化/检查点元数据，参数组 13 个文件、6,335,864,568 字节。没有 optimizer / train_state；本轮未重新加载模型。
- **全参数 1000**：本地仅有 13 个文件、2,908,019,867 字节，属于残缺备份，不能作为可恢复训练的完整检查点。旧云端 inventory 记载的完整目录不等于本地已经取回。
- 两类现存文件均原样保留并纳入新 Release，不补零、不伪造缺失分片，不宣称已经恢复训练。

## 文件如何保存

| 内容 | 位置 |
|---|---|
| 适配、训练、评测代码，配置、紧凑结果 | 本仓库 scripts、tasks、models、docs、results |
| 原完整工作源码、上游资源、历史日志/轨迹/视频 | 原 archives 中 130 个分卷，保留原提交历史 |
| 新增示范与展开数组、参数备份、补充文件 | [fy5080-pi-artifacts-20261031 Release](https://github.com/kaiwen123-yang/-0--0.5/releases/tag/fy5080-pi-artifacts-20261031) |
| 逐文件来源与纳入范围 | [source inventory](publication/fy5080-source-inventory.json)、[新增成员清单](publication/fy5080-release-members.json) |
| 新分卷的大小与 SHA256 | publication/fy5080-release-assets.json；Release 中的 SHA256SUMS / package-manifest.json |
| 上游固定 commit 与许可证 | [来源记录](publication/upstream-provenance.json)、third_party_licenses |

本次从 fy-5080 选定 6,131 个文件、27,197,616,706 字节。与原 archive manifest 按路径和大小对照，5,083 个文件复用原归档，新增 1,048 个文件。新增资料形成 **29 个数据分卷**；加上清单、校验文件与许可说明，共 **33 个 Release 资产**，14,585,786,322 字节。

原 130 分卷沿用当时的文件数/大小验证记录，不将其改称 SHA256 认证。新增 Release 分卷按实际生成内容计算 SHA256，并与 GitHub 资产的 size / digest 核对。

## 在目标服务器恢复完整资料

在目标机器克隆仓库，并把历史资料恢复到独立目录，避免覆盖当前 README 和 D57 配置：

```bash
git clone https://github.com/kaiwen123-yang/-0--0.5.git pi-reproduction
cd pi-reproduction
mkdir -p restored/fy-5080
cat archives/source.tar.gz.part-* | tar -xz -C restored/fy-5080
cat archives/results.tar.gz.part-* | tar -xz -C restored/fy-5080

gh release download fy5080-pi-artifacts-20261031 \
  --repo kaiwen123-yang/-0--0.5 \
  --dir releases/fy5080-pi-artifacts-20261031

(cd releases/fy5080-pi-artifacts-20261031 && sha256sum -c SHA256SUMS)
for group in dataset checkpoints supplement; do
  cat releases/fy5080-pi-artifacts-20261031/fy5080-${group}.tar.gz.part-* \
    | tar -xz -C restored/fy-5080
done
```

源代码和结果已直接保存在 D57，本次没有在用户电脑下载或另行建立大文件归档。

## D57 上的后续安排

工作区：`/root/autodl-tmp/robot-repro/pi-reproduction`。

已迁入代码、固定上游资源、历史结果、示范和参数备份。两套官方 base 权重复用 D57 已校验的本地文件，π0 / π0.5 / Piper H 客户端继续使用各自隔离环境。详细位置、可复用部分与尚待准备的仿真环境见 [AUTODL_D57.md](docs/AUTODL_D57.md) 和 [paths.json](deployment/d57/paths.json)。

官方 pi0_libero / pi05_libero 权重仍在 fy-5080，必要时按保留的 GCS manifests 获取到 D57；本轮未重复镜像这两份官方权重。原 run.sh / run_cloud.sh 含旧机器路径，正式执行前按所选任务绑定 D57 路径；历史 results 不覆盖。

安装缓存、完整已安装环境、官方可重新下载的原始权重、Git 对象库、SSH 私钥和认证配置不作为新的 Release 数据上传。环境锁、补丁、官方权重来源及校验清单均保留。第三方源码、模型和数据继续受其原有许可约束，本仓库不为缺少上游许可的资源重新授予许可。
