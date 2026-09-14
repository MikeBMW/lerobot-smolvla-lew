# CANoe 极简风浅色主题 (2026-08-16 四版 — 朱红唯一强调色)

## 需求 (老倪)

"浅色风格太难看了, 别用那么多颜色, 就用简单的白色背景, 黑色边框, 清晰一点; 参考 vector 公司的 CANoe 设计"
→ 二次: "你看看这个UI 颜色也没那么多; 你重新设计一下UI, 如果需要颜色, 用跟 canoe 一样的朱红色"

## 官网配色实测 (vector.com CANoe 页)

HTML CSS 色值统计: **#3a3e3f 61次 (主文字深灰)** + **#ffffff 白底** + **#b70032 10次 (朱红强调色)**。
Vector 品牌朱红 = **#b70032** (深胭脂红)。设计 = 白底 + 深灰文字 + 朱红唯一强调色。

## 演进 (4 版)

1. 白底灰钮彩字 → "灰蒙蒙" 嫌弃
2. 全黑白 → 缺 CANoe 味道
3. 浅灰底+绿功能色 (参考截图实测 绿5.9%) → 用户说颜色还是多, 要朱红
4. **最终: 浅灰底 + 白卡片 + 黑边框 + 朱红 #b70032 唯一强调色**

## 四版参数 (最终)

