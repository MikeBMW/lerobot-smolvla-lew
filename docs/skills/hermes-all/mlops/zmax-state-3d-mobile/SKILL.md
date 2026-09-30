---
name: zmax-state-3d-mobile
description: Use when 仿真3D视图接手机看/控制, Three.js复刻 pyqtgraph 场景或方案A真联动.
---

# Z-MAX 状态空间 3D 手机化 + 方案A 实时联动 (2026-09-06)

把 pyqtgraph 本地 3D 视图（DreamView3D）复刻为手机 Three.js 网页，并接"手机点▶→引擎真跑→轨迹回传"实时联动。

## 架构全景
```
手机 App/网页 (state-3d.html, Three.js r128)
  ├─ 回放模式: fetch ss_traj_full.json (预导出的 330 帧轨迹 JSON)
  └─ 实况模式: 250ms 轮询 ss3d_live.json → run_id 变化 → 自动装载新轨迹 → 逐心跳 goto(i)
       ↑                                   （真实执行链）
  🔄新仿真按钮 → ECS ss3d_cmd.php?cmd=run (PHP8 命令端点, 写 ss3d_cmd.json 带 seed)
       → 本机守护 ss3d_daemon.py 轮询(2s) → sim.run() 真实执行 → 上传 live+traj JSON
```

## 关键文件
- `tools/gui/state_3d_mobile.html` — 手机版 3D 页 (源), 部署 ECS → state-3d.html
- `tools/gui/export_ss_traj.py` / `run_ss_once.py` — 轨迹导出/单次执行器 (sim.run() → 330帧 JSON)
- `tools/gui/ss3d_daemon.py` — 实况守护 (轮询 ECS 命令 → 真跑 → scp 上传)
- `tools/gui/state_space_sim.py` — 引擎 (轨迹含 x/peg/target/分层向量)
- ECS: `/www/wwwroot/datadrive.world/` state-3d.html + ss_traj_full.json + ss3d_live.json + ss3d_cmd.php + lib/three/ (本地化 r128)

## 坐标映射 (关键! 引擎 z-up → Three y-up)
- 引擎 (x, y, z↑) → Three (x, z, y): `P(v) = new THREE.Vector3(v[0], v[2], v[1])`
- 引擎 x 沿水平(光模块长轴/插入轴), z 是高度。所有几何常量从引擎抄 (HOLE_POS/HOLE_MOUTH/PEG/臂长), 不自己编。

## 真实几何来源 (从引擎/3D视图源码抄, 别拍脑袋)
- Sawyer: 底座=世界原点(0,0,0), 肩高 H_BASE=0.317, 上臂=前臂 L=0.42
- IK: 移植 ss_dreamview._ik_sawyer (2连杆余弦定理, 肘向+z上翻) — 网页 ikSawyer()
- 光模块: 0.20×0.03×0.03 沿X, 抓握点 peg 距销头端 0.13 (几何中心=peg-0.03X)
- 带孔盒: 中心(-0.2645,0.4623,0.095) 尺寸 0.19³; 孔口 HOLE_MOUTH(-0.1685,0.4623,0.1309) = 盒+X侧
- 夹爪: _box_mesh(腕+gap*Y, (0.05,0.016,0.05)), gap 0.024~0.048; 视觉修正按老倪审美调比例
- 3D 图层名/颜色: ss_dreamview._layers_def (感知层最前 → S2 → S3)

## Three.js 版本坑
- **three@0.157 已移除 examples/js/OrbitControls.js (404 → JS 报错黑屏)** → 用 **r128** (examples/js 仍在)
- CDN jsdelivr 手机弱网慢 → **three.min.js+OrbitControls.js 下载到 ECS lib/three/ 本地引用**
- playwright 无头验证: `--use-gl=swiftshader --enable-unsafe-swiftshader --ignore-gpu-blocklist`, 否则 NO_WEBGL 黑屏误判
- 手机黑屏排查: ①CDN/资源 404 (chrome console) ②WebGL 未开 (try/catch showErr) ③硬件加速 (APK 侧)

## 方案A 实时联动 (手机触发真实仿真)
1. **ECS 命令端点** ss3d_cmd.php: `?cmd=run` → 写 ss3d_cmd.json {ts,seed}; `?cmd=status` 返回 live+pending
2. **本机守护** ss3d_daemon.py: 轮询 https://datadrive.world/ss3d_cmd.json → ts 变化 → run_ss_once.py seed → 写 /tmp → scp 上传 ss3d_live.json{run_id,playing,i,n,done,dist} + ss_traj_full.json
3. **网页**: `btnRun.onclick` → fetch ss3d_cmd.php?cmd=run → 按钮禁用+setLive("引擎执行中")
   - pollLive 250ms 轮询 ss3d_live.json, `run_id !== liveRunId` → loadTraj + autoJoin 跟随; 结束回退"可回放"
4. 守护跑完 rm ss3d_cmd.json 防重复。仿真 ~5-10s, 端到端 2s 内 run_id 可见。
5. 部署: scp 网页+轨迹+PHP 到 ECS; 守护后台 `python3 ss3d_daemon.py` (重启需手动拉起)

## 验证 (playwright headless)
- 页面无 pageerror; 画布非黑 (读像素); IK 数值断言: len1=len2=0.42, 肩高 0.317
- goto(抓取帧): 腕-peg 3D 距离 ~0.014m (夹持); 销头-孔口距离插入帧趋近
- E2E: POST cmd=run → 轮询 ss3d_live.json 至 run_id 变化 (<60s)
- APK: 手机装后 🔄新仿真 按钮实际触发引擎 (logs 见 daemon)

## Pitfalls
- 夹爪"干涉/穿模" = 爪盒中心错位或爪尺寸方向错: 真实爪盒中心在腕±Y gap, 不是腕下方; 爪沿光模块长轴(X)延伸
- 光模块"太长" = 旧版缩放逻辑把 0.13 拉长: 用真实固定 0.20 本体, 销头在 peg-0.13 (不缩放)
- 轨迹 x 是**腕中心**不是夹爪中心: 夹爪几何相对腕点算
- 引擎 peg_head 键在导出里有, 网页 goto 直接用 peg (销头=peg 局部 -0.13)
- 守护进程含 SSH 密码 → 只存本机/仓库私有, 不入公开文档
- 手机 App 黑屏先查 WebView 版本/硬件加速 (见 android-webview-shell-apk 技能)
