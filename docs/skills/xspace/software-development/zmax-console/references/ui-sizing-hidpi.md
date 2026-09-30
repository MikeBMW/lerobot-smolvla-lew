# Simulink 页 UI 尺寸适配 (高分屏按钮/面板放大) — v2.8.4

2026-08-25 老倪: "画布上面的按钮太小了, 里面的字都挤在一起了" + "模块库太窄了, 里面的字太挤了"。

## 屏幕背景 (必须先记住)
- 面板 3200x2000, 物理 846x529mm → **真实 ~236 DPI**, 但 X 报 96 DPI (`xdpyinfo | grep resolution`)。
- 禁 QT_SCALE_FACTOR (会整体错位) → 只能**逐控件放大字号/padding**。
- 结论: 11pt (字高 22px) 在这块屏上物理只有 ~2.4mm, 按钮 35px 高 ≈ 3.8mm → 看着"又小又挤"。
  全站基线: 普通控件字 18-20px (13-15pt), 终端 60px。

## 实测探针 (先量再改, 不许拍脑袋)
```bash
cd ~/lerobot-smolvla-lew
QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/probe_ui_metrics.py 3068 2400 1800 1200
```
读**真实 Qt 控件几何** (非估算), 输出:
1. 工具栏每按钮 宽/高/字号px/文字所需宽/余量 → 余量<12px 判"挤压"
2. 多窗口宽度下工具栏行数 (验证 FlowLayout 换行)
3. 模块库 434 个模块按钮在不同面板宽度下被切条数 + 文字宽分位数
4. `switch_theme("dark")` 后字号/按钮高是否保持

⚠️ 必须 `QT_QPA_PLATFORM=offscreen`: 老倪弹窗零容忍, 真实 DISPLAY 下 show() 会闪窗。
offscreen 平台字体度量与真机一致 (同 fontconfig), 但会打印 `propagateSizeHints()` 噪音, grep 掉。

## v2.8.4 实测数据 (改前 → 改后)
| 项 | 改前 | 改后 |
|---|---|---|
| 工具栏容器 | QHBoxLayout 固定 44px 单行 | FlowBar(FlowLayout) 80px 自适应 |
| 工具栏按钮高 | 35px (emoji 差异 52~66 不齐) | 统一 66px |
| 按钮字高 | 22px (11pt) | 30px (15pt), padding 5x14→10x20 |
| 窄窗口 (2400/1200) | 挤压/文字省略号 | 2 行 / 3 行, 挤压 0 |
| 模块库宽 | 360px | 560px (LibraryPanel.LIB_W) |
| 模块名被切 | 270/434 = **62.2%** | 0/434 = 0% |
| 主窗口启动 | 写死 1400x900 (占 3068x1936 工作区 27%) | 可用宽≥2560 → 最大化 |

模块名文字宽分位: P50=333 P75=408 P90=461 P95=472 P99=505 P100=625px
→ 面板宽 460 切 25.3% / 500 切 15.0% / **560 切 0.9%** / 620 切 0.5%; 560 是性价比拐点。

## 新增模块 tools/gui/ui_flowlayout.py
- `FlowLayout(parent, margin=(l,t,r,b), h_spacing, v_spacing)`: Qt 官方 Flow Layout 移植,
  `heightForWidth` 实现换行; 兼容糖 `addSpacing(px)` / `addStretch()`(空操作)。
- `FlowBar(QFrame)`: 内置 FlowLayout 的工具栏容器, `resizeEvent/showEvent` 里
  `setFixedHeight(flow.heightForWidth(width))` → 行数变了高度跟着变。
- 用法 (simulink_module._build):
  ```python
  from ui_flowlayout import FlowBar
  tb = FlowBar(margin=(12, 7, 12, 7), h_spacing=10, v_spacing=8)
  tl = tb.flow()          # 之后 tl.addWidget / addSpacing 照旧
  ```

## 坑 (踩过的, 别重复)
1. **QSS 字号没生效就算 sizeHint**: `setStyleSheet` 后必须 `ensurePolished()` 再取
   `sizeHint()/fontMetrics()`, 否则拿到默认字号 (「◀ 收起」写死 72px 就是这么切字的)。
2. **FlowLayout 跳过隐藏控件不能用 `it.isEmpty()`**: QSpacerItem.isEmpty() 恒 True,
   会把 addSpacing 一起吃掉 → 用 `it.widget() is not None and it.widget().isHidden()`。
   (`btn_back` 「⬅ 返回总系统」默认 setVisible(False), 不跳过会在行里留 180px 空洞)
3. **QBoxLayout 对子 widget 的 heightForWidth 不可靠** → 别指望 QFrame 自己长高,
   用 FlowBar 在 resizeEvent 里显式 setFixedHeight (同值不再 set, 不递归抖动)。
4. **emoji 让按钮高矮不齐** (⛶ 比 ▶ 高 14px): 组装完统一
   `h = max(b.sizeHint().height()); b.setFixedHeight(h)`, 别一个个设 minimumHeight。
5. **窗口大小有两处写死**: `StudioMainWindow.__init__` 的 `resize(1400,900)` **和**
   `main()` 里 `win.setGeometry(..., 1400, 900)` — 只改前者无效, main() 会覆盖。
   大屏判据: `QGuiApplication.primaryScreen().availableGeometry().width() >= 2560`。
6. **switch_theme 只替换颜色不动字号** (实测 light→dark 字高 30px 保持) → 放大是安全的;
   但按钮样式里的颜色会被替换成金属渐变/黑字, 新增按钮别用白字。
7. **超长文字**: 434 条里 4 条 >506px, 用 `fm.elidedText(text, Qt.ElideMiddle, usable)`
   中间省略 (保留开头模块名 + 结尾 VEH.5.xxx 编号), 完整名留 tooltip。

## 验收清单
- [ ] `probe_ui_metrics.py`: 挤压 0 / 溢出 0 / 模块库被切 0
- [ ] `tools/ci/integrity_check.py` 五处版本一致绿
- [ ] 重启 studio (`pkill -9 -f "gui-venv311/bin/python studio"` → 后台重启),
      `xdotool search --name "XSpace Studio" getwindowname/getwindowgeometry` 确认
      标题版本号 + 窗口已最大化 (3068x1862), `/tmp/studio_launch.log` 无 traceback
- [ ] ⚠️ pkill 别写 `pkill -9 -f studio.py` — 会匹配到 Hermes 自己的 shell 把命令整条打死
      (exit -9, 后续命令不执行); 用 `pkill -9 -f "gui-venv311/bin/python studio"`
