# 2026-08-07 数据集管理页并入本地数据 + 磁盘铁律

## 1. 数据集管理页 (DatasetModule) 全管本地训练数据 (老倪: "控制台应该全管")

- **表格 = 本地训练数据集 (HF 云端条目已全删, DATASETS 空列表)**: `_populate_table` 用
  `self._local_datasets() + self.DATASETS`。本地行在最前, 缓存列恒 "✅ 本地" (绿)。
- **`_local_datasets()` 探测**: 固定候选目录列表, 目录存在才入表; 帧数/eps 从
  `meta/info.json` (total_frames/total_episodes) 或 `train.npz` (`len(d["observations"])`, eps="npz") 探测。
  每行带 `local_root` / `local_npz` / `local: True` 字段。
- **显示原则 (老倪多轮纠正, 08-07 晚)**:
  - **名称列两行命名 (最终版)**: `📁 光模块插拔\npeg-insert-side-v3` — 上行中文名 / 下行**官方任务名**。
    `_local_datasets` cands 结构 `(dir, 中文名, 官方名, tag, robot)` → `name = f"📁 {cn}\n{official}"`,
    行高 60 够两行。官方名是 metaworld 任务名 (peg-insert-side-v3 / nut-on-peg), 本地目录名
    (metaworld_act/peg_lerobot) 只是磁盘代号, 官方仓库 GitHub Farama-Foundation/MetaWorld policies/
    只有官方名 (老倪连问 "哪有 metaworld_act" 三次 — 目录名 vs 官方名要区分讲清)。
  - **任务数列 = "—"**: 本地是单一任务演示集, 不填帧数 (曾误填 4800/696, 老倪 "为什么显示任务数4800个");
    帧数/eps 在描述列。
  - **机器人列真实名称**: Sawyer (metaworld) / Orin (真机) — 不填 "metaworld"。
  - **一个机器人/一套数据只一行**: orin 的 4 个子目录 (orin_live/orin_real_v1/orin_archive/closed_loop)
    合并 1 行 (老倪 "就一个orin不都一样么")。
  - **orin 行 local_root 指向 orin_real_v1 (真机视频出图)**: 老倪 "加载帧没有啊" 后明确 —
    他要图像帧; orin_live 是 json 采集包 (文本, 之前指向它被嫌没图)。真机视频 64×64×21 帧低清,
    查看器平滑缩放 (Qt.SmoothTransformation) 改善。最终 3 行: peg_lerobot + metaworld_act + orin_real_v1。
  - **下载按钮语义 (老倪: "orin应该在cicd.html下载")**: 本地 orin 行 → 按钮 "📥 CICD" 点击
    `QDesktopServices.openUrl(QUrl("https://datadrive.world/cicd.html"))` (网页采集下载, 不走 HF);
    本地 metaworld 行 → "本地" 禁用 (无需下载); HF 云端行才走 `_mk_download_func` (HF 下载)。
    ⚠️ connect 只在分支里挂一次 — 旧的兜底 connect 行要删, 否则本地行同时触发网页+HF下载报错。
- **orin 数据格式知识 (cicd.html 上传的数据在哪)**:
  - `data/orin_live/` = **114 个 json 采集包** (auto_*.json, meta: source=orin/relay=ECS/frames 150/n_joint 6/n_action 6) —
    CICD 链路 Orin 采集 → ECS 中转 → 拉回本地。查看器 `_load_json_package()` 显示包 meta + 帧 state/action 文本
    (无图像, 纯状态数据)。
  - `data/orin_archive/` = **3124 个产线状态快照** (snap_*.json 工序状态: 料盘识别/取料/尝试插入/插入完成 + jpg)。
  - `data/orin_real_v1/` = 真机 v1 lerobot 格式 (parquet + 视频 mp4 64×64×21帧, 早期低清)。
  - 采集包帧字段: `frames[i]["observation.state"]` (6D 关节) / `frames[i]["action"]` (6D)。
- **查看按钮通用化**: `_on_view_dataset` 不再特判 repo_id, 直接读 `ds.get("local_root")` /
  `ds.get("local_npz")` → DatasetViewer(local_root=, local_npz=) + `viewer.show()` 非模态。
