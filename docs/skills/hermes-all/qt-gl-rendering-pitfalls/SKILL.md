---
name: qt-gl-rendering-pitfalls
title: "Qt/pyqtgraph GL 渲染坑与 QPainter 2.5D 替代"
description: "Use when pyqtgraph GL 渲染空白/报 GLError/第二窗口崩, 或要画曲面."
trigger: "pyqtgraph GLViewWidget 渲染失败、'Error while drawing item'、glGetAttribLocation、第二/多 GL 窗口、曲面/碗可视化、QPainter 投影自绘"
---

# Qt/pyqtgraph GL 渲染坑与 2.5D 替代 (2026-09-07 实测)

一套实测钉死的跨平台 Qt OpenGL 可视化经验, 覆盖 pyqtgraph GL 的上下文
陷阱、GLSurfacePlot 网格绘制、以及"干脆用 QPainter 自绘 2.5D"的替代路线。

## 坑 0 (最狠): paint() 里抛异常 = Qt 直接 abort 整个进程 (2026-09-13 实测)

- 症状: 用户报"一打开某某界面程序就崩"(不是卡死, 是硬崩); 日志尾是
  `Fatal Python error: Aborted` + faulthandler 线程转储, 栈顶落在某个 `paint()`。
- 实例: `simulink_module.py` 背景行 paint → `_wrap_title(name, fm, avail)` →
  `QFontMetrics.elidedText(text, Qt.ElideRight, avail)` 里 **avail 是 float**
  → `TypeError: argument 3 has unexpected type 'float'` → Qt abort 全 GUI。
  (根因: 上游 `avail_w = max(80.0, float(...))`, 旁边虽算了 `_aw = int(avail_w)` 却传错了变量)
- **规则**: 凡是传给 Qt API 的宽度/坐标/尺寸参数一律先 `int()`/`float()` 显式转换;
  `QFontMetrics.elidedText` 的 width **必须 int** (PyQt5 不做隐式转换, 直接 TypeError)。
- **排查姿势**: 崩在 paint 里时 `try/except` 包住没用 (异常已逃到事件循环 → abort);
  正解 = 用 offscreen 复现: 加载场景 → 直接 `item.paint(painter, option, None)`
  或 `scene.render(painter)` → 把异常抓成字符串;
  再加**单元阴性对照** (`fm.elidedText(..., 300.0)` 应抛 / `..., 300` 应正常) 钉死根因。
- 只在特定数据下崩 (如"某个标题刚好需要省略号才崩") = 分支触发型 bug: 修复要放在
  **函数入口做类型归一**, 而不是只改那一个调用点。

## 核心坑 1: pyqtgraph shader 全局缓存绑「第一个」GL 上下文

- pyqtgraph `opengl/shaders.py` 在模块导入/首次绘制时编译一次, ShaderProgram
  句柄绑定创建它的那个 GL 上下文, 全局缓存。
- **再新建一个 GLViewWidget = 新 GL 上下文** → 旧句柄失效 → 该窗口所有 GL item
  绘制报 `GLError ... glGetAttribLocation` (或 stderr "Error while drawing item ..."),
  界面可能整体黑/缺内容, 无弹窗。
- 已知的"窗口复用"修复 (close 不销毁、只复用首窗) 只解决**同一窗口重开**;
  需要**第二个独立 GL 窗口** (如从主 3D 视图开辅助曲面窗) 时 pyqtgraph GL 不可用。
- 判断: 第二窗口所有 item 全报错 = 上下文问题; 首窗口正常。

### 解法 A: 多窗口场景禁用新 GLViewWidget
辅助曲面/仪表窗用非 GL 方案 (见 QPainter 2.5D)。

### 解法 B: 单窗口内的 mesh 绘制注意
- `GLSurfacePlotItem(x=1D数组, y=1D数组, z=2D, shader=None)` 在本机
  (Mesa/兼容上下文) 崩 `glGetAttribLocation` → 改用 `GLMeshItem`:
  自己构造 `gl.MeshData(vertexes=(N*M,3), faces=(2*(N-1)*(M-1),3) uint32)`,
  再 `GLMeshItem(meshdata=md, color=单色RGBA, smooth=False, shader=None,
  drawEdges=True, edgeColor=...)` — 纯色+边线路径与主场景已验证 mesh 一致。
- 同一程序里 GLScatterPlotItem/GLLinePlotItem 不要对第二窗口设
  `setGLOptions("additive")` — additive shader 同样跨上下文崩; 默认渲染即可。

## QPainter 2.5D 正交投影自绘 (零 GL 依赖的曲面方案)

固定视角下画"网格曲面 + 动态点/线"的可靠替代, 无 GL 上下文问题:

1. 正交相机: `eye = dist*(cosEl*sinAz, cosEl*cosAz, sinEl)`; `fwd=-eye/|eye|`;
   `right=norm(cross(fwd, worldUp))`; `upv=cross(right, fwd)`。
   投影点: `d=p-eye` → `x'=dot(d,right)*s+cx`, `y'=cy-dot(d,upv)*s` (s=像素/mm 缩放),
   深度 = `dot(d,fwd)` 用于排序。
2. **静态网格预渲染 QPixmap**: 把曲面四边形网格 (含参考环/十字线) 一次性画进
   QPixmap (远→近排序, 半透明 fill + 边线); resize 时重渲。每帧只投影动态
   点/轨迹/竖线叠上去 → 帧开销极小。
3. paintEvent 每帧: 画缓存 pixmap + 动态元素 (QPainter drawLine/drawEllipse)。
4. 数值实时放 QLabel (widget 布局内), 别塞画面。

## 渲染验证 (offscreen/真实 DISPLAY 通用)

- 像素级验证不要走 `QImage.bits()` + np.frombuffer (PyQt5 sip.voidptr 无 size 坑);
  直接 `widget.grab()` / `view.grabFramebuffer().save('/tmp/x.png')` → PIL 读图统计:
  非背景像素数、特定色系像素数 (青网格等) 判断"真画出来了"。
- 注意阈值: 深色背景 (#0d1117 ≈ 13,17,23) 会被 `>10` 全判亮 → 统计用 `>60` 或数色系。
- QWidget 小窗未 resize/未 processEvents 时 grab 尺寸极小 → 先 `resize()`+`show()`+
  `processEvents()` 再抓。
- QPainter/QPen/QPixmap/QPolygonF/QBrush 模块级使用必须显式 import;
  **QPolygonF 在 PyQt5.QtGui, 不在 QtCore** (QPointF 在 QtCore) — 实测 ImportError。
- 测试脚本里 numpy 的 `&` (位与) 会被命令安全检查误判为后台符号 — 用 `*` 或 np.logical_and。

## 常见流程

1. 新 3D 可视化: 单窗口 → GLMeshItem/GL items (首上下文 OK)。
2. 第二窗口 (曲面/辅助图) → QPainter 2.5D (预渲染 pixmap + 动态投影)。
3. 验证: 存 PNG 数像素, 别裸奔上线。
