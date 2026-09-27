# 工位机系统体检 / 清理报告

- 时间：2026-09-28 06:41（本机显示；机器 NTP 有已知偏移，真实约 00:41）
- 主机：Ubuntu 24.04.4 LTS · 内核 6.17.0-14 · nproc 32 · 已运行 23h51m · load 1.00
- 触发：用户「清理本地系统，清缓存，清理DNS，检查磁盘，保证运行效率」

## ① 自检表

| 项 | 值 | 判读 |
|---|---|---|
| systemctl --failed | **0 loaded units listed** | ✓ 无失败单元 |
| 内存 | 31G 总 / 14.9G 用 / **16.9G 可用** | ✓ 充裕 |
| swap | 15G 用 45MiB · swappiness 10 | ✓ |
| 磁盘 | nvme0n1p5 396G · 已用 284G · **可用 92G (76%)** | ✓ 黄灯以内 |
| NTP | synchronized: yes · service active | ✓ |
| CPU governor | powersave（**实测三组 A/B 无差异 ⇒ 不动**，见技能 §6） | 保持 |
| GPU | RTX 4060 8G · util **0%** · mem 674MiB · persistence **Enabled** | ⚠ 空转（见⑥） |
| 在役服务 | zmax-tunnel-proxy ✓ · zmax-tunnel-lhr ✓ · zmax-dds-ss ✓ · docker ✓ · cron ✓ | ✓ |

## ② DNS 清理

`resolvectl flush-caches` 已执行。flush 后逐域解析（冷态）：

| 域 | 耗时 |
|---|---|
| open.feishu.cn | 7ms |
| github.com | 7ms |
| www.baidu.com | 26ms |
| pypi.org | 171ms |
| hf-mirror.com | **806ms** |

⇒ 长尾仍是 `hf-mirror`（806ms）与 `pypi`（171ms），与上次记录一致；整体解析无异常。
（口径：这是 flush 后的冷态数字，不代表清理带来的加速。）

## ③ 清理明细（只清可再生项）

| 项 | 前 | 后 | 释放 |
|---|---|---|---|
| journal | 294.3M | 193.5M | **→ 封顶 200M** |
| 轮转日志 /var/log/*.1 *.gz | 466.9M | 297.6M | 169M |
| crash 转储 | 6.6M | 0 | 6.6M |
| apt 缓存 | 123.5M | 122.7M | 0.8M |
| 用户缓存（mesa/chromium snap 等） | ~3.5M | 0 | 3.5M |
| **合计** | | | **≈ 280MB** |

⇒ **系统本来就干净**：没有可观的缓存堆积。清理前 285G → 清理后 284G。

## ④ 性能项（技能里实测有效的 4 条，全部核过）

1. GPU persistence：**Disabled → Enabled** ✓（本轮唯一实质性变更）
2. fstrim.timer：enabled / active ✓
3. journal：已封顶 200M ✓
4. CPU governor：**保持 powersave 不动**（本机 3 组交错 A/B 全在噪声内，改了是表演性设置）

## ⑤ 保护清单复核

| 路径 | 状态 |
|---|---|
| /home/ubuntu/zmax_rel (1.3G) · zmax_train (7.2G) · lerobot-smolvla-lew (36G) | ✓ 全在 |
| /home/ubuntu/.hermes (7.9G) · zmax_data (5.0G) · .cache/huggingface (9.5G) | ✓ 全在 |
| HF 在役权重 model.safetensors | 1 个 ✓ |
| HF 断链扫描 find -xtype l | **0 个** ✓ |

## ⑥ 磁盘大头（未动，等指示）

| 路径 | 大小 | 说明 |
|---|---|---|
| **stable-wm-cache/** | **151G** | datasets 137G + checkpoints 14G |
| └ datasets/**cube_single_expert.h5** | **95G** | 单个文件，metaworld cube 专家数据 |
| └ datasets/l5_gen_v4.h5 · optical_insert_v5_disturb.h5 · l5_gen_v6.h5 · v6_train_rand.h5 等 | 42G | 各版本训练集 |
| INTACT-JEPA | 11G | 仓库 |
| hermes-portable.tar.gz · hermes-backup-2026-09-26.zip | 1.5G | 备份件（**只列不删**） |
| docker ros:humble-ros-base | 1.19G | 未被容器使用（可重新 pull） |

**引用情况**：`stable-wm-cache` 被 `INTACT-JEPA/config/train/*.yaml` 引用 ⇒ **属在用数据，本轮未动**。
95G 的 `cube_single_expert.h5` 是否为当前训练所需，需要确认（不是我能单方判断的）。

## ⑦ 两个发现（需处理）

1. **GPU 完全空转**：`utilization 0%`，且无任何训练进程（`train=0` / `joint_train=0`）。
   与「训练不要停 / GPU 不许空转」的既定要求冲突 ⇒ 需决定是否拉起训练。
2. **`cam_live_stream.py` 吃满一个核**：100% CPU · 107 线程 · 已跑 9h02m。
   这是当前运行效率上最大的一笔，且可能与手臂画面偏慢相关 ⇒ 建议排查（未动在役服务）。

## ⑧ 台账

- 清理台账：`reports/sys_cleanup_20260928_064130.json`
- 本轮脚本：`/tmp/sys_check_readonly.sh`（只读体检）· `/tmp/sys_clean_full.sh`（清理）
