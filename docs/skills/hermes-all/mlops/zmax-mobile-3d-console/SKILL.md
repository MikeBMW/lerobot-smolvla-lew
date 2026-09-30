---
name: zmax-mobile-3d-console
description: Use when 把状态空间3D复刻成手机Three.js页看/控, 或手机触发真引擎的实况联动.
---

# Z-MAX 手机 3D 控制台 (状态空间 3D → datadrive.world 网页/App)

把桌面控制台 pyqtgraph 3D 分层空间(机械臂插光模块仿真)复刻成手机可看的 Three.js 网页 + 实况联动真实引擎。
产物: `https://datadrive.world/state-3d.html` + `ss_traj_full.json`(轨迹) + `ss3d_live.json`(实况) + WebView 壳 APK(见 android-webview-shell-apk)。

## 数据流(方案A 实况联动 — 全程真实执行, 非预录回放)
```
手机点「🔄 新仿真」 → GET ss3d_cmd.php?cmd=run (ECS PHP, 写 ss3d_cmd.json 带 ts+seed)
本机守护进程 (轮询 2s) → 真实执行 run_ss_once.py [seed] → sim.run() 330 步
→ 上传 ss3d_live.json {run_id, i, n, done, dist} + ss_traj_full.json → 删命令标记
网页/App 250ms 轮询 ss3d_live.json → run_id 变化 → 装载新轨迹自动播放
```
- ECS PHP 8.0 在 `/www/server/php/80/bin/php`; BT nginx 直接服务 .php(不用配)。
- PHP 端点写跨域头 `Access-Control-Allow-Origin: *`(OPTIONS 预检 204)。
- 守护用 `urllib GET https://datadrive.world/ss3d_cmd.json` 轮询(比 ssh 快), 上传用 sshpass scp。
- 网页已有 live UI 骨架(liveChip/liveTxt/errBox/resultChip + pollLive 250ms + 心跳 4s 中断判定), 加按钮只需 fetch 命令端点。

## 引擎轨迹导出 (export_ss_traj.py / run_ss_once.py)
- 数据键: `x`(3D末端=腕) `peg`(光模块抓握点) `peg_head`(销头) `target` `grasped` `stage`
  分层向量(每步): u_ff_vec/latent_vec/prior_vec/corrected_vec/u_fb_vec/u_fuse_vec/u_limit_vec/u_exec_vec。
- ⚠️ `tr["u_ff"]` 是**标量模长**, 3D 箭头要用 `u_ff_vec` 等向量键!
- `x` 前3维即末端位置(3D), 不是 39D obs。降采样 330→≤400 帧手机流畅。

## ⚠️ Three.js 手机页硬坑 (2026-09-06 黑屏排查)
- **three@0.157 已删 `examples/js/controls/OrbitControls.js`(404)** → 整个页面 JS 崩 → 黑屏。
  用 `three@0.128.0`(examples/js 路径还在) 或 importmap+jsm。验证: curl CDN 该路径 200。
- **手机弱网/飞书内置浏览器拦 jsdelivr** → three.min.js + OrbitControls 下载到同域 `/lib/three/`, 页面同域引用。
- 同页 live 轮询会请求 `ss3d_live.json`(无服务时 404) → 设计成 catch 后回放本地轨迹, 404 无害不算错。
- headless 验证: `playwright chromium --use-gl=swiftshader --enable-unsafe-swiftshader --ignore-gpu-blocklist`
  (无这些 flag → NO_WEBGL 黑屏, 无法验证渲染); 截图后 PIL 算饱和像素占比确认画面非黑。
- 页面 JS 改完自检: 括号配对 + 旧变量残留 grep(如删了 armTip 还有引用)。

## 🎯 几何必须按引擎真实常量 (老倪铁律: 对照 metaworld 视频比例, 不拍脑袋)
用户会逐帧比对 metaworld 视频和真机构造, 发现比例/干涉立刻指出。所有尺寸/位置从引擎源码常量抄:
- 光模块 `_PEG_SIZE=(0.20,0.03,0.03)` 沿引擎X长条, 抓握点 peg 距销头端 0.13(`PEG_HEAD_OFF=[-0.13,0,-0.01]`),
  本体范围 peg-0.13~peg+0.07, 几何中心 = peg-0.03。
- 带孔盒 `_BOX_CENTER=(-0.2645,0.4623,0.095)` `_BOX_SIZE=(0.19,0.20,0.19)`; 孔口 `HOLE_MOUTH=(-0.1685,0.4623,0.1309)`
  在盒 +x 侧面; 插入终点 `HOLE_POS=(-0.2345,0.4623,0.1309)`。画: 盒+深色插槽凹口+红圈孔口+插入箭头。
- Sawyer 臂(ss_dreamview): **底座=世界原点(0,0,0), 肩高 `_ARM_H_BASE=0.317`, 上臂=前臂=`_ARM_L1=_ARM_L2=0.42`**,
  肘由 `_ik_sawyer` 2连杆余弦定理逆解(肘上翻朝+z)。**不要用"肩-腕中点抬高"伪臂** — 比例一眼假。
- 夹爪 `_box_mesh(腕+gap*Y, (0.05,0.016,0.05))` = 沿光模块轴向X长0.05, Y厚0.016, Z高0.05, 分列 peg 两侧 gap 0.024~0.048。
- 3D 视图里画网格也是这个思路: 每帧 setMeshData 用引擎关节/物体位置, 不用简化形状。
- 用户视觉修正史: 夹爪要"垂直长如手指"(y 0.085 > x 0.055), 光模块不能缩放变形(固定 0.2 整长),
  "最后一个轴穿过了光模块" = 简化臂假几何导致。改完必用 playwright 截抓取/插入帧, 量腕-peg 距离应 ≈0(夹持)。

