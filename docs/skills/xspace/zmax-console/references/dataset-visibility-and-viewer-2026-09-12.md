# 数据集可见性 + 数据集查看器 (2026-09-12 实测)

老倪原话: "**现在很多数据根本看不到, 全面清理没用的数据**" → "**图片, 下一帧, 点击没有反映, 而且图像上下颠倒了**"。
本文件记录两类修复: ① 让控制台看得见 `$STABLEWM_HOME/datasets` 下的 h5; ② 查看器窗口/翻帧/朝向。

## 1. 数据集管理页原来看不到 stable_wm_cache 的数据

原探测逻辑 (studio.py 数据集管理页):
- `_current_dataset_html()`: 只从仓库根最新 `config_*.yaml` 的 `root: data/...` 探测 → 只认 `<repo>/data/`。
- `_local_datasets()`: `data/{metaworld_peg, metaworld_peg_long, metaworld_peg_far, yolo_peg_full}` 白名单 + `data/` 自动补全 + HF 缓存。

⇒ `$STABLEWM_HOME/datasets/*.h5` (域内 `zmax_insert*.h5` + 官方 `tworoom.h5` / `cube_single_expert.h5`) **一个都看不到**。

**修法 = json 台账 + 只读消费** (gui-venv311 没装 h5py, 不能在 GUI 进程里读 h5):
```
# 台账生成 (外部项目 venv, 有 h5py + hdf5plugin)
HDF5_PLUGIN_PATH=/home/ubuntu/.h5plugins \
/home/ubuntu/INTACT-JEPA/.venv/bin/python tools/zmax_ds_meta.py
# → <cache>/datasets/zmax_datasets.json: 名称/路径/大小/回合/帧/动作维/观测维/帧std/真图判据/用途/时间
```
- 缓存解析顺序随 swm 官方: `$STABLEWM_HOME → $LOCAL_DATASET_DIR → ~/.stable_worldmodel (swm 默认) → ~/stable-wm-cache`。
- 控制台新增卡片 `🧠 INTACT / 域内数据集` 只读该 json + 「🎬 浏览数据集」按钮 (选"正在训练"的那个, 从最新 ckpt 的
  `train_config.yaml` 里 `name:` 反查) + 🔄 重读。
- 官方 `tworoom/cube` 的 pixels 是 blosc 滤波器 (32001) → 读前必须 `import hdf5plugin`。
- 无头验证: `QT_QPA_PLATFORM=offscreen` 里 `DatasetModule()._intact_ds_html()` → 4 个数据集全列出、
  训练中的那个带「⬅ 正在训练」、全部「真图✓」。

## 2. 查看器 (dataset_viewer.py) 三个实测坑

1. **窗口太小 / 底部按钮被裁**: `setFixedSize(1100,700)` 装不下 640×480 图 + 两行滑块 + 两行按钮。
   修: `resize(1180,880)` + `setMinimumSize(980,740)` + `setSizeGripEnabled(True)`;
   图片 `setMinimumSize(520,380)` + `QSizePolicy.Expanding` + `resizeEvent` 里
   `setPixmap(pix.scaled(label.w, label.h, KeepAspectRatio, SmoothTransformation))`。
   自检: `layout().totalMinimumSize() <= size()` (实测 566×744 ≤ 1180×880 = 不裁切)。
2. **点「下一帧」没反应** (两个真根因):
   - 帧滑块上限**写死 300 / 100 (假值)**, 不是该回合真实帧数;
   - `_on_frame_changed` 的触发条件 `if video_files or parquet_files or local_npz` **没有 h5** → 只改数字不重载图。
   修: 上限取 h5 `ep_len[ep]`; 触发条件加 h5; 状态行 `帧 k/N 加载中…` + `QApplication.processEvents()`
   (子进程读帧约 1 秒, 没有即时反馈用户会以为没反应); 帧缓存 `{(ep,frame): (QPixmap, vec)}` ≤64 键;
   `keyPressEvent` 支持 ←/→。
3. **路径是目录不是文件**: 数据源节点右键「查看数据集」传的是 `data/xxx` 目录 → 不能只认"以 .h5 结尾",
   要 `glob(dir/*.h5) + glob(dir/*/*.h5)` 找候选。

## 3. "图像上下颠倒" — 先验数据, 再改显示

诊断法 (客观, 不靠争论): 取数据集首帧 + 引擎自己验证过的演示视频首帧, 归一化灰度 2D 相关:
```
正向 +0.98 · 上下翻 +0.17 · 左右翻 +0.32   ⇒ 数据方向与引擎渲染/视频同向, 没颠倒
```
⇒ 用户看到的"颠倒"来自显示路径或旧数据。同时给查看器加「↕ 上下翻转」按钮 (只改显示不改数据,
`pixmap.transformed(QTransform().scale(1,-1))`, 状态行标「已翻转」) — 一键可切最省事。
验证: 翻转后逐行像素比对 == 翻转前上下颠倒 (atol=2)。

## 4. 跨 venv 读大文件给 GUI 的通用形态

```
tools/h5_frame_reader.py  (外部项目 venv 跑)
  --info        → JSON: episodes / ep_len[] (每回合真实帧数) / action_dim / obs_dim / pixels_shape / attrs meta
  --ep E --frame F --out /tmp/x.png --vec  → 单帧 PNG + action/observation 向量 + frame_std (黑帧判据 >5)
```
GUI 侧 `subprocess.run([<venv>/bin/python, ...])` 取 stdout 末行 JSON + 有界缓存；
同款骨架可复用到任何"GUI 要展示只有外部 venv 才读得动的文件"的场景。注意 GUI 进程**不要** import h5py。

## 5. 数据清理口径 (老倪: "只删明显垃圾")

已删并验证释放 7.2GB: 已合并进 h5 的 `reports/*_partNN.npz` (~7.0G) / 全部 `__pycache__` (300M) /
`/tmp` 旧帧转储 (~400M)。**保留**: reports 视频+json (证据)、data/、outputs/ (含别的会话在写的日志)、
HF 缓存、官方 cube(95G)/tworoom(12G) 数据集 (删了要重下数小时, 且 cube 仍是待评测项)。
清理前务必先 `du -sh` 汇总再动手: **不要 `ls -la` 大目录** (322 个文件的清单会把上下文冲爆)。
