# 状态空间 3D → 手机网页 Three.js 复刻 (2026-09-06)

触发: 老倪要"把状态空间 3D 分层空间接到手机飞书/浏览器远程看+控制"。
路线: 桌面 pyqtgraph 3D 是本地渲染, 手机端用 **轨迹数据 JSON 导出 → Three.js 网页逐帧回放**
(不是推流桌面, 也不是 VNC 整屏 — 用户要的是"那个模型"的 3D 视图)。

## 1. 引擎轨迹 → JSON (tools/gui/export_ss_traj.py 模式)
`StateSpaceSim().run()` 返回 tr, 轨迹键 (state_space_sim.py tr 初始化):
- **位置系**: `x` (末端, 3D) / `peg` (光模块) / `peg_head` / `target` (孔位) / `gripper` /
  `grasped` (bool) / `stage` (阶段名带 "阶段 " 前缀+ "·推进" 后缀, 需清洗取主阶段) / `dist` / `done`
- **分层向量** (3D 视图图层数据源, 每步 3D 向量): `u_ff_vec` (①前馈) / `latent_vec` (②状态估计
  x̂) / `prior_vec` (③先验预测) / `corrected_vec` (④状态校正) / `residual_vec` (残差) /
  `u_fb_vec` (⑤反馈) / `u_fuse_vec` (⑥融合) / `u_limit_vec` (⑦安全限幅) / `u_exec_vec` (⑧执行下发) /
  `z_k_vec` (卡尔曼观测)
- **标量** (别当向量取 [:3]!): `u_ff`/`u_sat` 是**范数 float**; `residual` 标量; `contact_p`
- 导出坑: np.float32/ndarray 要 round(float()) 转纯 Python; 降采样 `step=max(1,n//400)` 控大小
  (330 帧全量 ~203KB 可接受); 帧内嵌 stage 清洗后的主阶段名

## 2. Three.js 手机页 (state_3d_mobile.html → 部署 datadrive.world/state-3d.html)
- **three 版本坑 (黑屏根因)**: `three@0.157` **已删除 examples/js/controls/OrbitControls.js**
  → script 404 → JS 抛错 → **整页黑屏**。必须用 **three@0.128** (examples/js 还在,
  robot2.html 同款) 或改用 examples/jsm + importmap。这是手机黑屏的第一排查点。
- **CDN 本地化**: 手机/飞书内置浏览器访问 jsdelivr 慢或被拦 → 把 three.min.js + OrbitControls.js
  下载到站点同域 `/lib/three/` (nginx 直服务), 页面引相对路径
- **坐标映射 MuJoCo z-up → Three y-up**: 引擎 (x, y, z↑) → Three `(x, z→y 高度, y→z)` 即
  `new THREE.Vector3(v[0], v[2], v[1])` — 引擎 z 是高度 (光模块台面 z≈0.03, 抬升加 z)
- 场景元素: 台面 box (y≈0.01) / 带孔盒 (HOLE_POS 处, 孔口红环 Torus + 半透明 Cylinder) /
  光模块金色 group 跟随 peg / 机械臂末端 = hand group (蓝色圆柱 + 左右夹爪 jawL/jawR,
  grasped 时夹爪收拢 gap 0.003, 未抓 0.010)
- **分层向量箭头**: 每个图层 = ConeGeometry 箭头, 位置 = 末端 + 向量, quaternion.setFromUnitVectors
  (0,1,0 → vec.normalize); 长度 < 阈值隐藏; 右侧图层按钮 toggle visible
- 控制: OrbitControls (单指旋转/双指缩放, touch-action:none) + ▶/⏸ + slider 拖动 +
  顶部 stage 标签变色 (STAGE_COLOR 每阶段一色) + 距孔 dist HUD + 阶段进度条
- r128 API 注意: renderer.shadowMap 可用; 所有 API 用 r128 兼容版 (TorusGeometry/ConeGeometry
  都在); 验证页面所有 script src + fetch 的 JSON 都 200 再交付

## 3. 验证 (无头浏览器不可用时的替代)
本机 snap chromium 沙箱写不了 /tmp、browser-use daemon 起不来 → 用静态检查:
- `curl` 逐个资源 200 (页面/three.min.js/OrbitControls.js/traj JSON)
- 页面内 JS 括号配对计数粗查
- JSON `python3 -c json.load` 可解析 + 首帧键齐全
- 最后请用户手机打开确认 (黑屏先查 three 版本 + CDN 资源)

## 部署 (datadrive.world)
`sshpass scp state_3d_mobile.html root@datadrive.world:/www/wwwroot/datadrive.world/state-3d.html`
+ 同名 JSON。放站点根 (不走 /novnc/ location, 那是 VNC 专用路径)。
