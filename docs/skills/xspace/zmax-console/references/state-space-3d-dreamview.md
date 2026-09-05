# 状态空间 3D 视图 (ss_dreamview.py, v3.0.0)

> ⚠️ **v3.0.0 起数据源变了**: 3D 视图优先读「与操作视频同源」的 metaworld episode trace
> (`reports/ss_episode_latest.npz`), 相机用 corner2 真实外参精确对齐 (三轴角差 0.00°)。
> 完整设计/实测数字/坑 → **references/state-space-video-same-source.md** (必读)。
> 本文件下面的 numpy 引擎版参数 (elev88/az270 正俯视等) 仅为退回模式的历史记录。

2026-08-25 新增, Apollo Dreamview 风格 OpenGL 3D 分层视图。

## 文件 + 入口
- 文件: `tools/gui/ss_dreamview.py` (577 行), 依赖 pyqtgraph (已装进 gui-venv311, 阿里云镜像装的)
- 入口: simulink_module 工具栏「🧭 3D 视图」按钮 (btn_ss_3d) + 状态空间仿真跑完自动打开 (open_ss_3d, 在 _ss_finish 里)
- 复用窗口: open_ss_3d 检查 `_ss_3d_windows` 里 isVisible 的窗口, raise 而非重复开

## 数据源: tr 每步处理层向量
state_space_sim.py 的 run() 每步落盘 (原本只有 io_trace 抽样):
```
tr["u_ff_vec"] / u_fb_vec / u_fuse_vec / u_limit_vec / u_exec_vec
tr["latent_vec"] / corrected_vec / residual_vec / z_k_vec / v_vec
```
3D 视图读这些 key 渲染各层。加新处理层要同步改 state_space_sim.py 的 tr 初始化 dict + 记录段 + ss_dreamview 的图层。

## 图层 (左侧 QCheckBox 面板)
scene(含机械臂联动)/yolo/traj/uff/ufb/ufuse/ulimit/latent/contact
- 机械臂 arm 随 scene 层开关联动 (_apply_layer_visibility 特判 key=="scene")

## 视角 (与操作视频一致, 2026-08-26 修正)
- 俯视 `setCameraPosition(pos=QVector3D(0.11,-0.02,0), distance=0.50, elevation=88, azimuth=270)`
- **azimuth 必须=270 (不是 180)**: pyqtgraph 相机 viewMatrix 是 `rotate(elevation-90,X轴)*rotate(azimuth+90,-Z轴)` 后乘, azimuth=270 才使世界+X→屏幕右/+Y→屏幕上 (与操作视频一致)
- azimuth=180 会让世界+X→屏幕上/+Y→屏幕左 (与操作视频差 90°, 视觉上"视角反了")
- center 必须对准场景(0.11,-0.02) 不能默认(0,0,0), 否则场景偏出屏幕一侧
- distance=0.50: 孔位落在屏幕右侧~73% (操作视频里孔位 73.7%), 机械臂底座(y=-0.2)仍在视野下方可见
- 操作视频 gen_state_space_video.py 是 X 向右/Y 向上的 2D 俯视图 (非等比, X 拉伸 ~1.34 倍); 3D 是等比透视, 朝向对齐但比例无法完全一致
- 验证: QMatrix4x4 手算 viewMatrix 投影 +X/+Y 方向 (省得跑 GUI); 或 grabFramebuffer 截图数孔位红色像素 bbox 中心

## Sawyer 机械臂 (2 连杆 IK)
- `_ik_sawyer(target, base, L1=0.16, L2=0.15)`: 底座在 (0.12,-0.20,0), 肩高 0.09, 肘朝 +z 弯曲
- 几何: `_cylinder_mesh(p1,p2,radius)` 两点间圆柱 (Rodrigues 旋转), `_sphere_mesh(center,radius)` 球
- 夹爪: 两瓣 box 沿 **x** 开合 (夹 peg 长边 0.07), gap = 0.045+(1-gripper)*0.025 (闭合贴 peg 边缘 / 张开远离), 瓣尺寸 0.020×0.075×0.05, 纯色青色 shader=None, 浮起 z+0.015
- 光模块 peg: 金色 box (0.07,0.05,0.05) 随末端

## 坑
1. **光模块/插座俯视遮挡**: 插座 box 高度曾 0.06 盖住光模块(z=0.048) → 插座压矮到 z<0.03, 光模块露在插座上方
2. **方向反**: azimuth=0/180 都反 (0→孔位在屏幕左, 180→孔位在屏幕上), 正确值 azimuth=270 (使 +X→右/+Y→上)
3. **peg 重复渲染**: peg_dyn(scatter) 和 arm[peg](mesh) 曾同时渲染同一物体 → 只保留 arm 里的 mesh
4. **GLViewWidget 循环重建崩溃**: 测试时 for 循环里反复 new DreamView3D 会 GL 上下文冲突, 一个进程只建一次
5. **grabFramebuffer 验证**: 用 `w.view.grabFramebuffer().save()` 拿截图, 别用 xwd(无转换工具)
6. **被操作视频窗口遮挡**: 操作视频窗口 (MLPRolloutDialog/InferenceVideoDialog) 经 `_show_nonmodal` 打开时强制置顶 (WindowStaysOnTopHint), 而 DreamView3D 若不置顶会被永久盖住 → `__init__` 加 `setWindowFlag(Qt.WindowStaysOnTopHint, True)` + `open_ss_3d` show 后 `raise_()/activateWindow()` (2026-08-25 老倪)
7. **夹爪抓取动作俯视看不见** (2026-08-26 老倪): 原夹爪沿 y 开合 + 瓣太小(0.012×0.014) + 灰蓝与关节混淆 + shaded 光照压暗 → 俯视完全看不出"抓取"。改法: 沿 x 方向(peg 长边)夹持, 瓣 0.020×0.075, gap=0.045+(1-g)*0.025, shader=None 纯色青色(0.20,0.85,0.90), 瓣浮起 z+0.015 不被机械臂/peg 遮挡。验证: 直接读 `GLMeshItem.opts['meshdata'].vertexes()` 算夹爪开口(张开~0.140m vs 闭合~0.094m), 别用截图颜色(有光照+遮挡干扰)

## 验证
- 渲染验证: 截图数像素颜色 (金色光模块 r>200&g140-230&b<90, 红插座 r>200&g30-90&b<70, 橙机械臂 r>120&g40-130&b<80)
- IK 验证: 肩→肘=0.16, 肘→腕=0.15 恒等, 腕==末端位置
