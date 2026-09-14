# Qt 自绘窗口三坑 + 可视化 UI 设计铁律 (2026-09-05, 直方图 v3 重设计)

老倪连续反馈: "直方图没输出…字体太小看不到, 也没有任何图示, 重新设计 UI, 你这个设计太差了, 快点改" → 重设计后整窗近乎空白 (内容比 0.001) → 逐层排到 3 个 Qt 坑。承接 playback-sync-probe-seq-2026-09-05。

## 坑 1: QFont pointSize 必须 int — float 静默整窗空白 (实测)
- `QFont("Sans", 9.5)` / `QFont("Sans", 10.5, QFont.Bold)` → TypeError ("argument 2 has unexpected type 'float'")。
- 崩在 paintEvent 内部, try/except 吞掉后只画"绘图异常" → **窗口看起来全空** (内容比 0.001, 无报错无日志)。
- 铁律: 自绘代码所有 QFont 字号 int; **任何 paint 改动后必须渲染探针**: `w.grab().save()` + PIL 数内容比 (阈值 >45 灰度的占比), 期望 ≥0.05 (有标题/图例/柱)。空白先手动调 paint 路径 (不包 try) 打 traceback — paintEvent 的 except 是静默杀手。
- 排查快捷: 内容比 ~0.001 = 只画了"绘图异常"/背景; ~0.05+ = 正常有内容。

## 坑 2: QLabel 在 QVBoxLayout 被拉伸占满整窗 (实测)
- 自绘 QDialog 里放一个 QLabel 状态条 (`lay.addWidget(self._cap)`), 无 stretch 控制 → QLabel 高度被拉到**整窗** (840px), 布局在 show 前 geometry 未算 (offscreen 下 height()=480 假值)。
- paint 用 `self._cap.height()` 定位 → 绘图区被推到窗外 → 内容比 0.001。
- 正解: **自绘窗口的状态条一律用 QPainter 画** (fillRect 顶部色带 + drawText), 不依赖 QLabel/布局; 或 `addWidget(w, 0)` + QSizePolicy.Fixed。offscreen 布局几何不可信 — 固定值最稳。

## 坑 3: cv2 自带 Qt xcb 插件污染 (报告子进程 xcb 崩, 实测)
- 进程先 import 验证层/ultralytics (cv2) 再建 QApplication → Qt 从 `cv2/qt/plugins` 加载 xcb (缺系统依赖) → "platform plugin xcb found but couldn't be loaded", 即使 DISPLAY 正常。
- 正解 (QApplication 创建前): 扫 sys.path 找 PyQt5 真实插件目录并设:
  `os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = <site-packages>/PyQt5/Qt5/plugins`
  无 DISPLAY 再回退 `QT_QPA_PLATFORM=offscreen` (3D GL 会失败, 诚实记录)。
- 适用: gen_viz_evidence / gen_verif_auto_report 这类"先跑用例(import cv2)后开 Qt 窗"的工具。

## 坑 4: 带 parent 的 QDialog min/max 按钮无效 (2026-09-05, 老倪: "最小化,最大化没效果")
- 与 qdialog-maximize-2026-08-28 同根: QDialog 默认 Qt.Dialog 类型被 WM 当对话框; 本会话扩展到 FFHistView/FFAttribView/StateSpaceScopeDialog (**都带 parent=self**) — min 和 max 都点了没反应。
- 修: __init__ 里显式 `setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.WindowSystemMenuHint | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)`。
- 验证 (程序化, 不依赖点击/WM): show → showMinimized → isMinimized=True; showMaximized → isMaximized=True。offscreen 可测状态切换。
- 同会话: 直接 `win.show()` 无 parent 在 WSLg/多屏弹屏外=看似没反应 → 统一 `_show_nonmodal(win)` + `_popup_on_main_screen(win)` (见 playback-sync ref)。

## 可视化窗口 UI 设计铁律 (老倪纠正: "字体太小看不到, 没有任何图示, 设计太差")
- **自解释**: 窗口内必须有图例/说明文字 (白柱=近150帧分布·朱红=最近一帧·x=0 虚线=ReLU截断休眠; 归因的 4 色块=4 输出维谁在指挥), 用户不该猜"这是啥"。
- **每行语义标题**: 层名大字 + 该层真实作用 (第 1 层·输入编码 W0: 39D 观测→512 特征), 活跃度进度条 + "活跃 N/512" 大字。
- **别用缩字号躲重叠** (前一轮 7-8pt 防 192DPI 重叠 → 用户"太小看不到"): 字号不足是错误方向 — 改布局/行高/留白, 字号 10-13pt 起步。
- **状态行随帧更新** (帧数/u_ff/主导输出维) — 窗口"活着"可感知, 也回答"在动吗/啥意思"。数据不动=用户报"没输出"的首要来源, 先把数据流打通再看样式。
- 空态文案给操作引导 ("先点 ⚡引擎快演 ▶运行 或 ⏭单步, 数据会自动进来")。
- 版本细节: LAYER_DESC 逐层说明 + 右列 u_ff 大字块; 默认 1200×840; 整窗无布局依赖全 QPainter 画。
