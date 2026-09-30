# 控制台子窗口「拖到扩展屏就自己跳回主屏」— 2026-09-17 (v5.6.25 修)

老倪: 「YOLO 目标检测的窗口, 为什么不能拖拽到扩展屏幕上呢? 拖过去之后就自己跳回到原来的屏幕」。

## 结论: 不是显示器/mutter, 是窗口自己的 clamp

- 窗口 = 「📺 输入图像 · 实时视频流 + 标定 (YOLO 目标检测 节点)」(`tools/gui/yolo_input_viewer.py`)。
- `_clamp_to_screen()` 原来**只拿 `QApplication.primaryScreen().availableGeometry()`** (eDP-1 1920x1200) 当边界,
  而 `_tick()` (66ms QTimer, 15Hz) 里 `if time.time() - self._last_clamp > 5.0: self._clamp_to_screen(silent=False)`
  每 5 秒调一次 ⇒ 窗口被拖到 HDMI (x≥1920) 被判"越界" → `setGeometry` 拽回主屏。
- 该 clamp 本意是"拔外接屏后别把窗口留在看不见的地方"(注释记 `2436x797` 落屏外那个 case), 漏了双屏正常使用。
- **排除法**: 主窗 XSpace Studio 一直待在副屏 `X=1920 Y=74 W=1920` 没事 ⇒ mutter 不会在手动移动后搬回窗口
  (若是 X screen / WM 问题, 主窗也待不住)。

## 实测数字 (真双屏 eDP-1 1920x1200 + HDMI-1-0 1920x1080 @+1920+0)

| 台架 | 结果 |
|---|---|
| 现场真窗口: `wmctrl -i -r <wid> -e 0,2000,100,-1,-1` | t=5.0s 跳回 x=572 (= 1920−1348); 窗口日志打印 `屏幕变化 → 窗口拉回屏内: (572,98) 1348x945 (屏 1920x1200)` |
| 台架·**老实现** (`git show HEAD:tools/gui/yolo_input_viewer.py`) | t=5.0s x=2000→572 ❌ |
| 台架·**新实现** | x=2000 停满 14s 不动 ✅ |

## 修了什么 (v5.6.24 → 待发 v5.6.25)

`tools/gui/yolo_input_viewer.py`:
1. `_clamp_to_screen` 边界改**所有屏幕** + 按可见面积占比: `vis = Σ area(rect ∩ screen.availGeo())/area(rect)`,
   `vis >= 0.4` → 完全不动 (拖到副屏=不干预); 真越界 (拔屏/坐标飞屏外/窗口比屏大) 才拉回**离窗口中心最近的屏**
   (原自愈功能保留)。新增 `_screens()` / `_visible_ratio()` 两个 helper。
2. `open_input_viewer()` 初始位置跟随**父窗所在屏**: `QApplication.screenAt(parent.window().frameGeometry().center())`
   → 主窗在 HDMI 时子窗直接开在 HDMI 居中, 不用每次手拖 (原来永远弹在笔记本屏)。

新增取证脚本: `tools/verify_viewer_clamp_multiscreen.py` (7 case 假屏幕注入单测) ·
`tools/verify_viewer_clamp_live_window.py` (真窗口 A/B 台架, `CLAMP_VARIANT=old|new`)。

## 生效方式 (重要)

- 改的是 **GUI 进程内模块 ⇒ 必须重启控制台**才生效。
- `zmax-studio.service` 是 **`Restart=no`** (老倪 2026-09-17 要求彻底关掉自动拉起) ⇒
  **kill PID 不会自动拉起**, 用 `systemctl --user restart zmax-studio`
  (该命令会被 Hermes 安全策略 flag 但**自动批准**, 实测成功, 新 PID + 启动时间即刻可查)。
- 重启后「输入图像」窗口不会自动恢复, 要用户从节点右键菜单重开一次。

## 通用套路 (其他窗口/其他项目同样适用)

见 `pyqt5-gui-development` SKILL.md §13 + `references/multiscreen-window-clamp.md` +
`scripts/multiscreen_clamp_probe.py`。三条要点:
①判定先分清 WM 与应用 (主窗能停副屏 = 应用代码); 固定节拍跳回 = 应用自己的定时 clamp;
②判据用逐屏求交的可见面积占比, 别用 `primaryScreen()` 也别用 `virtualGeometry()` 并集;
③台架要 A/B (老实现当对照组) + 注意 stub 绑 `@staticmethod` 的假 PASS 陷阱。
