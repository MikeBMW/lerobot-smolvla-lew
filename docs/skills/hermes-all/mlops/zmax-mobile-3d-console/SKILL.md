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
- 本机守护用 `urllib GET https://datadrive.world/ss3d_cmd.json` 轮询(比 ssh 快); **上传一律走 HTTP 端点, 不要 scp**
  —— `sshpass scp` 依赖 ssh 认证, 认证一失效就**零报错静默冻结**(实况文件停更很久都看不出), 参见下节 ②。
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

## ⏱️ 手机端"太慢/反馈不及时"的两条根因 (2026-10-01 实测)
症状一句话: **指令有回执、画面/状态不更新** ⇒ 别急着怪网络, 是两个独立环节。
- **① 指令往返慢 = 桥的轮询节奏, 不是执行慢**: `web_agent_bridge.watch()` 里 `time.sleep(interval)` 是往返延迟的**主导项**。
  出厂的 `--interval 5` ⇒ 每次操作**无谓白等 0~5s**(平均 2.5s, 最坏 5s), 与功能本身耗时无关。
  ⇒ 改 `interval` 默认值 **和** systemd 单元 `zmax-web-agent-bridge.service` 的 `ExecStart ... --interval 5`
  (**单元写死, 只改代码默认值不生效**), 然后 `daemon-reload` + `restart`。
  实测口径(工具 `tools/phone_latency_probe.sh`, 走手机同一条路 + 只读指令): 5s ⇒ **端到端 1.43s** ✓。
- **② 实况看不到 = 页面取的是相对地址**: `state-3d.html` 的 `LIVE_URL = "ss3d_live.json"`(相对) ⇒ 只在
  **页面所在主机**可达。页面从局域网 IP(如 `10.163.146.78:8791`)开、手机走移动网络 ⇒ 够不到; 若再依赖
  公网隧道而隧道已挂 ⇒ **画面与状态永远不刷新**, 但命令因为走 ECS 中转(独立通道)仍有回执 ⇒ 极易误判成"网络慢"。
  ⇒ 修法(已落地、可照抄): ① 站点根推送端点(纯 HTTP, 无 SSH): 必须带 **token** + **文件名白名单**
  (只能写实况那两个 json) + 临时文件 `rename()` 原子替换; 越权写白名单外名字回 400、无 token 回 403, **两种拒绝都要实测**。
  ② 本机常驻推送器: 每 ~1s 采集**真机真实状态**(相机各路 fps/帧龄、本地推理 online/device/last_ms/infer_count、
  珞石 TCP 真值)推上去; `run_id` **保持固定不变**(一变页面就去拉那份可能已过期的轨迹)。
  ③ 挂 systemd(`Restart=always` + `enable`), 真逻辑进**仓库**, 别放 `/tmp`(重启就没了 ⇒ 这次实况冻了 24.8 天)。
  ⇒ 顺带绕开"HTTPS 页取 http 流的混合内容红线"(推快照比 MJPEG 更适合弱网)。
- **验收必须是"读消费者那个 URL 两次、看它在动"**(唯一站得住的判据):
  第一次后隔几秒再读一次, 比较**时间戳字段在走**且**业务计数器在变**(如 infer_count 递增)、与本机时钟差 < 1s。
  只读一次 200 或看文件存在**都不能证明活着** —— 冻死的数据照样 200。
- **"慢"与"死"是两种故障, 先定性再动手**: 先看消费者读的那个文件/接口里的**时间戳字段**陈旧多少
  (本机 mtime + 内嵌 beat/ts), 除以 86400 换成天。陈旧 = 推方早就不推了(去查推方进程在哪、怎么上传的),
  而不是带宽/延迟问题。
- 排查顺序(先量再改): 看页面 `setInterval(pollLive, ...)` 打的是**绝对还是相对** URL → 从**手机能到的 IP**
  curl 那个 URL 是否 200 → 再看桥的 interval → 最后才怀疑带宽。

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

## 手机到底能碰哪些服务 (2026-10-01 实测·别再搞错)
- **`127.0.0.1:<port>` 的服务手机一律够不到**(回环)。实测: **8796(SAM3) 只监听 127.0.0.1** ⇒ 手机三个页面里引用 8796 的次数 = **0**;
  `ss -ltn` 里 **8791 是 0.0.0.0**(局域网可达), 8794 也是。
- ⇒ **8796 这类本机服务 = "源头", 手机看的是它推到公网/局域网的镜像**。要手机能拿的东西(状态 JSON、画布 PDF)**必须双发**:
  ① 本机端口给只读路由(本机/局域网用); ② 推 ECS 站点根(纯 HTTP 通道, 实测可用) ⇒ 手机固定用站点根那条 URL
  (如 `https://datadrive.world/canvas_latest.pdf` · `zmax_status.html`)。用户说"推到 8796"时, 别把它当成"手机能直接访问 8796"。
- **手机 APK = WebView 壳, 加载的是远端页面** ⇒ **改网页 = 手机上刷新就生效, 不用重新打包/签名/分发**;
  只有当 HTML 被打进包内 `assets/` 时才必须重打包(拿不准就拆包看 `assets/`)。⇒ 用户问"APP 要不要升级"时,
  先用证据回答(页面能否从站点根 200 取到 + 8796 是否回环), 别默认要先改 APK。
- 想让手机**直连本机**(同一 WiFi)才需要把监听从 `127.0.0.1` 改成 `0.0.0.0` —— 这会**小范围暴露服务**, 属安全红线,
  **不擅自改**, 等用户点头。

## 相关文件(本仓库 tools/gui/)
- `export_ss_traj.py` / `run_ss_once.py [seed]` — 引擎跑仿真 → /tmp/ss_run_out.json
- `state_3d_mobile.html` — 手机页(部署为 datadrive.world/state-3d.html; 同目录 lib/three/)
- `tools/web/ss3d_push.php` — 站点根推送端点(token + 文件名白名单); 部署到站点根后用 `curl` 验拒绝分支
- `tools/ss3d_live_push.py` + `tools/systemd/zmax-ss3d-live-push.service` — 实况推送器与常驻(真逻辑在仓库)
- `tools/phone_latency_probe.sh` — 手机链路端到端往返实测(只读指令, 走同一条路)
- ECS `ss3d_cmd.php`(手机按钮命令口) / `ss3d_push.php`(实况写入)