- **信息按钮本地分支**: `_show_dataset_info` 里 `ds.get("local")` → 不查 HF API (local:// 会 404),
  直接 `_msg_ok` 显示路径/类型/状态。
- **📌 当前训练数据集卡片** (顶部, 绿框): `_current_dataset_html()` 从**最近 mtime 的
  config_*.yaml** 的 root 字段探测 (即最近训练用的数据) + 类型判定 (路径含 "peg" = 光模块绿标,
  否则 nut-on-peg 套环黄标) + 帧数/eps/state 维。🔄 按钮刷新。
- **坑**: config 的 root 行是**缩进的** (`  root: data/...`) — regex 必须 `^\s*root:\s*(data/\S+)`
  (漏 `\s*` 会探测失败回退兜底路径, 显示旧数据)。
- **坑**: HF 条目 `_is_cached` 查本地数据要**递归 glob** (`data/**/*.parquet` recursive=True) —
  parquet 在 chunk-000/ 子目录, 非递归匹配不到 → 缓存列错显 "—" (老倪 "缓存也没显示有")。

## 2. 磁盘铁律 (老倪: "你得保护好自己，当前磁盘空间，绝对不允许增加")

- **smolvla 系列 checkpoint 巨大**: 每 ckpt ~1.4G (模型+优化器状态), 4000 步训练保存 ~25 个
  (每 ~160 步存一个) = **35G/模型**! smolvla_lew_ft 37G + smolvla_ft 35G 实测爆盘 (133G/14%)。
- **训练后必清**: 每目录只留最后 ckpt + 重建 `last` 软链:
  ```bash
  ck=outputs/train/<dir>/checkpoints; last=$(ls $ck | grep -E '^[0-9]+$' | sort -n | tail -1)
  for c in $(ls $ck | grep -E '^[0-9]+$'); do [ "$c" != "$last" ] && rm -rf "$ck/$c"; done
  rm -f "$ck/last"; ln -s "$last" "$ck/last"
  ```
  rollout 加载 glob 最新 ckpt → 只留最后不影响推理。清理后磁盘 133G→39G。
- **训练开始前先预算磁盘**: 大模型 (smolvla/lew) 长训练 (4000 步) = 25 个 ckpt; 训练完立即清,
  不要在训练链里累积多个模型再清。
- **临时产物即时删**: /tmp 的 rollout 测试帧、预览 PNG、diag 目录 (占 / 分区)。

## 3. 控制台关闭/重启 (老倪 "先关掉控制台" / "再启动")

- **kill -9 跳过 closeEvent**: studio.py 的 closeEvent 会 pkill lerobot_train + cicd_pipeline —
  若只是关 GUI 保训练 (后台训练链是独立 bash 进程), 用 `kill -9 <GUI_PID>` (不触发 closeEvent,
  不杀训练)。正常 pkill 会连带杀 lerobot_train。
- 启动: `cd tools/gui && ZMAX_AUTO_RUN=1 DISPLAY=:0 bash run_studio.sh` (auto_run 自动回 simulink 页)。
- 无训练进程时 auto_run 不触发训练 (ZMAX_AUTO_TRAIN=1 才训练) — 重启安全。

## 4. 数据统一光模块终态 (老倪: "simulink 的数据，应该是光模块数据" → 全链路只留光模块)

- **simulink 画布数据源 = 光模块**: 模板全部 `"📦 metaworld_peg_lerobot 数据"` (replace_all,
  25 处含节点名/连线/引导文案) + `_ensure_training_data` 的 placeholder 改
  `data/metaworld_peg_lerobot` (原 `metaworld_act` 硬编码)。desc 帧数 696→4800,
  日志文案同步 (data/metaworld_act 不存在 → peg_lerobot)。
- **metaworld_act (套环) 数据删除 + 引用全清**: `rm -rf data/metaworld_act` 后必须清代码引用:
  数据集管理 cands、simulink 功能块数据集组 (`_dset_cands`)、数据源切换候选
  (`_show_source_info` cands)、`_current_dataset_html` 兜底路径、`_on_view_dataset` 的
  metaworld_mt50 特判 (local_npz)、closed_loop json 采集统计 (1510 行)、orin 候选。
  **验证**: `grep -rn "metaworld_act" tools/gui/` 应只剩注释。
- **data/ 清理终态 (老倪 "没用的都删掉" + 手动删 orin/closed_loop 后检查)**: 只剩
  `metaworld_peg_lerobot` (光模块训练) + `yolo_peg_full` (YOLO 检测数据)。删除原则:
  旧版本目录 (peg_v2~v7/joint/cartesian)、中间产物 (mt50 原始 parquet——act 已转 npz、
  npz→lerobot 后的源 npz)、无图像旧数据全删; 训练中目录不碰。
- **数据集管理终态 1 行**: 本地行只剩 `📁 光模块插拔\npeg-insert-side-v3` (两行命名)。
- **⚠️ 大段删除纪律 (execute_code 截断事故)**: 用 Python 字符串索引 (`src.index/meta_item+src[i+len(seg):]`)
  删大段时索引错位会**静默截断文件** (studio.py 8057 行 → 1266 行, 丢 TrainingModule 等全部)。
  恢复 = `git checkout tools/gui/studio.py` (HEAD 含当天大部分改动) + **重新应用 HEAD 之后的
  patch** (本会话 8 处: _is_cached 分支/_on_view_dataset 非模态/当前数据集卡片/_local_datasets/
  DataSpaceModule/modules dict/首页卡片/DATASETS 删减)。大段删除**只用 patch 工具** (精确 old_string),
  或 execute_code 但**先备份 + 写后立即 wc -l/ast.parse 校验行数与语法**。
- **GUI 启动崩溃自查**: 手动 patch 误删创建行 (manual_btn) → 启动 NameError → 先跑
  `python3 -c "import ast; ast.parse(open('studio.py').read())"` + offscreen 构造 StudioMainWindow 再交付。

## 5. 数据集管理页实现速查 (本 ref 全文结构)

- 表格 = `_local_datasets() + DATASETS` (DATASETS 已空); 本地行缓存列恒 "✅ 本地"。
- 两行命名 cands 结构 `(dir, 中文名, 官方名, tag, robot)`; 任务数列 "—"; 机器人列真实名。
- 下载按钮: orin→CICD 网页 / 本地→禁用 / HF→_mk_download_func; connect 只挂一次。
- orin 数据: orin_live=json 采集包 (relay=ECS) / orin_archive=产线快照 / orin_real_v1=低清视频。
- 📌 当前训练数据集卡片: 最近 config root 探测 (`^\s*root:` 带缩进)。
