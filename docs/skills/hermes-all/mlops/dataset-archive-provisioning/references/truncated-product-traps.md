# 截断产物陷阱 —— SKILL.md「归档里的东西不一定被用到」那条已被推翻 (2026-09-13)

> ⚠️ **本条覆盖 SKILL.md「坑」小节里那条旧结论**。旧结论说：
> "tar 内可能是另一版本数据集 (例: 98.9G reacher.h5), 而实际评测跑的是别的小文件
> (`datasets/dmc/reacher_random.h5`)。删前用「结果 JSON + 评测日志的实际加载路径」确认。"
> **这条是错的，并且正是它导致了一次真实的错删。** 详见下方案件复盘。

## 案件: reacher 数据集 23.7G 归档被错删

时间线 (全部有文件系统 mtime / 日志为证)：
```
09-12 03:00~03:09  reacher 评测成功 (3 seed: 95/99/97 = 97.00, 与官方 97.0 一致)
                   —— 那次评测日志写的是从 datasets/dmc/reacher_random.h5 读 stats
09-12 21:57 / 22:03  该路径与 datasets/reacher/reacher.h5 被一次**中断的解压**覆盖成残片
                   (两份都是 2,030,042,624 B, mtime 21:57 / 22:03)
09-13 08:10       我据"那是 2G 的小数据集, 归档没被用到"判定 → 删掉 reacher.tar.zst (23.75G) + 那份残片同级副本
09-13 10:21       四任务全量复跑: pusht/cube/tworoom 全过, **reacher 三个 seed 全失败**
09-13 10:30       查出真相并追加更正记录
```

## 真相: 那 2GB 文件是 98.9GB reacher.h5 的截断残片

```
$ python -c "import h5py; h5py.File('/home/ubuntu/stable-wm-cache/datasets/dmc/reacher_random.h5')"
OSError: Unable to synchronously open file
  (truncated file: eof = 2030042624, sblock->base_addr = 0, stored_eof = 98905882624)
```

`stored_eof = 98,905,882,624` —— 正好是 `reacher.tar.zst` 里那个 `reacher.h5` 的大小
(tar 内唯一条目)。也就是说：**归档里那个 98.9G 的 reacher.h5 就是评测要用的数据集本体**，
所谓"小文件 `dmc/reacher_random.h5`"只是它的半截副本（评测 config 的 `dataset_name=dmc/reacher_random`
只是个名字，布局别名 `dmc/reacher_random.h5 → ../reacher.h5` 就是这个意思）。

⇒ 删掉 reacher.tar.zst = 删掉了 reacher 数据集**唯一完整来源**。恢复要重下 23.7G + 解出 98.9G。

## 两种截断报错，怎么认
| 报错 | 出现位置 | 真因 |
|---|---|---|
| `Unable to synchronously open file (truncated file: eof = X, sblock->base_addr = 0, stored_eof = Y)` | `h5py.File(...)` 打开时 | 文件被截断；`Y` 才是应有大小 |
| `Can't synchronously read data (filter returned failure during read)` | 读具体行时 (例 `get_row_data(...)`) | **伪装成 HDF5 filter/插件故障**，实为读到 EOF 之外。不要先去折腾 `HDF5_PLUGIN_PATH` |

## 修订后的规则
1. **删归档前必须打开"替代物本体"验证**：h5py open 成功 + 逐回合索引自洽 + 末帧可读（std>5）。
   `ls -l` 看着合理、名字对、大小像"小数据集" —— 都不算证据。
2. **别用文件大小推断"这是另一个小数据集"**。想看它是什么，打开它，读 superblock 的 stored_eof。
3. **布局别名的目标是"归档里那份原文件"**：reacher 正确布局 = 解到 `datasets/reacher.h5`，
   再 `ln -sfn ../reacher.h5 datasets/dmc/reacher_random.h5`；**不要再复制进 `datasets/reacher/` 子目录**
   （上次就是这样多出一份半截副本，还差点当成"另一个小数据集"）。
4. **判断错了就追加带日期的更正段**到证据日志，不改写历史（本次已追加到 `released_archives.log`）。
5. 恢复链要带安全门：下载 → sha256 → 空间门 → 解压到临时目录 → h5 真实可读性校验 → `mv` 落位 →
   建软链 → 删压缩包 → 复跑。压缩包在产物验证通过前**不要删**。
