# 状态空间 3D → 手机网页回放 (2026-09-06, 老倪: 把 3D 分层空间接到手机飞书远程控制)

触发: 老倪要在手机/飞书看控制台状态空间 3D 分层空间并远程控制。桌面 Qt 窗口在
Mutter 下 X 层不 map (见 gnome-x11-qt-iconic-minimize) → **不走截图/推流, 走数据级
网页复刻**: 引擎轨迹导出 JSON → Three.js 手机页逐帧播放。手机流畅、可旋转缩放、
图层开关即数据开关。这也是未来"手机触发仿真→轨迹回传"联动的基础。

## 1. 轨迹导出 (tools/gui/export_ss_traj.py, gui-venv311 跑)
`StateSpaceSim().run()` 返回 tr (330 步 done=True)。tr 键超丰富, 网页 3D 分层空间
用这些 (全 3D 向量, 已降采样 ≤400 帧):
- `x` = 末端 3D 位置 (3 维, 不是 39D!); `peg`=光模块; `peg_head`; `target`=孔位
- `gripper`/`grasped`/`stage`/`dist`/`contact_p`
- **分层向量** (每层一条, 对应 3D 视图图层): `u_ff_vec` ①前馈加速器 · `latent_vec`
  ②状态估计 x̂ · `prior_vec` ③先验预测 · `corrected_vec` ④状态校正 ·
  `u_fb_vec` ⑤反馈 · `u_fuse_vec` ⑥融合 · `u_limit_vec` ⑦安全限幅 · `u_exec_vec` ⑧执行
- ⚠️ 标量键 `u_ff`/`u_sat` 是模长 (float), 向量键才带 `_vec` 后缀 — 别混。
- JSON: `{n, step_skip, done, dist_final, stages, frames:[{x,peg,target,stage,dist,
  u_ff,latent,prior,corrected,residual,u_fb,u_fuse,u_limit,u_exec,z_k,gripper,grasped}]}`
  (~200KB/330帧)。上传 ECS 站点根 `/www/wwwroot/datadrive.world/ss_traj_full.json`。

## 2. 坐标映射铁律 (引擎 MuJoCo z-up → Three.js y-up)
引擎坐标 (x, y, z↑高度): 台面 z≈0.03 (光模块 peg z=0.03), 末端 x0=[0.0046,0.6014,0.1951],
孔 HOLE_POS=[-0.2345,0.4623,0.1309]。Three.js 场景搭建:
```js
function P(v){ return new THREE.Vector3(v[0], v[2], v[1]); }  // tx=x, ty=z(高度), tz=y
```
台面/孔盒/光模块/末端的 y 全用引擎 z。**直接拿引擎 y 当 Three z, 引擎 z 当 Three y**。
孔 = 红 Torus + 半透明 Cylinder 标记; 光模块独立 group 每帧 set position (抓取后与末端
同移动由轨迹 peg 序列天然体现); 夹爪开合由 grasped 切换 jaw gap。

## 3. 图层开关 = 箭头可见性 (不是重建)
每层一个 Cone (箭头从末端画到 末端+向量), `cone.visible = layerBtn[key].checked`。
向量极短 (u_ff ~0.35m/s 满格) 需放大? 网页版按 3D 视图惯例把箭头画到 末端+vec,
len<0.0008 隐藏 (噪声)。右侧竖排按钮带色点, 图层顺序照状态空间链路。

## 4. 播放控制 (手机触屏)
- `OrbitControls` 天然支持单指旋转/双指缩放 (`canvas` 加 `touch-action:none`)
- slider + play/pause (setInterval 60ms/帧) + HUD 阶段标签 (按 STAGES 色表变色)
- 进度条拖动 → setPlaying(false)+goto(idx)
- 轨迹线 = 全部帧 x 连成的 THREE.Line (预建 BufferGeometry)

## 5. 部署/验证
`scp state_3d_mobile.html → /www/wwwroot/datadrive.world/state-3d.html` +
`ss_traj_full.json` 同目录 → 手机浏览器 https://datadrive.world/state-3d.html。
静态资源 CDN (three@0.157.0 three.min.js + OrbitControls.js) 直连可用。
自检: `curl` 两文件 200 + JSON `python3 -c json.load` 可解析。

## 6. (规划中) 真机联动
手机点▶ → 控制台触发 `StateSpaceSim().run()` → 新轨迹 JSON 写站点 → 网页 reload —
靠 ECS 中转/WS 推送, 复用 datadrive.world 通道。坐标系/JSON schema 与回放版一致,
联动版只换数据源。