## 坐标映射
- 引擎 MuJoCo **z-up**(x,y,z↑) → Three **y-up**: `P(v) => new THREE.Vector3(v[0], v[2], v[1])` (引擎x→Three.x, 引擎z高→Three.y, 引擎y→Three.z)。
- 引擎几何常量可直接 P() 转 Three; IK 输入要**反映射**回引擎(w.x, w.z, w.y)再算, 输出再映射。

## 相机/镜头
- 初始对准作业区(盒/孔/光模块三角区), controls.target 设场景中部; 手机触屏 OrbitControls 自动支持单指旋转/双指缩放。
- 老倪会要"镜头跟随末端"→ btnFollow + 心跳同步 goto(lv.i) 与画布同帧。

## 手机现场页: 相机会议 + HIL 人机在环 + 远程操作 (与画布共用同一个大脑)
老倪口径: 「通过 APP 跟状态空间交互, 人机在环; 把工位总揽所有相机推流到 APP, 像开视频会议一样选视角/全看/远程操作」。
- **页面由相机那台工位机用 http 提供**(如 `http://<工位机>:8791/room`), 不要挂在 https 站点上:
  相机流是 http MJPEG, https 页里嵌会被混合内容拦死(页面能开、画面永远黑) ⇒ 页面与数据必须同源。
  页面本体放 `tools/web/*.html` 由推流服务读文件服务, 比塞进 py 字符串好维护。
- **HIL 部分绝不另起一套逻辑**: 现场页只连本机**本地 HIL API**(`tools/hil_local_api.py`, 0.0.0.0:8795),
  它按**文件路径**加载 `src/lerobot/policies/left_right/state_space/hil_bridge.py` 的
  `build_snapshot()` / `handle_instruction()` ⇒ 手机、画布 n_hil 节点、公网 hil.html **同一份状态、同一套指示处理**。
  ⚠️ 别直接 `import hil_bridge`: `tools/hil_bridge.py` 只是个**同名 CLI 壳**, 会先命中它 ⇒ 运行时 `AttributeError`;
  用 `importlib.util.spec_from_file_location` 按路径加载(核心模块纯 stdlib, 不必拉起 torch/lerobot 整条 import 链)。
- 现场设备在局域网时**不要绕公网 relay**: 本地 API 直连, 又快又不依赖外网; 公网那条保留给远程访问。
- **红线随入口走**: 涉及真机动作的指示由 `handle_instruction` 在**服务端**拒答(只记为待授权),
  换手机入口也绕不过去; 手机页的远程操作另走 `/ctl/*` 两步授权(无授权服务端 403)。
- 页面要写死的现场纪律: **本页没有软急停**(急停用示教器/现场按钮), 默认未授权并显示剩余授权秒数。
- **路由必须回读核对, 别只看“页面能开”**: 8791 上 `/app` 曾被 room.html 那条 `elif` **抢先命中**(后面那条
  `p in ("/app",...)` 成了死代码), 而 `/overlay` 发的是 `cam_live_stream.py` 里 **py 内嵌的旧副本** ⇒
  改 `tools/web/<页>.html` 完全不生效(改完 curl /overlay 仍是旧内容)。判据: `curl -s 页面 | sha256sum`
  与 `sha256sum tools/web/<页>.html` 必须相等; 要新增/改路由必须**重启**服务(它是手工起的进程, 无 systemd,
  杀掉按 **PID**, 别 `pkill -f cam_live_stream.py` —— 会连自己那条同名命令行一起杀), 重启后用同一条
  `--port 8791 ...` 原命令行拉起并核对 `/stats` 各路 fps 回来了。
- **在线判据用 `/stats` 的 `fps>0.1`, 不写死**: arm/depth 会长时间掉线(Orin `/frame.jpg` 返 503/拒连),
  页面要么运行时探测、要么如实标“未上线不上屏”; “未上线”提示要**每轮都重绘**(只在重建瓦片时写会被下一轮
  清空擦掉)。每格标 **帧龄 + 拍照时间(=本机时钟−帧龄)**, 导出 CSV/JSON 也带这两列 ⇒ 实时数据可取证。
- **叠加框要先看真源脸色**: sim/scene 只对**臂上相机**成立(要手眼), vlm/det 是三路都能跑的纯 2D;
  `sim` 会**重建整份** overlay_spec(把其它来源的框冲掉), `vlm`/`det` 只替换各自那一类 —— 跑之前想清楚
  会不会把别人正在看的框弄没。
- 多路相机的连接预算见 android-webview-shell-apk / sim-real-scene-overlay:
  全看=1 条串行轮询快照, 单看=1 条 MJPEG, **永不同时开 N 路 MJPEG**(手机只有 6 条 HTTP 连接)。
- 验收: 从**手机能到的那台 IP**(不是 127.0.0.1)逐个 curl 页面/接口 → 200; 再开页面看每格都有真画面、帧龄在动。

## 相关文件(本仓库 tools/gui/)
- `export_ss_traj.py` / `run_ss_once.py [seed]` — 引擎跑仿真 → /tmp/ss_run_out.json
- `state_3d_mobile.html` — 手机页(部署为 datadrive.world/state-3d.html; 同目录 lib/three/)
- `/tmp/ss3d_daemon.py` 守护 + ECS `ss3d_cmd.php`
