# pyqtgraph/OpenGL 3D 视图「看得懂」工程学 (2026-08-25 老倪连环反馈总结)

一次会话里老倪连问五轮: 视角不一样 → 动作轨迹不一样 → 还是一堆点 → 取消所有选项还有绿黄线
→ u_ff 是什么/为什么一个点一条线/方向呢。每一轮的根因都**不是**我以为的那个。
本文件是这类「3D 可视化用户看不懂」问题的通用排查+修法清单。

## 铁律 0: 用户说"看不懂"= 缺自解释信息, 不是几何画得不对
改形状/改颜色都救不了。必须补三件套:
1. **取景** — 元素在画面上要够大 (见铁律 1)
2. **标注** — 每个元素旁边写清 名称 + 数值 + 单位 + 方向
3. **数值面板** — 侧栏逐帧滚动全部关键量 (老倪明确要求实时滚动, 不要一次性静态填充)

## 铁律 1: 先量画面占比, 再谈画得对不对
`tools/probe_view_pixels.py` 读 framebuffer 逐元素统计像素占比 + 输出 60×26 文字色块图
(给看不到图的场景用)。判据: **背景占比 > 90% 就是取景失败**。
实测教训: 严格 1:1 复刻视频相机 → 背景 96.8%, 光模块 51px、夹爪 458px、轨迹 5px
⇒ 用户看到的就是"一堆点"。自动取景 (投影迭代收紧, 见 state-space-video-same-source.md)
→ 背景 71.8%, 夹爪 19384px。

## 铁律 2: 标量 → 几何长度必须按**实测数据范围**归一化 + 最短保底
坑: 箭头长度写 `clip(|u|,0,1) × 80mm`, 而真实 |u| 只有 0.031~0.331 m/s
→ 箭头 2.5~26mm, 近距缩到 2mm ⇒ 屏幕上只剩箭头尖那个点 (老倪: "为什么是一个圆点和一个线段")。
正确: `length = clip(|u|/U_REF, MIN_FRAC, 1.0) × L_MAX`,
U_REF 取实测上限 (0.35 m/s), L_MAX=0.10m, MIN_FRAC=0.22 保底 → 22~100mm 始终可见。
**任何"幅度→长度/半径/粗细"的映射都先把该量的真实 min/max 打出来再定系数。**

## 铁律 3: 方向必须有箭头头 + 文字人话
一根两头一样的线段看不出朝向。
- 锥形箭头头: `gl.MeshData.cylinder(radius=[r, 0.0], length=L)` + Rodrigues 旋转对齐
  (占箭杆末段 ~28%, 底半径 ~0.42×头长)
- 文字方向人话: 把单位向量主分量翻成场景语义, 例 `−X(朝孔位) / +Y(朝台面外) / ↓下压 / ↑抬升`
  (阈值 |分量|>0.25 才列出, 全小于则"几乎静止")

## 铁律 4: ⚠️ pyqtgraph `GLTextItem` 在本机 (Mesa 25.2 + GLViewWidget) **完全不渲染**
源码 `GLTextItem.paint()` 走 `QPainter(self.view())` 直接画控件表面 →
本机实测: 清空/恢复文本前后屏幕像素差 **0 px** (抓真实窗口验证, tools/probe_text_labels.py)。
**替代方案 (已验证 11257 px 文字上屏)**: 自绘透明覆盖层 `LabelOverlay(QWidget)`
- `setAttribute(Qt.WA_TransparentForMouseEvents)` + 透明背景, 作为 GLViewWidget 的子控件
- `project_world(view, p)` 算屏幕坐标 → `QPainter.drawText` + 半透明深底圆角 + 引线指向目标
- 尺寸跟随: `installEventFilter(self.view)` 拦 Resize + 自身 resizeEvent 双保险
- 所有标注 (物体名/箭头名/坐标轴 XYZ 字样) 统一走这一层, GLTextItem 全部删掉

## 铁律 5: 数据层要 `setGLOptions("additive")` 穿透遮挡
末端轨迹恰好走在机械臂/夹爪实体位置 → 默认深度测试下被完全挡住 (只剩 5px)。
traj / 动作箭头(杆+尖+锥头) / YOLO 框 / 估计线 / 接触球 全部 additive; 线宽 ≥3.5。

