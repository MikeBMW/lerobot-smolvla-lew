# 流形曲面可视化 (2026-09-07 v5.0.1, 老倪: "流形是拓扑的一种, 应该有形状, 至少应该有个曲面代表")

需求: 流形导航层 (接触流形/性能流形, src/lerobot/manifold/manifold_layer.py) 之前只有
Scope 波形/数值, 老倪要看到"流形的几何形状"。数据现状: manifold 只在引擎快演算, sim_real
(真实化) 没接, 3D/Scope 无流形几何。

## 设计 (数学自洽, 不是画饼)

**接触流形 = 插拔安全通道管** (管状 2D 曲面嵌入 3D):
- 数学: 插拔路径 = 1D 测地线 (通道轴), × 该阶段法向容差 (radius) → 管面
- 3D 视图 (ss_dreamview) 新图层「🧮 流形导航层 · 接触通道曲面」: 青色线框管 (5 环 + 3 母线,
  多 GLLinePlotItem), 半径 = RISK_TH 阶段容差 → **越接近成功通道越窄** (下降族 30mm 粗管 →
  插入 6mm 斜细管 → 完成 4mm 孔轴管), 教学感强
- 中心白线 = 通道轴 (测地线); 金色小球 = 光模块头; 状态偏离线 (头→管轴垂线 e_perp):
  绿 = 在流形 (<0.5×容差) / 黄 = 贴边缘 / 红 = 离流形
- 阶段驱动通道几何 (世界系锚点):
  - 下降/抓取/抬起: peg 上方竖直管 (peg_xy, z 从 peg_z+0.050 → peg_z+0.002), R=0.030
  - 插入: 孔口悬高 (mouth+(0,0,0.02)) → 孔底 hole 斜管, R=0.006
  - 完成: mouth → hole 水平孔轴, R=0.004
  - 接近/对位/转移 (自由空间, channel_axis=None): 不画管, 灰线 = 手→target 进度 (e)
- 数据同源: 每帧现算 `ContactManifold(hole_pos=现场, hole_mouth=现场).decompose(hand=x,
  peg_head, target, v, stage)` — 3D 侧探测 import manifold_layer (见 SKILL.md 探测法), 不塞 sim_real

**性能流形 = 光耦合代价碗** (2D 曲面嵌入 3D):
- η(dy,dz) = exp(−Vp/σ²), σ=4mm (PerformanceManifold 同款几何, 高斯光束近似非实测)
- 独立曲面窗「📉 性能流形曲面」: 横 = 光模块头相对孔底横向错位 ±16mm, 竖 = η×16mm 视觉放大;
  金点 = 当前位置落碗, 底部橙线 = 最近 120 步错位历史 (z=0 平面), 参考环 4/8/12/16mm
- 播放/滑条同步: 主 3D set_frame/set_trajectory 转发到碗窗 (sip.isdeleted 判活)

## ⚠️ 坑 (全实测)

1. **pyqtgraph 第二个 GLViewWidget 窗口 = 新 GL 上下文, 全部 GL item 绘制崩** (GLError
   glGetAttribLocation / "Error while drawing item"): shader 全局缓存绑**第一个**上下文。
   3.3.0 记录的是"二次打开背景丢"(复用同一窗口可解); **新开第二窗口无解** → 弃 GL,
   碗窗改 **QPainter 2.5D 正交投影自绘**: 静态碗网格 (21×21=400 quad, 按中心深度远→近排序,
   半透明青 fill + 边线) 预渲染 QPixmap (resize 重画), 每帧只投影动态点/轨迹/竖线 (fixed
   camera: az 24°/el 30°/dist 75mm, s=11 px/mm, 正交无透视, depth 仅用于排序)。零 GL 依赖最稳。
2. **GLSurfacePlotItem 本机崩**: shader=None + colors → GLMeshItem.paint glGetAttribLocation
   GLError。改用 GLMeshItem (MeshData vertexes/faces + color 单色 + shader=None + drawEdges,
   edgeColor) — 与主 3D 已验证路径一致。
3. **QPolygonF 在 PyQt5.QtGui 不在 QtCore** (ImportError 实锤); QPointF 在 QtCore。
4. 新 GL 内容区像素验证别用 whole-widget grab: 底部 QLabel 白字/边框贡献亮像素会误判
   "画出来了"; 要按控件区域切分或按色系 (青网格) 统计。

## 图层机制复用要点 (ss_dreamview)

- 图层注册: `_layers_def` 加 (key, 名, 默认开, tooltip); 名称对齐画布节点 (🧮 接触流形)。
- GL items: `_gl_items[key] = [item...]` list (list 内自动受 _apply_layer_visibility 控);
  专用索引另存 self._mani_ix = {tube/ax/ball/line} 便于 _update_frame 每帧 setData。
- 每帧绘制挂 `_update_frame` 头部 try/except (绘制崩不拖垮播放); _MANI 探测失败直接 return
  (打包缺 manifold_layer 时图层空转不崩)。
- 验证: 引擎 369 步全帧遍历无错 + 帧像素统计 (3D 亮 65k / 碗窗 canvas 亮 21.6k + 青 1.9k px)。
