---
name: zmax-console
title: "Z-MAX Console"
description: "Maintain PyQt5 GUI studio.py: version, Docker, backup, docs sync, PPT engine, auto-update."
trigger: "Use when the user mentions '控制台', 'Console', '远程GUI', '迭代控制台', or 'studio.py' — PyQt5 desktop, NOT web console.html."
---

# Z-MAX Console — 维护指南

## 🔎 数据空间视图(dds_canoe.BusView)顶部搜索
- 位置: 顶栏(测量组)最右端 = `ed_find` + `lb_find`, 按名筛**信号表**(报文/信号/节点)三组, 不是 Trace(Trace 另有 `ed_search` 只筛帧)。
- 坑①: 清空搜索时**必须递归取消 hidden**(`_unhide_all`, 根+叶子一起); 只把根 un-hide 会出现“组标题出来了、叶子还藏着”。
- 坑②: 信号表会被 `reload(force_tree=True)`(「只看活报文」勾选/刷新钮)整棵重建 ⇒ 重建函数末尾必须再调一次筛选, 否则用户打了一半的词白打。
- 坑③: 可搜文本 = 各列文字 + tooltip + column0 的 `Qt.UserRole`(话题 key/类型常藏在里面) ⇒ `ss_plan` / `zmax/ss_plan` / `zmax::SSPlan` 三种写法都能命中。
- 无 GUI 环境验证: `QT_QPA_PLATFORM=offscreen` + `gui-venv311/bin/python` 起 `build_view(None, standalone=True)`, 显式 `v.reload(force_tree=True)` 再跑 1.8s 事件循环后树才建出来(只 processEvents() 得 0 条)。
- 数据空间里的名字对照: MoveIt 规划输出 = `ss_plan`(`zmax/ss_plan`, `zmax::SSPlan`); 状态空间引擎动作 = `ss_action`; 搜 `moveit` 还能命中画布节点「🧭 MoveIt 运动规划 · SDK 直驱桥(Orin)」与连线信号。

