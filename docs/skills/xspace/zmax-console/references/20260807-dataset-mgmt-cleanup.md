# 数据集管理整改实录 (2026-08-07)

老倪一轮轮要求的数据集管理 (studio.py DatasetModule) 整改, 终态规范:

## 显示规范 (每行两行命名)
- **名称列 = 两行**: `📁 {中文名}\n{官方任务名}` (QTableWidgetItem 支持 \n, 行高 60 够) — 老倪: "命名两行, 上面是中文名/下面是官方任务名"
  - 例: `📁 光模块插拔` / `peg-insert-side-v3`; `📁 套环` / `nut-on-peg`
- **任务数列 = "—"**: 本地数据集是**单一任务演示集**, 没有"任务数"概念 — 之前误填帧数 (4800/696) 被老倪抓 "为什么显示 4800 个" → 改 "—", 帧数/演示数放描述列
- **机器人列 = 真实机器人**: metaworld 数据 = `Sawyer (metaworld)` (不是 "metaworld"); Orin = `Orin (真机)`
- **描述列**: `中文名 (官方名) · N 帧 · eps` — 光看名称不知道是啥 → 中文描述放最前
- **eps 解释 (老倪反复问)**: eps = episodes = 演示次数 (一次完整操作轨迹); 帧 = 总图像张数

## 下载按钮语义 (老倪: orin 真机下载不对, 应该在 datadrive.world/cicd.html 下载)
- **本地行** (is_local): 下载按钮**不走 HF**:
  - tag 含 "orin" → 按钮 `📥 CICD` → `QDesktopServices.openUrl(QUrl("https://datadrive.world/cicd.html"))` (真机数据网页采集下载)
  - 其他本地 (metaworld) → `本地` 按钮 setEnabled(False) (无需下载)
- **HF 云端行** 才走 `_mk_download_func`
- ⚠️ 改按钮逻辑时**别留旧 `dl_btn.clicked.connect(self._mk_download_func(ds))` 在 styleSheet 之后** — 本地行会同时触发 openUrl + HF 下载 (报 "缺少 huggingface_hub 库" 错误)。本会话误删了 manual_btn 创建行 → GUI 启动 NameError (manual_btn not defined), 补回 + 删重复 connect 两处一起做, 然后 offscreen 完整构造 StudioMainWindow 验证

## 数据集清理原则 (老倪: 数据集里没用的都删掉)
- **data/ 只留训练用数据**: 本会话终态只剩 `metaworld_peg_lerobot` (光模块训练) + `yolo_peg_full` (YOLO 检测数据) — metaworld_act (套环)/metaworld_mt50 (原始 parquet)/metaworld_peg_v2-v7 (旧版+中间产物)/orin 系列/closed_loop 全删
- **删除 = 目录 + 代码引用一起清**: 数据源候选 (_dset_cands)、训练 placeholder (_ensure_training_data 的 `placeholder = os.path.join(root, "data", ...)`)、数据源切换候选 (cands dict)、采集包统计 (glob closed_loop)、查看器特判 (_on_view_dataset 的 mt50 local_npz)、日志文案 — grep 全部引用逐处清, 验证脚本断言 `grep -c "name"` 无活跃引用
- **曲线 ckpt 引用判断保留**: outputs/train 清理时先读 train_curve_*.json 的 ckpt 字段 (假路径 *_latest 会兜底 glob 最新 → 保留 mtime 最新的 ft 目录, 删 v7/restore 过时目录)
- 磁盘铁律下清理是减少: 删 13 目录释放 ~6G (39G→33G)

## 老倪 "删掉X" 指令处理铁律 (本会话两次理解错)
- "YOLO 3D, 删掉检测" → 我理解成删 YOLO 3D 检测节点 + 误删背景行大字 → 老倪连纠正三次: "背景字删掉" → "就是删掉 检测两个字" → "别删多了"
- **铁律: 老倪说"删掉X"先确认 X 的最小粒度** — 是删名字里的字 / 删背景字 / 删节点 / 删功能? 先 grep 确认 X 出现的所有上下文再动手; 删错了立刻 git 恢复 (simulink_module.py 背景行大字从 git show HEAD 提取还原)
- 数据集管理删行同理: 老倪说 "MetaWorld MT50 重复了删掉" = 删 HF 云端行 (本地 metaworld_act 已覆盖套环); "local://orin_real_v1 无效, 删掉" = 删 orin 行

## simulink 数据源统一光模块 (老倪: simulink 的数据应该是光模块数据)
- `replace_all "📦 metaworld_act 数据" → "📦 metaworld_peg_lerobot 数据"` (simulink_module.py 25 处: LIBRARY/模板/布局/引导步)
- `"frames": 696 → 4800` (8 处模板) + desc 文本 `(696帧 → (4800帧`
- `placeholder = os.path.join(root, "data", "metaworld_peg_lerobot")` (训练数据源)
- 验证: 画布数据源含 peg_lerobot 且无 metaworld_act + placeholder 指向光模块
