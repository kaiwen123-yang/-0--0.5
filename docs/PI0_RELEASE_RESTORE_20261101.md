# π 数据完整备份与恢复

Release：`pi-complete-backup-20261101`，仓库 `kaiwen123-yang/-0--0.5`。本页随执行更新；**实际完成与清理状态以 [恢复索引](../publication/pi-complete-backup-20261101/index.json) 的 `phase`、`source_deleted` 及每组验证记录为准**。开始执行时尚未删除源数据。

用户已明确授权：补齐 π 系列尚未备份的数据，完整上传 GitHub Release，核对大小和 SHA256，确认可恢复后删除对应服务器数据；其他项目不动。既有“只保留基础权重来源”的默认规则在这次完整恢复副本请求内由当前指令取代，两套官方基础权重也纳入备份，并附原许可与来源说明。认证信息、已安装环境二进制和其他项目不发布。

## 备份的含义

新 Release 保存各轮 π0 完整模型/优化器检查点、冻结 v2 数据、原始评测数组与视频、运行记录、其他尚未提交的 π 结果和两套官方基础权重。已经由 `fy5080-pi-artifacts-20261031` 覆盖的历史数据/参数按准确分卷引用复用，不重复上传；它们同样需要重新下载并逐文件验证。Git 已提交的源码和紧凑结果继续由仓库保留。

每个新归档是标准 `tar.zst`，按不超过 **512 MiB** 切为有序分卷，低于 GitHub 的单资产上限。每组可以单独恢复。`backup-catalog.json` 记录每个文件的相对路径、大小、SHA256、权限、时间戳、符号链接目标，以及对应 Release/tag/分卷顺序。新归档分卷的摘要另见 Release 中 `SHA256SUMS`。

验证包含四层：

1. GitHub asset 的 state、size、SHA256 与服务器归档逐一一致。
2. 从 GitHub **重新下载所有分卷**，再次核对大小和 SHA256。
3. 在独立目录完整解包，所有选定原文件逐一匹配源快照 SHA256，检查路径、数量及链接。
4. 对新任务起点 B，实际加载回下载恢复的模型与完整优化器，核对累计计数 **4020**、优化器计数 **[4020,4020]** 和 RNG；不执行训练更新或新评测。

所有组完成后才发布最终 Release 并把可信索引推到 GitHub。随后再次核对源文件未变，并仅删除明确白名单内、已经完成上述验证的原始数据。源码、Git 历史、恢复脚本、现有 pi0/pi05 隔离环境及运行工具保留。旧 π0.5 全参数 1000 原本残缺、LoRA 1499 原本无 optimizer 的事实不因备份改变，不能声称它们成为完整可续训状态。

## 恢复前准备

使用本任务分支 `codex/pi0-b-coverage-correction-test-20261101` 的最新提交。D57 保留的仓库路径是 `/root/autodl-tmp/robot-repro/pi-reproduction`。

需要已认证 `gh`、Python 和 `zstandard`。D57 的 `/root/miniconda3/bin/python` 已具备 `zstandard`，可直接使用；新机器若缺依赖，在独立工具环境中安装，不修改其他研究项目环境。恢复程序会核对已提交索引中的 catalog SHA256、远端 asset 摘要、下载文件和解包后的所有文件。

下面的 `PI_RESTORE_ROOT` 是**工作区根目录**，不是仓库目录。恢复后会得到 `PI_RESTORE_ROOT/pi-reproduction/outputs/...` 和 `PI_RESTORE_ROOT/assets/openpi-assets/checkpoints/...`。

## 只恢复下一合并任务所需的数据

原数据盘扩容后恢复到原路径：

```bash
cd /root/autodl-tmp/robot-repro/pi-reproduction
git pull --ff-only origin codex/pi0-b-coverage-correction-test-20261101
gh auth status
PI_RESTORE_ROOT=/root/autodl-tmp/robot-repro
PI_RESTORE_CACHE=/root/autodl-tmp/pi-restore-download-20261101
/root/miniconda3/bin/python scripts/pi_release_backup.py restore \
  --minimal-b --workspace-root "$PI_RESTORE_ROOT" --cache "$PI_RESTORE_CACHE"
```

