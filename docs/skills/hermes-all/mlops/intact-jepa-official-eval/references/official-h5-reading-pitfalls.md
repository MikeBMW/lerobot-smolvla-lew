# 读官方数据集 h5 的五个真坑 (2026-09-18, 直跑时一条条暴露)

同一个 `data_source.py` 在读官方 4 域数据时连续抛了 5 个错。每一个都**不是**"环境没配好",
而是 h5 布局假设写错了 —— 五个都在 v5.6.28 直跑里被逐个打掉, 记下来省得下次重踩。

| # | 症状 | 真因 | 修法 |
|---|---|---|---|
| 1 | `ValueError: The truth value of an array with more than one element is ambiguous` | `str(ep) in grp` 在 h5py 上返回**数组**而不是 bool | 先取键列表再判断: `_keys = list(grp.keys())` |
| 2 | `AttributeError: 'Dataset' object has no attribute 'keys'` | 同一个键在不同数据集里可能是 **Dataset**(整块) 也可能是 **Group**(每 episode 一个 dataset) —— 换成按 Episode 写的实现后必踩 | 两分支都写: 有 `keys()` 走 Group, 否则整块索引 |
| 3 | 读出来的形状全错 / 被压成 1 维 | 官方大数据是**扁平存储**: `pixels(N,224,224,3)` + `ep_offset`/`ep_len`, **不是** per-episode group | 按 `grp[ep_offset[ep] : +ep_len[ep]]` 切片 |
| 4 | 存在性判断"明明有却走错分支" | `"ep_offset" in f.keys()` **会失效** (同一类问题: h5py 的 `in` 不保证给 bool) | `{"ep_offset","ep_len"} <= set(f.keys())` |
| 5 | 喂编码器报 `expected 4 (channels), got 1` | 键选择器 `next(k for k in f if "obs" in k or "pixels" in k)` **先匹配到 `observation`**(28 维状态向量), 被当图像送进 ViT | 优先级写死: **先 pixel 后 obs** |

配套两个环境点:
- 读像素前 **`import hdf5plugin`** —— 官方数据用插件式压缩, 否则 `OSError: can't open directory (/usr/local/lib/plugin)`。
- **两个 venv 都要装**: 外部项目 venv 一份 + GUI venv 一份 (GUI venv 没有 `pip`, 用
  `uv pip install --python gui-venv311/bin/python hdf5plugin`)。

实测的 cube 数据布局 (供对照, 别照抄到别的域):
```
pixels       (2010000, 224, 224, 3) uint8
action       (2010000, 5)
observation  (2010000, 28)
ep_idx / ep_len / ep_offset   ← 扁平索引三件套
```
`reacher` 的官方 eval 期望路径是 `datasets/dmc/reacher_random.h5` (不是 `datasets/reacher/reacher.h5`) ——
解压后要建 `datasets/dmc/` 并对齐文件名, 否则 `FileNotFoundError` 看起来像"数据没下"。
