# 全息数据空间 + 数据一致性整改 (2026-08-07)

老倪三连需求: ①左侧功能块看不到已有数据集 → ②全局数据空间=数据库对应每个 node (全息信息) → ③数据一致性整改 (数据源字样统一 + YOLO 文字截断)。全部实测落地。

## 全息数据空间 (tools/gui/data_space.py, GlobalDataSpace 类)
- **五类数据对象注册表**: `datasets` (扫描 data/, 光模块/套环/Orin 各带帧数/eps/state_dim/action_dim/ts) · `curves` (reports/train_curve_*.json → points/tail/ts) · `models` (outputs/train/*/checkpoints 最后一步, policy=目录名 rsplit("_",2)[0]) · `rollouts` (reports/rollout_* 帧数) · `reports` (pdf/mp4)。
- **node_objects(node) 映射规则**: 节点名含"数据"/params.source → 数据集; 含"训练/蒸馏/基准" → 曲线+模型; 含"推理/视频/仿真" → rollout (video_policy 过滤); 含"Scope/评估" → 曲线; 含"PDF/报告" → 报告。节点名里没有的语义 (如训练节点的 policy) 从 params 读。
- **consistency()**: 数据集目录缺失 / 模型目录无对应曲线文件 → 问题列表。summary() 返回各注册表计数 + 问题数。
- scan() 有 3s 缓存节流, 刷新用 scan(force=True)。

## GUI 集成
- **左侧功能块数据集组**: LibraryPanel 构建循环后动态探测 data/ 目录 (metaworld_peg_lerobot/peg_v2/act/mt50/closed_loop/orin_*) → 每组一个 QToolButton, 点击 `module.add_node_at_center("data", f"📦 {d} 数据", {source, data_dir, desc})` 拖入画布。功能块 = 模块库, 动态探测目录才能\"同步显示已有数据集\"。
- **数据空间页 (studio.py DataSpaceModule)**: modules dict 加 `"dataspace": 12` + stack.addWidget(DataSpaceModule(self)) (self.simulink 必须先建); 首页 _modules_grid 加卡片 ("dataspace","🌐","全局数据空间")。表格 7 列: 节点/类型/关联对象/属性/时间/状态/路径, 每 node 取 node_objects 前 3 条。刷新按钮 scan(force=True)。
- **数据集管理并入本地训练数据** (_local_datasets): 探测 data/ → 行 dict 加 `local: True, local_root, local_npz`; 表格行数 = local + DATASETS; 本地行缓存列恒 "✅ 本地"; **信息按钮本地分支跳过 HF API** (ds.get("local") 直接 _msg_ok 显示本地信息); 查看按钮 `ds.get("local_root")/ds.get("local_npz")` 通用化 (不再特判 metaworld repo)。
- **当前训练数据集卡片** (_current_dataset_html): 扫描 config_*.yaml 按 mtime 倒序取 `root: data/...` → 探测 info.json/npz → 显示路径+类型(光模块=绿/套环=黄)+帧数。**坑: root 行有 2 空格缩进, 正则必须 `^\s*root:\s*(data/\S+)` (m 标志), 写 `^root:` 匹配不到 → 兜底显示 metaworld_act**。

## npz 查看器 (dataset_viewer.py)
- **系统 python3 (GUI 用) 没有 pandas/pyarrow, 只有 numpy+PIL** → parquet 内嵌图像读不了 (ImportError)。加 `local_npz` 参数 + `_load_npz_frame`: np.load → observations[N] (3,H,W) → transpose→uint8 → QImage → scaled(640,480)。np.load 结果缓存 (self._npz_cache) 防拖动滑块重复读 28MB。
- **翻帧坑**: Frame 滑块 valueChanged 原来只更新数字不加载图 (\"点不了下一帧\") → `_on_frame_changed` 里调 `_load_video_frame()` (内部路由: 无 mp4 有 parquet → parquet/npz 分支)。
- obs 兼容: V3 reset 返回可能 dict 也可能裸数组, `isinstance(obs, dict)` 判断后再取 observation.state/image。

## 节点文本截断修复 (SimNodeItem.paint)
- **根因: `if len(name) > 16: name = name[:15] + \"…\"` 字符数截断** (中文/emoji 下"🎯 YOLO 3D 检测"9pt 只有 106px 但字符判断把名字砍了)。
- 修法: **像素宽度自适应字号** — fontMetrics().horizontalAdvance(name) 与可用宽 (self.w-20) 比较, 9→8→7pt 逐级降, 仍超则 fm.elidedText 兜底。视频节点分支 (左下角 8pt) 与普通节点分支都用 disp。实测: "🎯 YOLO 3D 检测" 9pt 106px ≤ 110px 完整显示; 长名 "🎮 仿真推理 · VLA-Touch" 8pt 129px 在视频节点 (宽 160px, 可用 148px) 内放得下。

## 数据源名统一 (数据一致性)
- 画布数据源节点名 = **实际数据集路径** ("📦 metaworld_act 数据"), 与左侧功能块数据集组 (📦 metaworld_act) 完全一致 — 老倪\"好几个, 不知道你用的是哪个\"。
- replace_all "📦 metaworld 数据" → "📦 metaworld_act 数据" (~20 处: 模板 name + 布局 links + ACT_BUILD_STEPS 引导文本)。**引导文本里的按钮名也要同步改, 否则高亮匹配失败**。
- 训练 config 的 `root:` 字段是数据源唯一真相 (GUI 训练 _ensure_training_data 硬编码 placeholder=data/metaworld_act 是另一个待改点 — 数据源切换节点逻辑应先于 placeholder)。

## _check_newer_ckpt 误触发 → 视频白屏 (2026-08-07 二次)
- 曲线 json 的 ts 字段被写成\"修正时刻\"(当前时间) > 视频帧 mtime → 判定\"新 checkpoint\" → 每次打开视频对话框触发 7 模型重新生成 → 生成中白屏。
- 修复: 曲线 ts 回填真实训练完成时间; 残缺曲线 (<100 点) 不触发重生成 (早前防护); 或重新 rollout 让视频帧更新。
- 教训: **任何重写曲线 json 的操作必须保留/回填真实 ts**, 不能写现在时间。
