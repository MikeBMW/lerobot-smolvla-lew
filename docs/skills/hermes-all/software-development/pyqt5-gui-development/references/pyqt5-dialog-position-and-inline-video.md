# PyQt5 弹窗定位 + 画布内嵌视频 + 静默失败 (2026-08-18 Z-MAX 控制台实测)

## 1. 弹窗定位: VcXsrv 多屏 = 单一虚拟大屏 (用户"视频/波形都没有"的真相)
- 症状: 弹窗/播放器"看不到"但窗口其实在 — `DISPLAY=... xwininfo -root -tree` 显示 `+3707+237` 等 x>3000（副屏/屏缝坐标）
- **根因①: VcXsrv 把多显示器合成一个虚拟 X 屏**（宽 5120）— `QApplication.primaryScreen()`/`screenAt()` 返回整个虚拟桌面, `availableGeometry().center()` = 两屏之间 (x≈2159) → "屏幕居中"落在缝隙, 用户永远看不到
- **根因②: `dlg.move()` 在 `show()` 之前会被 Qt 强制居中父窗口覆盖**（QDialog(parent) 的 show 语义）→ move 白做。**必须 show 之后再 move**
- **正解: 按主窗口几何区域内居中**（不按屏幕）:
  ```python
  def _popup_on_main_screen(self, dlg):
      try:
          from PyQt5.QtWidgets import QApplication as _QA
          _mw, _mx = None, 0
          for _w in _QA.topLevelWidgets():        # 排除 [画布] 浮动窗后取面积最大
              _t = _w.windowTitle() or ""
              if not _w.isVisible() or "[画布]" in _t:
                  continue
              _g = _w.frameGeometry()
              if _g.width() * _g.height() > _mx:
                  _mx = _g.width() * _g.height(); _mw = _w
          if _mw is None:
              _mw = self.window()
          _g = _mw.frameGeometry()
          dlg.move(_g.left() + (_g.width() - dlg.width()) // 2,
                   _g.top() + (_g.height() - dlg.height()) // 2)
      except Exception:
          pass
  # 调用顺序: dlg 构造 → show()/_show_nonmodal(dlg) → _popup_on_main_screen(dlg)
  ```
- **找主窗口别按标题匹配品牌名**: 主窗口标题可能是 `studio.py`（未设置 windowTitle）, 而 "XSpace Studio..." 是浮动画布窗口的标题 — 用"排除 [画布] 后取面积最大可见顶层窗口", 别用 `"XSpace" in title`（会选中浮动画布或匹配不到回退 self.window() 又是浮动画布 → 反复弹副屏, 排查多轮）
- 播放器/Scope/硬件属性面板等所有非模态弹窗统一走此函数; 每次新增弹窗都要检查

## 2. 视频播放: QMediaPlayer/gstreamer 不可靠 → ffmpeg 抽帧 + QTimer 帧轮播
- 容器无 PulseAudio 时 QMediaPlayer 播放**跳跃不连贯**（gstreamer 时钟问题）或黑屏（渲染失败）; 播放完还可能卡死窗口关不掉
- **正解: mp4 → ffmpeg 抽帧 PNG → QTimer 轮播 QPixmap**（避开 QtMultimedia 全家）: 66ms/帧 ≈ 15fps, 用户观感连贯
  ```python
  # 抽帧 (后台线程, 不碰 Qt): ffmpeg -y -i src.mp4 -vsync 0 f_%04d.png
  # 完成: 类级 pyqtSignal(str) emit → 主线程槽刷新帧列表 (跨线程铁律)
  ```
  - 抽帧放后台线程（250 帧 PNG 2-5s）; 主线程跑会 GUI 假死几秒 → 测试 QTimer 链全停 → 误判"崩溃"
  - 帧目录缓存 `reports/_mlp_cache_<视频名>/`: 缓存命中秒开; **缓存目录必须 gitignore**（250 张 PNG 进 git → commit 卡死超时, 实测踩过）
- **画布内嵌视频**（用户要求"在 simulink 画布上显示视频", 不要弹窗）:
  - SimNodeItem 加 `video_pixmap = None` / `video_overlay = ""` 属性 (QGraphicsObject 可挂 Python 属性)
  - `paint()` 里主体框画完后: `pm.scaled(节点内可用尺寸, KeepAspectRatio, SmoothTransformation)` + `painter.drawPixmap(QRectF(...), pm, QRectF(...))`
  - 播放 timer 每帧: `item.video_pixmap = pm; item.video_overlay = "文件名 · 帧数"; item.update()` → 画布直接动起来
  - 节点尺寸要放大（340×260 才看得清画面）; 双击节点 = 播放/暂停 toggle
- **播完一圈自动暂停**（用户嫌循环播放"插拔动作重复太多"）: tick 里 idx 归零时 `timer.stop()` + overlay "已播完 · 双击重播"
- 文字反/片源不对: 右键菜单加"转正 180 度"(`pm.transformed(QTransform().rotate(180))`) + "下一个/上一个视频"切换（metaworld 视频可能带旋转内容, 文件名 rot180 变体是旋转过的）

## 3. 🐛 QPixmap 局部 import → 方法 NameError 被 except 吞 = 静默失败
- 症状: 视频"不显示", overlay 卡"加载中", pixmap 恒 False; 手动调该方法"没异常"（except: pass 吞了 NameError）
- 根因: `QPixmap, QTransform` 只在某函数里 `from PyQt5.QtGui import ...` 局部 import, 其他方法（_mlp_show）引用时 NameError → 被 try/except 吞
- **修复: 依赖 Qt 类的工具方法一律模块级 import**（模块顶部 import 列表加 QPixmap, QTransform）
- 排查口诀: "功能没生效 + 手动调用无异常" → 把 `except Exception: pass` 临时改 `print(repr(e))` 暴露（本案例就是 spy 计数 + 手动调用组合才定位到）

## 4. Python 类级访问坑 (动态加载模块时高频踩)
- **property 需实例访问**: `PW.total_mass`（类上访问）拿到的是 property 对象 → `float / property` TypeError（被 except 吞 → 面板静默失败, 只看到日志一句"面板失败"）
- **实例方法需实例访问**: `PW.generalized_mass()` 类上调用报 `missing 1 required positional argument: 'self'`
- 修复: 先 `_pw = PW()` 实例化, 所有 property/方法走实例; 类属性（HARDWARE_SPEC/AXIS_MOTORS 等 dict/list）可直接类访问

## 5. importlib 动态加载源码模块 (不依赖 sys.path)
GUI (tools/gui/) 引仓库 src/ 下的模块时, 仓库根不在 sys.path → `from src.lerobot...` 直接失败。
**正解 (与 state_space_sim.py 同款)**: 
```python
import importlib.util
path = os.path.join(self._repo_root(), "src/.../execution.py")
_spec = importlib.util.spec_from_file_location("state_space.execution_hw", path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
```
注意模块名唯一（execution_hw 后缀防与已有模块冲突）。
