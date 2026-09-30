# 3D 流形几何可视化 + 真实化 io 输出补齐 (2026-09-07, 老倪: "流形是拓扑要有形状" / "流形没有输出, 可视化层要能看到")

## 需求背景
1. 老倪: 接触流形/性能流形 "应该有几何形状, 至少有个曲面" → 3D 视图要能"看到流形"。
2. 老倪: 画布上 🧮 接触流形/🧮 性能流形 节点 "没有输出" → 可视化层节点播放时要吐 out 值。

## 流形的数学→几何落地 (设计自洽, 诚实)
- **接触流形 = 插拔安全通道**: 1D 测地线(通道轴) × 该阶段法向容差(半径) → 管状 2D 曲面嵌入 3D。
  阶段半径用 manifold_layer RISK_TH 真值: 下降/抓取/抬起 = peg 上方垂直粗管 30mm;
  插入 = 孔口悬高(mouth+(0,0,0.02))→孔底 斜细管 6mm; 完成 = 孔轴水平最细管 4mm
  ("越接近成功通道越窄" 是几何教学点)。自由空间(接近/对位/转移)无接触约束 → 不画管。
- **性能流形 = η 代价碗**: η(dy,dz)=exp(−Vp/σ²) 高斯碗, σ=4mm 标定 (PerformanceManifold 同款几何,
  高斯光束近似非实测)。横轴 = 光模块头相对孔底横向错位 ±16mm (mm 显示), 竖轴 η×16 视觉放大。
- 可视化元素: 通道管线框(5 环+3 母线 GLLinePlotItem) + 中心白线(测地线) + 金球(光模块头) +
  状态偏离线(头到轴垂线): 绿=在流形/黄=贴边缘/红=离流形。
  碗窗: 曲面 + 底部参考环 4/8/12/16mm + 当前点落碗 + 最近 120 步横向错位轨迹(底平面)。
- 数据同源: 每帧从 tr 现算 (tr 含 stage/x/peg_head/target; 现场 hole/goal 来自 _meta), 播放/滑条同步。
  3D 侧 import manifold_layer (探测 src/lerobot/manifold, 失败 None 不阻塞), 每帧 ContactManifold.decompose。

## ⚠️ pyqtgraph 第二 GL 上下文 = 全崩 (本会话实锤, 最大坑)
- 症状: 新建第二个 GLViewWidget (性能碗独立窗) 时, 该窗**所有 GL item** 绘制抛
  `OpenGL.error.GLError: GLError(...) at glGetAttribLocation`, 画面全黑/部分画不出。
- 根因: pyqtgraph shader 程序全局缓存只编译一次并绑定**第一个** GL 上下文; 第二窗口 = 新上下文,
  旧句柄失效 → 一切走 shader 的 item (含默认) 全挂。(与 3.3.0 "3D 视图二次打开背景丢" 同族坑,
  那次修法是**只复用不新建**主 3D 窗口; 本次是**真新建第二窗口**, 复用逻辑救不了。)
- 解法: **弃 GL, 改 QPainter 2.5D 正交投影自绘** (性能碗窗):
  - 静态碗网格预渲染到 QPixmap (resize/首帧一次性: quad 按中心深度远→近排序, 半透明青 fill+边线,
    + 底部参考环/十字轴), paintEvent 只 drawPixmap + 每帧投影动态点/轨迹/竖线 (11px/mm 正交)。
  - 零 GL 依赖 → Windows/Linux 都稳, 不踩上下文/shader 全家坑。
- 次要坑: ① GLSurfacePlotItem(shader=None) 本机也崩 glGetAttribLocation → 用 GLMeshItem
  (MeshData vertexes/faces + color + drawEdges=True) 纯色渲染稳; ② QPolygonF 在 **PyQt5.QtGui**
  不在 QtCore (ImportError 实锤); ③ QPainter/QPixmap/QPen 等需模块级 import, 别只在别的类里局部 import。

## sim_real (真实化) io 流形补齐 — "可视化层要有输出"
- 背景: GUI ▶运行默认 = 真实化 RealStateSpaceSim; 引擎快演 StateSpaceSim 每步发布
  🧮 接触流形/性能流形/潜空间 (io_snapshot + tr mani_* 序列), 但 **sim_real io_snapshot 只有 12 个模块
  key, 无任何 🧮 流形 channel** → 画布流形节点播放无 out = 老倪报"没有输出"。
- 修: sim_real 主循环每步 (io_snapshot 调用前) 用真实输入现算:
  `ContactManifold(hole_pos=geom goal, hole_mouth=geom hole).decompose(x, ph(site), target, self.v, stage)`
  + `PerformanceManifold(hole_pos=goal).evaluate(ph, stage)` → self._mani_out → io_snapshot 发布与引擎
  **同构**三 channel: 🧮 接触流形 (进度e∥/法向偏离e⊥/V/状态) · 🧮 性能流形 (δ⊥/插深剩余/Vp/η) ·
  🧮 潜空间 (潜坐标/速度场 prior−x̂ₖ)。
- 现场几何: metaworld 布局漂移 → cm/pm 必须用 geom["goal"/"hole"] (非模块常量 HOLE_POS),
  在 run() 内 lazy 构造 (每次 _reset 后几何刷新)。
- 验证: seed104 R0 343 帧三 channel 全发布; 接触流形状态分布如实
  (自由107/边缘13/在流形127/离流形96 — 离流形多为插入前期对孔偏差, 真实非误报);
  η 峰值 0.77 (完成几何自洽: 插深剩余~4mm → η=exp(−½·0.4·d²/σ²)≈0.77)。
- **铁律: 画布/数据总线/3D 消费的是 io_trace 的 key; 新增运行源 (sim_real vs 引擎) 都要对照 io key
  集跑一遍, 引擎有的 channel sim_real 必须同构补齐, 否则真实化演示"节点没输出"。**

## 视觉验证方法 (无 vision 助手时)
- 引擎轨迹全帧遍历 `_update_frame(i)` 不抛 = 逻辑覆盖 (阶段集含 下降/插入/完成/自由 各分支)。
- 渲染验证: 主 3D `view.grabFramebuffer().save(png)`; 自绘窗 `w.grab().save(png)` → PIL 读图统计
  亮像素/特征色 (如青色碗网格像素 >0) 确认真画了, 别只看"没崩"。
- 注意: 整窗 grab 的亮像素可能来自 label/边框文字 — 统计 canvas 区 (去掉底部 label 行) 才算碗本身。

## 相关文件
- tools/gui/ss_dreamview.py: 图层 "mani" (接触通道曲面, 默认开) + 📉 性能流形曲面按钮 →
  ManifoldBowlWidget/_BowlCanvas (QPainter 2.5D); set_frame/set_trajectory 转发碗窗。
- tools/gui/state_space_sim_real.py: _load_simreal_manifold + run() 每步流形 + io_snapshot 3 channel。
- src/lerobot/manifold/manifold_layer.py: ContactManifold/PerformanceManifold 数据源。
