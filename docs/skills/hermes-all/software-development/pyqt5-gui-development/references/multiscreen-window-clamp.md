# 多屏窗口放置 / 被拽回主屏 (clamp 误判) — 2026-09-17 实测

场景: Ubuntu 原生 GNOME 46 (Mutter X11) + PyQt5 5.15, 双屏 eDP-1 1920x1200 (primary, 笔记本屏)
+ HDMI-1-0 1920x1080 (副屏, `+1920+0`, 单 X screen `/tmp/.X11-unix/X0`)。

## 用户报的现象
老倪: 「YOLO 目标检测的窗口, 为什么不能拖到扩展屏幕上? 拖过去之后就自己跳回原来的屏幕」。
跳回节奏 = **拖过去最多 5 秒**, 不是随机、不是立刻。

## 根因 (应用自己的代码, 不是 mutter/显示器)
`tools/gui/yolo_input_viewer.py`:

```python
def _tick(self):                                   # 66ms QTimer, 15Hz
    if time.time() - getattr(self, "_last_clamp", 0) > 5.0:   # ← 每 5s 一次
        self._last_clamp = time.time()
        self._clamp_to_screen(silent=False)        # ← 元凶

def _clamp_to_screen(self, silent=True):           # 旧实现(有 bug)
    scr = QtWidgets.QApplication.primaryScreen().availableGeometry()   # ← 只认笔记本屏
    w = min(self.width(),  max(700, scr.width()  - 40))
    h = min(self.height(), max(460, scr.height() - 40))
    x = min(max(self.x(), scr.x()), scr.x() + max(0, scr.width()  - w))
    y = min(max(self.y(), scr.y()), scr.y() + max(0, scr.height() - h))
    if (w, h, x, y) != (self.width(), self.height(), self.x(), self.y()):
        self.setGeometry(x, y, w, h)               # 拽回主屏
```

原意是好的 (注释记着"拔屏后窗口 2436x797 落到 1920x1200 屏外 → 用户看到窗口跑屏幕外去了"),
漏了"双屏正常使用"这一种情况: 窗口 x≥1920 落在副屏 = 被判越界。

## 现场取证 (三步, 顺序别反)
1. **排除 WM**: `wmctrl -lx` 看到**主窗** XSpace Studio 就在副屏 `X=1920 Y=74 W=1920` 一直待着没事
   → 说明 mutter 不会在手动移动后把窗口搬回去, 是子窗自己的代码。
2. **复现跳回**: `wmctrl -i -r <wid> -e 0,2000,100,-1,-1` → 每 0.5s `xdotool getwindowgeometry --shell <wid>`:
   ```
   t=0.5s..4.5s  x=2000  扩展屏✅
   t=5.0s        x= 572  主屏⬅      ← 1920-1348=572, 正好是 clamp 的边界
   ```
3. **窗口自己留证**: 该窗口日志区出现 `屏幕变化 → 窗口拉回屏内: (572,98) 1348x945 (屏 1920x1200)`
   (老实现 `silent=False` 时打印) — 应用自证。

## 修法
1. **clamp 判据改多屏 + 可见面积占比**:
   ```python
   def _screens(self):                       # 全部屏幕可用区
       return [s.availableGeometry() for s in QtWidgets.QApplication.screens()
               if s.availableGeometry().width() > 0]

   @staticmethod
   def _visible_ratio(r, screens):           # 逐屏求交(不是 virtualGeometry 并集)
       area = max(1, r.width() * r.height()); vis = 0
       for ag in screens:
           i = r.intersected(ag)
           if i.width() > 0 and i.height() > 0:
               vis += i.width() * i.height()
       return vis / area

   # _clamp_to_screen 内:
   if self._visible_ratio(rect, screens) >= 0.4:   # 任一屏可见 ≥40% → 用户放哪就是哪, 不动
       return False
   target = min(screens, key=...)                  # 真越界 → 拉回离窗口中心最近的屏
   ```
   为什么不用 `QApplication.virtualGeometry()`: 两屏高度不等时并集矩形包含不存在的区域 (幻影区),
   逐屏求交才是真可见性。
