# HDF5 数据集可用性验证 (真解码) — 2026-09-12

配套脚本: `scripts/verify_h5_dataset.py <file.h5>` (结构树 + 真解码抽帧 + 分集一致性, rc=0 才算可用)。

## 为什么需要 (核心教训)

**解压成功 ≠ 可读；小块元数据能读 ≠ 整个文件可读。**

h5 里不同 dataset 的压缩滤镜可以不同。INTACT `tworoom.h5` 实测 (h5py 3.16.0 / hdf5 2.0.0):
- `pixels` (920809, 224, 224, 3) → **blosc 滤镜 id 32001** → 读帧时才炸
- `action` / `proprio` / `ep_len` / `ep_offset` → 无滤镜 → 读得动

所以"我读了几个字段, 没问题"是**假阳性**。必须抽真实帧解码。

## blosc 坑与正解

症状:
```
OSError: Can't synchronously read data (can't find plugin. Check either HDF5_VOL_CONNECTOR,
HDF5_PLUGIN_PATH, default location, or path set by H5PLxxx functions)
# 或
OSError: Can't synchronously read data (can't open directory (/usr/local/lib/plugin))
```

试过无效的做法: `HDF5_PLUGIN_PATH=/空目录`、`HDF5_PLUGIN_PATH=` (清空) → 错误变成 can't find plugin, 仍读不出。

**正解**: 在任何读操作之前 `import hdf5plugin` (h5py 3.16 不自动注册插件)。该包已在 INTACT venv
`/home/ubuntu/INTACT-JEPA/.venv` 里; 缺则 `pip install hdf5plugin`。

查某个 dataset 用什么滤镜:
```python
import h5py
d = f['pixels']; pl = d.id.get_create_plist()
[(pl.get_filter(i)[:1], pl.get_filter(i)[3]) for i in range(pl.get_nfilters())]
# → [(32001, b'blosc')]
```

## 抽检清单 (每个下载/解压出来的 h5 都跑)

1. 结构: dataset 名 / shape / dtype / chunks / filters 打一遍。
2. 真解码 3 帧 (0, N//3, N-1): 图像 `std > 5` 才算真图 (全黑/全白=假数据, 项目老红线); `np.isfinite().all()`。
3. 末帧 `action=nan` **属正常** (末帧无后继动作, 评测 valid-start 过滤会剔掉) — 不要报成损坏。
4. 分集一致性: `np.diff(ep_offset) == ep_len[:-1]` 且 `ep_offset[-1] + ep_len[-1] == 总帧数`。
5. 有现成评测/训练结论时, 用参考日志里的真实量交叉验证数据真被读了 (例如 tworoom eval 日志
   `670809 valid starting points found for evaluation.` + `success_rate 81.0`) — 空壳结果要当场识破。

## 归档下载/解压的配套纪律 (tworoom 3.1GB / cube 46GB 实测)

- aria2c: `-x16 -s16 -k1M -c --file-allocation=none --max-tries=0 --retry-wait=10`, 可反复续传。
- 下完 **size + sha256 双核校验**, 通过才解压 (`tar --zstd -xf` / `zstd -d -T0`)。
- 解压成功后立刻删归档回收磁盘 (46GB 级归档不删会把盘打满)。
- 解压目标路径与评测配置期望的路径不一致时, 用**符号链接**接别名 (如 `dmc/reacher_random.h5 -> ../reacher.h5`), 不要复制 GB 级文件。