- L_BG #f0f0f0 / L_BG2 #e8e8e8 / L_CARD #ffffff / L_HOVER #e0e0e0
- **L_GREEN = L_RED = #b70032** (朱红统一功能色, 绿红都映射朱红)
- 其余 L_* 彩色全 #000000; L_BORDER #000000; L_GRAY #333333
- THEME_PAIRS_BTN: 按钮背景 → #ffffff 白底黑字 (去彩色)
- 替换顺序妙处: #3fb950/#f85149 (绿红文字) 走 THEME_PAIRS → #b70032 朱红;
  按钮深色底 (#0d3b33 等) 不在 THEME_PAIRS 只被 BTN 处理 → 白底。互不干扰。
- 验证: offscreen 736 QSS → 彩色按钮 0 / 非朱红彩字 0 / 朱红 120 处 / 深色残留 0

## 🐛 #fff 污染坑 (关键!)

替换链里 `("#fff", "#000000")` 短格式规则若在 `#ffffff` 生成规则**之后**执行,
会把刚生成的 `#ffffff` 二次匹配 → `#000000fff` 乱码 (background:#000000fff)。

**修复**: pairs 组合时 `#fff` 规则提最前, 并从 BTN 剔除:
```python
pairs = [("#fff", "#000000")] + THEME_PAIRS + THEME_PAIRS_EXTRA + \
        [p for p in THEME_PAIRS_BTN if p[0] != "#fff"]
```
apply_ui_theme 和 apply_ui_font **两处**都要改 (都拼 pairs)。

## 关闭崩溃 SIGSEGV (2026-08-16) — closeEvent 补全 timer 清理

老倪: "怎么又崩了" — exit code -11 SIGSEGV, 日志末尾:
`QObject::killTimer: Timers cannot be stopped from another thread` + `QObject::~QObject: ...`

**根因**: 运行时启动的 QTimer 在 closeEvent 清理列表里漏掉 → 关闭窗口时 timer 仍在跑,
析构时跨线程 stop → 段错误。崩溃发生在用户"运行时直接关窗口" (没先点停止)。

**漏掉的 timer** (已补全):
- simulink SimulinkModule.closeEvent: **+_flow_clock** (1s 流程时钟, start_sim 时启动, stop_sim/流程结束才停 —
  运行时关窗必崩)
- studio StudioMainWindow.closeEvent: **+_cam_timer (无 parent! 5948行 QTimer() 裸创建)** +
  _log_flush_timer (200ms常驻) + _zoo_timer (15s) + _remote_log_timer (5s) + _env_timer (30s)
- CICDPanel.closeEvent: **+_pulse_timer** (500ms 脉冲, 训练中关面板崩)

**排查方法**: `grep "self\._[a-z_]* = QTimer"` 列出全部 19 个 timer → 逐个核对 closeEvent 覆盖。
有 parent(self) 的 timer 随父销毁自动清理 (理论上安全), 但**运行时还在跑**的必须显式 stop。
**无 parent 的 QTimer() 裸创建** (如 _cam_timer) 最危险 — 必须 closeEvent 停。

## 启动黑影闪动 (2026-08-16) — QSplashScreen 占位方案

老倪: "控制台启动前, 屏幕有黑影闪动" + "一直也没修好"

**根因**: VcXsrv 网络合成下, 窗口映射瞬间 (QApplication 创建空白窗 → 2000ms 后 show 真实窗口)
产生黑色条纹闪烁。08-15 的"延迟 show 2000ms"方案不够 — 窗口首次映射瞬间仍闪。

**根治**: QSplashScreen 纯色占位 — 启动即显示 1x1 纯色 splash (无内容无闪烁),
窗口完全就绪后 win.show() + splash.finish(win) 平滑移交焦点:
```python
_splash_pm = QPixmap(1, 1); _splash_pm.fill(QColor(C_BG))
_splash = QSplashScreen(_splash_pm); _splash.show(); QApplication.processEvents()
def _show_ready():
    win.show(); win.raise_(); win.activateWindow()
    _splash.finish(win)  # 平滑移交, splash 消失
QTimer.singleShot(2000, _show_ready)
```
注意: splash 先 show 会占满屏但纯色稳定; finish(win) 移交焦点时无黑条。

**2026-08-17 修正 (老倪"左上角黑色横条阴影, 闪烁10秒"实测回炉)**: 原方案 `QPixmap(1,1)` 是坑 —
1x1 splash 在 VcXsrv -multiwindow 下落左上角渲染成"黑色横条阴影"闪烁 ~10s。
正确做法:
1. splash 尺寸 = 主窗口同尺寸同位 (`setGeometry` 到 60,40,1400,900 或 win.geometry()),
   主窗口 show 时无缝覆盖, 无黑条;
2. **splash 必须提前到 `win = StudioMainWindow()` 构建之前创建** — 重量级 GUI 加载
   数秒, 放后面则加载期无占位; 闭包 _show_ready 延迟引用 win 没问题 (回调 2s 后才执行);
3. 兜底 `_splash = None` + `if _splash is not None` 防 import 失败; finish 后 splash
   X 层窗口 IsUnMapped 残留无害 (Qt 延迟销毁)。

**排查过程 (不重蹈)**: 先排除运行时闪 (连线动画已惰性化 08-15 / hover轮询有鼠标不动保护 /
_flow_clock 仅运行时 / CICD脉冲仅对话框) → 确认是"启动前" → 锁定窗口映射瞬间。

## 十版 (2026-08-16) — 暗夜风格按钮浅色残留修复

老倪: "暗夜风格, 为什么有的按钮还是浅色调。你要全局修改"

**根因**: simulink_module.py 源码里按钮 QSS 硬编码浅灰底 `background:#e9edf2` (深色主题下也这样)。
switch_theme 的 pairs 来自 THEMES light 值 (已改 #e0e0e0/#d9d9d9 等, 不含 #e9edf2) → 深色替换不处理它。

**修复** (simulink_module.py switch_theme):
1. pairs 补 `("#e9edf2", "#14181f")` — 源码浅灰按钮底 → 深色 input 底 (初始深色 + 浅→暗都覆盖)
2. dark 分支: 金属渐变 → `#14181f` (light 分支把 #e9edf2→渐变, 切暗要还原成 #14181f 不是 #e9edf2!)
   `ss = _re.sub(r"background:qlineargradient\([^)]*\)", "background:#14181f", ss)` + 还原坏值
   (#000000fff→#ffffff, #ddd33→#e6edf3 — 渐变里的 #ffffff 被深色替换规则误伤成坏值)
3. 注意 import re 需局部 (文件顶部没 import re)

**验证**: 初始深色画布按钮 {#14181f x21, #1a2230 x19, #1f6feb x17(蓝原设计), ...} 浅色残留 0;
浅→暗后无渐变残留; 主窗口初始暗夜 + 浅→暗往返均无浅色按钮。往返一致。

## 八/九版 (2026-08-16) — 画布边框全黑 + 背景灰度统一

老倪: "浅色风格的simulink画布的方框边框, 全换成黑色" + "浅色风格的背景, 别搞那么多灰度, 统一一下; 参考 canoe 的窗口"

### 画布方框边框全黑 (simulink_module.py)
- **节点边框**: paint() 里 `color = QColor(COLORS.get(t))` 后加 `if _CUR_THEME == "light": color = QColor("#000000")`
  (类型色紫/蓝/青/金/红只用于内部标签/徽章; 状态色 running青/success绿/error红/step_active金 保留 — 是运行指示非配色)
- **z700_internal 模块**: _paint_internal 传入黑 (浅色)
- **row_bg**: 边框黑; 底色深色 (13,17,23,120) → 浅色白底 alpha150; 色相薄层 alpha90→40; 大字白→黑
- 验证: 渲染节点像素采样顶部边框 rgb≈0 全黑

### 背景灰度统一 #e0e0e0 (CANoe 窗口同款)
- L_BG = L_BG2 = **#e0e0e0** (原来 #f0f0f0/#e8e8e8 三种灰 → 统一); L_HOVER #d9d9d9 (唯一 hover 深)
- THEME_PAIRS_EXTRA: #0d1117/#161b22/#252d3a/#14181f/#010409/#0a0a0f/#0a0e14/#21262d/#0d2a24 → 全 #e0e0e0
- 画布 THEMES light: canvas/bg/bg2 全 #e0e0e0
- 验证: 主窗口背景只剩 #e0e0e0 (主) + #ffffff (卡片) + #d9d9d9 (hover) + 黑灰系; 往返零漂移
- 可接受的杂色: #6e7681 (禁用按钮中灰), #00000022/#33333322 (半透明 hover 阴影), #000 (黑底提示)

## 七版 (2026-08-16) — 按钮文字全黑

老倪: "浅色风格, 按钮都是黑字"

**坑**: `color:#ffffff` 长格式不在替换链 (#fff 短格式规则只匹配 3 位) → 深色黑底白字的按钮
浅色换底后白字残留 → 浅灰/渐变底配白字看不见。
**修复**: apply_ui_theme + apply_ui_font 按钮分组 + simulink switch_theme light 分支, 三处都加:
```python
ss = ss.replace("color:#ffffff", "color:#000000")
ss = ss.replace("color:#f0f0f0", "color:#000000")
```
**验证**: 主窗口按钮文字色 {#000000 x49, #24292f x31, 灰 x2} 白字 0; 画布 40 按钮白字 0。

## 六版 (2026-08-16) — 文字全黑 + 按钮金属光泽

老倪: "有的字是红色有的是黑色; 除了大字标题, 都变成黑色; 一些有特点的图标可以考虑红色; 其它的没啥特点的都是黑白; 按钮要有金属光泽"

### 文字规则 (最终)
- **普通文字全黑**: L_GREEN/L_RED 改回 #000000 (THEME_PAIRS 的 C_GREEN→L_GREEN 会覆盖 EXTRA 规则, 必须改常量本身); EXTRA 里 #3fb950/#f85149/#ff4444/#ff6b6b/#ff9f43/#f87171 → #000000
- **朱红 #b70032 只留**: 大字标题 (scope lbl_head 15px/head 14px 直接写 #b70032)、波形 base 线、分隔线 _GOLD_LINE、按钮 hover 边框
- scope 状态判定 "✅提升" color 改 #000000

### 按钮金属光泽 (3 处实现)
1. **全局对话框按钮** (_build_global_qss): light 时 btn_bg 用 qlineargradient 垂直渐变
   (stop:0 #ffffff → 0.45 #f2f2f2 → 0.55 #e8e8e8 → 1 #d9d9d9) + 黑边框黑字;
   hover 渐变更亮, pressed 渐变反转 (上暗下亮); dark 保持原 C_CARD/C_BLUE
2. **主窗口按钮** (apply_ui_theme + apply_ui_font 两处): BTN 分组替换后,
   `background:#ffffff` → 金属渐变字符串
3. **画布按钮** (simulink_module.switch_theme light 分支): 按钮控件彩色文字
   (#00d4aa/#58a6ff/#d29922/#ff4444/#ffd700/#3fb950/#a371f7/#f85149/#1f6feb → #000000)
   + `background:#e9edf2`/`#ffffff` → 金属渐变

### 验证
- 主窗口: 按钮全金属渐变 (白底残留 0) / 朱红普通文字 0 / 残留彩色 0
- 画布: 运行/单步/分析/前馈PD/停止 按钮全金属+黑字
- 注意: THEME_PAIRS 的 (C_*, L_*) 优先于 EXTRA 的裸色值规则 — 改文字色要改 L_* 常量


老倪铁律: "全局搜索, 所有页面统一风格; 只能有红色和黑色, 白色; 按钮可以高光灰色"

### 替换链按控件类型分组 (关键架构!)

纯字符串替换**无法区分**同色值"按钮背景 vs 文字" (如 #58a6ff 既是按钮底又是文字色):
```python
from PyQt5.QtWidgets import QPushButton, QToolButton, QCheckBox, QRadioButton, QMenuBar
_BTN_TYPES = (QPushButton, QToolButton, QCheckBox, QRadioButton)
_WHITE_FIX = [("color:white", "color:#000000")]  # 关键字白字 → 黑 (hex 替换不覆盖 white)
text_pairs = _WHITE_FIX + [("#fff", "#000000")] + THEME_PAIRS + THEME_PAIRS_EXTRA
btn_pairs = _WHITE_FIX + [("#fff", "#000000")] + \
            [p for p in THEME_PAIRS_BTN if p[0] != "#fff"] + THEME_PAIRS_EXTRA
# 按钮控件 → btn_pairs (白底黑字); 其他 → text_pairs (彩→黑/朱红)
```
apply_ui_theme 和 apply_ui_font 两处都要。**THEME_PAIRS_BTN 自身末尾含 ("#fff","#000000") 条目必须剔除**防二次污染 #ffffff。

### EXTRA/BTN 分工 (2026-08-16 实测)

- **THEME_PAIRS_BTN** (按钮白底): 15 彩色按钮底 + #238636/#2ea043(绿) + #ff4444(红) + hover/pressed 态 (#388bfd/#79b8ff/#56d364/#4ade80/#22c55e/#ef4444 → #e0e0e0 高光灰)
- **THEME_PAIRS_EXTRA** (文字/描边): #58a6ff/#d29922/#a371f7/#39d2c0/#00b4d8/#e3b341/#d4a800/#ffd700/#f778ba → #000000; #3fb950/#f85149/#ff6b6b/#ff9f43/#f87171/#ff4444 → #b70032 朱红; #00d4aa/#1f6feb → #000000 (非按钮时)
- ⚠️ 同一色值既是按钮底又是文字 (如 #00d4aa/#ff4444): 按钮走 BTN(先执行)→白底, 文字走 EXTRA→黑/朱红。btn_pairs 里 BTN 在 EXTRA 前 → 按钮先变白, EXTRA 找不到原色 ✓

### 独立对话框统一 (dataset_viewer/node_logic_dialog/version_sync)

这些文件有自己的 C_* 常量硬编码 → 切浅色不变。改法:
```python
try:
    from studio import C_BG, C_BG2, ...  # 浅色主题自动跟随
except Exception:
    C_BG = "#0d1117"; ...  # 兜底 (独立运行场景)
```
node_logic_dialog 可修改区底纹 _GOLD_BG 改 #f0e8ec 浅朱红调, _GOLD_LINE #b70032。

### 验证 (offscreen 主窗口 736 QSS)

按钮残留 0 / 文字残留 0; 允许: 白/浅灰(#e8e8e8/#f0f0f0/#e0e0e0)/透明/中灰(#6e7681)/黑底/半透明(rgba, #00000055 等)。朱红 88 处。