2. **子窗初始位置跟随父窗所在屏** (原来用 primaryScreen → 父窗已拖到 HDMI, 子窗还永远弹在笔记本屏):
   ```python
   c = parent.window().frameGeometry().center()
   scr = QApplication.screenAt(c) if hasattr(QApplication, "screenAt") else None
   scr = scr or QApplication.primaryScreen()
   ag = scr.availableGeometry(); win.resize(min(w, ag.width()-80), min(h, ag.height()-80))
   win.move(ag.x() + (ag.width()-w)//2, ag.y() + (ag.height()-h)//2)
   ```
3. **改的是 GUI 进程内的模块 ⇒ 必须重启 GUI 才生效**。本机 unit `zmax-studio.service` 是
   `Restart=no` (老倪要求彻底关掉自动拉起) ⇒ **kill PID 不会自动拉起**, 用
   `systemctl --user restart zmax-studio` (会被 Hermes 安全策略 flag 但自动批准)。

## 验证 (两层, 都要)
**① 纯逻辑单测** `tools/verify_viewer_clamp_multiscreen.py` — 用真实方法体 + 假屏幕注入 (替换模块命名空间里的
`QtWidgets`, 因为 PyQt 类属性不让改), 7 个 case: 拖副屏/副屏右缘/骑两屏/副屏最大化 → 不许动;
拔屏后 x=2332 → 拉回 (572,60); x=-5000 → 拉回; 拔屏+窗口 3000 宽 → 拉回并收窄 1880x1160。全绿。

**② 真实窗口 A/B 台架** `tools/verify_viewer_clamp_live_window.py` (通用版见本技能 `scripts/multiscreen_clamp_probe.py`)
— 真 QDialog + 同款 66ms 定时器/5s 节流 + 真双屏, `CLAMP_VARIANT=old|new`:
- 老实现 (从 `git show HEAD:tools/gui/yolo_input_viewer.py` 抠函数源码 exec 进来) →
  `t=5.0s x=2000→572` ❌ + 打印"屏幕变化 → 窗口拉回屏内"
- 新实现 → `x=2000` 停满 14s 不动 ✅
同一台架 old❌/new✅ 才算证据; 只跑新代码"没跳回"说明不了是修好了还是根本没触发 clamp。

## ⚠️ 写这个台架时踩的坑 (会让你得到假 PASS)
- **stub 类绑定被测方法时 `@staticmethod` 会被当实例方法绑定 self**:
  ```python
  class Stub:
      _visible_ratio = yiv.YoloInputViewer._visible_ratio        # ✗ TypeError: takes 2 args, 3 given
      _visible_ratio = staticmethod(...)                          # ✓
      # 通用写法:
      import inspect
      setattr(Stub, "_visible_ratio", inspect.getattr_static(cls, "_visible_ratio"))
  ```
  该 TypeError 被被测代码的 `except Exception: pass` 吞掉 → 函数直接 `return False`
  → "不许动"的 case 全部假 PASS。**排查口诀: 一个本该 MOVE 的 case (窗口飞到屏外) 如果也 `moved=False`,
  说明异常被吞了, 不是逻辑对**。
- 诊断被吞异常最快的办法: 临时把那个 `except Exception: pass` 换 `traceback.print_exc()` 再跑一遍诊断脚本,
  定位后还原 (别在正式代码里留 print) —— 与"静默失败陷阱"同款套路。

## 老倪口径
- 他问"为什么"→ 要**先给根因 + 证据** (现场复现数字 + 代码行号), 别先给方案列表。
- 修完必须**真窗口实测**, 口头/单测不算 (本机铁律: 要证据才认完成)。
- 汇报里说清"改了什么"(哪些文件/行为变化) + 需要他做什么 (重启 GUI / 重开窗口)。
