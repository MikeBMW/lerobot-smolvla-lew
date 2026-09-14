# 2026-08-08 Qt QSS 颜色坑 / 视频白屏根治 / 训练状态监视 / 数据透明可控

## 🐛 Qt QSS 8位hex 颜色 = #AARRGGBB (alpha 在开头!)
- QSS 8 位 hex 是 **alpha 在前**（不是 CSS 的 #RRGGBBAA）
- `border:1px solid #00d4aa88` → Qt 解析 alpha=0x00（全透明）→ **边框完全不可见**
- 触发案例: 首页四层分组框, 架构层青色 #00d4aa 恰好首字节 00 → 只有架构层看不到边框
  (其他层颜色首字节非0 → "有边框"但颜色其实错乱——更隐蔽)
- 老倪诊断: "鼠标放上有边框, 默认看不到" = hover 用全色(生效) vs 默认用 8位hex(透明)
- **修法**: QSS 带透明度一律用 `rgba(r,g,b,a)` 或干脆全色 6 位 hex
- 本会话最终态 (老倪两轮校正): ①全色边框太亮不协调 → ②**默认 `border:2px solid rgba(r,g,b,0.40)` (暗淡) + hover `border-color:{gcol}` 变全色点亮**; 标题色条 ▍+组名保持全色 (层级标题仍醒目)。分层分组框 QFrame 用 C_BG 深底 (比卡 C_CARD 浅色深, 深框浅卡对比)——验证: 亮度断言 `lum(C_BG) < lum(C_CARD)` (16 < 35)
- **功能模块卡验证坑**: ModuleCard 无 `title`/`sys_label` 属性 (badge 是 _build 内 QLabel) — 断言用 `card.mid` + `card.findChildren(QLabel)` 找文本, 别访问不存在属性

## 🎬 视频对话框白屏根治 (反复出现 3 次, 根因各异)
1. `_check_newer_ckpt` ts 伪未来 → 每次打开重生成 → **打开先 _play() 显示历史视频, ckpt 更新只改提示文本, 重生成改手动按钮** (simulink_scope.py InferenceVideoDialog)
2. 残缺曲线(<100点) 不算新 ckpt (防中断残留误触发)
3. lab.size()=0 → scaled(0,0) 白屏 → 尺寸有效才缩放
- 原则: **历史视频永远秒开, 新视频用户点按钮才生成**

