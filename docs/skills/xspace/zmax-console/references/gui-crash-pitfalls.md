# GUI 崩溃与渲染坑 (PyQt5 / VcXsrv / 容器, 2026-08-18 实测)

全部在状态空间仿真视频/波形开发中实锤。核心纪律: **Qt 对象严禁工作线程**。

## 1. QPainter/QImage 工作线程渲染 = SIGSEGV (最致命)

症状: 视频导出线程用 QPainter 画帧 → 进程崩, exit -11, stderr 出现
`QObject::killTimer: Timers cannot be stopped from another thread` +
`QObject::~QObject: Timers cannot be stopped from another thread`。

根因: PyQt 对象(QPainter/QImage/QObject 派生)在非主线程创建/使用/析构。
offscreen 平台下测不出来(无 X 连接, 时序不同) — **必须真实 X 环境验证线程安全**。

修复: 渲染改用 **Pillow (纯 Python, 线程安全)**:
```
uv pip install --python /root/gui-venv/bin/python Pillow
Image.new("RGB", (W,H), "#0d1117") + ImageDraw → 画网格/椭圆/矩形/线段/文字
ImageFont.truetype("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", size)  # 中文
ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")   # 数字
→ PNG 帧 → ffmpeg -framerate N -i frame_%04d.png -c:v libx264 -yuv420p out.mp4
```

## 2. 工作线程首次 import PyQt5 模块 = SIGSEGV

症状: 同上 SIGSEGV, 但线程里没有画图 — 只有 `from xxx import make_video`
首次触发模块顶层 `from PyQt5.QtWidgets import ...`。

根因: 真实 X 环境下, 非主线程 import PyQt5 触碰 Qt 全局初始化/连接。

修复: **主线程预加载**, 线程内走 sys.modules 缓存:
```python
def _start_video_export(self, tr):
    import gen_state_space_video  # noqa: F401 — 主线程 import (PyQt5 顶层 import 在此执行)
    def _worker():
        from gen_state_space_video import make_video  # 缓存命中, 不重复执行顶层
```

## 3. 崩溃留证: faulthandler 常驻

studio.py 顶部:
```python
try:
    import faulthandler
    faulthandler.enable()   # SIGSEGV 时 dump Python 栈到 stderr
except Exception:
    pass
```
再崩直接看栈, 不用猜。复现测试: offscreen + QTimer 事件循环驱动完整 GUI 流程
(加载画布→start_sim→播放→视频线程→继续跑 8s), 观察是否延迟崩溃。

## 4. PyQt Python 子类的 QSS 选择器坑

`QPlainTextEdit { ... }` 选择器**不匹配 Python 子类** (_CodeEditor), 报
`Could not parse stylesheet of object _CodeEditor` — PyQt 为子类注册动态
metaObject (className="_CodeEditor"), Qt QSS 解析器不认。
- 类名选择器 (含 `_CodeEditor` 写法) 无效
- 修复: `setObjectName("srcEditor")` + `#srcEditor {...}` — **仍然报错**
- 真正干净: 放弃 QSS, 用编程式样式 `QFont + QPalette(setColor(Base/Text/Highlight))`

## 5. 主题映射表外的颜色 = 暗底灰字

switch_theme 只替换 THEMES light→dark 映射对里的颜色。log_box 文字色
`#57606a` 不在映射表 → 暗色主题下暗底深灰字, 看不清。
修复: 固定暗底白字 `background:#0d1117; color:#ffffff` + switch_theme 循环里
跳过该控件 (`if wdg is getattr(self, "log_box", None): continue`)。

## 6. 中文字体: DejaVu 无 CJK 字形

QFont("DejaVu Sans") 渲染中文 → Qt fallback 到低质量字体 → 模糊。
- 修复: 不指定字体 (系统默认走 wqy-microhei) 或显式 QFont("WenQuanYi Micro Hei")
- Pillow 渲染: ImageFont.truetype("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc")

## 7. QtMultimedia 内嵌播放 (GUI 播视频)

依赖: `apt-get install -y libpulse0 libpulse-mainloop-glib0 gstreamer1.0-plugins-good gstreamer1.0-libav gstreamer1.0-plugins-base`
- 容器无 PulseAudio → stderr "Failed to connect: Connection refused" 无害 (视频照播)
- 验证: QMediaPlayer mediaStatus==3 (BufferedMedia) + error==0 = 解码 OK
- offscreen 下 "no service found for org.qt-project.qt.mediaplayer" 是平台限制, 非故障