> 📌 refs: veh-id-system,ssh-remote-gpu,config-center-excel,relay-middleware,simulink-id-and-skill-tokens,wsl-display-links,simulink-flow-json,gui-navigation,devflow-panel-pdf-2026-08-15,gui-debug-and-crash-forensics
> 🐛 「断点进不去」不是代码没跑: 先 `ss -ltnp | grep 5678` —— **无监听 = 控制台是非调试模式**(studio.py 只在 `ZMAX_DEBUG=1` 时 listen), 要用 `ZMAX_DEBUG=1` 起或 F5「🚀 全新调试进程」;
> 再确认节点"逐行执行"链 `_trace_exec` 的 `sys.settrace` 没顶掉调试器(`debugpy.is_client_connected()` 为假时它会装 —— 判据必须在**执行过程中**读 `sys.gettrace()`, 返回后再读被 finally 清成 None)。
> 📸 **从整屏截图里裁「某个 CSD 窗口」时, 别信 `wmctrl -lG` 的 y —— 先用 `_NET_FRAME_EXTENTS` 核**:
> 本机 mutter 是 CSD(阴影+标题栏由应用画), 实测 `_NET_FRAME_EXTENTS = 0,0,74,0` —— 拿错误的 y 去裁,
> 会把窗口**顶部一整条(含测量条/标题)切掉、底部却多收一段背景**, 子代理会据此报「窗口没有 Start/Stop、
> 底部是个半成品空盒」这种**不存在的问题**。做法: 裁完先验一下顶部该有的特征物(如 C_YELLOW 的
> Start 按钮像素数 > 0、非背景占比 > 15%), 否则先修裁切偏移再下结论。
>
> 🪟 **独立窗口一律用「无 parent 的 QMainWindow + 显式 MinMaxClose」, 不要用 `QDialog(父窗口)`**:
> `QDialog(父窗口)` 在 mutter 下是**附属窗(transient)** ⇒ 标题栏最大化钮灰着/点不动
> (老倪 2026-09-29「独立打开的全局数据空间的最大化按钮不好用」)。验法: `xprop -id <wid> _NET_WM_ALLOWED_ACTIONS`
> 必须含 `_NET_WM_ACTION_MAXIMIZE_HORZ|VERT`, `_NET_WM_WINDOW_TYPE` 应为 `_NET_WM_WINDOW_TYPE_NORMAL`。
> 深色主题不会丢 —— `app.setStyleSheet` 是**应用级** QSS, 与 parent 无关; 无 parent 窗要自己留引用
> (防 GC) + `app.aboutToQuit.connect(w.close)` 防孤儿窗。
> ⚠️ 本机 fractional scaling 下 `move()/resize()` 与 `screen().geometry()` **不在同一坐标空间**
> (按 0.56×屏宽算出的窗实测大到出屏) ⇒ 摆位一律在 `show()` 后用**真实 frameGeometry** 夹回, 不靠推算。
>
> 💥 崩溃(窗口消失/Aborted)的取证清单、QThread 自查点: 见 `references/gui-debug-and-crash-forensics.md`。
> 🎛️ **仪表盘/图形化表达(圆环·状态条·指示灯)、独立窗口多视图、CANoe 三窗格数据空间、192DPI 自绘取证**: 见 `references/console-dashboard-widgets.md`。
> 🕳 工具栏/面板「中间一大块空白」的**第一诊断 = 量那块矩形的亮像素数**(亮度>90 的像素为 **0** ⇒ 控件在但看不见, 不是缺控件): Qt 给 `QCheckBox`/`QRadioButton` 的默认字色是**黑**, 画在深色工具条上对比度 ≈1.1:1 —— 全局深色 QSS 会覆盖 QPushButton 的背景却常常不碰 QCheckBox 的字色(mk_btn 那套浅色配方看着"没生效"就是这个原因)。修法 = 给每个勾选框显式深色 pill 样式(`background:#14181f;border:1px solid #30363d`, **padding 与按钮一致**才等高, 勾选态绿字 + 绿指示块), 改完复测该区亮像素: 实测 0 → 17258。
> 老倪铁律: 硬件/资源类卡片**少堆文字** —— 数值用 圆环/状态条/指示灯 表达, 原文退到 tooltip + 「📋 复制参数」按钮(他要可复制的纯文本); 缺测显示 "—", 数据源不通必须点红/灰灯, 不能还是绿灯。
> 🐌 **2026-09-29 老倪「全局数据空间怎么卡住了」= 表格 `ResizeToContents` 逐格量列宽**(v5.16.22):
> ① **根因不在 fill 函数里**: 新页带了 1.5s 自刷新, 逐函数计时只看到 `_fill_trace` 2ms/整轮 11ms, 但进程 `ps` 实测 **81.7% CPU**。真开销是 **`QHeaderView.ResizeToContents`** —— 单元格一变就为**每一列逐格重新测量文字宽度**(192DPI 下 9 列×150 行), 而且算在**事件循环**里(不在调用栈里, 所以计时看不见)。
> ② **定位手法(可复用)**: `resource.getrusage(RUSAGE_SELF)` 量 CPU + **分组停 QTimer 做 bisect**: 基线 83% → 只停该页定时器 **3%**(其余页定时器各 0%) → 确认就是这一处; 再换成显式列宽 → **5%**。停定时器的清单 `widget.findChildren(QTimer)` + `isActive()/stop()`。
> ③ **规矩**: 高频自刷新的表 **一律不用 `ResizeToContents`**, 改 `Interactive` + 显式宽度(名字列才用 `Stretch`); 再加三道闸: `if not self.isVisible(): return`(不在看的页不刷)、文件(体积,mtime)签名没变就整轮跳过、只读文件尾部(不 `readlines()` 整个文件) + 行数封顶。
> ④ **验收要看两件事**: 现场 `/proc/<pid>/stat` 前后采样算实时 CPU(修后 ~0-5%), 且**两帧截图对比像素必须仍在变**(证明不是“不刷了”假好): 实测测量条 1025px/Trace 35847px 在变 = 数据真在走而 CPU 没烧。
> 🌐 2026-09-29 老倪「全局数据空间 参考 portal.vector.com/de/web/help/canoe-demo 重新设计UI」= 该页从「12 个 Tab 堆叠」改成 **CANoe 主窗口范式**(v5.16.16→v5.16.18; 新模块 `tools/gui/dds_canoe.py` 的 `build_view(main_win)`):
> ① **CANoe 的范式是「多窗格同时在线」**(官方截图逐像素实测: 顶部功能区 + 上排左 Scene Window ~41% ｜上排右 Data ~57% + **下 Trace 整宽** + 底部 Configuration|Measurement|Data Window 页签), 不是「把功能切成 Tab」⇒ 照抄骨架比照抄配色重要。
> ② 映射: 测量组(⚡Start 黄 / ⬢Stop 灰 / ↺) ｜ **Data 面板列名照抄** Name|Value|Unit|**Last Value Time [s]**|**Bar**(实心蓝条=实测/设计, 自绘 `BarDelegate` 按 `Qt.UserRole` 比例画在单元格里) ｜ **Trace 整宽** 9 列 Time|Name|Object Type|Classification|Probability [%]|Sender Name|Sender Id|Tracking Id|Group, Time 用「相对测量起点 3 位小数」, Δt 切「与同话题上一帧之差」。
> ③ 数据全真: `busdb.json`(画布导出的 DBC: 74 节点/182 信号/14 报文) + `live.json`(每话题 hz/丢包/jitter/帧龄/rules/灯) + `trace.jsonl` + `loop.json`; 缺测一律 `—`; **旧页面零丢失** = 右上「🗂 经典视图」开关(两套控件都在内存, `main._canoe_classic_cb` 切显隐)。
> ④ vision 质检实测出的 UI 通病: **不要用「整行改灰前景」做斑马纹**(半张表像褪色, 6.7:1 vs 18:1) → 改浅底; Qt 列头默认**居中**而单元格左对齐 ⇒ 列头比内容右移 32-42px, 要 `setDefaultAlignment(Qt.AlignLeft)`; 等宽对齐文本**中文按 2 列宽算**才算得齐(自写 `_pad()`), `%-14s` 对中文无效; 暗灰 `#484f58` 对比度 2.3:1 几乎看不见 → `#6e7681`; 同一规则+同文本的告警会重复渲染 ⇒ 三元组去重。
> ⑤ 验证口径: 离屏 `QT_FONT_DPI=192 QT_QPA_PLATFORM=offscreen` + **先 `cv._timer.stop()` 再测**(1s 自刷新定时器在 processEvents 循环里反复重建 500 行表, 探针表现得像「卡死」); 判据 = 树空文本行 0 / 各填充步骤 ≤0.01s / Trace 变灰列数 0 / 截图出图 / 页面宽==视口宽。
> 🔎 **「某节点的输出是哪个 topic?」(以及「哪个 topic 是 MoveIt 的输出 action」一类问法) = 三件一起查再答**:
> ① 设计态 `busdb.json` 的 `signals[]` —— `src`==该节点的那条连线的 `topic` 字段(全图连线走**同一条** `zmax/link_value`,
> 信号身份 = `(src, port)`; `dds_link_bus.py` 注释里的 `zmax/link/<node_id>` 是旧设计, 别照它答);
> ② 实测态 `live.json` —— **`hz=-1` = 本档没在发**(不是坏了); ③ 内容 `trace.jsonl` 的 `digest`;
> 最后再补一句上游那一级(如 MoveIt 本体)此刻有没有在跑 —— MoveIt2 的输出接口是 ROS2 **服务**
> `/plan_kinematic_path`(非 DDS 话题), `docker ps`/`pgrep -af move_group` 空就是没起。
> 键名坑(`live.json` 短名 vs `trace.jsonl` 全路径 ⇒ 按话题 join 的列全「—」) 与独立窗「🌐 数据空间窗口」(`ds_win`) 见
> `references/dataspace-dds-tab-2026-09-29.md`。
> 🖥 **硬件/状态仪表盘页**: 用户口径 = 「不要用那么多文字来表达, 换成状态条 / 圆环百分比 / 红绿灯指示灯」(参考 CANoe hardware · Vector Hardware Manager 的集中式设备面板) ⇒
> ① **实现形态**: 自绘控件模块 `tools/gui/hw_widgets.py` —— `Ring`(轨道圆 + 12 点顺时针弧 + 环内大号数值 + 环下短标题) · `StatBar`(名称 + 圆角条 + **底槽** + 右对齐数值) · `Lamp`(发光圆点 + 名称 + 一行小字) · `HwVisual`(装配: 设备灯带 → 圆环行 → 状态条行)。`HardwareCard` 的旧文字标签**保留但 `setVisible(False)`** —— 采集线程照旧更新它们, 只用于 tooltip 与「📋 复制参数」; 版面全交给控件。
> ② **数据通道与显示通道必须分开**: 采集线程 `_collect()` 除 HTML 文本字典外再挂一份**数值载荷** `out["_metrics"] = {"local": {...}, "devices": [...], "remote_src"|"remote_src_off": ...}`, GUI 线程 `refresh()` 推给 `HwVisual.set_data()`。**绝不让可视化控件去解析/正则 HTML**。
> ③ **排序本身就是需求**: 「4060/本机」要沉到**灯带最右**, 整卡也移到首页**最底**并加节标题(与「功能模块/项目状态」同规格)。灯带每次 `set_data` 用 `insertWidget(i, lamp)` **重插已有灯**(只插新灯 ⇒ 旧灯卡在旧位次); 同一台机既出现在本机指标又出现在 DDS 节点列表时**合并成一盏灯**(按显卡名认), 否则用户看到"一台机两盏灯"。
> ④ **阈值按物理语义, 不是"越大越红"**: 显存/CPU/内存 <80 绿 · 80-92 黄 · >92 红; 磁盘 <80/80/90; 温度 <70/70/82; **GPU 利用率反着来** —— 空闲(<5%)灰 · 训练中 <50% **判黄**(掉载口径) · 其余绿。
> ⑤ **不许编造量纲**: 状态条的分母必须是真实量 —— 功耗条用 `nvidia-smi --query-gpu=power.limit`; 读不到就**只显数字不画条**(拿"本次观测峰值"当分母会让空载满格, 反而误导); 无训练时吞吐显示 `—`; 缺测一律 `—` 不用 0 冒充; 数据源不可达要亮**"未连通"红灯** —— 否则整卡全绿看不出是占位/过期数据。
> ⑥ **自绘仪表盘做完必过一次 vision 逐像素质检**(两张图: 控件本体 + 整页), 高频真缺陷与修法清单见 `references/ui-visual-qa-defect-classes.md`; 本页实测踩到: 底槽与卡底色几乎同色 ⇒ 看着像"4 条只画了 2 条"; 圆环**圆头端帽**让 34% 画出 36% ⇒ 改 `Qt.FlatCap`; 前导 `addStretch()` 把内容挤到右端 ⇒ 卡左侧 31% 全空; 名称/小字按**字数**截断而非按**实测字宽** ⇒ 硬裁无省略号; 一排按钮三档高度/字号。
> ⑦ **现场验收口径**: 重启后 `wmctrl -lG` 的窗口标题必须带**新版本号**(不带 = 起的是旧码), 再 `ffmpeg -f x11grab -video_size 3068x1862 -i :0.0+132,212` 抓图, 并用 PIL 抽检**控件特征色像素数**(环轨 #30363d / 条与灯 #3fb950 / Bar #2f81f7 > 0) ⇒ 才算证明"画到屏上了", 不是只存在于离屏脚本里。
> 🛑 2026-09-28 老倪两次问「控制台怎么自己重启呢」——查证: 控制台**本身没有自启机制**
> (systemd 用户单元 zmax-studio.service 是 Restart=no, 退出后一直 dead; crontab 11 条没一条碰它),
> 是 **agent 改完 GUI 代码就重启它** ⇒ 现场只看到窗口闪来闪去。
> 🪟 2026-09-29 夜 「窗口没显示完全」的**出屏判定**(双屏 3200x2000@0,0 + 3840x2160@3200,0 ⇒ X 虚拟屏 7040x2160, 主屏只可见 y<2000):
> ① WM「最大化」按**跨屏工作区**算 ⇒ 窗口可大部落在主屏可见线外(实测 3068x1862@132,212, 底边 2074 ⇒ 最底一行版本提示/跑马灯永久看不见)。
> ② **不能只看 `frameGeometry()`**: mutter 给每个窗口配一个 `mutter-x11-frames` 外框窗口(实测 3124x1994@104,40), **CSD 外框/阴影不计入应用自报几何** ⇒ 应用自报「刚好贴屏底 1992」时真实外框已到 2034。判定交叉核对 `xdotool getwindowgeometry <win>` + `xdotool getwindowpid <win>`(用它认领外框窗, **别当成第二个控制台实例**) + `wmctrl -lG`。
> ③ **主屏可见线以下(y≥2000)的 framebuffer 可能是陈旧的** —— X 不重绘没被任何显示器显示的区域 ⇒ 在那块拍到控制台配色 **≠** 内容被切(重启后重拍才算证)。
> ④ 修法: `_fit_window_to_screen()` 里**最大化也要查越界**(越界先 `showNormal()` 再夹), 纵向预算再留 **48px** 安全边(宁矮不切)。
> ⑤ QLabel + `wordWrap` 在 QVBoxLayout 里会被按 sizeHint 估算**压扁**(实测组件行需 374px 只给 243px ⇒ 尾行整行看不见): 布局跑完后按**实际宽度**复算 `heightForWidth` 并锁最小高, 两遍收敛。
> 🎨🔴 2026-09-29 晚 老倪「(主界面)功能模块太宽了, 不协调; 不要下面的横向拉条。修改, 不要那么宽」= **真实根因在 HardwareCard, 不在模块网格** (v5.16.12→v5.16.13):
> ① **量口径(先量再改)**: 验 UI 宽度只看 `QScrollArea` 的 **`page.width()` vs `viewport.width()`** + `horizontalScrollBar().maximum()`。实测 `page=5542 / viewport=3052` = **1.82×** ⇒ ①底部必有横条 ②网格按 page 宽等分 ⇒ 每张卡 1752~1795px(设计 260), 卡内文字只占左侧 ~320px、右边全空 = 用户说的"太宽/不协调"。
> ② **元凶**: `HardwareCard` 里 24~28px 富文本标签 **没开 wordWrap** ⇒ 单个标签 `minimumSizeHint` 5428px 就把**整页最小宽**顶到 5542(`lb_remote` 最大, 其次 `lb_gpu` 1804 / `lb_nodes` 1051)。**任何超长文本 QLabel 都能把整页撑宽** ⇒ 首页/子页动态标签一律 `setWordWrap(True)` + `setMinimumWidth(1)`。
> ③ 模块侧: `ReflowCardRow(max_card_w=470)`(超上限按上限给宽 + 整行居中留白) + 分组框再套一层 `ReflowCardRow(min_card_w=900, max_cols=2)`; 每次 reflow 先清**历史列**的拉伸/最小宽(`setColumnStretch/MinimumWidth(0)`), 否则留下看不见的空列把卡片推开。
> ④ **别在 offscreen 单测里判 UI 宽度**: 硬件卡是**后台线程 2s 后**才把长文本贴进标签 —— 离屏探针不 `processEvents()+sleep 等到采集落地` 就量, 得到 `最小宽 2459` 是**假的**(现场 5542)。必须 `QT_FONT_DPI=192` + 等采集 + 跑整窗冒烟。
> ⑤ API 坑: **Qt 的 8 位 hex 是 `#AARRGGBB`**(不是 CSS 的 `#RRGGBBAA`) ⇒ `f"{color}55"` 变成"alpha=0x58 + 黄绿"(老倪: "卡片标签怎么是绿底")。半透明一律写 `rgba(r,g,b,a)`(`rgba_of()`)。修前角像素 `#a4ff54` → 修后 `#304e76`(= 0.33×#58a6ff + 0.67×卡底, 逐层色同样吻合)。
> ⑥ 改完必跑(探针已归档 `release_archive/v5.16.13_20260929/src/probes/`): `card_text_check2.py`(按 `TextWordWrap` 复算每个标签需要的宽/高, **溢出 0** 才算过) + `studio_smoke.py`(整窗 + 11 页切换异常 0) + 修后截图量 **`页面宽 == 视口宽` 且 `横条 max==0`**。
> 🎨 2026-09-29 老倪「窗口没显示完全 + 没有横向拖动的拖动条 + 方框里字被遮挡」= **UI 五条真根因与修法** (v5.16.5):
> ① **横向条被永远关掉**(最直接的根因): 三处 `QScrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)` ⇒ 内容一宽过窗口就既看不到右边、也没有横向拖动条。改 `AsNeeded`(0)。
> ② **滚动条 QSS 必须挂 widget 级**: 只改全局 `app.setStyleSheet(_build_global_qss())` 会被页面级/控件级样式表压掉 —— 实测"改了全局 QSS 但像素一点没变"。用**附加**写法 `scroll.setStyleSheet("QScrollArea{border:none;}" + SCROLLBAR_QSS)`(studio.py 常量), 画布 view 单独 `setStyleSheet(simulink_module.CANVAS_SCROLLBAR_QSS)`。验收判据 = 截图右缘**蓝色列数**: 修前 0(只剩两条灰线) → 修后 16 列(16px 蓝手柄 #4d8fdb)。
> ③ **色带(row_bg, 老倪说的"方框")名字被截 = 名字区宽度算错**: 原取**全画布**最小节点 x(本画布=0) ⇒ 每条色带名字区都被压到下限 80px ⇒ 15/15 全部省略号。必须按**本条色带内**的节点算(节点中心 y 落在本带 y..y+h 内) ⇒ 80px → 284~11070px, 实测 15/15 → 0/15。
> ④ **节点字多 = 换显示名, 不是缩字** (✅ v5.16.6 定稿): 数据名平均 18.7 字(最长 41) ⇒ 两行还挤。改 `node_display_name()` 为**字数预算制**: 预算 **10 字** = 每个中文字 1 字 + 每个西文/数字词 1 字 (`Transformer`/`ACT`/`43D` 各算 1 字), 取值优先级 = 原名≤10字**原样保留(连括号)** → 去括号补充(≥5 字才用) → 人工短名表 `NODE_CORE_LABELS`(43 条, 权威 5~10 字) → 按词裁剪(≥5 字); 另加**单行像素预算 300px** (超了就只能折行) 与**括号保护** `(?<![A-Za-z0-9])[（(【\[〔]` (否则 `SU(2)`/`D064` 这类技术记号里的括号会被当补充说明删掉)。图标(emoji/①②/◉)不计字数, 自动带在标签前。配 `autofit_node_size()` (按最终标签撑宽/长高)。
> 🔴🔴 **“字只显示一半”的第一个该查的东西 = 屏幕 DPI, 不是文字长度** (v5.16.8 实测根因): 本机桌面 `xrdb -query | grep Xft.dpi` = **192** (2x), 而节点排版常量是按 1x 字形设计的 (标题行 20px / 副行 16px / radio 格 48px) ⇒ `QFont(族, pt)` 现场字形是设计值的 **~1.93 倍** (同一句“抗干扰”: 离屏 42px → 现场 81px; 行高 22→40) ⇒ 行叠字、末字被框边切掉。
> • 修法: 画布文字一律 `QFont(fam)` + `setPixelSize(...)` (**不做 pt**), 排版常量不变 ⇒ 现场 = 离屏 = 审计三边一致。字号倍率要**扫**出来: `ZMAX_NODE_PX_SCALE` 1.15 通过 / 1.30 互压 / 1.45 越框。
> • **审计必须在“现场口径”也跑一遍**: `DISPLAY=:0 QT_QPA_PLATFORM=xcb` vs `QT_QPA_PLATFORM=offscreen` (后者不读 Xft.dpi → 永远 1x → **必然假通过**)。只要两种口径结果不一样, 就是这类 DPI 坑。
> • 画布里别再用 `QFont("Arial", 9)`/`QFont("Consolas", 9)`: 本机两个字体**都不存在** (Arial→Liberation 只有西文字形 → 中文逐字回退; Consolas→回退), 用 `_node_font()`/`_node_mono()`。
> • **运行期文本**是第二个病灶 (静态扫不出来): `str(x)[:64]` 只截**字数** —— 64 个中文字 ≈ 850px 塞进 406px 的框, 而 `drawText(QRectF,…)` 的矩形**不裁剪** ⇒ 直画到框外/压邻居。统一走 `_fit_text()` (按框宽 elide + 全串进 tooltip)。自查: `scripts/node_runtime_text_check.py` (把 l5_lines 塞满长中文/报错串后复检)。
> • 🐛 **`QFontMetrics.elidedText` 的宽度必须 `int`**: 传 float 会 `TypeError`, 被 `except Exception` 吞掉 → **静默退回“不省略”**(看上去像没修)。本文件 356 行已记过, 又踩了一次 —— 写完 elide 后一定要 assert 返回值宽度 ≤ 预算。
> ⛔ **别用“按分隔符从前往后取前缀”** (v5.16.5 的做法, 已废): 它把「🏆 L4 · 工作安全 + 物理世界导航」砍成「L4」——**层号是分类不是功能**, 老倪一句「怎么只是剩下 L4」打回。判据 = 标签字数 ≤10 且 ≥5 且不得只剩 `L[1-5]`。
> 🔍 **“字太多/太挤/看不清”是另一个毛病, 用代理画笔查** (v5.16.7): `scripts/node_text_audit.py` —— 包一个 `AuditPainter` 转发 set*/draw*, 只拦 `drawText(qrect, flags, text)`, 逐条判三件事: ①文字宽 > 绘制矩形宽 (=会被裁/挤) ②文字矩形画到方框外 ③两块**贴合文字**的矩形互压(大容器矩形要排除, 否则一团假阳性)。实测全 flow 1025 个节点修前 91 处 → 修后 4 个 0。
> 🐛 该体检抓到的三类**真**毛病 (改文字之外记得顺手查这三处): (a) 小按钮里写死长文案 (📥导出 34px 按钮装 43px 字) → 按钮加宽 + `elidedText`; (b) 色带标题绘制矩形按“带内节点最小 x”算会比**色带自身宽**还大 → 绘制矩形必须 `min(_aw, self.w-16)`; (c) 色带 `paint` 用 `node.get("h", 244)` 而 `__init__` 里是 `node.get("h", DH=110)` ⇒ 没写 `h` 的色带画出来高 134px、标题跑到框下面 —— **paint 一律用 `self.w/self.h`**, 不要另取一个默认值。
> 🎛 **带自绘控件的节点** (如“能力档位” radio): 标题别写死长句(尤其别用 `QFont("Arial")` —— 本机无该字体, 中文逐字回退→宽窄不一), 走 `node_display_name` 拿短标签 + 统一字体; 详细说明进 tooltip; 每个 radio 子标签先量 `QFontMetrics.horizontalAdvance` 再画 (放不下就不画, 宁少勿挤)。
> 自检命令 (26 个 flow / 1107 个标签, 三个“0”才算过): 超 10 字 = 0 · 超 300px = 0 · 只剩层号 = 0; 同口径看收益用 `scripts/node_text_before_after.py`。
> ⑤ **「窗口没显示完全」先量再改, 别急着改尺寸**: `xwininfo -root -children` **看 frame 那一行**(GNOME mutter 会 reparent, 客户窗几何带偏移会骗人) + `wmctrl -m`; 实测老倪窗口 `_NET_WM_STATE_MAXIMIZED_*`, frame 3068x1936+132+64 = **正好铺满 3200x2000** ⇒ 窗口没出屏, 是**内容**宽过视口 + 条被关掉。仍保留 `_fit_window_to_screen()` 兜底(尺寸+位置双夹紧进 availableGeometry, 留 8px 边距; 启动与 show 后各一次; 记 `/tmp/studio_show_diag.log`)+ 菜单「🖥 窗口适配屏幕」。
> ⑥ **改完画布渲染必须逐个跑真 `paint()`**: paint 里抛异常 = Qt **直接 abort 整个 GUI**(不是打印异常)。探针见 `scripts/canvas_node_render_selfcheck.py`(造 nodes/links shim + QImage 逐节点 paint, 断言"异常 0 / 标题截断 0"), 收益对照用 `scripts/node_text_before_after.py`(两边各走自己的 autofit = 同口径)。
> 📌 改完照例: `tools/bump_version.py --to X.Y.Z --summary-file ...`(7 处版本号 + VERSION.md 表首, 工具会回读校验) → `git commit` → `git push origin main`。
>: 单元是 `enabled`(WantedBy=default.target)
> ⇒ **图形会话一进就会自动弹一个控制台**(只是 Restart=no, 所以关了不会自己弹回来)。
> 老倪开机看到的是 **v5.15.13 旧版**, 根因 = 单元里 `WorkingDirectory/ExecStart` 还硬编码在**共享检出**
> `/home/ubuntu/lerobot-smolvla-lew`(被并行线切到 mac-hw ⇒ 那边 GUI 停在 v5.15.13), 真源是 worktree
> `/home/ubuntu/zmax_rel`(v5.16.4)。桌面图标 09-26 已改成按脚本位置推仓库根, **只有这个 systemd 单元没跟上**。
> 纪律: **凡"开机自启/常驻"入口一律指 worktree** —— 现在 `ExecStart=/home/ubuntu/zmax_rel/tools/gui/launch_studio.sh`
> (自带 worktree 优先 / DBUS 会话总线补全 / 已有实例去重激活); 改完必 `systemctl --user daemon-reload` 并回读
> `systemctl --user show zmax-studio.service -p ExecStart -p WorkingDirectory`。
> 排查「界面怎么是旧版」: 两个检出各查一次 `grep -m1 CURRENT_VERSION <检出>/tools/gui/update_checker.py`,
> 再对 `pgrep -af studio.py` 的 cwd (`readlink /proc/<pid>/cwd`) —— 界面版本 = 那个 cwd 的代码版本。
> 纪律: **改 GUI 代码攒成一批, 重启前先问老倪**; 确需重启走 `bash tools/studio_ctl.sh restart --force`
> (起不到 300s 的实例会被硬闸拒, 退出码 3), 每次动作记 /tmp/studio_ctl.log 可追谁在重启。
> 🔌 另: 关机/kill 走 SIGTERM —— 老版本会 "QThread: Destroyed while thread is still running" → SIGABRT + core dump;
> 现 studio.py main() 用 `signal.set_wakeup_fd` + 看门狗线程 + QTimer → win.close() → os._exit(0) 干净退
> ⚠️ 这句只覆盖 kill/关机路径 —— **无信号时也会出现同一组签名**(实测日志里「收到信号」0 条, 仍 `QThread: Destroyed while thread is still running` + `Fatal Python error: Aborted`)
> ⇒ 见到这组话别默认归因 kill: 按 `references/gui-debug-and-crash-forensics.md` 的清单逐条排除后再定性。
> (⚠️ 用普通 `signal.signal(SIGTERM, py_handler)` **无效**: 主线程在 Qt 的 C++ 循环里, 处理器根本跑不到)。
> ⚠️纪律: 只patch改; kill-9重启(pkill 用 "gui-venv311/bin/python studio" 别用 studio.py, 会打死 Hermes 自己的 shell); --gpus all本地/--runtime nvidia远程; -o Port; 主线程禁网络请求(摄像头坑); 启动/黑屏见 launch-guide.md; 训练入口/状态见 gui-navigation.md; 控件小/字挤/面板窄见 ui-sizing-hidpi.md; refs: gui-discipline, simulink-flow-and-buttons, simulink-flow-authoring, help-menu-doc-open
> 🔖 版本迭代/发布归档 → `references/release-version-bump.md` (**bump 先 `--dry`, 任一行 ❌/`旧命中 0` = 历史漏同步, 先补齐再写盘**; 含「保存数据」现场批次归档目录模式)
> 🔖 重启/启动崩溃排查/无显示离线取证 → `references/gui-restart-and-offscreen-verify.md` (launch_studio.sh 已有实例时 exit 0 不干活; `QT_QPA_PLATFORM=offscreen` 起真类调真方法)

## 🖵 工具栏按钮 → 开浏览器页 (studio.py / simulink_module.py)
- 开浏览器**必须用独立 profile**, 且 profile 要放 **snap 可写**目录 `~/snap/chromium/common/<用途名>`
  (无 snap 目录才回落 `~/.cache/...`), 配 `--no-first-run --no-default-browser-check`。两条实测原因:
  · 不带独立 profile ⇒ `--new-window` 被**已经在跑的 chromium 实例吞掉**: 页面变成别的窗口里的
    后台标签, `wmctrl -l` 12s 内一个窗都不出现 = 用户说"网页还是没打开";
  · profile 放 `~/.cache` ⇒ **snap(受限)拒写**(浏览器自报 `Failed to create .../SingletonLock` +
    `Failed to create a ProcessSingleton for your profile directory`) ⇒ 进程起来又静默退出。
  · 两个页面要能同开就各给一份 profile(同一 profile 再请求新窗可能只是复用它那一个窗, 实测顶掉前一页)。
- 浏览器 stdout/stderr **落文件**(如 `/tmp/zmax_page_browser.log`); 认窗超时把它最后两行打进日志 —— 
  丢 DEVNULL 的话, "进程起来了但没窗口"这种故障两眼一抹黑。
- **点了先出声**: 主线程立刻回执 → 进程起来报"页面加载中(最多 12s)" → 最后报几何 + 可复制地址;
  任一段静默别超 ~3s —— 用户判"没反应"看的是**日志不出声**, 不是页面的真实状态。
- 已有同类窗口 ⇒ **复用(搬屏+最大化+置前)就返回**, 不关不重开: 关掉重开要白付一次 chromium 冷启(8~15s)。
- 页面**要能从控制台一步打开**: 只能从另一个页面里点链接跳过去 = 用户眼里的"这个网页搞丢了" ⇒ 给工具栏按钮。
- 验收不许靠自报日志: 离屏直调 handler + `wmctrl -lG` 几何断言(`tools/verify_station_button.py` 是模板)。
  两个坑: `self._log()` 的行**到不了** `log_signal`(断言要匹配 `log_signal.emit` 那几条);
  控制台日志面板的内容**不在** `/tmp/studio_launch.log` 里(要留证得自己写文件, 或让用户贴面板原文, 先按它定因)。
- `simulink_module.py` **无模块级** `subprocess`/`urllib`/`socket`(LSP 报错 + 运行时 `hasattr` 双证)
  ⇒ 用到就在函数里显式 import; 这类 NameError 会被周围 `except Exception: pass` 吞掉,
  表现就是"按钮点了什么都不做"—— 找不到原因时先怀疑 NameError。
精确参数 / 失败串原话 / 取证脚本形状 / 拉流漏参丢页见 `references/button-opens-browser-page.md`。

## 🏷 画布节点**改名/移位**必同步清单 (2026-09-24 融合定位实测, 漏一处即静默失效)
画布节点名 = **数据总线通道名** = `node_logic` 注册匹配键, 改名不是改 JSON 一件事。逐处清单:
| # | 位置 | 漏了会怎样 |
|---|---|---|
| 1 | `flows/state_space_obs.json` (node.name/x/y/inputs/outputs + links) | — |
| 2 | `tools/gui/data_world.py` `MODULE_ORDER` | 数据总线/3D/面板排序丢该模块 |
| 3 | `tools/gui/simulink_module.py` `SS_MODULE_TO_NAME` (键+值) | 变量监控高亮不到连线 |
| 4 | `tools/gui/simulink_module.py` 双击面板 `elif "<名>" in nm:` 分支 | 双击弹空白/错面板 |
| 5 | `tools/gui/state_space_sim_real.py` io 发布 dict 键 | **引擎每帧 io 挂不上 → 画布播放无该节点信号** |
| 6 | `tools/gui/state_space_sim.py` (非真实引擎) io 发布键 | 同上 (两引擎必须同源) |
| 7 | `tools/gui/node_logic.py` `_reg(key, [匹配名…], desc)` | 右键/双击「查看节点逻辑」→ match_node=None → 显示"定位中…" |
| 8 | `tools/gui/auto_test_suite.py` 用例判据 (如 TC09 `any("传感器" in n …)`) | **验收用例假失败** (改名后特征字串消失) |
| 9 | `src/lerobot/verification/node_func_tree.py` 显示名 (+ `ss_dreamview` 注释) | 网页功能清单显示旧名 |
验证四件套 (改完必跑): ① `python -c "import node_logic; node_logic.match_node('<新名>')"` 非 None
② `tools/canvas_level_audit.py` → **⚠无执行注册 0 · 真缺口 0** ③ 几何体检: 区内 反向/重叠/交叉 = 0 (新增线也不能引入)
④ `tools/studio_ctl.sh restart` (GUI 无 autosave, 改码+改画布必须重启) 后 `/tmp/studio_launch.log` 的 `Traceback|Error` 计数 = 0。
**备份纪律**: 改前 `cp flows/state_space_obs.json flows/…bak_pre_<改动>_<ts>` (回滚靠它, 不用 git 历史);
过期快照别留在工作树 → 移 `~/zmax_data/canvas_baks_archive_<日期>` + `.gitignore` 覆盖 `.bak_/.bak./.bak-` 三种命名。

## 🐛 版本号迭代 (bump_version.py) — 6 处同步 + 1 行历史
`gui-venv311/bin/python tools/bump_version.py --to X.Y.Z --summary-file /tmp/v.txt [--dry]` 自动改:
studio.py 品牌 QLabel + 2 处窗口标题 + changelog 注释行 + `update_checker.CURRENT_VERSION` +
`docs_sync` 两键 + **`version_sync.py` 的 `zmax_ver`** + VERSION.md 表首插一行。
- ⚠️ **`version_sync.py` 的 `zmax_ver` 值不带 v 前缀** (`zmax_ver = "5.13.0"`), 而工具里的 ov/nv 带 v →
  原正则**永远 0 命中 = 静默漏同步** (版本面板长期停在旧号)。2026-09-24 已修 (`ov.lstrip("v")`) —— 若再见到
  `version_sync zmax_ver 旧命中 0`, 就是又被改回去了, 手工补完再修工具。
- 工具**只改不提交**: 先 `--dry` 看逐处命中再去掉 --dry; 之后由调用方 `git add/commit` (打 tag 会触发
  Windows/macOS 桌面包 CI —— 小版本默认只 commit+push, 要出包再单独 tag)。
- 归档照 `tools/archive_release_5_13_1.sh` 模式: 只放真实产物+改动文件+审计证据, 生成 MANIFEST(sha256)。

## 🧹 哨兵/任务清理判据 (2026-09-24: 18→9 条)
删之前**逐条查终态证据**, 只删"目标已终态"的 (脚本留在 `~/.hermes/scripts/`, 需要时一行重建):
`ls <flags>` 已报过 (`.four_tasks_reported`/`zmax_release_watch_<tag>.done`) · 流水线 `status.txt=DONE`+`RC=0` ·
被监视目录 >24h 无新文件且**无相关进程** (`ps aux|grep`) · 远端口令失效(permission denied) · 一次性公告已过期(旧版本号)。
保留三类: 基础设施 (sys-watchdog/数据链路/磁盘红线/技能记忆同步) · 活跃项目哨兵 · 现场工具 (仍 pause 待现场的不删)。

## 🧰 汇总终端: curl 可复制 + 终端页 + 图片右键复制 (2026-09-24 实测)

老倪四条要求对应的做法 (已落在 `tools/gui/aoi_inspect_console.py`, 可照抄):

1. **"curl 命令显示在窗口, 我复制后在终端执行"** → 让客户端把**等价命令**带出来: 在统一出口
   `_curl()` 里按同一组参数拼 `curl -s -m {timeout} -X {method} '{url}'` (+ binary 时 ` -o frame.png`),
   via=orin 时拼 `sshpass -p <pw> ssh <orin> "…"` → 放进 `info["cmd"]`, 再透传到 meta/dict (`_cmd`)。
   ⚠️ 别在窗口里手写命令字符串 —— 会与真实请求参数漂移, 必须同源生成。
2. **"要有个终端看 JSON 反馈"** → 独立 Tab〔终端〕: 上=命令框(只读等宽, 最多 400 行) 下=JSON 原文
   (带 `[HH:MM:SS]` 时间戳, 800 行); 每行都可选中复制, 配 [📋复制命令][📋复制反馈][📋复制命令+反馈][🗑清空]。
   本地图像处理 (如过曝切除) 也往同一页打, cmd 传空串即可。
3. **"每个技能点击即可执行得到结果"** → 技能 = 真函数 + 结果落可见位置: 推理类写判决表/缺陷表,
   服务类写终端 JSON + 日志; 验证时**逐个 `.click()` 断言产出** (不许只看按钮存在)。
4. **"图片右键即可复制, 可粘贴到别处"** → 画面控件换子类 `CopyImageView(YoloLabelWidget)`, 复写
   `contextMenuEvent`: **编辑态且命中框时不弹菜单** (保住"右键删框"既有行为), 否则弹
   复制图片/复制图片路径/另存为/画面信息。
   ```python
   md = QtCore.QMimeData(); md.setImageData(img.copy())
   if path: md.setText(path)                 # 粘到文本处=路径, 粘到图处=图片
   QtWidgets.QApplication.clipboard().setMimeData(md)      # ✅ 一次性
   ```
   ⚠️ **实测坑**: 先 `clipboard.setImage()` 再 `clipboard.setText()` → **图片被冲掉** (剪贴板只保留一份 mime
   载荷), 表现为"复制成功但剪贴板 0x0"。另外 **offscreen 后端的 `clipboard.image()` 恒 0x0** →
   剪贴板类断言必须放**真桌面**(DISPLAY=:0)跑, offscreen 里只能验 mimeData/逻辑。
   ⚠️ 同族坑: 在 DISPLAY=:0 下**先 import cv2 再 import PyQt5** 会抢走 xcb 插件 (报 "Could not load the
   Qt platform plugin xcb") → 测试脚本里 PyQt5 必须最先导入。

## 📋 画布节点「右键打开新窗口」标准做法 + 汇总终端 (2026-09-24 外观质量检测实测)

**三处接线 (缺一处点了没反应/无菜单项)**:
1. `simulink_module.py` `SimCanvas._show_node_menu`(RightButton 分支) 加菜单项, 触发条件用**节点名子串**
   (`"外观质量检测" in item.node.get("name","")` 或 `params.<flag>`; 同 YOLO 的 `"YOLO" in name`)
2. 同函数下方**动作分派链**加 `elif a_xx is not None and chosen == a_xx:` 分支, 帧源跟随画布:
   `_src = "sim" if _canvas_src_state(self.module) == "仿真" else "real"`
3. 新窗口模块 `tools/gui/<name>_widget.py` 暴露 `open_xxx(parent, module=..., source=...)` (单实例复用:
   类属性 `_cur` 存实例, 再开先 close)
4. ⚠️ 改完 GUI **必须重启** (`bash tools/studio_ctl.sh restart`) 入口才活; 日志 `Traceback|Error` 计数=0 才算通过

**汇总终端窗口骨架 (质量检测汇总终端为样板)**: 三行头 (①技能行 ②标定行 ③数据/训练行, 全常显) +
QSplitter(左画面 `YoloLabelWidget` / 右面板 判决表→定位→缺陷清单→训练日志) + 状态栏 (链路/判决/导出);
快捷键 `Enter/N/F/G` 且**焦点在输入框时不抢键**。

**复用既有件 (别重写)**: 标定控件 `yolo_label_widget.YoloLabelWidget`(拖框/缩放/右键删/撤销) ·
数据层 `yolo_annot_dataset`(`save_sample/build_dataset/check_dataset/iter_samples/add_class`) ·
训练 `yolo_annot_train.py`(体检不过退出 2, 训练后真推理验证)。

**四个实测坑**:
1. **`save_sample` 的 boxes 契约是 5 元组 `(x1,y1,x2,y2, cls_id|cls_name)`**, 不是 `(box, cls)` —
   传错在 `float(b[2])` 处炸, 被 try/except 吞成"保存失败"(静默), 排查时先看落盘数没涨。
2. **QProcess 信号里别引用 `self._proc`**: 进程结束时 C++ 对象已删 → `RuntimeError: wrapped C/C++ object
   has been deleted`。用默认参数绑进闭包 `lambda pr=_p: ...`。
3. **关窗必须收口**: `closeEvent` 里 `disconnect()` 三个信号 + 若在跑则 `kill()`; 否则进程收尾信号打到已销毁
   控件 → RuntimeError → **进程 abort (core dumped)**。`log()` 也加 try/except 兜底。
4. **`load_frame_file` 要分支视频**: `cv2.imread` 读不了 mp4 → 走 `cv2.VideoCapture` 取首帧。

**验证套路 (两层, 记取"offscreen 全绿≠人能用")**:
`tools/verify_aoi_console.py` (offscreen: 入口可达性 `isVisible() and isEnabled() and width()>20` · 四技能判决表 · ROI 拉伸尺寸 ·
标定落盘计数 · 体检 · 构建数据集 · 导出 · **真训练 smoke 产出 best.pt**) +
`tools/verify_aoi_console_real.py` (真桌面: 窗口在 availableGeometry 内 · 按钮 `width() ≥ sizeHint().width()` · 截图)。

## 🌐 功能清单/测试用例 → 网页 (datadrive.world, 2026-09-24 新增 L2 专项页)

**真源三处 (改功能/用例只改这三处, 网页全部自动带出)**:
| 内容 | 文件 | 关键点 |
|---|---|---|
| 功能定义 | `src/lerobot/verification/capability_levels.py` | `CAPABILITY_LEVELS[层]["funcs"]` = {fid,name,desc,groups} |
| 测试用例 | `src/lerobot/verification/verification_layer.py` | `FEATURES` 元组 `(id,域,名称,源,方式,方法,层)` + `FEATURE_META[id]=(kind,role,spec)` + `def t_F_B12(self, np)` 真断言 (返回 `(bool, 详情str)`) |
| 分层功能树 | `src/lerobot/verification/node_func_tree.py` | `NODE_TREE[节点key]["funcs"]` 每 func 带 `tests:[(名称,auto/semi/manual,方法名,备注)]` |

**生成 + 部署 (深色主题 #0d1520/#00d4aa, 打印友好)**:
- 功能清单总表 + 需求规格书: `tools/gen_web_feature_pages.py` → `reports/web/{function-list,requirements-spec}.html`
- 专项页 (L2 3D视觉引导/触觉反馈闭环, 含 Markdown 导出): `tools/gen_l2_guide_tactile_page.py`
  → `reports/web/l2-guidance-tactile.{html,md}`, 顶部按钮「⬇下载 Markdown / 📋复制 Markdown」,
  **现场真跑**两条用例把 PASS+实测明细写进页面 (`--no-run` 跳过)
- 上传: `ZMAX_ECS_PW=<密码> python <工具>` 或 `sshpass -p <pw> scp 文件 root@39.102.211.79:/www/wwwroot/datadrive.world/` + `chmod 644`
  (**22 端口**; 23 端口连不上) → 复核 `https://datadrive.world/<页>.html`
- ⚠️ **主页 `index.html` 只在 ECS 上, 仓库里没有源**: 改导航要 `scp` 拉回本地 → 本地 patch (锚点断言 count==1) → `scp` 回传 → HTTP 复核
- 计数类文案别手写: `tools/canvas_update_verif_nodes.py` 从真源重算并刷新画布 `ssfeat`/`sstest` 的 `desc`
  (加用例后 "B六层 11" 这类数字会过期; 该脚本幂等, 改画布前先 `bash tools/studio_ctl.sh stop`)

**测试用例写法纪律**: 阈值必须**先实测再写** (`tools/measure_l2_guide_tactile.py` 这类量测脚本先行),
断言里带上"判据 + 实测值"字符串; 口径不确定时先核对真源 (实例: 触觉通道 0 = 原始开度, 轨迹 gripper = 夹紧度 = 1−开度
→ 必须用**互补一致率**断言, 按"相等"比会得 0%); 未实现/占位通道要**如实标注**不得冒充。

## 架构速查

```
tools/gui/
├── studio.py              # 主程序 (PyQt5) — 入口
├── docs_sync.py          # 文档同步系统 (GitHub API + 分类 + 版本追踪)
├── ppt_engine.py         # PPT 指令引擎 (PPT作为控制台指令源)
├── update_checker.py     # 自动更新检查 + 下载升级
├── Dockerfile             # 轻量 X11 挂载容器化
├── Dockerfile.win         # Wine 交叉编译 (备选)
├── docker-run*.sh
├── version_sync.py        # 版本信息面板
├── training_backend.py    # 训练后端
├── hardware_simulator.py  # 硬件仿真
├── inference_client/server.py
├── dataset_viewer.py
├── le_robot_studio.py     # 简化版
└── le_robot_home.py

.github/workflows/
├── docker-console.yml     # CI: tag v* → build → push 阿里云 ACR
└── build-win-exe.yml      # CI: tag v* → PyInstaller .exe → Release
```

**三层解耦架构**: Sys-0 ← Sys-11+12 ← System 2

**9 大模块**: 系统架构 / 数据集 / 训练 / 推理服务 / 硬件仿真 / 评估 / 配置中心 / 实时监控 / 插拔场景

## 常见操作

> 📄 全部常见操作 (训练/评估/视频/报告/飞书/配置表/画布节点/数据集 等) 见
> `references/common-operations.md` — 2026-08-25 从本文件拆出 (SKILL.md 曾撞 10 万字符上限)。
> UI 尺寸适配 (按钮太小/字挤/面板太窄/高分屏) 见 `references/ui-sizing-hidpi.md`
> (含实测探针 `tools/probe_ui_metrics.py`)。

## 陷阱
> 📌 **Orin 生产设备红线 (2026-09-16 老倪: 「不要在orin上增加新程序…你先只是转发orin的感知信号」)**:
> Orin 侧**零自研程序零自启** (我此前放的 ss_edge/ss_shadow/ss_infer + crontab `@reboot` 已全清);
> 采集改走 **4060 侧 Docker 远程只读订阅** (`ros:humble --network host` + `ROS_DOMAIN_ID=0` 可直读 Orin 生产话题,
> 实测 tcp_pose 49.79 Hz / real_joint_states 100.43 Hz); 采集节点 `enable_rosout=False` **零发布** (self_publishers 自证,
> `/parameter_events` 关不掉要如实说明); 标定桥 z7 缺现场几何 → **拒算不编造**。细节 + 两坑
> (`ssh` 上 `pkill -f` 模式串出现在自己命令行会自杀 → 锚定 `^python3` 或按 PID; `/tmp` 备份会被清理 → 写 `~/zmax_data`)
> 见 `references/orin-zero-program-remote-read-2026-09-16.md`。
> 📚 历史细节(2026-08-05~09-14: 三模型对比下半场 · CrossAttn/子系统 · auto_loop 闭环守护 ·
> 多分身共享 git · 画布边与代码通路一致性 · 记忆层集成阶梯) 已搬到
> `references/history-2026-08-and-09-details.md` —— 需要过程/实测数字时按需读。
> ⚠️ **2026-09-14 追加 (v5.5.48, 这条把上面两条都盖住了)**: 记忆层当时**被喂错了坐标系** ——
> 桥传 `s.peg_head()`, 而冠军轨迹/引擎肌肉记忆用**夹爪真实位置** (引擎 `self.x = obs[0:3]`,
> state_space_sim_real.py:634)。同一 seed 下两者差 (0.017,0.054,0.176)m ⇒ 势场在**自己坐标系之外**求梯度,
> 意图=噪声。所以"记忆层没效果"主要是这个 bug, 不是(只是)权重问题。
> **判据/自查**: 用 `tools/mem_field_probe.py` 打坐标系对照 —— 同源时 `d_perp` 应 ≈ 0 (~1e-4),
> 异构时 ~0.13m; 同源时相位会正常 SK01→SK07 推进。**任何"记忆层没效果"的结论, 先查这一条**。

---

## 🧠 v6: 让 L4 的 INTACT **看到并复用 L2 原子技能** (2026-09-14 老倪下令, 已落地)

**契约 (改顺序=换版本)**: `skill_ctx` 24 维 = `[引擎相位 one-hot(13) | L2 势场技能软权重 w(8) |
d_perp(1) | arc_frac(1) | grip(1)]`, 单一事实来源 `src/lerobot/policies/intact/skill_ctx.py`
(采集器 `tools/intact_insert_dataset_v5.py` 与闭环桥 `tools/intact_sw_optical_bridge.py` **共用同一函数** →
训练/推理同口径; 有 `tools/skill_ctx_consistency_check.py` 做同口径回归)。

**模型侧零回退构造 (关键)**: `IntentActionActor(skill_dim=24)` 新增 `E(s)` 分支, 但
①`skill_dim: 0` 是默认值 → 参数形状与老配置逐字节相同, 老 ckpt 仍能 `strict` 加载;
②打开时 `skill_enc` 末层**零初始化** 且 入口层 `net.0.weight` **老列逐位复制 + 新列置零** (缺后者
暖启动会差 0.43 — 入口层形状变了被部分加载跳过, 随机初始化污染全网络, 自检检查 C 抓出来的);
③`get_action` 里 skill_dim>0 却缺 skill_ctx → **直接报错, 不许静默降级**。
自检: `INTACT-JEPA/tools/intact_skill_channel_check.py` 五条闸全过才算接上。

**"有提升"判据 (老倪 09-12 口径)**: 同一权重同一批真帧跑 `--skill on` vs `--skill zero` (全零消融)
→ 判三条: 赢常数基线 ∧ `MAE(on) < MAE(zero)` ∧ 预测std/教师std ≥ 0.30。
哨兵 `/home/ubuntu/.hermes/scripts/v6_judge_watch.py` (cron, 静默无新 ckpt)。

**坑 (踩过的)**:
- `project_polyline()` 返回 **(最近点, 距离, 弧长, 段号) = 4 元组**。按 3 元组解包 → 每帧 ValueError
  → 被引擎 `_frame_sink` **静默吞掉** → part npz 里**整列 skill_ctx 都没有**, 而日志一切正常 ✗✗
  (老倪红线: 静默降级 = 白做)。教训: sink/回调里的构造失败要显式 raise 或至少记 `_SKERR` 进 meta。
- 采集器 flush 时 `np.savez_compressed(p, **kw, ...)` —— `kw` 忘了 `**` → pixels/action/observation
  全不落盘, 文件只有几 KB 而日志说"窗口 18" ✓ 假成功。**落盘后必须验 keys + 帧std>5**。
1. **场权写死太低**: `blend_action` 里 `w = w_max·max(conf, w_floor)`, 桥用 `w_max=0.5`, `w_floor=0.2`,
   而现场 `conf ≡ 0` (离最近轨迹管 207mm) ⇒ w̄ 恒 = **0.1** → 10% 的场权扳不动 600mm 模型误差。
   已修 (增益调度): `far = clip((d_perp−d_near)/(d_far−d_near),0,1)`, `w = max(w_max·max(conf,w_floor), w_far·far)`,
   默认 `w_far=0.85, d_near=30mm, d_far=150mm` —— **在管内维持原公式 (不回退), 远场让场主导**。
2. **模型动作塌缩**: `IntentActionActor` 输入 = 潜槽 (z_t, m_t, z_t·m_t) + a_{t-1} 嵌入, **没有本体/几何输入**;
   而数据集 `optical_insert_v4.h5` 里明明有 `observation` (39D) —— 但 `grep observation train.py jepa.py module.py`
   **零命中 = 这个状态通道从来没人消费**。亚毫米插入能从 224²/patch14 的潜空间补出来吗? 补不出来 →
   动作头预测条件均值 → 幅度只有教师 7~22% (v3/v4/v5 全如此) → 输给常数基线。
   → 这是"模型直驱"这条路的天花板, 也是**记忆层势场存在的意义** (Φ 用引擎真几何/冠军轨迹建)。

**其它落地铁律**:

老倪口径: "集成 L2肌肉/L3流程/L4工作/总装记忆… 稳步推进… 要看到最终成功抗干扰的插拔… 能力要稳步提升不要波动,
数据一致性最重要"。落地三条铁律:

1. **抗干扰必须真注入** (本次查出的关键缺口): 桥原来 `sim.run(max_steps=…)` **不传 cap** → 引擎 `_jitter_on=False`
   ⇒ L4 链从来没被注入过干扰 (引擎里只有 `cap=='l4'` 才注入来料移位/转向 ±3.5cm/±15°物理/90°转台视觉 + 恢复预算×2)。
   现在桥有 `--cap {l2,l3,l4}` 并透传 → **解析链与模型直驱同吃一份干扰** (同口径); 每格结果必须记真实干扰元数据。
2. **同口径阶梯台** `tools/mem_ladder_integration.py`: 每次跑先冻结 manifest (权重 sha256+epoch · 反归一化 stats
   sha256+action_space · 记忆开关快照 · 引擎/桥/势场源码 sha256 + git rev) → manifest_hash 不同就是不同历史行;
   矩阵 = 5 臂 (off/L2/L23/L234/assy) × 2 干扰档 (none=cap l3 / disturb=cap l4) × N seed, **每格跑完 append**
   → 断点续跑; 6 道闸: N1 L2 准确性 / N2 L23≥L2 / N3 抗干扰 (干扰档 ≥ 自身无干扰 −1/n 且 ≥ off 干扰档) /
   N4 总装 ≥ 任一臂 / N5 零搜索 (candidate_sequences=0 且 调用/步≤1.05) / N6 稳定 (跨 seed 深度 std≤25mm)。
   历史 append-only `reports/mem_ladder/ladder_history.csv` → 跨 ckpt 同一格直接对比 = 能力提升可追溯。
3. **无人值守**: `~/.hermes/scripts/mem_ladder_watch.py` (no_agent cron 每 20min, 静默=无变化): 崩溃格报告 /
   进程死且格未跑完**自动重启**(阶梯可续跑, 所以重启安全) / 新汇总结论推飞书。
   ⚠️ cron 建任务时 schedule 必须写 `every 20m` (只写 `20m` = 一次性!)。
4. **语义提醒**: 引擎在干扰轮会**主动旁路 L2 肌肉记忆** (标杆按摆放固化, 布局变了标杆失效 → 正确降级全精算伺服)。
   即"抗干扰"这档本来就主要靠 L3/L4, 阶梯表里干扰档 L2 介入下降是**预期**而非回退 —— 但要在报告里说明, 不能当卖点。

## 🚀 L4 INTACT 策略化 + 连线 (v5.5.40, 2026-09-13 — metaworld → INTACT → decoder → L3)
老倪: 「将 INTACT 接入 L4 层, 把 L4 节点的 INTACT 代码迁移到 src/lerobot 的 policies 文件夹, 做好连线;
数据源直接接入 metaworld, 输出接一个 decoder 再进 L3; **不能让原有 L2 L3 能力下降**」。
- **代码落位**: `src/lerobot/policies/intact/` = `configuration_intact.py` (注册名 `intact`) +
  `modeling_intact.py` (`IntactPolicy`: select_action / predict_action_chunk / predict_intent;
  `forward()` 显式 NotImplementedError = 不假装本仓能训) + `decoder.py` (`IntactIntentDecoder`) +
  `runtime/` (**原 `src/lerobot/manifold/intact_node/` 整体 git mv 进来**, 实现一字未改)。
  旧路径 `manifold/intact_node/__init__.py` 只剩兼容转发 → 桥/自检/引擎/工具零改动。
  注册三处: `policies/__init__.py` · `factory.get_policy_class("intact")` · `PreTrainedConfig.register_subclass`。
- **数据源直连 metaworld**: `runtime/metaworld_source.py` → `MetaWorldSource` (MT1 peg-insert-side-v3 ·
  camera corner2 · `env.render()` 224² 真渲染 + `_get_obs()[:39]` 现场读 + 本域真实目标帧
  `reports/intact_goal_frame_optical.npy`), 注册名 `metaworld` (与 `l4_episode`/`official` 并列)。
- **解码器两路** (`decoder.py`): ① `u_ff` 先验 4D = `act×K_ACT` (K_ACT **现读引擎源码**, 量纲逆运算,
  **无需标定**) ② L3 流形条件 = 需 `models/intact_l3_map.json` (闸值 R²>0.3 且 null<0.1);
  未标定 → **拒绝返回并计数** (`cond_src="拒绝(未标定)"`), 绝不写死映射。
- **画布连线** (77 节点/83 连线): `ssdata →💾→ ssintact`(🎯 INTACT 策略, L4 行) `→ ssintact_dec`(🎯 INTACT
  意图解码器, L4 行) `→ ssdec`(L3 DiT)。**两节点都在 L4 行内 (cap=4) → L2/L3 档根本不执行** = 结构性零回退。
  改 flows/state_space_obs.json 用**文本级替换脚本**(正则锚点 + 断言其它节点逐字段不变), 别 json.load+dump。
- **引擎三档** (`state_space_sim_real.py`, 与既有 `SS_INTACT` 同纪律): 不设 `SS_L4_INTACT` = 逐位零变化 /
  `_SHADOW=1` = 影子(真渲染帧→真推理→真解码→记录, 不接管) / `=1` = 按 w 融合
  `u_ff=(1−w)·analytic+w·L4` (w=0 恒等)。取证: `sim.l4_intact_summary()` (calls/reuse/refused/blend/
  w_zero/frame_std/shift/goal_src/u_ff_src/l3_cond_src/err)。
- **工具**: `tools/l4_intact_ab.py` (A 关 / B 影子 / C 接管, **逐臂子进程**隔离 env, 同 seed 同 cap) +
  `tools/l4_intact_arm.py` (单臂) + `tools/verify_l4_zero_regression.py` (画布执行集按档位对比 git HEAD)。
- **实测**: 节点级真跑 (真权重 trained=True · chunk(8,8) · `candidate_sequences=0` 零搜索 · 1396ms/步 CPU ·
  动作维自动对齐 4→8); 三臂 seed0/1 700 步: A `dist 0.0186/0.3891` · B **逐位相同** + 真推理 78 次 ·
  C `0.126/0.1221` + blend 700/700 步 → **无提升证据** (只证明通路真在跑, 提升待 v5 权重配对复验)。
  零回退: L2 档 55 / L3 档 60 节点逐 id 不变, 原有 80 连线全在。
- **两个必修的坑** (A/B 首轮抓到): ① 未设 `STABLEWM_HOME` 时桥退回 `<repo>/.cache` → 权重全找不到
  (`FileNotFoundError: Checkpoint not found`) → adapter 改为优先共享缓存 `stable-wm-cache`;
  ② 引擎"直喂帧"路径没人设 goal → `goal_displacement` 每帧 `ValueError` (**影子臂 60/60 次"真推理"实为空转,
  计数照涨**) → 节点加 `ensure_goal()` 三级兜底 (已 set_goal > 数据源自报 > 默认目标帧文件), 兜不到才显式报错。
  **教训: `calls>0` 不能单独当"真接入"证据, 必须同看 `err`/`reuse`/`u_ff_src`/`goal_src`。**
- 复现: `INTACT_RUNTIME=root INTACT_DEVICE=cpu INTACT_POLICY=intact_goal_optical_insert_v4_s3072/weights_epoch_2.pt
  gui-venv311/bin/python tools/l4_intact_ab.py --seeds 0,1 --max-steps 700 --cap l4`
  · 设计 `docs/design/zmax_l4_intact_policy.md`

### 🎨 画布排版硬规则 (v5.5.41 — 改 flows 坐标前必读, 否则算出来的摆位全废)
画布**加载时会自己重排**, JSON 里的 x/w 只是输入:
- 普通节点最小 **w≥280 / h≥110** (`simulink_module.py:5146/5147`) + `autofit_node_width` 撑宽到不裁字(≤380)
- `_relayout_row_gaps(min_gap=56)` (12044 行): 按 **`round(y/60)` 分桶**, 桶内按 x 排序, 后一个节点必须
  `x ≥ 前一个.x + 前一个.w + 56` (**行首 x 不变**) → 想让某节点 x 自由, 就把它放到**不同的 y 桶**里
  (差 ≥60 即可分桶; 但 110 高的框要差 ≥110 才不重叠)
- 连线端口: 起点 `ax = src.x + src.w`(源右缘), 终点 `bx = dst.x`(目标左缘) (`SimLinkItem._path:3298-3305`)
  ⇒ **"右出线连到左入线" 判据 = ax > bx**; 要竖直线 ⇒ `src.x+src.w == dst.x`
- row_bg 行带加载时会被统一左移到 `minx-266` 并右界不变 (5174-5190)
- 所以: 布局要**按规则反推坐标**; 改完必须用真画布取证 ——
  `QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_l4_layout.py`
  (加载真画布逐条量 ax/bx + 渲染 PNG) 而不是只算 JSON 里的 x/w
- 教训 (本次踩到): 我先按"配置坐标 = 渲染坐标"排了一版 → 画布把同行节点右推 36px, 那条线照样倒退。
  量出来是 `240+300+56=596` 的规则在起作用。
- **端口 slot 只认 link 数组先后, 与 `in1/in2` 命名无关** (`SimLinkItem._path:3289`):
  `ay = src.y + h·(i+1)/(n+1)`, `i` = 该连线在该节点**出/入线里的序号**, `n` = 总条数。
  所以"让连线整体不乱穿"的正解 = 把 `flows/*.json` 的 **`links` 数组按 `(src.y, src.x, dst.y, dst.x)` 全局排序**
  (同一节点的出线/入线 slot 就单调于来向 → 两两不交叉), 排序对逻辑零影响; 想改端口几何就调 link 在数组里的位置。
- **用户视角加载路径 = `open_state_space()`** → `load_flow_file()` **+ `_relayout_row_gaps()`** (11140 行)。
  取证脚本必须显式补调一次 `m._relayout_row_gaps()` —— 少这一次, 量到的就不是用户看到的画布
  (本工具早期版本踩过: 反向线少报 1 条、方框重叠多报 15 对)。
- 工具: `tools/relayout_canvas_l4_row.py` (可复跑摆位: 备份 + 坐标表 + 全局连线排序) ·
  `tools/verify_l4_layout.py` (真画布体检: ①反向 ②重叠 ③穿框 ④交叉 ⑤关键链 ax/bx ⑥L4 区+全画布 PNG)。
- **"变成一层"的代价要诚实说**: 老倪要 L4 一层 ⇒ 5 个节点同行 ≈1660px 宽 ⇒ 下游 (DiT/前馈/状态机/执行器/
  物理世界/验证/可视化) 必须依次右移 (本版画布右界 +1300px); 且两个**语义闭环回流**线
  (物理世界→状态校正器 `↩观测反馈`, 引擎→渲染源 `↩渲染回流`) 天生反向, 消不掉, 只能标 `↩`。
- L2 技能行 11 节点 (通用算子 A/B/C + SK01-08) = 3640px 行宽 > 执行器 x ⇒ SK04-08→执行器 5 条反向;
  正解是**把执行器挪到该行尾右侧** (不是拆成两行 —— 老倪明确要一层), 顺带 +185px 让 L4→通用算子的出线也前向。

## 🧲 分层记忆势场 (v5.5.38, 2026-09-13 — L2/L3/L4 + 总装机记忆联络, 与 L4 INTACT 链对接)
老倪: 「把势场逻辑实现到 L2肌肉记忆 / L3工艺流程记忆 / L4物理工作空间记忆 / 总装机记忆的联络策略,
然后逐步打开每层记忆提高 L4 INTACT 性能」。
- **统一接口 = 标量势场 Φ(x)**, **−∇Φ = 意图** (不传技能标签)。L2 `Φ_SK` (谷底=冠军轨迹真末点, σ=谷宽,
  λ=4·k_att·σ², 锥形项 k_lin=3·k_att·σ) → L3 `Φ_process=Σw_k(t)Φ_SK` (Σw≡1, raised-cosine 交叉淡入) →
  L4 `Φ_global = Φ_process + Φ_obstacle(孔壁/台面现场几何) + Φ_world(世界模型预测项, 未接恒 0 且标记)`。
  代码 `src/lerobot/memory/potential_field.py`, 画布节点 `🧲 总装机记忆 · 势场联络` (mem_nodes::node_ss_mem_field)。
- **逐层开关 = data/memory_layers.json** (`L2/L3/L4/assembly`, **默认全关**): 全关 → compose=None /
  blend_action **恒等** (零回退, 可断言); 开层后 L4 INTACT 链按 `u=(1−w)u_model+w·u_field`,
  `w=w_max·max(conf,w_floor)` 混入 −∇Φ 意图; **相位按状态判** (时钟进度与模型直驱不同步)。
  台账 data/assembly_memory.json; 仲裁: 接触段 L2 优先 / 自由段 L3 优先。
- **实测 26/26** (真数据: muscle_memory 7 条冠军轨迹 + 引擎真几何): 梯度误差 1e-9 · 横向势单调 ·
  收敛 98~127 步到 <1mm 且 Φ 严格降 · Σw≡1 · 孔壁斥力双向正确 · 逐层开关逐项生效。桥 e2e: 全关 0 介入 / 开 L2 介入 120/120。
- **⚠️ 三个必须记住的设计约束 (都踩过)**: ① 谷底只能取 champ_x 末点 — muscle_memory 的 io.entry/exit
  **锚点不同源** (差 15~145mm, SK06/07≈PEG_HEAD_OFF_XY=0.13), 用 io.exit 当谷底会导致场的最小值不在谷底 → 不收敛;
  ② λ 必须按 λ=4·k_att·σ² 归一 + 加锥形项 k_lin, 否则短轨迹会出现离谷底 3~5mm 的次极小 (流量停住);
  ③ muscle_memory.json 是**活数据** (rollout 会更新), 判据数字会漂移, 别写死。
- 📄 详见 `references/memory-potential-fields-2026-09-13.md`

## 🌍 L4 · 光模块插拔链 (v5.5.37, 2026-09-13 — 红方块抓取 → 光模块抓取插拔)
老倪: 「把红色小方块的抓取实验, 改造成光模块的抓取插拔实验」。
四节点与 cube 链**同构**, 只换任务: 🧪 环境渲染图像源 → 🎯 INTACT 插拔策略 (本域微调) →
🌍 Z-MAX 引擎 RealStateSpaceSim (metaworld 真物理) → 🎬 插拔渲染视频。
- **切任务** = `data/intact_sw_task.json` (`optical_insert` 默认 / `cube` 保留), **不埋代码分支**;
  `data/intact_sw_policy.json` 可指定 policy/stats/mode/seeds/device。cube 旧桥不删。
- **两个 venv 分工**: 引擎跑 `gui-venv311` (只有它有 metaworld), 模型由 `IntactRuntime` 起
  **INTACT venv 子进程** (gui venv 无 torch 链)。cube 链相反 (env 在 INTACT venv 里)。
- **动作口径**: v4 数据集动作列 = `sim._u_vec` (m/s) → 闭环必须按引擎自有约定还原
  (`act[:3]=clip(u/K_ACT)` · `act[3]=CLOSE if u[3]>0.5`) 再给 `env.step`; 统计用
  `tools/action_stats_from_h5.py` **现算** (权重/统计同源, 不许手写)。
- **⚠️ 最坑: stale status 竞态** — 上一轮 status.json 还是 `stage=done` 时, 节点等待循环首轮即
  判"本轮跑完" (实测光模块链读到 cube 终态: env=OGBCube / 52 帧 / cube 视频, 校验全红却查不出因)。
  修法: `_sw_start` 在 Popen **之前**先写 `{"stage":"starting"}` 作废旧状态。
  判定法: 报错里出现"上一轮的任务名/帧数" = 读到旧 status。
- **验收**: `tools/verify_l4_optical_chain.py` 节点级 11/11 (真跑整链): 1800 帧 · 1800 次真推理 ·
  frame_std 56.5 · 解析链 2/2=100% (插入 65.13/64.78mm · 全链插→拔→AOI=True) ‖ 模型直驱 0/2 (过冲) —
  与离线判闸一致 (预测std 仅教师 7~16% = 塌均值), **模型能力问题非接线问题**, 日志/status 诚实标注。
- **判闸根因 (配置级, 非训练量)**: ① `loss.intent.local_weight=0.1/goal=0.05` 而 `forward=1.0`
  → actor 几乎不发声; ② `min_log_std=-5.0` → std 可缩到 0.007, "输出均值+极小方差"就是 NLL 最优解
  ⇒ 塌缩是最优解。对策 = `intact_goal_optical_insert_v5.yaml` (权重 1.0/1.0 + min_log_std -2.0)。
- **训练接力**: `train.py` 写死 `timeout 14400` (4h) 而 12 epoch 要 ~9.2h → 必被 SIGTERM (v3 死因 rc=124);
  `l4_ab/train_intact_optical_chain.sh` 从最新 ckpt 换名续训到累计 TARGET epoch (CFG/FAMILY_V/TARGET/PER_RUN/DEADLINE)。
- 📄 全部细节 (桥执行流/坑清单/命令) 见 `references/l4-optical-insert-chain.md`

## 🌍 L4 · SW 仿真世界引擎链 (v5.5.28, 2026-09-13 — INTACT cube 集成进状态空间)
老倪: "把独立的 INTACT 运行环境集成到状态空间中, 点击运行就能跑 INTACT, 触发开关是 L4"
- **链条 (独立, 只增不改)**: 🧪 SW环境渲染图像源(数据源) → 🎯 INTACT策略·cube(中间) →
  🌍 SW仿真世界引擎(硬件层) → 🎬 SW渲染视频(可视化) = 4 节点 + 1 个 row_bg + 4 连线
  (flows/state_space_obs.json 文本级插入, 保持原缩进; 原有 70 节点/72 连线一字未动)
- **L4 触发开关 = 复用既有档位机制**: 节点落在名字含 "L4" 的 row_bg 色带内 →
  `_ss_node_cap_level()` 直接返回 4 → 只有 L4 档的单步/播放链执行它。**不需要新代码分支**,
  L2/L3 档零影响 (offscreen 实测 L2/L3 节点全在)
- **桥 = tools/intact_sw_bridge.py (跑在 INTACT venv, 跨 venv 子进程)**: 与 paper_runtime
  eval 逐行同源 (同 World / load_pretrained / PriorOnlySolver 零搜索 / _extract_init_goal +
  _apply_callables / img_transform + StandardScaler); 唯一区别 = **逐帧流式**
  (spool/*.jpg + status.json) + 末尾官方 `save_panel_videos` 出 3 面板 (agent|dataset|goal) mp4
  + concat 合集 = 「从 stable world 取出的 3D 视频」
- **⚠️ 三个实测坑 (都踩过)**:
  ① 桥**必须**用 INTACT venv 解释器 (`/home/ubuntu/INTACT-JEPA/.venv/bin/python`); 仓库 `.venv`
     没有 numpy/torch → `ModuleNotFoundError: No module named 'numpy'` (症状: bridge.log 尾部报错,
     status.json 永不出现)
  ② `_sw_paths()` 返回序是 **(dir, frames, status, video)**; 解包错位 (`_, st, fr, vd = ...`)
     会静默把 frames 当 status → 三个节点同时报 "桥进程已退出, stage=None" 却查不出原因
  ③ 桥跑完会**退出进程**, 此刻 status 可能正处 `os.replace` 瞬间 → 读到 `{}`。正确姿势:
     节点顺序链里**第一个节点负责启动桥并等到 `stage=='done'`**, 后续节点只读终态;
     `_sw_wait` 里加"进程死亡 → 再读一次终态 → 才判定失败"并打印 bridge.log 尾部
- **验证脚本**: offscreen 画布载入必须**按节点名匹配** (载入器会重生成 node id,
  用插入时的 id 查不到); 端到端真跑实测 13.6s / 52 帧 / frame_std 30.26 (>5 真图) /
  模型真调用 52 次 / candidate_action_steps=0 / 4 个视频文件

## simulink 工程完整性检查 (2026-08-28 v3.3.1, 老倪: 全面检查)
新增 `tools/ci/zmax_integrity_check.py` 一键检查器, 五项全绿:
1. **NODE_TYPES 三处同步** (simulink_module 15种 = validate_flow = simulink_ci) —
   曾不同步 (主15/验证6/CI8) → 画布 type=data/scene/row_bg 被验证器误判"非法"。
   新增节点类型必须三处同步 (老规矩, 检查器自动验证)。
2. **状态空间/业务闭环豁免**: flow_x.json/cooperation_closed_loop 的环是架构反馈
   (卡尔曼校正/感知-决策-执行/供应商区-实验室-现场), 非错误 — validate_flow 和
   simulink_ci 均降级警告。普通模板有环仍 FAIL。
3. **check_params 语义级校验**: 原只有类型白名单 → "pos":"not-a-list" 误判通过。
   PARAM_SCHEMA 只收确定类型的控制参数 (Kp/K_ff/Kd 数值; limit 兼容单值/区间;
   force_res="0.1N"/grid="7x9" 是文本; encoding 是 dict; in_dim/frames 可能是
   描述文本 '39D obs+4D action' — 实测校准, 不可一刀切)。
4. **check_ports 隐式端口兼容**: 真实画布节点无 outputs/inputs 字段 → 原代码
   p["id"] 对字符串索引 TypeError → 无端口列表的画布跳过。
5. **check_format 降级**: 合作闭环 (zmax-cooperation-closed-loop)/旧格式
   (hermes-flow) 模板硬判 FAIL 误伤 → warn 尽力校验。
模板加载验证: offscreen 下 SimulinkModule 构造后 monkeypatch `_qmsg_yes/_qmsg_info`
(否则第二个模板弹确认框 exec_ 卡死), 逐个 load_reference_app 断言 nodes==items。
**共享节点设计**: Model Zoo 的「🧩 结构条件」(无·后缀) 在 load_reference_app
4685 行被显式跳过 (已下放各模型行), 不进 layout 是正确设计 — 检查器要豁免它。

## VSCode 断点调试 node_logic 坑 (2026-08-31 老倪: "点运行进不了这个函数的断点")
- **症状**: 节点逻辑真实执行了(终端出现该函数日志如 "📦 数据源:")但 VSCode 断点不命中。
- **根因 ①(最常): node_logic 可修改区动态 exec** — 在 GUI「查看/编辑节点逻辑」里保存过 → `save_node_logic` 把 `NODE_LOGIC[key]["fn"]` 替换为 `exec(compile(new_code, "<node:key>"))` 出的函数, co_filename=`<node:data>` **无真实行号 → VSCode 磁盘文件断点永不命中**(函数照常执行)。判定: 断点红点空心/灰 = 未绑定。
- **根因 ④(2026-09-01 实测, py-spy 铁证): 引擎内部断点堵死播放 — ▶运行 = 先同步跑引擎 sim.run()(500步, 含传感器融合 fuse_sensors 等真实源码) → 引擎返回后才 _ss_tick 逐节点播放(80ms/节点)**。在 src/lerobot/policies/left_right/state_space/*.py (或 yolo_3d) 设的断点会**先于任何节点逻辑命中**, 主线程冻结在引擎里 (debugpy do_wait_suspend) → run() 不返回 → _ss_tick 永不启动 → 数据源等节点断点"永远进不去" (GUI 日志停在引擎阶段, 无"⏩ 数据源节点优先"/"▶ 仿真开始")。判定: `sudo py-spy dump --pid <gui>` 主线程栈 do_wait_suspend ← fuse_sensors ← _build_obs ← run ← _start_state_space_sim。解法: 删引擎内部断点 (只想调试节点逻辑时); 想调试引擎就接受每步都停 (500 步)。
- **根因 ⑤(2026-09-02 实测): spec_from_file_location 动态加载的模块断点不绑定 — 函数真实执行 (日志有输出) 但 VSCode 断点不停**。debugpy/pydevd 对"断点设置时文件未加载"的模块断点不生效 (import hook 捕获不到 spec_from_file_location 绕过 meta_path 的加载; 预加载到 sys.modules 也无用 — 同样绕过)。**解法: `exec(compile(src, 真实文件绝对路径, "exec"))` 加载 → 函数 co_filename 指向真实文件, debugpy 按路径查表必命中 (与引擎 perception/cognition 断点同行为)**; exec 的命名空间必须注入 `{"__file__": 路径, "__name__": ...}` (数据层 _repo_root 引用 __file__ 会 NameError)。
- **根因 ⑥(2026-09-02): 断点设在 def 行/docstring 不命中 — 函数第一条语句是 docstring, def 行无可命中字节码**。**_EXTERNAL_LOC 的 line 参数必须指向第一行实际代码** (不是 def 行); 指引用户断点设在 for 循环/return 等实际执行行, **别设 return None 行** (本机有数据时提前 return, 永不执行)。
- **根因 ⑦(2026-09-02 再实测, py-spy 铁证): 疑似"整机卡死" = 引擎断点挂起, 先 py-spy 判定再动手** — 老倪报"刚才怎么卡死了? 就鼠标能动, 其它都不动" (F5 调试 + 状态空间仿真运行中)。`sudo py-spy dump --pid <gui>` 主线程栈连续 3 次: `do_wait_suspend ← fuse_sensors ← _build_obs ← run ← _start_state_space_sim` — 引擎内部断点每步命中, debugpy 挂起主线程 → GUI 全死 (鼠标=X 服务器画的还能动, 窗口点击全无响应, 连日志都停写)。**判定流程: ①先查系统级 (uptime/负载/内存/D状态) — 系统正常 = 不是整机问题; ②py-spy dump GUI 主线程 — do_wait_suspend = 断点冻结 (删断点即恢复, 无需重启); ③freeze 在 paint 等非断点栈 = 真死循环/重绘风暴**。别急着重启机器 — 删 VSCode 引擎内部断点 (perception.py 等 src/lerobot/policies/left_right/state_space/*.py) 立即恢复。同会话 LiveUSB 无 swap 教训: 31G 内存 0 swap, 内存顶满直接冻结且无 OOM 日志 (systemd-oomd 报 "No swap; memory pressure usage will be degraded") → 防御=加 swapfile, 卡死先 Ctrl+Alt+F3 切 TTY 看谁吃满。**⚠️ LiveUSB overlay 上 swap 不能直接 swapon (Invalid argument — /cow overlayfs 内核不允许), 必须 loop 设备方案**: `sudo fallocate -l 8G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile` → `LOOP=$(sudo losetup -f --show /swapfile) && sudo swapon $LOOP` (实测 8G OK); 开机自启用 systemd oneshot service (ExecStart 里先 `swapon --show | grep -q /dev/loop` 幂等跳过, **别写 ExecStop/swapoff -a — 会把已挂的 swap 全关掉**), enable 后重启自动 losetup+swapon; /swapfile 落 U 盘 casper-rw (sda2 ext3) 持久化分区, 重启不丢。
- **YOLO 首次加载卡主线程弹 not responding (2026-09-02 老倪: "studio.py is not responding 不要跳出来")**: 状态空间播放 YOLO 节点真实执行 → _yolo_ensure_aligner 首次加载模型 10-40s (主线程同步) → 系统弹 not responding。解法: studio.py main() 启动即后台线程预热 `node_logic._yolo_ensure_aligner(None)` (YoloStateAligner 构造纯计算不碰 Qt, 线程安全), 播放时 _YOLO_ALIGNER 已缓存不卡。
- **数据源节点架构 (2026-09-02 老倪: "数据源应该在 lerobot 框架, 至少 datasets 文件夹")**: ss_* 节点 (传感器融合/前馈等) 全部 _EXTERNAL_LOC 映射到 src/lerobot/policies/left_right/state_space/*.py 真实源码, **唯独 data (📦 metaworld 数据源) 曾无映射** — 只是 node_logic.py 的切换开关模板, 右键/断点进的是 tools/gui 控制台文件, 与感知/决策节点不同构。整改: 新建 src/lerobot/datasets/metaworld_data_source.py (probe_data_source 按 DATA_ROOTS 优先级真实探测本机训练仓库 info.json 帧/集/特征; resolve_source 数据源策略; 无 GUI/torch 依赖), node_metaworld_data 可修改区 **exec(compile(真实路径)) 加载真实调用** (co_filename 真实 → 断点命中), _EXTERNAL_LOC["data"]=(datasets 文件, 第一行实际代码, "def probe_data_source")。**新增节点接真实源码的三件套: ①框架层真实实现文件 (policies/datasets) ②node_logic 节点函数加载真实调用 (exec(compile(真实路径)) 保证断点命中) ③_EXTERNAL_LOC 映射 (右键/断点进真实文件, line 指第一行实际代码)**。v3.4.0 落地 (老倪验收: "进到断点了")。
- **右键「打开源代码 / 打开 VSCode」定位优先级 (v5.5.44)**: ① 节点 `params.source` (+ `params.source_symbol` 按符号**现搜**行号) →
  ② `node_logic._EXTERNAL_LOC[key]` 映射 → ③ 都没命中就退回 `node_logic.py` 自身 co_filename (= **GUI 文件**)。
  **坑 (必踩): 代码搬到 src/ 后忘了改 `params.source` / 忘登记映射 → 右键永远停在 GUI 文件**
  (老倪 2026-09-13: 「VEH.5.022 INTACT意图解码器 右键打开 vscode 源代码, 还是原来的 GUI, 你怎么没有跳到
  src/lerobot/policies 文件夹里呢?」—— 这次两条一起犯: INTACT 家族没登记映射 **且** `open_in_vscode()` 当时只认映射不看 `params.source`)。
  **一律给符号名, 不写死行号** (行号随重构漂移, 上次就跳到了 import 区看起来"没跳")。
  自查: `QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_vscode_source_loc.py [节点id ...]`
  (打桩 Popen 捕获 `code -g` 真命令, 断言路径含 `src/lerobot/policies` 且不含 `node_logic.py`)。
- **解法三选一**: ① 右键节点→查看/编辑节点逻辑→「恢复出厂逻辑」(restore_default 从文件重新 exec, 行号真实) ② 重启 GUI(_SOURCE_CACHE 是内存, 重启即清) ③ `ZMAX_DEBUG_BREAK=1` 启动 GUI — execute_node_logic 开头(node_logic.py:124) `debugpy.breakpoint()` 任何节点逻辑执行前强制停, **不依赖断点绑定**, 调试动态 exec 函数唯一办法。
- **执行证据判定法**: 状态空间画布点运行 → 终端出现 "📦 数据源:" = node_metaworld_data 执行了; 有日志但断点没停 = 断点绑定问题(不是代码路径问题); 没日志 = 没执行到(画布/路径不对)。
- **F5 调试端口冲突**: 「🚀 全新调试进程」启动时 debugpy adapter 占 5678(--port 5678 --for-server), studio.py main 里 `debugpy.listen(5678)` 失败被 try/except 吞 → 想用「🔌 Attach 现有控制台(5678)」必须没有 F5 会话; GUI 启动即 listen 5678(main 内, 不阻塞)。
- **GNOME/Xorg 黑屏 (2026-08-31)**: studio.py main 的 `AA_UseSoftwareOpenGL` 软件 GL 在 Mutter 合成器下窗口内容渲染全黑(该行是 WSLg 假死修复, 已注释) — WSLg 环境才需要, 本机 GNOME 桌面不要开; 症状=窗口在但全黑, 关窗后事件循环 quitOnLastWindowClosed 退出(exit 0)。

## 本机推理/仿真环境 (2026-08-30 实测)
- **推理/评估/出视频的 python = ~/lerobot-venv**(项目无 .venv;GUI 用 gui-venv311 无 torch)。
  on_infer_rollout/on_eval_state_space 已改多候选探测: `.venv → ~/lerobot-venv → gui-venv311`。
- **metaworld 3.1.1 + mujoco 3.3.0 + glfw + PyOpenGL + scipy** 已装进 ~/lerobot-venv(2026-08-30)。
  requirements-macos.txt 锁 metaworld==3.0.0(3.0.0 wheel 从 files.pythonhosted.org 下载不稳/中断,未装成)。
- **⚠️ pip/uv 装 metaworld 系列会僵死**(resolver 卡,0% CPU 无网络,杀不掉会一直挂着):
  正解 = `pip download`/curl 拿 wheel → 校验 `unzip -t` → `--no-deps` 安装或直接 unzip 解包进 site-packages → 逐个补缺的 import(glfw/imageio/scipy/PyOpenGL, aliyun 源快)。
- **gen_insert_video 12/12 seed 卡"转移/下降"诊断**: full_pipeline.pt(08-24 fallback)与新 metaworld 3.1.1 物理不匹配 —
  contact_head 预测 0.30-0.41 徘徊达不到 0.5 阈值, 降阈值 0.35 会误进转移但 peg 抓空(peg z 不变)。
  **本机可用 left_right 模型被磁盘红线清光** → 要出视频需训练新模型或从 4090 拉。
- 历史: left_right_20260813_164959(曾验证成功 seed2)已被磁盘清理删除, 勿再引用。

## ⚠️ Windows/macOS exe 3D 无法渲染 = AA_UseSoftwareOpenGL 平台条件 (2026-09-07 v5.0.0, 老倪: "3.2.4 能启动并渲染3D, 之后版本不能")
- **症状**: Windows exe (及 macOS app) 从 v3.3.4 起 3D 视图 (GLViewWidget/pyqtgraph) 无法渲染;
  v3.2.4 及之前 (全平台无条件 `AA_UseSoftwareOpenGL, True`) 正常。
- **根因**: v3.3.4 为修 Linux GNOME/Mutter 黑屏 (软件 GL 在合成器下全黑) 把
  `AA_UseSoftwareOpenGL` **整行注释** → Windows/macOS 无硬件 GL 环境 (虚拟机/远程/无独显驱动)
  3D 无兜底 → 渲染失败。软件 GL 对 Linux GNOME 是毒药, 对 Windows/macOS 打包版是救生圈 —
  平台 GL 策略不同, 不能一刀切。
- **修 (v5.0.0)**: 平台条件启用 — `if sys.platform in ("win32", "darwin"): setAttribute(AA_UseSoftwareOpenGL, True)`;
  Linux 源码版不启用 (GNOME 黑屏修复保留)。studio.py main() QApplication 创建前。
- **铁律**: 跨平台 GL/渲染设置改动 (AA_UseSoftwareOpenGL/AA_UseDesktopOpenGL 等) 必须按
  sys.platform 分叉, 禁止无条件开/关; 打包版 (win/darwin) 优先可用性 (软件 GL 兜底),
  源码 Linux 版优先合成器兼容。老倪验收口径 = 每个发布版都要在**无独显 Windows 环境**
  实测 3D 渲染, 不能只在 Linux 源码版验证。回归判据: 3.2.4 (正常基线) vs 新版本 diff
  里找平台性设置变化。

## Windows exe 画布打不开 = /tmp 打点无保护 (2026-08-28 v3.3.2, 老倪: "3.3.1 3.3.0 无法打开画布, 3.2.4 可以")- **症状**: Windows exe 上 simulink 画布 tab 打不开/空白, 状态栏 "⚠️ Simulink 初始化失败: [Errno 2] No such file or directory: '/tmp/...'"; 源码版 Linux 正常 (有 /tmp)。
- **根因**: 3.3.0 为排查 Mac 黑屏加的 SimulinkModule 构造打点直接 `open("/tmp/zmax_simulink_init.log", "a")` — studio.py `_init_simulink` 里 `_mk` lambda **无 try/except** → Windows 无 /tmp 目录 → FileNotFoundError 抛在 `SimulinkModule()` 之前 → 画布从未创建。simulink_module.py 里同款打点有 try/except 所以不崩 (静默失效)。
- **铁律**: ①跨平台诊断打点/临时文件一律 `os.path.join(tempfile.gettempdir(), name)` + try/except, 禁止裸 `/tmp` (Windows 没有); ②`_init_simulink` 这类"建画布"路径里任何语句抛异常都会让画布整体消失 — 打点类语句必须自身容错, 不能依赖外层 try 兜底 (外层 catch 后画布也没了); ③验证必须模拟 Windows: monkeypatch `tempfile.gettempdir` → 不存在目录, 再跑 `SimulinkModule()` + `load_flow_file`, 断言 nodes>0。
- **排查流程**: 3.2.4 正常 → 3.3.0 坏 = 二分 diff `git diff <v3.2.4>..<v3.3.0>`, 找新增的 IO/路径类语句; 用户报"Windows 打包的版本"时优先怀疑平台差异 (路径/权限/编码), 不是 UI 逻辑。

## QDialog 最大化按钮点了没反应 (2026-08-28, 节点逻辑/参数/源码窗口)
老倪「最大化按钮不好使, 不是让你禁用, 修复它」— 第一轮误把"不好使"理解成"禁用"
加了 `~WindowMaximizeButtonHint` (方向错误, 被纠正)。**根因**: QDialog 默认 Qt.Dialog
窗口类型在 X11 WM 下标题栏最大化按钮点击无效 → 显式转普通窗口类型:
```python
self.setWindowFlags(Qt.Window | Qt.WindowMaximizeButtonHint
                    | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint)
```
验证 (真实 DISPLAY, offscreen 会误判): showMaximized → isMaximized=True + 尺寸≈屏宽
(本机 3068x1862)。**教训: 老倪说"XX按钮不好使"= 修复功能, 绝不是禁用**;
窗口类型/按钮 hint 类问题先确认 Qt.Window vs Qt.Dialog 类型再动手。

## 状态空间画布连线因果检查 (2026-08-28, 触觉感知孤立节点)
老倪「触觉感知的数据源, 也应该是metaworld啊」— 画布上 🖐 触觉感知节点入度=0 (孤立),
但引擎真实数据 (state_space_sim._build_obs) 的 tactile4=[gripper, contact] 就是 metaworld
夹爪开度+物理接触检测。**画布连线必须如实反映引擎数据流**: 感知类节点 (传感器融合/YOLO/
触觉感知) 都应有 📦 metaworld 数据源 入边。排查法: 遍历 flows/*.json 入度=0 的非 row_bg
节点, 对照 state_space_sim/源码确认是否真有上游。修法: 补 link {f:ssdata, t:sstactile,
label:触觉数据} + 节点 desc 注明数据来源。拓扑验证: 单步第一节点应变为数据源 (因果正确)。
铁律: 画布每个节点要有真实的数据源连线, 不许有"引擎内部取数但画布孤立"的节点。

## 3D 视图↔程序执行状态映射 (2026-09-02 v3.4.3, 老倪: "3D视图的显示状态要与debug程序代码的执行状态保持一致")
- **需求**: 点 ▶运行 时 3D 视图要跟程序执行走, 不是独立播离线 episode; 断点停在哪一步 3D 显示哪一步。
- **实现三件套**: ①`open_ss_3d` 数据源优先 `self._ss_tr`(sim.run() 程序轨迹), 没运行过才退回 episode npz(保持与操作视频同源能力); ②`_ss_tick` 每帧把引擎步 `idx` 推给 3D 窗口: 窗口 tr 不是当前 tr 先 `set_trajectory(tr)` 再 `w.set_frame(idx)`(sip.isdeleted 判活); ③`DreamView3D.set_frame(i)`: `_pause()` 停自播防双驱动 + `_update_frame(i)` + slider/lbl 同步。
- **断点天然同步**: 引擎断点挂起主线程 → 推送停 → 3D 同步停; F5 放行 → 继续。无需额外逻辑。
- **配套 (fe2c82af)**: 打开即自动播放 — set_trajectory 末尾 `_timer.start(60)`(原默认静态第 0 帧, 用户以为"打不开")。
- 验证: sim.run() 322 步 set_frame 0→321 跟随, 0.5s 不被自播抢动。
- **🐛 real sim.run 轨迹喂 3D 缺 residual_vec KeyError → 窗口打不开 (2026-09-07 v4.4.0 实锤, 老倪"3D视图无法打开")**: open_ss_3d 优先用 _ss_tr (真实化 sim.run 轨迹) 时, ss_dreamview._update_frame 直读 `tr["residual_vec"]` (无 .get 容错, 引擎轨迹才有该 key) → KeyError 崩在 10774 构造行, 日志停在"3D 视图数据源: 程序执行轨迹"无后续。修: sim_real run() 补 latent_vec/prior_vec/corrected_vec/residual_vec 四个顶层向量通道 (对齐引擎 tr 格式, 数据每帧已有: prior/latent/corrected/residual)。排查: GUI stderr (studio_launch.log) 见 KeyError; 3D 打开后日志缺"✅ 已打开 3D 分层视图"行。**铁律: 任何新轨迹源 (sim_real/gen/episode) 喂 DreamView3D 前, 对照 ss_dreamview 引用的 18 个 tr key 全量补齐**。

## _EXTERNAL_LOC 行号铁律 (2026-09-02 v3.4.3, 老倪连续 3 轮 "源码不是这个")
- **症状**: 双击画布节点编辑器显示正确类, 但「VSCode 打开/复制位置」跳到错误代码 → 用户反复看到"自适应状态估计器源码=forward"(ss_est 映射行号 34, 类实际 45, 34 行正好是 FeedforwardAccelerator.forward 的代码)。
- **根因**: _EXTERNAL_LOC 的 line 是"兜底行号", 符号名匹配成功时行号不参与截取, 但 VSCode 打开用行号 → 行号错位 = 定位到错代码。文件头加注释/改行 → 全部错位 +1。
- **铁律**: 新增/修改 _EXTERNAL_LOC 后跑符号名+行号双查脚本(逐行 strip 匹配 `sym`/`sym(`/`sym:` 找真实行), 全量 29 条 0 错位才算完。symbol 必须是真实定义(`def synth_tactile` 不是 `gen_tactile`; 类行号含 `class X:` 冒号)。
- **配套修复**: ss_est→AdaptiveStateEstimator(45), ss_sched→def decide(167, 动作调制器双击直接看核心决策), ss_aoi→AOIQualityChecker(40), ss_bg5 符号误写路径字符串"planner.py"→class TaskPlanner。

## debugpy 僵尸占 5678 → SystemExit:1 (2026-09-02 v3.4.3)
- **症状**: VSCode 弹 "Exception has occurred: SystemExit / 1" (debugpy adapter __main__.py sys.exit(1)); F5 调试启动失败/attach 失败。
- **根因**: F5 会话主进程退出后 pydevd 子进程残留, 一直占着 5678(studio.py main 里 debugpy.listen(5678) 的 attach 端口)。`pkill -f "[s]tudio.py"` 杀不到 — pydevd 命令行是 `pydevd.py --port ...` 不含 studio.py。
- **清理**: `ss -tlnp | grep 5678` 看谁占 → `kill <pid>`; 反复 F5 会反复留僵尸, 每次调试会话结束都查一次。attach(5678) 必须无 F5 会话 + 5678 空闲。

## 标定层 (2026-09-02 v3.4.4 → 2026-09-03 v3.4.5 闭环, 老倪: Drifting Models 引力/斥力二分 + 平衡点)
- **需求**: 参考 arXiv:2602.04770 反称场思想 (Vp,q(x)=−Vq,p(x), q=p⇒V=0), 第一性原理把引擎全部超参数二分: **引力=快速动作** (Kp+STAGE_V_CAP/STAGE_V_MIN 各阶段速度上限/下限), **斥力=状态预测** (K_kalman+残差EMA+接触增益+否决阈值+反馈增益+先验A), 平衡偏差 = 引力势−斥力势 (V≈0 无漂移)。状态/阶段=明确标定量。
- **代码位置铁律**: 标定层在 `src/lerobot/calibration/`(与 datasets/、policies/ **同级别**), 不在 tools/gui。CalibrationLayer: attr/rep 标定表 + attraction_potential/repulsion_potential/equilibrium_gap + export(json) + **apply_to_engine/apply_to_file (v3.4.5)**。
- **🎯 标定闭环 (v3.4.5, 老倪: "标定值直通引擎, 不再手动同步")**: 💾保存 = `layer.apply_to_engine(root)` **精确写回引擎源码字面量** (值无关正则, 只认代码上下文, 锚点命中数 != 预期 → ValueError 不静默):
  | 标定参数 | 引擎落点 (tools/gui/state_space_sim.py 每次 ▶运行 importlib 重载源码 → 下次运行即生效, 无需重启 GUI) |
  |---|---|
  | Kp | parallel.py `Kp = 1.2` |
  | u_clip | parallel.py forward 两处 `np.clip(..., ±u_clip)` (值无关整行模式) |
  | stage_v_cap/min | cognition.py `STAGE_V_CAP/MIN = {...}` 类 dict (**整块内逐 key** — 引擎无参实例化 ActionModulator 吃类默认) |
  | veto_th / k_fb | cognition.py `__init__(..., veto_th=2.0, k_fb=1.0, ...)` 默认参 |
  | K_kalman / contact_gain / safety_limit / prior_A | state_space_sim.py run() 内联点: `state_correction(prior, z_k, K=)` / `contact_probability(r_scalar, gain=)` / `saturate(u, limit=)` / `PriorDynamicsPredictor(A=)` |
  | res_ema | state_space_sim.py 系数对 `(0.85 * self.res_ema + 0.15 * ...)` → (1−α, α) **同步写** |
  `apply_to_file(calib_path)` 写 calibration_layer.py 镜像 (下次打开表格的默认值源)。
- **⚠️ 镜像/引擎写回必须块内替换**: V_MIN 的 key (接近/对位/抬起/转移) 在 V_CAP 也出现 — 裸 key 正则会把 V_MIN 值**串写进靠前的 V_CAP** (v3.4.5 实测 bug)。stage dict 一律 `re.search(rf'"{dname}": \{{(.*?)\}}')` 块内逐 key。
- **⚠️ 数值格式**: stage dict 用 `.2f` (引擎 0.30/0.10 带尾零); 标量用 `%.6g` + 整数补 `.0` (2.0/1.0/8.0 引擎风格) — 否则默认值 apply 也会产生 diff。
- **⚠️ 标定表默认必须 = 引擎真值**: prior_A 曾抄 parallel.py 默认 0.95, 但引擎 est/dyn **显式 A=1.0** (物理自洽: 位置保持 + dt 积分) — v3.4.5 校准为 1.0。改引擎参数时同步校准此表。
- **生效证明验证法**: apply 后 **importlib 重载引擎** (`spec_from_file_location('tools/gui/state_space_sim.py')` + `StateSpaceSim()`) 断言 `sched.v_cap/veto_th/k_fb/v_min` 吃到新值; 默认值 apply 后 `git diff` 引擎文件必须为空 (表默认=引擎默认的零副作用检查)。
- **画布**: flows/state_space_obs.json **append** ssbg6(row_bg 🧮标定层) + sscalib 节点(params.calib_layer=true) + link ssworld→sscalib(状态标定量)。只增不改 — 不动任何现有节点/连线/流程。
- **UI 三入口**: ①双击/右键查看逻辑 → CalibrationDialog(引力组8阶段速度上限表当前阶段高亮+斥力组+平衡条; **v3.4.5 起 💾应用标定按钮也走 apply_to_engine**, 构造传 calib_path); ②**右键菜单专属项「标定表格 (引力/斥力参数编辑)」→ CalibrationTableDialog**(21 行全参数表, 双击单元格编辑, 保存 = apply_to_engine + apply_to_file + export); ③节点执行 node_ss_calib 读 module._ss_tr 当前步 stage/speed/residual/contact_p 算势。
- **右键菜单加专属项套路**: `if item.node.get("params",{}).get("calib_layer"): a_calib = menu.addAction("标定表格 ...")` + `elif chosen == a_calib: self.module.on_open_calib_table(item.node)`。菜单项去 emoji(VcXsrv 黑块坑)。
- **QMessageBox 深色**: calibration_dialog 里静态 QMessageBox.information/warning 会黑字 → 手动构造 mb + setStyleSheet(_DARK) + exec_(AA_DontUseNativeDialogs 下生效)。
- 验证 (v3.4.5 13/13): 默认值 apply 引擎零 diff / V_MIN 改值不串 V_CAP (引擎+镜像) / UI 全链路表格改3值 → 引擎文件+实例吃新值, run 正常 / 锚点破坏 → ValueError。

## 🧩 功能清单网页统稿 (v4.2.0, 2026-09-04 老倪: VIS-01 编号 + 场景 + HDM 几何分类)
- **node_func_tree.py 三组新注册表 (全 110 功能向后兼容注入, 旧消费端无感)**:
  - `FUNC_DOMAINS` 21 域三字母编号 → 每功能注入 `code` (VIS-01 格式: 域码-域内序)
    + `dom`; VIS 域 = ssyolo(01-05)+ss2d3d(06-10), VIS-01=YOLO 目标检出 (老倪锚点)。
    校验 check_codes() 全绿 (110 唯一)。
  - `SCENES` 5 大客户场景 (SC-01 FW Loading 金手指插拔/SC-02 ATS 光纤连接/
    SC-03 老化墙批量插拔/SC-04 上下料流转/SC-05 光耦合主动对准): 每场景
    story 作业故事线 + object/env/targets(量化目标**必须取自 RFP/TECH 真值**,
    禁造数字)/status(诚实标 ✅/🔶)/funcs。校验 scene_funcs_ref()。
  - `GEOM_CLASSES` 几何三分类 (纤维丛): LFP 局部精细感知(30, 本体无关仅重标定外参)
    /LFO 局部精细操作(35, 绑定运动学换本体旧联络失效)/HDM 全局高维流形泛化
    (45, 跨本体微调即新截面)。每功能注入 geom; hdm_funcs_of_scene 汇总跨本体泛化。
    校验 check_geoms()。
- **gen_web_feature_pages.py 五章节**: 几何总纲+HDM 汇总 → 场景详述(功能表) →
  编号图例 → 组合链 → 三层总表 (110 主行 + 550 用例子行 code-T1~T5 全展开,
  验证方法列 = VerificationLayer.<ref>() 原样去重, 手动用例子行带步骤全文)。
- **上传通道 (实测)**: datadrive.world = ECS 39.102.211.79 nginx,
  **站点根 = /www/wwwroot/datadrive.world/** (宝塔路径, /var/www/html 是默认页不算);
  zmax-website 仓库在 ECS /root/zmax-website。上传:
  `sshpass -p '<ECS密码>' scp reports/web/*.html root@39.102.211.79:/www/wwwroot/datadrive.world/`
  → curl https://datadrive.world/function-list.html 验证 (grep 新章节锚点)。
- 版本中迭代 v4.2.0 同步点同 v4.1.0 五处 + VERSION.md 历史表两行 (v4.2.0+v4.1.0 补录)。

## 📋 技术规格书 TECH_SPECS + RFP (v4.1.0, 2026-09-04 老倪: 供应商规格全写入清单)
- node_func_tree.py TECH_SPECS 3组12项规格 → 量化映射产品作业+功能 fid:
  组1 核心本体·运动控制 (Gauge Covariant Operations, 光耦合/光纤·模块插拔工位):
  极致定位±0.02mm+单模50nm多模100nm · 六维力亚牛顿0.5% 1-2N拖拽 · EtherCAT
  1kHz无抖 · 紧凑高刚性1.6T OSFP多角度安装
  组2 复合移动·柔性流转 (Locomotion & Flexibility, 上下料/跨工位/分拣): 全向底盘
  ±10mm蟹行 · 移动-操作解耦驻停毫米级 · 双臂10kg 0-2.5m 双孔0.3° · 多模态避障
  组3 智能认知·系统集成 (Gauge Symmetry & Invariance): VLA自进化 · UPH400不停机
  换料 · CPK1.67 良率99% AOI 0漏杀 · EtherCAT/Profinet/Modbus TCP + ESD/IP65
- RFP_SPEC (客户需求) 与 TECH_SPECS (供应商规格) 双注册表并存, 均 → 产品作业 →
  功能 fid 同源映射; GUI 对话框 Tab3 RFP / Tab4 技术规格书, Excel Sheet6/7。
- 版本中迭代 v4.1.0 同步五处: studio.py(窗口标题/QLabel/changelog注释前缀) +
  update_checker.py CURRENT_VERSION + version_sync.py zmax_ver + docs_sync.py
  ("version" + "zmax_version" 两键)。漏一处 → exe 标题旧版。changelog 巨长注释
  用 Python 脚本前缀插入 (锚点 '# v4.0.2:' 现为 '# v4.1.0:')。

## 📊 产品作业分级 PRODUCT_TREE + RFP + 一键自动测试 (v4.0.3/v4.0.4, 2026-09-04)
- **PRODUCT_TREE** (node_func_tree.py 尾部): 客户视角作业分级, 物理判据 刚体→柔性→
  性能极值: L1 基础功能·刚体接触插拔类 (光模块插拔/刚体取放/视觉定位, 全已实现,
  路线=分段式解析控制+状态机) · L2 高级功能·柔性物体插拔类 (光纤接头插拔/线缆整理/
  微力控, 规划中, 路线=端到端 VLA 插拔头/柔顺导纳 — 解析难建柔性模型) · L3 扩展功能·
  性能调节类 (光耦合主动对准/耦合质量闭环, 路线=世界模型+优化搜索, 端到端模仿难学
  搜索行为)。每 job: funcs 引用技术树 fid + model_route + gen 泛化指标 + detect + status。
- **泛化指标 G 组** (VerificationLayer t_g*_ 断言, 全真实引擎跑): G_data 数据外推
  (引擎 X0 初始扰动 ±10/±15mm 真跑), G_pose 位姿外推 (模块级 HOLE_POS monkeypatch
  偏移 2~10mm 真跑, **跑完 finally 恢复原常量**), G_skill 技能复用 (FUNC_CHAINS 引用
  校验 + L1∩L2 共享子技能 ≥3)。引擎模块 monkeypatch 法: importlib.import_module +
  改 m.HOLE_POS/m.X0 再 StateSpaceSim().run(), 引擎控制器自洽跟随观测真值 (偏移
  10mm 终态误差仍 ~3mm = 自洽收敛)。
- **RFP_SPEC**: 光模块 RFP 9 量化指标 (★否决 5 项: ±0.02mm 重复定位/50nm 耦合/亚牛
  顿力控/UPH400·CPK1.67·良率99%/…) → 关联产品作业 + 支撑功能 fid。
- **一键自动测试** tools/gen_verif_auto_report.py (gui-venv311, reportlab 5.0.1 已装):
  环境自检 5 项 → run_tree 全部 auto → PDF 7 章报告 (摘要/环境/按节点 PASS 表/
  产品分级/RFP 映射/G 组实测/结论) + Excel 6 sheet。GUI: ss_test 节点右键
  「⚡ 一键自动测试」→ _run_auto_test 子进程跑 (reportlab 在子进程防卡 GUI) →
  解析 stdout REPORT_PDF=/EXCEL= → scp 上传 datadrive.world 弹 URL。
- **⚠️ reportlab 中文**: 本机无 wqy 字体! 回退链 wqy-microhei→wqy-zenhei→
  arphic/uming.ttc→DroidSansFallbackFull.ttf; Noto CJK 是 CFF reportlab 不认。
- **GUI 对话框深色坑**: 全局 app.setStyleSheet (studio _build_global_qss) 存在时,
  子 QDialog 靠级联 QSS 不可靠 — 每个 QTreeWidget 必须**控件级显式 setStyleSheet**
  (QTreeWidget{background:#161b22; color:#e6edf3...}), 否则树区白底灰字。
- **QDialog 最大化坑**: QDialog 默认 flags 无 MaximizeButtonHint → 右上角最大化
  按钮点了没反应; 需 setWindowFlags(flags | Qt.WindowMaximizeButtonHint |
  Qt.WindowMinimizeButtonHint), 在 _show_nonmodal (simulink_module.py) 统一补。
- VerificationDialog 3 Tab: ①技术树(G1/G2/G3→节点→功能→用例) ②产品分级
  (L1/L2/L3+泛化+选型+检测) ③需求规格书 RFP (★否决项分组→作业→功能);
  右键 a_verif/a_rfp/a_auto 三分支; _open_verif_dialog(node, tab="rfp") 初始切 Tab3。

## 🧩 验证层 = 规范场三层三级树 (v4.0.2, 2026-09-04 老倪 Gauge Theory 重构)
- **主真源 = src/lerobot/verification/node_func_tree.py** (新注册表 550 用例):
  规范场三层 → 节点 → 功能 → 用例: G1 场感知 (9节点/45功能/225用例) · G2 协变操作
  (10/50/250) · G3 对称认知 (3/15/75); 22 节点 × 5 功能 (名 5~10 字, check_contract 强制)
  × 5 用例 (auto 339 / semi 16 / manual 195); FUNC_CHAINS 模块化组合链 (截面合成)。
- **VerificationLayer.run_tree(skip_slow, only_node, log_fn)** 三级执行器: auto 全真实断言
  (引擎/六层源码/标定/流形/planner 规则/源码审计 _audit); semi 需真机/DISPLAY 默认跳过;
  manual 永不自动跑 (清单展示)。**零空转铁律**: 自动用例禁止 `return True, "说明"` —
  纯文字断言一律改 _audit(文件, needles) 真实读源码, 或真算数值/委托 t_F_*。
- CLI tools/ss_feature_tests.py: --list 三级清单 / --only-node <key> / 全量 auto (semi 跳过)。
- GUI verification_dialog.py: 树按三层分组 → 节点 → 功能 → 用例, ▶运行自动用例后台线程
  → 结果 ✅/❌/⏭ 注入树; 导出 Excel 4sheet (功能清单含规范场列/功能用例/分类统计/测试明细)。
- ⚠️ CLI 直接执行坑: `python tools/ss_feature_tests.py` 时 sys.path 无仓库根 →
  `import tools.*` ModuleNotFoundError → VerificationLayer.__init__ 已把 root+tools/gui 入 path。
- 旧 45 项 FEATURES/FEATURE_META (v4.0.1) 保留兼容 (旧入口/run_all 不破坏), 不双轨展示。
- 规范场映射: G1=底空间观测(YOLO/2D3D/触觉/融合/obs/data/world/AOI/lat), G2=联络动作+流形
  (ff/est/pred/innov/sched/limit/act/calib/mani_c/mani_p), G3=规划编排诊断 (llm/reason/skill)。
- 画布 ssfeat/sstest 双击/右键 → _open_verif_dialog (0.0 分支最前, 防 source 字段抢先)。

## 断点挂起"卡死" = debugpy 暂停全进程 (v4.0.1, 2026-09-04 老倪两次"只能鼠标动,其它程序都不动")
- **认知修正**: 之前 real-run-gui-integration reference 写"断点命中在后台线程 → GUI 不冻"是**错的** —
  pydevd/debugpy 断点命中默认挂起**整个进程所有线程** (VSCode 线程面板全变暂停)。真实化 run() 虽在
  daemon 线程, detect_3d/fuse_sensors 断点命中一样冻 GUI 主线程 → 表现"只能鼠标动"(X server 画的
  鼠标还在动), 窗口/日志全停。F5 调试 + 引擎/感知源码断点 + ▶运行 是四次同款卡死的共同组合。
- **防御 (v4.0.1 代码)**: `_start_real_sim` 开头检测 `debugpy.is_client_connected()` (listen 未附加不算,
  比 sys.gettrace 可靠) → 日志+气泡醒目提示: 断点命中=GUI 暂停非故障, 处理 = ①F5 放行(逐次)
  ②删引擎断点只留目标行 ③取消 F5 直接跑。**判定法不变**: 卡死先 `sudo py-spy dump --pid <gui>`
  主线程栈 `do_wait_suspend` = 断点冻结 (删断点即恢复, 无需重启)。
- **真实化运行进度可见 (v4.0.1)**: RealStateSpaceSim.run() 每 25 步 self.log 周期进度
  ([step] 阶段/残差/接触p/grp/YOLO检出率) + simulink `_real_logs/_real_log_ix` 共享引用 →
  `_on_real_poll` 每 400ms 增量 flush 到 GUI 日志 — 修 5-9 分钟静默 = 用户误判"卡死" (两次报告背景)。
  新改动后重启 GUI 必给日志三连证据。

## 🧩 验证层 Feature/Test 节点 = VerificationDialog (v4.0.1, 2026-09-04 老倪: 按钮导出 Excel + 分类)
- 画布 ssfeat/sstest 双击/右键 → `_open_verif_dialog` → tools/gui/verification_dialog.py:
  45 项表格 (ID/域/类别/模型角色/功能名称/模型特点/层/验证方式) + 分类统计行; feature 模式有
  「▶ 运行全部测试」后台跑 (skip_slow, 结果列 ✅/❌/⏭); 「导出 Excel」= openpyxl 3 sheet
  (功能清单/分类统计/测试明细) → scp 上传 datadrive.world → URL。
- **数据源**: FEATURES 6 元组不动, 新增并行 `FEATURE_META {fid: (基本功能|泛化功能, 角色, 特点)}`
  45 条 (基本29/泛化16; 角色: 感知模型6/世界模型7/决策4/规划3/安全2/引擎8/平台5/标定3/GUI7) —
  加在文件末尾 main() 前 (放 FEATURES 后会错位 _EXTERNAL_LOC 行号锚点 47/97!)。list_features 返回
  dict 列表 (GUI/导出复用), 打印带分类统计。基本=确定性规则(引擎/状态机/安全/画布), 泛化=模型驱动
  (感知/世界模型/规划) — 感知模型=把传感器变状态(YOLO/触觉/AOI/融合), 世界模型=预测演化
  (估计器/动力学/校正/潜空间/流形)。
- **⚠️ 分支顺序坑**: ssfeat/sstest 节点带 `source` 字段 → 双击会被更早的"数据源切换"分支拦截,
  verif 分支必须放 on_node_activated **最顶部** (0.0), 不能放 state_space 分支附近。

## DataWorld 逐帧同步 — 3D 与画布信号同帧 (2026-09-03 v3.4.6, 老倪: 参考百度 Apollo Dreamview)- **架构语义**: 每个画布节点 = 一个算法模块 (channel, io key = 画布节点名); 引擎每步把
  各模块 in/out 发布到数据世界 → 画布播放 / 3D 视图 / 数据总线消费**同一 DataWorld +
  单一帧游标** → 点 ▶运行 后 3D 渲染数据与画布实际信号严格同帧 (Dreamview:
  "模块输出 → 主视图渲染", Layer Menu = 通道显示开关)。
- **数据源**: `state_space_sim.run()` 的 `tr["io_trace"]` **逐帧全量** (v3.4.6 起每步
  append — 原来每 25 步抽稀是 3D/总线跳帧的根因)。帧 = `_io_snapshot()` 产物:
  9 引擎模块/23 画布节点 key, value={"in"/"out": [(label, value)...]}。
- **tools/gui/data_world.py — DataWorld 类**: 由 tr 构建, frames=io_trace;
  cursor (set_cursor) = 单一游标; frame(step)/module(name, step)/module_out_values/
  stage/diff_modules; **module() 前缀匹配回退** (画布节点名带 [W-01] 后缀时按
  MODULE_ORDER 找包含匹配)。
- **_ss_tick 播放游标铁律**: 播放按**引擎步线性推进** — `stride = (n-1)//_ss_ticks`,
  `idx = round*stride`, _ss_ticks = max(60, min(120, n*0.006)) (≈5-7s 播完)。
  **禁止再按 io 快照数均匀抽样** (n 快照≈25 时 idx 每 80ms 跳 25 步 = 3D 大步跳变,
  用户感知"3D 与画布信号不同步")。每 tick: dw.set_cursor(idx) → 节点动画轮转 +
  execute_node_logic → log 该步数值 → 3D set_frame(idx) + set_active_node(节点名, dw)
  → 总线 feed 当前帧。
- **3D「▶ 画布信号」面板行** (ss_dreamview.lbl_mod): set_active_node(node_name, dw)
  显示画布正在执行的节点 + 该模块本帧 out 摘要 (from data_world import _fmt)。
- **播放结束对齐**: _ss_finish 把 dw cursor + 3D set_frame 精确推到引擎末帧 (stride
  余数可能差几步, 不补 3D 终态停在末帧前 = 显示不一致)。
- **数据总线静态视图防卡**: model_tree.refresh 时间序全量铺会 500×60 行卡死 →
  抽稀 ≤150 帧 (`_trc[::_stp]` + 补末帧); 运行中动态 feed 不受影响 (90 tick × 60 行
  ≈ 5400 行动态追加可接受)。
- 验证: 引擎 305 步/305 帧 0.05s 零开销 (io 帧 dict 每步本就构造, 只多 append);
  端到端 offscreen: SimulinkModule() + load_flow_file(state_space_obs.json) +
  _start_state_space_sim() → processEvents 推进 → 播放完成游标=末帧; 假 3D 探针
  (set_trajectory/set_frame/set_active_node 记录) 验证收到连续帧 + 节点广播。
- ⚠️ _ss_tick 内 execute_node_logic 用 `_ss_order[min(_ss_round, len-1)]` 保底防越界;
  播放完成判定 = `idx >= n-1 or round >= max(_ss_ticks, len(_ss_order))`。

## 3D 世界操作按钮 (2026-09-03 v3.4.7, 老倪: "3D 上也要有运行按钮, 与画布统一; 一点画布运行 3D 就被覆盖")- **DreamView3D 绑定画布 module**: 构造签名 `(tr, parent, on_top, module=None)`; open_ss_3d
  传 module=self, 复用窗口分支也补 `w.module = self`。无 module (命令行自测 __main__) 不建控制区。
- **左侧「🕹 3D 世界操作」区** (图层列表上方): ▶运行 = module.start_sim() (**画布统一入口**,
  状态空间画布 → 引擎+逐帧同步 3D), ⏹停止 = module.stop_sim(), 📌窗口置顶 toggle
  (setWindowFlag(Qt.WindowStaysOnTopHint) + show() 重生效; 手动开置顶 → 画布运行/弹窗不再盖 3D),
  引擎状态行; **300ms QTimer 轮询** (module._ss_timer.isActive / _sim_running / btn_run.text) →
  ▶运行/⏹停止 禁用启用联动 (同一引擎同一状态)。
- **画布 ▶运行开始 raise 可见 3D 窗口** (raise_ + activateWindow) — 修"点画布运行 3D 被画布覆盖";
  只 raise 不置顶 (置顶会盖画布 = 2026-08-26 黑屏投诉重演), 用户可点 📌 手动置顶。
- **坑**: PyQt5 枚举比较 `w.windowFlags() & Qt.WindowStaysOnTopHint == 0` 断言挂 (枚举 == int 语义),
  必须 `int(...)` 包裹; DEBUG bool() 会掩盖该问题 (bool 与 ==0 不等价)。
- 验证 7/7 offscreen: 控制区创建/▶运行→start_sim/⏹停止→stop_sim/置顶 flag 随 toggle/
  busy→▶禁用⏹启用/就绪恢复/无 module 不建控制区。

## 播放"卡住"根因 = execute 冷加载 + 平滑播放 (2026-09-03 v3.4.8, 老倪: "运行后没有连续动作, 好像卡住了")
- **真机计时铁证**: 播放 tick 间隔中位 81.6ms 正常但**最大 1632ms** = 📡传感器融合节点
  execute_node_logic 真跑 → `_yolo_ensure_aligner` **冷加载 1.6s+** (metaworld MT1 env +
  YOLO 模型构造) 冻结主线程 → GUI "卡住"。判定法: 包 execute 打点计时
  (`_slow_exec` 包 execute_node_logic, dt>30ms 打印) — 别猜。
- **execute_node_logic 加 demo 参数 (v3.4.8)**: ▶运行 播放演示 = demo=True 轻量路径
  `_demo_node_output` — 读 module._dw 当前帧该节点 out (引擎真实算的, 同源不伪造) 打印,
  **不重跑节点真实函数** (YOLO 采样/LLM/传感器融合重执行又慢又重复 — 引擎 run() 已真执行过)。
  ⏭单步/右键运行/双击 = demo=False 仍走真实 fn (VSCode 断点可进, 调试链路不变)。
  **铁律: 播放动画循环里禁止同步执行可能慢的真实节点函数** (YOLO/LLM/env 构造类)。
- **播放节奏 (v3.4.8)**: 80ms×60tick 大步跳 (60 tick 播 305 步 = 每 80ms 跳 5 引擎步 →
  视觉一顿一顿"不连续") → **30ms/tick 逐引擎步**: `_ss_tick_ms=30`,
  `_ss_ticks = max(n_order, min(n_steps, 267))`, idx = round*stride, 结束 idx>=n-1。
  3D set_frame **每 tick** (连续); 节点动画轮转/execute(demo)/日志(~40行)/总线 feed
  按抽稀散布 (exec_every = ticks//n_order 等), 不再每 tick 全量刷。
- **resize 自动取景**: 窗口尺寸变化 >6% 且未手动转视角 (`_user_cam` eventFilter 鼠标旋转
  标记) → 250ms 防抖后 `_fit_view("fit")` 场景撑满放大视口。诊断结论: 布局本身正常
  (view 926→2814px = 3 倍, GL 视口自动放大), 用户"没放大"多为最大化错窗口/旧版未重启。
- 验证: 卡点 1632→70ms (传感器融合节点 0.23ms), e2e 305 tick 播放完成游标=末帧,
  _update_frame 0.9ms/帧渲染零压力 (真机)。

## pyqtgraph GL 跨上下文 shader 失效 (2026-08-28, 3D 视图二次打开背景丢)
**症状**: 老倪「3D 视图第二次打开, 场景背景没了」— 首次打开正常, 关窗再开只剩纯背景色。
**根因**: pyqtgraph `opengl/shaders.py:420 initShaders()` 模块导入时编译一次、全局缓存
ShaderProgram, 句柄绑定**第一个** GL 上下文。窗口 close 后再开 = 新建 GLViewWidget =
新 GL 上下文 → 旧句柄失效 → 绘制报 `GLError 1281 glUseProgram(3) invalid value`
(debug.printExc 打 RuntimeWarning, 界面无弹窗)→ 所有 GL item 静默失败。
**验证方法** (tools/gui 下跑, DISPLAY=:0): `view.grabFramebuffer()` 统计非背景像素,
实测 531589→0 px 复现; 同一窗口 close→show 像素不变 (531589→531589) → 只复用不新建。
**修法**: open_ss_3d 窗口复用逻辑从 `if w.isVisible()` 改为 `if w is not None` —
close 只是隐藏 (无 WA_DeleteOnClose), 对象+GL 上下文都在; 数据源变了再
`w.set_trajectory(tr)` 重建场景; close 停掉的 `_cam_watch` 定时器要重启。
`_ss_3d_windows` 清理用 `sip.isdeleted` 判断, 别用 `isVisible` 过滤 (会误删可复用窗口)。
**连带坑**: `_build_scene` 重建时同一 item 被多 key 引用 (yolo 列表 ↔ yolo_hand/peg/hole),
重复 `view.removeItem(x)` 抛 `ValueError: x not in list` → 重建中断。修: 按 `id(x)` 去重 +
`except (ValueError, RuntimeError)` 容忍。**铁律: pyqtgraph GL 窗口一律复用不新建;
重建 GL item 树必须去重 removeItem。**

## simulink 字体大挤调小 (2026-08-28, 192DPI)
老倪「终端字体/画布方框字体/工具栏按钮字体都大, 很挤」。真机 `logicalDotsPerInch=192`
(X 上报 96, 但 Qt 用 192) → 12pt 渲染成 **32px**。调小一档: 工具栏 mk_btn 12pt→10pt
(minHeight 34→30, padding 7x14→6x12); 终端 log_box 12pt→10pt; 画布节点标题
12/11/10→10/9/8; 节点内部文字/徽章/ID/背景行模型名 11→10、10→9; 连线数据流标签 10→9。
**⚠️ offscreen 是 96 DPI (10pt=14px), 真机 192 DPI (10pt=27px)** — offscreen 只能验
布局逻辑/文字放不放得下, 像素尺寸验证必须真实 DISPLAY=:0。验证:
`QFontInfo(QFont('Arial', pt)).pixelSize()` 打真机 px。

- **🗂 模板多行展开布局 (2026-08-05, commit ada65fb1, 老倪: \"你每次都是从一条直线上开始给出, 你需要把所有节点展开, 不要重叠成一条线; 类似的功能, 例如 Action Head, 应该垂直对齐\")**: **用户偏好 — 模板加载节点禁止单行横排 (13+ 节点一条直线出画布外)**。REFERENCE_APPS 条目支持可选**第4元素 layout** (3元组模板兼容, 4元组才启用): `layout = [[节点名...]每行]` 网格 — **行 = 模型分支 (y 递进 230), 列 = 功能角色 (x 递进 260), 空串 \"\" 占位跳过**。同名节点多行出现 → 取各自候选坐标 → **同列垂直对齐** (三模型 Action Head 都落第5列 x=1420, y=80/310/540)。load_reference_app 加 layout 分支: 先 `pos.setdefault(nm, []).append((x,y))` 收集同名多行坐标 → 每节点取 `next(p for p in cands if p not in used)` (used 去重保证共享节点只画一次, 如 metaworld 三行共用顶部一个) → 兜底单行。**⚠️ REFERENCE_APPS 改 4 元组后全仓库 3 处 `for nm, nodes, links in REFERENCE_APPS` 解包全崩 (ValueError) — 必须逐个改 `for item in ...: nm=item[0]`** (参考应用按钮 1758 / _act_build_link_existing / _act_build_finish)。验证 (offscreen): 三模型模板 18节点 / Action Head `len(set(x))==1` 且 `ys == [80,310,540]` / metaworld 只画一次 / 双模型+ACT-Meta 回归 (3元组) 不崩。
## 控制台两个高频故障 (2026-09-18 实测, 都已修)

### ① 模式下拉切「🔌 本地连接 (Local)」→ 整个控制台 SIGABRT (无弹窗, 直接消失)
根因: `_on_mode_changed` 里 `modes=["sim","local","real"]` 但 `Z700_ROS2_NODES` 只有 sim/real 两个键
→ `KeyError: 'local'` 抛在 Qt 槽里没人接 = **Qt 槽内未捕获异常 → qFatal → 整进程中止**
(日志 /tmp/studio_launch.log: `Fatal Python error: Aborted` + traceback 到 studio.py:7317)。
同一类坑 2026-09-14 出现过一次 (`Z700_ROS2_NODES["real"]` 被当 dict 调 `.get()`)。
**纪律: 任何 Qt 槽体都要包 try/except 兜底 (异常只记日志, 绝不冒泡) — 这是"点一下就崩"的通式。**
修法: 未知/越界模式键一律退回 sim 表 + 如实打日志; 槽体总兜底。
排查证据: `journalctl --user -u zmax-studio --since "…"` 找 `Fatal Python error`, 看 `Current thread` 那几行。

### ② 「输入图像」真机源"永远无画面", 但 L2 其实一直在吃帧
`yolo_input_viewer.py` 的真机源原来**只认 srv 落盘** `live_frame.jpg/.json`
(Orin `/zmax/live_frame` → 本机 Docker `ss_frame_srv_client.py`)。
Orin 侧服务不可达时 (容器日志 `❌ 服务 /zmax/live_frame 不存在 → 退出`) 该文件冻结在旧时间戳
→ 窗口按"不上旧帧"纪律显示空/占位, **而真机图像其实一直在流**: Docker tap 落盘 `cam_rs.png`
(0.x 秒龄, 只读订阅生产话题), **L2 侧 (`ss_yolo_on_real.py` CAND) 吃的就是这条**。
口径: 窗口显示的真机源必须 = L2 实际消费的那条流 → 加同源回退链
`cam_rs.png → cam_fp.png → cam_latest.png → srv_cam.png/.jpg`, 逐文件 mtime 新鲜度 (≤10s),
有新鲜帧就上屏并在状态栏标「来源 / 帧龄 / srv 为何回退」; 全不新鲜 → 占位逐条列候选状态。
**不要改回"只认 srv"**: Orin 红线=零自研程序, 话题落盘才是常驻正解。

## 输入图像窗口「三路源」+ 引擎实况取证 (2026-09-17/18, commit 6ef836a7)
**窗口 = tools/gui/yolo_input_viewer.py, 输入源下拉 3 项: 🎥 真机 RealSense / 🧪 仿真 metaworld / 💻 本机摄像头。**
- 数据根按源分开 (tools/yolo_annot_dataset.py): `data/yolo_annot`(真机) · `yolo_annot_sim`(仿真) ·
  `yolo_annot_usbcam`(本机摄像头) — 三路口径不混, 会话 tag 分别 d405/sim_corner2/usbcam。
- 💻 本机摄像头: `/dev/video0` = Luxvisions Integrated RGB Camera (内置 UVC, uvcvideo 内核自带), 1280x720 MJPG 30fps 可跑满。
  **坑1 (cv2 V4L2)**: `cv2.VideoCapture("/dev/video0", cv2.CAP_V4L2)` 报
  "backend generally available but can't be used to capture by name" → **必须换算成索引**(`cv2.VideoCapture(0, CAP_V4L2)`)。
  **坑2 (UVC 独占)**: `_start_source` 非幂等时 (`__init__` 的 singleShot(200ms) + 手切下拉各起一次) 旧采集线程成孤儿 →
  **设备被永久占用**, 之后任何一路都"打不开摄像头" → 修: start 前先收旧线程 + `join(1.5)` 等 release。
**仿真源语义**: 引擎没在跑时窗口渲染的是 `node_logic._YOLO_ALIGNER.env` (只 reset、**从不 step**) = 静止初始帧
(老倪两次误读成"光模块没插进槽"!). 点 ▶运行 后窗口自动跟随引擎实况帧 (SS_LIVE_FRAME 共享槽, 与 detect_3d 同一帧);
无实况 → 画面顶部压橙字横幅"引擎未运行 · 静态初始帧", 不假动。
**引擎实况取证 (1Hz)**: `/tmp/ss_live_frame.json` = 步号/阶段/**沿孔轴进深 mm**/**横向偏差 mm**/夹持/窗口消费计数,
每轮收尾强制落一次 → 这类"看起来没插进去"的问题直接用数据说话, 不用截图目测。
**窗口通用修复 (同批)**: ①`_clamp_to_screen` 必须按**所有屏幕**判可见性 (只认 primaryScreen → 拖到扩展屏 5s 被拽回,
  实测 t=5.0s 跳回 x=572); ②切源必须**清画面+清框** (只切链路 → 上一路画面残留, 真机源看起来在放仿真视频);
  ③真机源只让**新鲜**帧上屏 (meta.ok ∧ age≤5s), 超 10s 换占位画面写原因; ④标定冻结时不动画面。

## 插销/插槽"没插进槽/横向偏差" — 口径问题, 非控制偏差 (2026-09-18 实测)
**结论**: metaworld peg-insert-side 官方判据 = **杆头(pegHead 站点)到 goal 点** ≤7cm 算成功
(`metaworld/envs/sawyer_peg_insertion_side_v3.py:115`); 引擎把杆头推到 0.6mm 内、横向 2.1~2.5mm → 判据上是"完成"。
但光模块是 **24cm 长杆**(geom box 0.015/0.015/0.12, euler 0 1.57 0 使长轴沿世界 x), 只入槽 6~7cm、约 17cm 横在盒外
→ 老倪肉眼判"没插到槽里、和插槽横向差一截"。**槽道几何**: 盒内两根 3cm 立柱(碰撞 geom size[0]=0.03, world y=box_y±0.06)
形成 y 向 6cm 宽、z 向 6cm 高、x 向 19.2cm 长的通槽; 孔口 site(0,-0.096,0.13) 在盒 +x 面, goal=mouth+66mm(x 向)。
**待老倪定**: 是否改"光模块体坐进插槽"口径 (杆头推到槽道尽头 → 杆体 19cm 进槽) — 动 L2/L3/L4 共用插入段, 须同口径 A/B。
**取证脚本** (tools/): diag_insert_offset_truth / diag_insert_geom_truth / diag_scene_bodies /
diag_pixel_align_peg_slot (corner2 投影: 孔口到杆轴 0.3px) / diag_which_state_on_screen /
diag_compare_window_render (抓窗口与渲染帧逐像素比对) / ascii_render / zoom_insert_region。
**留档**: ~/zmax_data/20260918_0616_evidence/ (MANIFEST.md + 窗口抓图 + 候选帧 + 轮次日志) 与
~/zmax_data/ss_remote/20260918_0615/ (state/proposal jsonl.gz + MANIFEST)。
