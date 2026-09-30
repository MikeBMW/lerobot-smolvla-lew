# 状态空间数据总线 + 右键 3D RGB-D 渲染 (v2.5.3, 2026-08-23)

数据总线 = 仿 CANoe Trace 的全接口数据视图 (`model_tree.py` 的 `DataBusTrace` 类, 入口「🔌 数据总线」)。点 ▶ 运行后逐帧看数据在总线上按时间流动。

## 双显示模式 (用户可切换)
- `🔁 时间顺序`: 每帧 append 行、滚动 (默认)
- `📌 固定格式`: 信号行固定、值 + 时间实时刷新

## 接口清单
14 模块 51 接口 (演进: 9模块37 → 补视觉输入38 → 补全感知链51)。

感知链 5 模块 = 📦metaworld数据源 / 🎯YOLO / 📐2D→3D反投影 / 🖐触觉 / 🔍AOI。
权威 obs 定义见 node_logic.py。

## 防假死铁律 (最重要)
点运行后必须 `begin_stream` + `append_snapshot` 逐帧追加, **禁止跑完一次性 refresh 灌几百行**
(真实表格一次灌 629 行 → 主线程 "not responding" 假死)。引擎 `run(io_every=25)` 每 25 步取一次 io 快照
(17 快照 × 51 接口 = 867 行)。

## 传感器融合必须补全输入
`fuse_sensors(rgbd_feats, force_6d, tactile_marker)` 三输入全要, 漏主输入 rgbd_feats(39D) → 数据总线视觉 obs 无来源。
obs = concat([rgbd_feats, tactile_marker]) = 39 + 4 = 43; force 只用于接触检测不进 obs。

## 视觉信号右键渲染 RGB-D (v2.6.0 起 = 真实 metaworld 渲染)
视觉行右键「🎨 渲染 RGB-D 图片 (选相机视角)」→ 子菜单列 7 个相机视角。

**v2.6.0 方案 (最终)**: 装 mujoco 3.3 + metaworld 3.1 到 gui-venv311 (uv 装, 系统无 pip)。
用官方专家策略 `SawyerPegInsertionSideV3Policy` 跑 150 步真实插拔轨迹, 按相机缓存渲染帧。
右键按「插拔进度」(peg→hole 距离归一化) 映射到专家轨迹对应帧显示。

**7 相机视角** (`_MW_CAMERAS`): corner2(模型训练视角, 默认) / gripperPOV(腕部) / behindGripper /
topview / corner / corner3 / corner4。用 `env_cls(render_mode="rgb_array", camera_name=X)` 构造,
`env.render()` 出真图 (var>1000 判定)。

**关键坑**:
- metaworld corner2 渲染方向反 → `np.rot90(frame, k=2)` 180° 修正 (其他视角方向可能不同, 逐个验)
- mujoco 3.x API: `model.site("name").id` 取 id (不是旧 `site_name2id`)
- metaworld 依赖 `packaging` (uv 不会自动带上, 手动装)
- 懒加载 + 按相机独立缓存 `_MW_RENDER_CACHE = {camera_name: {...}}`, 首次 1.5-3.7s, 之后秒开
- EGL 退出时报 `Exception ignored in __del__` 无害 (OpenGL 上下文析构噪音)

**视角同构**: 模型训练数据用 corner2 (128×128), 右键默认也 corner2 (480×480) — 同一视角。

历史三阶段 (用户否了前两版): ①监控俯视图+轨迹线+HUD(像波形) → ②平面RGB+Depth(太假) →
③3D透视投影(立体感) → ④v2.6.0 真实 metaworld 渲染(最终)。
真机 rollout 视频在「🎥 操作视频」节点。坐标=逻辑主线图像=背景, obs 只含坐标+触觉数值不含像素。

## 版本号同步 (5 处, 修正旧"三处"说法)
1. `update_checker.py` `CURRENT_VERSION = "vX.Y.Z"`
2. `docs_sync.py` `"version"` + `"zmax_version"` (2 处)
3. `studio.py` `ver = QLabel("Z-MAX vX.Y.Z")` + `setWindowTitle("XSpace Studio — Z-MAX vX.Y.Z [W-01]")` (2 处)
- `version_sync.py` 是版本信息面板 (读 `_load_version_info`), 不硬编码版本号, 不用改。
- tag 必须新号不能复用。
