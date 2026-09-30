---
name: dataset-archive-provisioning
description: Use when 大归档(.zst)未解压致下游FileNotFoundError或需回收磁盘。
---

# 大归档供应 (下载 → 校验 → 解压 → 验证 → 安全回收)

## 触发
- 下游加载数据集/权时报 `FileNotFoundError: ... unable to open file: name = '.../xxx.h5'` (errno=2)
- 数据集"已下载"但训练/评测找不到文件
- 磁盘吃紧, 需回收大归档 (.zst / .tar.zst / 冗余 .h5), 老倪问"清了多少 / 有没有达标"
- 下载看门狗每几分钟报"卡住, 重新续传"

## 第一原则: 下载完成 ≠ 可用
落盘的归档只是**字节在盘上**。解压/转换那一步常常属于**另一条流水线**(自动接力脚本 / autopilot / 看门狗),
一旦流水线已结束、机器中途关机重启、或看门狗只管续传不管解压 → **永远没人解压**,
下游第一条语句就 FileNotFoundError。

所以**看到 FileNotFoundError 先别怀疑代码**, 先做"目标目录 vs 压缩包在哪"的对照。

## 诊断顺序 (实测有效)
```bash
ls -l <目标目录>                                   # 目标产物在不在? 字节数多少?
find ~ -maxdepth 5 -name '*.zst' -size +1G         # 压缩包落在哪个临时目录
zstd -t <file>.zst                                 # 完整性校验; 会打印头部声明的"解压后字节数"
tar -tvf <file>.tar.zst | head -20                 # tar 包列内容(能列完 = 流完整), 看里面到底是什么
```
`zstd -t` 输出形如 `xxx.zst: 46300921856 bytes` = 单帧有效 + 解压后大小; 用这个数当天花板去核对方。

## 解压 (先 .partial 再改名)
```bash
zstd -d -T0 -c src.zst > dst.partial && mv dst.partial dst
```
- **必须先写 `.partial` 再 mv**: 否则解压到一半被下游读到 = 半截文件被当成好数据 (比报错更糟)
- `-T0` = 全核, 40G+ 归档几分钟量级
- 解压前算磁盘: 头部声明大小 + 现有占用 是否越过红线 (默认口径 used ≤ 300G, 见 `~/.hermes/scripts/disk_redline.sh`)

## 验证解压产物 (h5 为例)
```python
import hdf5plugin, h5py     # ★ hdf5plugin 必须最先导入!
f = h5py.File(p, 'r'); print(list(f.keys()))
print(f['ep_offset'][-1] + f['ep_len'][-1], f['pixels'].shape[0])   # 相等 = 索引自洽 / 尾部完整
last = f['pixels'][f['pixels'].shape[0]-1]
print(last.mean(), last.std())                                       # std>5 才算真图 (老倪红线)
```
三个判据缺一不可: **keys 齐全** + **逐回合索引自洽** + **末帧可读且 std>5**。
只读 keys/形状是读元数据, 不算验证数据本体。

## 证明"修好了"
不要只回"文件存在了"。**用真实下游命令复跑一遍**, rc=0 且指标与历史记录一致才算硬证据:
```bash
bash ~/l4_ab/run_paper_direct.sh pusht recovery_delta_full_pusht_s3072 42 100   # → rc=0, success_rate 77.0 (与 09-12 一致)
```
且复跑输出落到**新文件**(如 `output.filename=...recheck_<date>.txt`), 不要覆盖旧证据 (eval.py 是 append 模式, 但混在一个文件里会让你分不清哪次是哪次)。

## 安全回收 (verify-before-delete, 两道门 + 留档)
删大归档前:
1. **下游可用物门**: 确认替代物在且字节数正确 (例: `pusht_expert_train.h5` == 46300921856 B == zstd 头部声明值)
2. **归档完整性门**: `zstd -t` 通过 (确认不是自己删了个半截包)
3. **留档**: 追加 sha256 + size + **来源 URL** + 「被什么替代 / 为什么不需要」到证据日志
   (本次: `/home/ubuntu/l4_ab/intact_results/released_archives.log`) → 删除变成**可重下**, 不是不可逆
4. **删后核账**: `df -h /` + `used_gb <= 300` 打印达标结论

一键门禁脚本: `scripts/clean_redundant_archives.sh` (改路径即用; 本环境长内联命令会被硬拦, 用 write_file 写脚本再 `bash` 跑)

## 坑
- **稀疏文件**: `du -sh` 与 `du -sh --apparent-size` **两个都要看**。中断/半成品副本常见 apparent 23G / 实占 9G;
  只看 apparent 会虚报回收量, 只看 du 会看不出"其实还有一份 23G 的完整副本"
- **同名的两份归档**: 先 `stat -c '%i %h %s %n'` 比 inode 和硬链接数。`link=1` 且 inode 不同 = 两份**独立数据**,
  不是硬链接 → 删一份前先确认哪份完整 (`zstd -t` / `tar -tvf` 各验一次)
- **.aria2 残留 + 看门狗误报**: 文件已 100% 下完但 aria2 控制文件没清 → 看门狗判定"没增长 = 卡住", 每几分钟"重启续传"。
  判据: 大小不再增长 + `zstd -t` 通过 = 已完成, 该清的是 `.aria2`(和误报逻辑), 不是重下
- **归档里的东西不一定被用到**: tar 内可能是另一版本数据集 (例: 98.9G reacher.h5), 而实际评测跑的
  是别的小文件 (`datasets/dmc/reacher_random.h5`)。删前用「结果 JSON + 评测日志里的实际加载路径」确认,
  不要凭名字推断"肯定用过"
- **只删归档不删证据**: 结果 json / SUMMARY / 报告 / 清单 (`zmax_datasets.json`) / demo 视频一律保留;
  要删的是"已解压/已落库/本次流程不需要"的归档
- **阈值口径要与用户同步**: 红线值改了要**同时**改 SKILL 记录、`~/.hermes/scripts/disk_redline.sh` 的
  比较数与 echo 字符串 (三处), 否则告警口径不一致

## 参考
- `references/intact-lewm-archives.md` — INTACT (lewm-pusht / lewm-reacher) 实测案例: 字节数、来源 URL、
  sha256、FileNotFoundError 原文、看门狗误报时间线
- 相关(用户自有, 不要自动改): `disk-redline-guard`、`hf-weight-download`