## 铁律 6: 「图层勾选框点了没用」的定位法
症状: 老倪"我把所有选项都取消了, 屏幕还有一小段绿线和黄线, 这是啥?"
定位 (30 秒, 不要猜): 全关后**逐元素打印 visible 状态**
```python
for k, it in dv._gl_items.items():
    items = it if isinstance(it, list) else [it]
    vis = [o for o in items if o.visible()]
    if vis: print(k, type(vis[0]).__name__, len(vis), '/', len(items))
```
本次根因: `_apply_layer_visibility(key)` 只查 `_gl_items[key]`, 而四层动作箭头存的是
`<key>_line` / `<key>_tip` / `<key>_head` (+ `ufuse_sphere`), 图层 key 本身不在字典里
→ `get()` 拿到 None 直接 return ⇒ **四个勾选框完全失效**。
残留绿线 = 前馈加速器箭头, 黄线 = 动作调制器箭头+大球 — **不是坐标轴**。
顺带: 任何 `_xxx` 下划线私有 key (网格 `_grid` / 坐标轴 `_axis` / 标签 `_labels`) 都不受图层控制,
要么纳入图层字典, 要么明确写进说明。
验收判据: **全部图层取消后, 画面非背景像素 = 0**; 每个图层逐个开→关像素归零。

## pyqtgraph 固定配色/语义备忘 (别猜, 源码为准)
| 对象 | 事实 |
|---|---|
| `GLAxisItem` | **绿=Z 黄=Y 蓝=X** (源码 updateLines 里 hardcode), 画在原点, 长度=setSize |
| `opts['fov']` | **水平**视场 (`r=near·tan(fov/2); t=r·h/w`) — metaworld fovy 是垂直, 必须换算 |
| `projectionMatrix()` | 本版需 `(region, viewport)` 参数, 离屏无 GL 上下文会抛 OpenGL 版本异常 → 自己手算 |
| `rotationMethod='quaternion'` | 才能精确设定相机朝向 (含 roll); euler 模式只有 elev/azim |
| `GLTextItem` | QPainter 路线, 本机不渲染 (见铁律 4) |

## 像素验证的三个假阴性陷阱 (踩过, 会误导结论)
1. **additive 混色**: 叠加后颜色被背景抬亮 (89,166,255)→(130,212,255), 窄容差 ±40 直接漏判成"只有 5px"
   → 用相对判据 `b>r+55 & b>g+30 & b>120` 而不是绝对色距
2. **同色系元素混一起**: 金黄箭头(255,199,31) 与金色光模块(242,184,26)、橙机械臂(217,76,46) 会被同一掩码抓到
   → 测某元素前先**关掉其它同色图层**; 或用比例判据 `g>0.6r & b<0.4r` 区分金 vs 橙
3. **深底标注反而降低"亮像素"**: 标注的半透明深色底板会遮住后面亮元素 → 亮像素总数**下降**,
   看起来像"标注没渲染" → 判据必须用**该元素专属文字颜色**逐色统计, 不能用亮像素总数
另: framebuffer 抓图 (`grabFramebuffer`) 抓不到 QPainter 覆盖内容; 抓屏幕要
`xdotool search --name ... getwindowgeometry --shell` 拿精确绝对坐标, 并临时最小化亮色窗口
(`xdotool windowminimize` → 验完 `windowmap` + `windowactivate` 复原), 否则裁到别的窗口。

## 命名规范 (老倪明确要求, 违反会被打回)
信号/图层名**直接用源模块名**, 不许夹带解释性措辞:
| ✅ 正确 | ❌ 被否掉的 |
|---|---|
| ⚡ 前馈加速器 | 前馈建议 u_ff / 左脑前馈预测动作 |
| 🔮 状态估计器校正 | 反馈校正 u_fb |
| 🧭 动作调制器输出 | 融合指令 u (action输出) |
| 🛡 安全执行边界 | 安全限幅 u_sat |
原话: "信号直接写前馈加速器就得了, 为什么要夹带前馈预测呢"。
改名时要全库搜 (`grep -rn 前馈预测\|前馈建议`) 把日志/HTML 报告/节点描述一起清掉, 不能只改图层标签。

## 相关探针 (都在 tools/, 离屏不弹窗)
| 脚本 | 用途 |
|---|---|
| `probe_view_pixels.py` | 逐元素像素占比 + 文字色块图 (判取景/可见性) |
| `probe_view_match.py` | 3D 视图 vs 视频: 视角角差/关键点屏幕位置/内容/轨迹同源 |
| `probe_view_render.py` | 真实渲染像素质心 vs 世界坐标投影 (判几何位置对不对) |
| `probe_text_labels.py` | 抓真实窗口验证文字标注是否上屏 (GLTextItem 那个坑) |
| `probe_canvas_nodes.py` | 画布节点文字拥挤度 (见 ui-sizing-hidpi.md) |