最小集合包括 B 最终完整检查点、A/B 非检查点记录、v2 冻结训练数据与场景/评测记录、固定观测诊断参考、官方 pi0_base。每组下载缓存验证/解包后自动清除分卷，避免同时保留整库压缩副本；不会覆盖内容不同的已有文件。

最小集合的检查点是：

```text
pi-reproduction/outputs/pi0-ab-old2010-20261101/B/checkpoints/pi0_piper_color_lora/ab_old2010/2010
```

目录名 `2010` 是上一轮局部步数；恢复后的 `resume.json` 必须是累计 `optimizer_updates=4020`。恢复成功会产生 `PI_RESTORE_ROOT/pi-restoration-receipt-20261101.json`，列出实际 B 路径、v2 数据路径、pi0_base 路径和每组文件校验结果。

## 恢复到另一个扩容盘

将上面两个变量换成已确认属于 π 项目的新卷路径，例如：

```bash
PI_RESTORE_ROOT=/已确认的新卷/pi-workspace
PI_RESTORE_CACHE=/已确认的新卷/pi-restore-download
/root/miniconda3/bin/python scripts/pi_release_backup.py restore \
  --minimal-b --workspace-root "$PI_RESTORE_ROOT" --cache "$PI_RESTORE_CACHE"
```

此时不能照抄历史 JSON 中的旧绝对路径。归档中的内部绝对符号链接会重定位到新的工作区根；原文件内容和历史 provenance 保持原样。新对话必须读取恢复回执，把实际 source checkpoint、dataset、scene、norm stats、pi0_base 和新运行输出绑定到新卷；模型环境仍使用保留的 pi0 隔离环境。新入口不可无条件覆盖这些实际路径为旧盘地址。

若需要维持原入口，也可以仅在旧路径确实不存在时，为这几个明确恢复完成的 π 运行目录和 pi0_base 创建指向新卷的符号链接。先核对两端解析后的路径与回执一致，不覆盖现有目录，不移动或链接其他项目。采用哪种绑定都写入新任务的 `restored_paths.json`，不篡改历史来源记录。

## 恢复全部或指定组

省略 `--minimal-b` 和 `--groups` 会恢复 catalog 中的全部数据：

```bash
/root/miniconda3/bin/python scripts/pi_release_backup.py restore \
  --workspace-root "$PI_RESTORE_ROOT" --cache "$PI_RESTORE_CACHE"
```

指定组的例子：

```bash
/root/miniconda3/bin/python scripts/pi_release_backup.py restore \
  --groups ab-b-checkpoint-2010 v2-training-data \
  --workspace-root "$PI_RESTORE_ROOT" --cache "$PI_RESTORE_CACHE"
```

单独恢复检查点不等于具备完整训练环境；执行下一任务优先使用 `--minimal-b`。所有组名、实际原始字节数及所需 tag 以索引和 catalog 为准。需要同时为已恢复文件和正在处理的最大一组分卷预留空间，不要把压缩体积当成解包后的容量。

## 新任务恢复后启动检查

1. 阅读恢复回执和 `experiments/piper-color-v1/pi0-b-coverage-correction-test-20261101/source_anchor.json`，以相对路径核对 B 文件大小/SHA256，确认完整 params/train_state/assets/resume.json 存在。
2. 验证当前 B 的累计步数 4020、旧归一化、冻结 v2 场景及数据摘要；恢复范围缺组时先补齐，不能从基础权重重新初始化冒充恢复。
3. 检查真实 GPU/磁盘，创建新的任务输出，原 A/B 结果保持归档历史。
4. 按合并任务执行覆盖评测、条件纠偏、冻结与一次测试。本备份任务没有启动它们。

备份执行日志与详细删除回执保存在新 Release。恢复程序只从该仓库及 catalog 明确引用的历史 Release 下载，保留可复用已验证文件；完成的模型失败试验不因恢复而重新生成。