## ⚙️ 训练状态监视 (老倪: "终端得看到训练状态")
- `_poll_train_state` (SimulinkModule, 挂 _poll_ext_log 每2s):
  pgrep lerobot_train → 最新 outputs/train/*/checkpoints 数字目录最大步数
  → config_{name}.yaml 的 steps 总步数 → `⚙ 训练中: <dir> · 步 N/M (P%)`
- 外部训练 (飞书端/其他会话启动, stdout 走 pipe) 也能显示 (只看 ckpt 目录+config)
- 去重: `_last_train_state` 变化才 log; 结束提示 "✅ 训练完成"
- 老倪要"详细信息": 步数/总步数/百分比; loss 只在曲线 json 比训练目录新时附上

## 📁 数据透明 + 训练结果可控 (老倪: "所有数据透明, 完全可控")
- `_local_datasets` 白名单 cands 后**自动补全 data/ 全部目录** (未列出的也显示,
  name="📁 <dir>\n(data/)") — 数据集管理完全透明
- DatasetModule 加 **训练结果区** (outputs/train 列表: 名字/步数/大小/时间 + 🗑 删除,
  训练中 pgrep 检测禁删) — `_refresh_train_results` / `_delete_train_dir`
- 数据统一命名: metaworld_peg_lerobot → metaworld_peg (变体风格: peg/peg_long/peg_far)

## 🎛 数据闭环模型选择器 (PipelinePanel)
- `_reload_models`: 读 reports/train_curve_*.json 7 模型 → QComboBox "名字 · MM-DD HH:MM"
- `_show_model_attr`: ckpt/训练时间/步数/尾loss
- `_on_sim2real` / `_on_stage3`: 选中模型写入 docs/PIPELINE_STATE.json stages[2]/[3]
- 验证技巧: PipelinePanel.__new__ + monkeypatch _refresh (免完整构造)

## 🏗 总系统标准化 + Z-MAX 架构入模块库
- 总系统 = Subsystem 节点: LIBRARY 模板「🎛 顶层总系统」(数据→🔬总系统→Scope,
  subsystem 指向「🔬 模型对比」) + LIBRARY 组「🏗 Z-MAX 架构 (4)」可拖节点
  (SYS2/SYS12/SYS11/SYS0) + node_logic `_reg("topsys", ...)` 双击展开
- 首页侧边栏 4 卡 → 三层: System 2(顶)/System 1(VLA-T+Z-Flow 合并)/System 0(红底),
  标签「三层系统」, layer_map 加 sys1→training
- 删除三模型对比: 模板定义 sed 行删 + LIBRARY 条目 + btn_compare3 + open_compare3
  + open_topsys 加载名修复 (残留坏引用清干净)
- 功能模块网格: 4 层分组框 (系统/架构/数据/场景) — 每层 QFrame(C_BG 深底) 包
  标题行(▍色条+组名+副标题) + 3 卡(C_CARD 浅色) — 深框浅卡对比
- 模块卡右上角 badge 统一 System N: training→System 1, hardware→System 0

## 🗂 功能模块网格最终布局 (2026-08-08 晚, 老倪逐轮给定)
- **模块顺序** (12 卡 4×3, 数组顺序即网格顺序): 第一行 数据集管理/训练控制台/硬件工具箱 → 第二行 系统架构/Simulink模式/配置中心 → 第三行 全局数据空间/实时监控/评估分析 → 最后一行 插拔场景/版本同步/**产品大屏** (website 卡最后, mid=website)
- **分组标题+副标题** (每层 QFrame 内标题行): 系统·平台底座(数据/训练/硬件) / 架构·系统结构(架构/仿真/配置) / 数据·数据资产(空间/监控/评估) / 场景·应用场景(插拔/版本/官网)
- **产品大屏卡** (原"产品主页"): `_on_nav` 开头特殊分支 `if target == "website":` — URL 卡不跳 stack 页面 (cards 点击一律 emit module_clicked, 特殊 mid 在 _on_nav return)
- 🐛 **WSL 打开浏览器: QDesktopServices.openUrl 失效** (WSL 无 xdg-open → openUrl 返回 False, 浏览器不弹) → 用 `subprocess.Popen(["cmd.exe", "/c", "start", "", url])` (Windows 默认浏览器, PATH 里有 /mnt/c/Windows/system32/cmd.exe, 实测 rc=0) — 任何"打开网页"类功能在 WSL 下都走 cmd.exe start, 别用 QDesktopServices

## 📖 数据集查看器 (dataset_viewer.py) — npz/AV1/翻帧坑
- **npz 压缩格式慢**: savez_compressed 的 npz, `d["observations"]` 每次访问**重新解压** (1.5s/帧) — 缓存 NpzFile 不够, 首次 load 后**提取数组到内存** (`self._npz_obs = d["observations"]`) → 翻帧 0-1ms (提速 1500x)
- **AV1 编码 mp4 cv2 解码失败** (如 metaworld 数据集 videos/) → "帧 0 超出范围" — **有 train.npz 时优先走 npz** (numpy 可靠路径), 视频/parquet 兜底
- **frame_slider 初始 maximum=0** → "下一帧点不了" — 打开查看器 `QTimer.singleShot(0, self._load_video_frame)` **自动加载第一帧** (maximum 就位)
- **图像 180° 旋转按数据集类型区分**: 插销数据 (peg*) 与视频同源需 rot90(k=2), metaworld_act 官方数据方向本来就对**不转** — 无条件旋转会转反 (老倪: "图像反了, 要旋转 180 度" 后又报 act 反了)
- orin 采集包 (json, 无图像) → `_load_json_package` 显示包 meta + 帧 state/action 文本 (查看器加 json 分支)

## 📚 LIBRARY 全覆盖模式 (老倪: "所有模块都要来源于左侧") — 可复用
- **盘点**: 模板节点 vs LIBRARY 条目差集 → 缺失补组 — 脚本: 遍历 REFERENCE_APPS 的 tpl[1] (节点元组) + tpl[3] (布局行) 收集节点名, LIBRARY 收集条目名, 差集即缺
- **补组策略**: 按类分组建组 (🧠 模型主干/🚀 训练/🎯 ActionHead/🎛 CICD 环节/🔬 总系统/硬件别名/仿真推理视频…) — 最终 20 组 134 节点, 11 模板 0 缺失
- **别名条目**: 模板节点名与 LIBRARY 名不一致时 (如模板"机械臂" vs "H03 机械臂", 模板"VLA-T" vs "🧠 SmolVLM2-500M") — **补同名别名条目** (功能同 H 编号), 不改模板 (画布不变)
- 仿真推理/视频组可用**列表推导式生成** (for m in 7 模型)
- **全局数据空间主数据**: data_space.py 加 `self.nodes` + `_scan_nodes()` (读 LIBRARY → 组/名/类型/params 摘要) + `node_objects()` 开头把节点自身注册为"节点"主数据 (node↔主数据全息关联)
- 验证: 重跑盘点断言 total_missing == 0; LIBRARY 分组数 ≥15
- **badge 三层命名统一**: dataset→System 2 · training→System 1 · hardware→System 0 (不再 Sys-11/Sys-12 旧名; 老倪逐卡点名改)
