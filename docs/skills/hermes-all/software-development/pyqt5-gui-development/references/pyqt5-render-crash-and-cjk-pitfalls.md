# PyQt5 渲染/崩溃/中文字体坑 (2026-08-18 Z-MAX 状态空间画布实测)

## 1. 渲染对象跨线程 = SIGSEGV (QPainter/QImage) → 用 Pillow
- 症状: 后台线程(threading.Thread)里用 QPainter/QImage 渲染视频帧 → 进程 SIGSEGV (exit -11),
  崩溃前 stderr 打 `QObject::killTimer: Timers cannot be stopped from another thread` +
  `QObject::~QObject: ...`; 视频文件本身已生成(线程跑完渲染), 崩溃发生在线程退出/Qt 对象析构
- 根因: QPainter/QImage 是 Qt 对象, 工作线程使用/析构 = 跨线程 Qt 操作
  (**offscreen 无 X 连接时不复现 — offscreen 测试通过 ≠ 真实 X 环境安全**)
- 正解: 视频/图像渲染一律用 Pillow (纯 Python, 线程安全):
  ```python
  from PIL import Image, ImageDraw, ImageFont
  img = Image.new("RGB", (W, H), "#0d1117")
  d = ImageDraw.Draw(img)
  d.ellipse/rectangle/line/text(...)
  img.save(png)   # → ffmpeg -framerate 25 -i frame_%04d.png -c:v libx264 -pix_fmt yuv420p out.mp4
  ```
- 线程安全验证必须模拟真实 GUI: offscreen + QApplication + threading.Thread 调渲染函数 +
  主线程 processEvents 循环, 线程 join 后继续跑事件循环数秒 — 只测函数返回值测不出析构期崩溃

## 2. PyQt5 模块保持主线程 import
- 工作线程首次 import 含 `from PyQt5.QtWidgets import ...` 的模块, 真实 X 环境有崩溃风险
  (触碰 Qt 全局初始化) → 调用方主线程先 `import 该模块` 预加载, 线程内 from ... import 走
  sys.modules 缓存; 模块顶层别放 `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")`
  (会污染主进程后续 Qt 初始化 — 只在 `__main__` 独立运行时设置)

## 3. QSS 类选择器不认 Python 子类 ("Could not parse stylesheet")
- 症状: `QPlainTextEdit { ... }` 样式应用到 `class _CodeEditor(QPlainTextEdit)` 实例 →
  stderr 报 `Could not parse stylesheet of object _CodeEditor` (PyQt 为 Python 子类注册动态
  metaObject, className=`_CodeEditor`, Qt QSS 解析器不认未知类名)
- 正解: ① `setObjectName("srcEditor")` + QSS `#srcEditor { ... }` 对象名选择器
  ② 或编程式样式绕开 QSS: `setFont(...)` + `palette().setColor(QPalette.Base/Text/Highlight)` +
  `setFrameShape(QFrame.StyledPanel)`
- 判据: `widget.metaObject().className()` 返回 Python 子类名 = QSS 类选择器必炸

## 4. DejaVu Sans 无中文字形 → QPainter 中文模糊
- 症状: 波形/图表窗口 `QFont("DejaVu Sans", 10)` 渲染汉字模糊 (DejaVu 无 CJK 字形, Qt fallback
  低质量字体)
- 正解: 不指定西文字体用默认 `f = QFont(); f.setPointSize(10); f.setBold(True)` (默认链含
  wqy-microhei); Pillow 侧 `ImageFont.truetype("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", size)`

## 5. SIGSEGV 崩溃留证: faulthandler + gdb
- faulthandler 常驻: 程序顶部 `import faulthandler; faulthandler.enable()` — SIGSEGV 自动 dump
  Python 栈 + **已加载 Extension modules 列表** (列表缺某扩展 = 该功能从未跑到, 可排除嫌疑)
- gdb 抓 C 栈 (Qt 内部崩溃 Python 栈只有 exec_ 一行): 
  `gdb -batch -ex run -ex "thread apply all bt" --args <venv>/bin/python studio.py > /tmp/gdb.log 2>&1`
  后台跑, 崩溃自动打全部线程 C 栈, GUI 窗口照常可用; core_pattern 只读改不了时这是唯一 C 栈途径
- 崩溃分类: `QObject::killTimer / Timers cannot be stopped from another thread` =
  有 QObject 被跨线程 stop/析构 — 查哪些窗口/QTimer 在非主线程被停、哪些 Python 线程持有 Qt 对象引用

## 6. QtMultimedia 后端依赖
- `from PyQt5.QtMultimedia import QMediaPlayer` 缺 `libpulse-mainloop-glib.so.0` → ImportError:
  `apt-get install -y libpulse0 libpulse-mainloop-glib0`
- 播放 mp4 还需 gstreamer: `apt-get install -y gstreamer1.0-plugins-good gstreamer1.0-libav gstreamer1.0-plugins-base`
- 容器无 PulseAudio 时 stderr 打 `Failed to connect: Connection refused` 但视频照常缓冲
  (mediaStatus=3 BufferedMedia, error=0) — 无害

## 7. 终端(日志区)固定暗底白字 + 主题切换不覆盖
- 日志区 QSS 文字色若不在 THEMES 映射表里, 暗色主题下 = 暗底深灰字看不清; 直接固定
  `background:#0d1117; color:#ffffff` + switch_theme 循环里 `if wdg is self.log_box: continue`
  (主题切换跳过该控件)
