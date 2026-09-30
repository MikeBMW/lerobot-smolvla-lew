---
name: zmax-live-video-stream
description: Use when 要看/录真机双相机实时流或压缩提实时性.
version: 1.0.0
author: hermes-agent
license: proprietary
metadata:
  hermes:
    tags: [camera, streaming, mjpeg, ros2, real-machine, zmax]
    related_skills: [real-arm-motion-control, camera-frame-forensics, orin-lan-direct-access]
---

## ⚠️ 相机设备号**按卡名+能力**解析, 绝不写死 /dev/videoN (2026-09-28 现场事故)

重启后 `video*` 编号会变, 同一台机器的笔记本相机有**两路**: MJPG 彩色 (video0) 与
**GREY(IR) 那一路 (video2)** —— IR 无照明时整幅近黑(实测 mean=6.0/median=0/96% 像素<20),
画面“有帧但全黑”, 端口/帧率/落盘全都正常, 只有像素质心不对。
排查一段一行的判据: `v4l2-ctl -d /dev/videoN --list-formats-ext` → 只有 `GREY` = IR 路, `MJPG` = 彩色。

后果(踩过): 把它当“笔记本相机(全局视角)”喂给 VL 安全闸 ⇒ 快层判『遮挡/糊化』⇒ **所有运动类原子技能被拒发**;
老倪看到的却是“技能又不好使了”, 与相机看似无关。

口径: 一律 `python3 tools/cam_dev_resolve.py` 解析(LOCAL=MJPG 彩色 / LOCAL2=MAXHUB),
`tools/boot_restore.sh local` 已接线; 手起流时也只允许用它的输出。

## 🌈 深度格(及任何"容器里生产、宿主读文件"的路)冻结 —— 看着像"没反映", 其实是生产者死了

8791 的深度格**不直连相机**: 真源是**容器 `ss-remote-tap` 内常驻的 `tools/ros_depth_stream.py`** 落的
`~/zmax_ss_remote/zmax_scene/depth_raw.npy`(宿主只读它)。重启/容器重建后没人拉它,
宿主就一直读旧图 —— 2026-09-28 实测冻结 **26.6h**(`age_s=95802 · frames_served=1 · dead=true`),
而且这份旧深度会被**拼进慢层判据画面**, 一直在给"画面异常/时间戳不同步"扣分 → 抬高拒发率。

- 判据: ①源文件 `mtime` 是否与同目录其它产物同时冻结 ②`sudo docker exec ss-remote-tap bash -lc
  "ps -eo cmd | grep -c '[r]os_depth_stream.py'"` 是否 ≥1; `/stats.depth` 看 `frames_served` 是否递增。
- 修法(官方用法, 分离运行): `sudo docker exec -d ss-remote-tap bash -lc 'source /opt/ros/humble/setup.bash &&
  export ROS_DOMAIN_ID=0 && python3 /repo/tools/ros_depth_stream.py --hz 5 >> /tmp/depth_stream.log 2>&1'`;
  修后实测: 源文件 0.1s 刷新 · `age_s` 0.3~1.4s · `stalled/dead=false` · 41~44KB/帧 · 重彩图 mean=121.3/非零 94.3%。
- 别再忘: `tools/cam_stream_guard.py` 已有**判据 D**(容器进程不在 或 源文件龄>20s ⇒ 自动拉起, 正常静默),
  `tools/boot_restore.sh` 开机补拉 + check ②b 体检。判据新增/改动后记得跑一次**故障复现**(杀进程→守护拉起→恢复静默)。

## 📡 面板要看“现场摄像头”时, 别接远端 ECS 快照 (2026-09-28 老倪: 「也不是现场摄像头」)

`硬件工具箱 · 摄像头实时画面` 原来只认 ① `https://datadrive.world/api/snapshot/latest`(Orin 侧 ECS 快照,
它**一直是 200**) ② Docker tap 落的 `cam_rs.png/cam_local.png` ⇒ 看着“已连接且在动”, 但**不是本机直连的现场相机**。

现口径: 现场画面 = **8791 的 `/snapshot/<name>.jpg`** (arm/local/local2/depth); 取帧共用口 `tools/cam_live_src.py`,
**帧龄取 `/stats` 里该路相机的 `age_s`**(相机自己的出帧时刻), **不许拿 0 或 HTTP 往返耗时冒充**;
负龄/取不到如实写「帧龄 —」。下拉已加三路现场实时流。

**但「自动」默认必须是【手臂相机】(arm / 随臂 D405 / Orin 硬连接), 不是本机那两个 USB 摄像头。**
2026-09-28 先改成"现场实时流·顶视 MAXHUB 优先", 老倪立刻回:「怎么变成笔记本USB连接MAXHUB的电视机摄像头了? 要手臂相机的」
—— 他的「硬件工具箱」默认就看臂上相机; 笔记本/MAXHUB 电视这两路只能进下拉作备选。
口径: `_CAM_LIVE_DEFAULT = "arm"`; 自动链路 arm → local2 → local → 远端快照 → 落盘文件。

# Z-MAX 真机双相机 · 压缩实时流 + 运动摄录取证

## 触发
老倪说"把实时视频流发过来" / "移动机械臂的时候拍摄视频" / 画面卡顿要提实时性；
或要判定机械臂到底走了什么形状（用视频而不是只看 TCP 数值）。

## 现场架构（2026-09-26 实测）
| 路 | 源 | 特性 |
|---|---|---|
| 🦾 手臂(Orin) | `/realsense/color/image_raw` | **只有原始话题，无 `/compressed`**；相机**自身仅 1.92 Hz**（0.52s/帧 · 0.92MB/帧 bgr8 · ~1.77MB/s 上行） |
| 💻 笔记本 | `/dev/video0`（本机驱动） | 640x480，可 15~30fps，帧龄可到 0.03s |

⚠️ **带宽不是瓶颈**（1.77MB/s 仅占千兆链路 1.4%）；**延迟瓶颈 = 相机 1.92Hz + tap 的 1Hz 解码节流**。
压缩对"显示/推送"有意义（手机/WiFi 省 93%）；对 Orin→4060 链路无意义 —— 要压必须在 **Orin 侧**，
而那是产线在役配置（改它等于动在役感知链，**须老倪点头**）。相机帧率是硬上限，代码再快也提不上去。

## 三条通道（按需要选）
1. **慢（现成）**：读 `ss_remote_tap.py` 落的 `~/zmax_ss_remote/cam_rs.png` —— 只有 **~0.5fps**
   （该 tap 是 `raw=True` 订阅 + **1Hz 解码**，源码注释原话「raw 订阅, 1Hz 解码」省 CPU）。
2. **快（推荐）**：容器内跑 `tools/ros_arm_tap_raw.py` 按相机原生帧率订阅 → **原子写**（tmp+rename）
   `/dev/shm/zmax_arm.raw` + `.meta` → 本机 `tools/cam_live_stream.py --arm-raw` 用 cv2 压 JPEG。
   实测 **帧龄 1.80s → 0.26s（6.9x）· 0.50fps → 1.86fps（3.7x）**。
   ```bash
   sudo docker run -d --name zmax-arm-raw --restart unless-stopped --network host \
     -e ROS_DOMAIN_ID=0 -v /dev/shm:/dev/shm -v /home/ubuntu/zmax_rel/tools:/repo:ro \
     ros:humble-ros-base bash -lc 'source /opt/ros/*/setup.bash; exec python3 /repo/ros_arm_tap_raw.py'
   ```
   ⚠️ **rclpy 订阅不能带 `raw=True`** —— 回调拿到的是 CDR 字节，没有 `.encoding/.height`
   （实测崩在 `'bytes' object has no attribute 'encoding'`）。要像素就别用 raw 订阅。
   ⚠️ 容器里**没有 cv2**（只有 numpy）→ 容器只搬字节，编码放本机（本机 `gui-venv311` 有 cv2 5.0）。
3. **推送**：`tools/cam_live_stream.py --port 8791 --quality 70 --fps 20 --arm-raw --local-dev 0`
   → `/`（两路看板，自动 0.7s 刷新 stats + 动作条）· `/arm.mjpg` · `/local.mjpg` ·
     `/snapshot/arm.jpg`（给飞书/取证）· `/stats`（fps · 每帧KB · 压缩比 · 帧龄）·
     `/motion`（当前动作，直读 `~/zmax_data/l2_daemon.log` **尾部 64KB** → 方向/Δ/pos/下发于 N 秒前）
   对外：`http://10.163.146.78:8791/`（WiFi）· `http://192.168.23.50:8791/`（产线口）

   ⚠️ 读 L2 日志**只 seek 到末尾 64KB** 再 `splitlines()` —— 全读会在日志长起来后卡住 HTTP 线程。
   动作条与相机用**同一系统时钟**渲染（日志里的 `[HH:MM:SS]` 转 epoch 与 `time.time()` 相减）→
   这是老倪要的"动作与视频实时同步"的实现口径，**不是事后拼接**。刷新 0.7s；动作 <20s 内亮绿灯。

## ⚠️ 手臂相机 1.83Hz：**不是设备上限** —— 已修到 16.6fps
老倪两次说"卡顿/不实时"后做过完整证伪（方法见 skill `low-latency-camera-streaming` 的
`references/frame-rate-ceiling-diagnosis.md`）。
🔴 **本节早期结论"就是设备上限、代码/链路无解"已被推翻，不要照抄去给用户下结论**：
重启节点实测 1.860 → 1.875Hz，连 `color_fps=30 + depth_fps=30 + publish_rate=30` 三重覆盖都毫无变化。
真正的两层根因与修法见下面「✅ 已经修好的那两层」。逐条证伪的过程证据仍然有效，继续保留在下：

- 节点：`install/camera/lib/camera/realsense_source`（PID 随 `ros2 launch launch/start.launch.py` 起）
  → 真实实现是 **编译好的 Cython `.so`**（`camera/realsense/realsense_node.cpython-310-aarch64-linux-gnu.so`），**无源码可读**。
- 启动参数文件 `/tmp/launch_params_*` 里 `color_fps:15 / depth_fps:15 / publish_rate:5.0 / frame_timeout_ms:5000`。
- **运行时 `ros2 param set` 全无效**（`publish_rate 5→15.0`、`color_fps/depth_fps 15→30`、
  关自动曝光+曝光压小、`max_points 50000→0`）→ 帧率始终 **~1.83Hz** ⇒ **参数只在启动时读**。
- `lsusb -t` = **USB 3.2 / 5000M**（非带宽）；节点 CPU 仅 **38.5%**（非算力）；
  `/dev/video0-5` **全部被同一 PID 独占**（无法另开一路高速流）。
- ⚠️ `ros2 param set` 数值参数**必须传 DOUBLE**（`15.0` 不能写 `15`，否则报
  `Wrong parameter type, expected 'Type.DOUBLE' got 'Type.INTEGER'`）。
- 🔴 **生产参数原值（试完必须逐项设回 + `param get` 回读确认）**：
  `color_fps=15 · depth_fps=15 · publish_rate=5.0 · color_exposure=156.0 · color_auto_exposure=True · max_points=50000`
- **重启该节点只解得开"挂死"，不改变帧率**（实测 1.860→1.875Hz，参数覆盖同样无效）。
  但 launch 由 `project_launch_utils.generate_named_project_launch_description()`
  动态生成，**静态核不出 `respawn`** ⇒ 未确认自动拉起前**不要 kill**（产线会丢感知）。
  要做真修（用直驱节点替掉它）必须先拿到老倪授权 + 备好原命令与参数文件以便回滚。
⇒ 交付时把"链路延迟已优化到底"和"帧率瓶颈在哪一层"分开说，不把"压缩比/延迟优化"说成"解决了卡顿"。

### ✅ 已经修好的那两层（授权后实测）
1. **型号层**：相机是 `Intel RealSense D405`（立体深度，**物理上没有 RGB 传感器**），厂商节点日志里有
   `RealSense color sensor not found, skip color option config` ⇒ 它配的 `color_fps`/曝光/分辨率
   **从未生效过**，跑的是内部回退路径。**这就是"改参数永远没反应"的答案。**
2. **传输层**：D405 硬件在 640×480 支持 **5/15/30/60/90 fps**（`pyrealsense2` 实读模式表，非猜测），
   pyrealsense2 直驱实测 30/60/90 全部达标；**但一发布到本机 DDS 就掉到 4.6fps**
   （921KB/帧 装不进 208KB 的 UDP socket 缓冲 → 分片丢包重传 → **216ms/帧**）。

**修法（已上线，双通道，产线零回退）**：Orin 上跑 `tools/rs_fast_node.py` —— pyrealsense2 直驱 30fps：
- ① 每帧压 JPEG(q72, ~32KB) 落 `/dev/shm` + 起 HTTP `:8792/frame.jpg` ⇒ **绕开 DDS 大消息这条死路**；
  4060 侧 `cam_live_stream.py --arm-http http://192.168.23.66:8792/frame.jpg --arm-fps 30 --fps 30` 取用
  （**`--fps` 默认 15 会封顶，必须一起传 30**，否则只能到 15fps）。
- ② DDS 仍按**原话题名**发 color/depth/camera_info，限流 ~2.2Hz（**≥ 厂商原 1.9Hz ⇒ vision_tag 不回退**）。
- ③ 守护脚本挂了自动拉起；**Orin 重启后厂商 launch 会抢回设备**，此时重跑一次切换脚本即可。

实测：**手臂 1.86 → 16.6 fps（8.9×）** · Orin 端产出 22.9fps · CPU 75~92%（厂商 92% 只出 1.9fps）。
完整配方、取舍与回滚编排见 `low-latency-camera-streaming` 的
`references/high-rate-camera-bypass-node.md`。

## 压缩收益（实测 JPEG q70，640x480）
| 路 | 原始/帧 | q70 | 压缩 | q60 | q80 |
|---|---|---|---|---|---|
| 手臂(Orin) | 921KB | **29.1KB** | **30.9x** | 24.5KB | 37.0KB |
| 笔记本 | 900KB | 38.4KB | 23.4x | — | — |

MJPEG（`multipart/x-mixed-replace`）天然免解码缓冲 → 低延迟；服务端**只推最新帧、旧帧丢弃**（不积压）。

## 运动摄录：eye-in-hand 相机拍不出"臂自己动"
臂一动相机跟着动 → 画面里**臂不动、只有背景平移** → 单看视频看不出走了方形。
老倪会因此判定"动作和视频不匹配" —— **交付时必须先把这层语义讲清楚**（画面里没有臂是正常的，
场景平移量 = TCP 真实位移），并把位移可视化出来，否则他只会看到"不动"。
**做法**：录手臂流 + `cv2.phaseCorrelate`（**必须加 Hanning 窗**，否则边界效应带偏）测帧间位移
→ 积分成轨迹 → 另起面板实时画出来。
- **每步方向必须对得上**：用方向性光流逐段验证（脚本见 `low-latency-camera-streaming` 的
  `scripts/verify_motion_in_video.py`）。实测 8 步 `dy=-3.04 → dx=+5.19 → dy=+2.96 → dx=-5.19`
  完美交替 ⇒ **视频确实精确拍到了命令动作**，这是"不是发错片"的硬证据。
- **自标定**：用"每边命令 10mm"反算 mm/px（实测 8.41px/边 → **1.19mm/px**）→ 轨迹坐标直接读成**真毫米**。
- **去线性漂移**再画（`traj -= linspace(0,1,n)[:,None]*traj[-1]`），否则累积误差把方块画歪。
- 实测 1cm 方块：整圈跨度 12.1x10.4mm · 各边 8.6~12.0mm（均值 10.3）⇒ 与命令吻合。
- 脚本：`tools/record_mjpeg.py`（录 MJPEG→MP4，按实测 fps 写入所以播放速度=真实速度）+ 合成脚本做双面板。
- ⚠️ **长循环录像要绝对位姿驱动**（相对位移逐步累积漂移，十几分钟就走样）—— 见 skill `real-arm-motion-control`
  的 `line_rel` 漂移节；路点生成器 `tools/make_abs_path.py --d <边长mm> --prefix <前缀>`。

### 双相机"同步抓拍"（老倪要照片而不是视频时）
`tools/loop_snap.py`：循环下发动作 + **每步稳定后同一时刻取两路最新帧**
→ `c{圈}_s{步}_{技能}_{arm|lap}.jpg` + `manifest.json`（每张含采集 epoch / 帧龄 / std）
→ 再拼两张交付图：**①每圈一对并排（手臂|笔记本，带时刻/帧龄/std）②全部步的手臂画面网格**。
用法：`python tools/loop_snap.py <逗号分隔技能序列> [speed] [每步等待秒]`（序列可传相对技能或绝对路点技能）。
- ⚠️ 抓拍前必须**等手臂路来新鲜帧**（帧龄 ≤0.25s，最多等 2s）再取两路 —— 否则抓到运动/收尾相位，
  同位姿两图差异非单调，会被误读成"位置漂移"。漂移 vs 帧相位的区分判据见 skill `real-arm-motion-control`。
- **两相机"同步"的物理上限 = 手臂帧龄**：实测两路采集时差中位 **193~219ms**（手臂 0.24s vs 笔记本 0.03s）。
  按这个量级如实报，别说成"同时"。
- ⚠️ 端点名是 `/arm.mjpg` 与 **`/local.mjpg`** —— 按"笔记本=laptop"猜 `/lap.mjpg` 会 404，
  且抓拍线程会**静默只存下一路**。抓完先数 `ls /tmp/pairs/*_arm.jpg | wc -l` 与 `*_lap.jpg`
  **两路张数是否相等**再往下走。

### 合成录像（双面板 + 动作条）= "动作与双相机同步"的直观证据
`tools/record_sync.py <秒数> <out.mp4>`：左=手臂流 · 右=笔记本流 · 底部=动作状态条
（直读 `/motion`，与画面**同一系统时钟**渲染，非事后拼接）→ 转 H.264 后发飞书。
- ⚠️ **cv2 VideoWriter + 采集 daemon 线程 → 退出时 C++ 线程析构崩溃**
  (`terminate called without an active exception`；文件其实已写完，但退出码难看、偶发丢尾)。
  修法：写完 `vw.release()` 后 `sys.stdout.flush(); os._exit(0)` **直接退**，别让 daemon 线程走析构。

## 配套：驱动小范围动作来摄录（方块/往复）
摄录要”有东西动”，常见需求就是让臂走小方块。四方向技能已注册（都是 `ros:"line_rel"`，参数只有 `d_mm`）：
`L2.lift`抬升=+Z · `L2.lower`下降=-Z · `L2.left`向左=+Y · `L2.right`向右=-Y → 抬升→向右→下降→向左 = 闭合方块。
`d_mm` **min=5** → 1cm 方块合法。

- **速度从 `spec.speed` 传**（daemon `sp = spec.get("speed", 60)`，技能级 `speed_max` 再收口）。
  实测标定（TCP 50Hz 快采样，三点）：**speed 11/19/30 → 1.17/1.90/3.00 mm/s ⇒ ≈0.100 mm/s 每单位**
  （要 1/2/3 mm/s 就下 `speed=10/20/30`；daemon 注释里那个 0.093 偏悲观，别拿它换算）。
- 下发：`echo '{"skill":"L2.lift","d_mm":10,"speed":11}' > ~/zmax_data/l2_cmd.fifo`
  → daemon 日志打印 `目标 … pos=(...) · Δ=(…)mm ↑上升(+Z) · 位姿来源 direct` —— **这就是现成的每步取证**。
- 每步给 **17s** 足够（10mm@~1.1mm/s ≈9s + 服务开销）；8 步方块实测 TCP Δ 逐位 **±10.00mm**，闭合误差 0.01mm。
- ⚠️ **别用 `docker run ros2 topic echo` 做每步取证** —— 每次起容器 ~4s，8 步会把整轮拖到 4 分钟以上（录像窗口都不够）。

### ⚠️ `/tower_light/status` 会假报 `state:"estop"`（2026-09-26 现场）
现场 tower light 报 estop，老倪确认是**假急停**（“假急停，现场安全，没事”）。
→ **别拿 tower light 当急停判据**。权威看：`/emergency_stop` `/physical_estop` `/usb_estop`（无消息=无急停）
+ `/robot_status` 的 power_state/operation_state/has_error 三查。报 estop 时把这三个话题的实测输出列给现场判，
别自己决定“到底能不能动”。详细解锁序列见 skill `real-arm-motion-control`（用户自持）。

## 取单帧 / 探端点（别下整条流、别信 200）
- **MJPEG 是无限流, 不是文件**: `curl -s <host>/arm.mjpg -o f.jpg --max-time 25` 会一直下
  —— 实测 25s 吃下 **28MB** 且停在半帧(文件不可用)。要"一帧"就 socket 读到 JPEG 边界:
  连上 → `GET <path> HTTP/1.0` → 累积 recv → 找 `\xff\xd8\xff`(SOI) 再找 `\xff\xd9`(EOI) → 切出来即完整一帧
  (**必须带上限 4MB + 超时**)。要"最新一帧"就断开重连, 别在同一连接上等。
- **HTTP 200 不等于端点存在**: 设备侧小 HTTP 节点常写成 `do_GET` 的 catch-all(未知路径返回同一份状态 JSON)。
  实测某相机节点只有 `/frame.jpg` 是真图(首字节 `ffd8ffe0`), 其余 `/depth* /status /info` **全是同一份 45B JSON**。
  判据: 逐路径比 `%{size_download}` 与首字节(`head -c 4 | xxd -p`) —— 大小+类型完全一样 = 兜底路由, 端点不存在。
  别把"200 + JSON"读成"端点有了只是没数据"。

## 对外交付：手机/APP 在别的网络看现场（公网通道）
内网 IP（`10.163.146.x`）出不了办公网 ⇒ 手机 4G / 外网 / 云主机**全打不开，这不是页面坏**。
对过的网段隔离实测：同办公网的 Mac（`10.163.148.x`）也够不到 `146.x` ⇒ 别在内网侧找原因。
定式 = **源侧推流 + 域名侧端口转发**，各干各的：源侧把流做成"别人拿来就能转发"的东西（只读闸门 + 机器可读清单）；
域名侧做 frp/nginx 转发与打包。**接口要定成 `host:port`，不要定成隧道 URL**（URL 会变，见 ④）。

### ① 暴露前必须加只读闸门（红线，先做这个再谈穿透）
`cam_live_stream.py` 上带着 `/ctl/arm` `/ctl/move`（真机动）与 `/gen`（真触发拍照+大模型调用）。
**把整条端口露到公网 = 把机器人放网上。** 定式：穿透只指向一个**只转发 GET 白名单**的小代理
（`tools/tunnel_proxy.py`，systemd 常驻，监听 8891 → 上游 8791），POST/PUT/DELETE 一律 403，
且 `/ctl/*` `/gen` `/station` `/tap` **即使带正确口令也 403**（点名拒绝列表优先于白名单判定）。
- 口令走 URL `?k=<token>`：首次带口令打开时由代理回 `Set-Cookie`，页面内**同源**子请求（MJPEG/`scene.json`）自动过闸——
  不靠 JS 兜（JS 兜不到 `<img>`/`fetch` 之外的路径）。
- **验收是一张真值表，不是"应该没问题"**（`tools/verify_tunnel_gate.py`）：只读路径 200 · 无口令 403 ·
  **带口令的 `POST /ctl/move` 必须 403** · `/gen` 403 · 随手路径 403。实测 14/14 才准放行。
- ⚠️ **判据自身要先被证伪**：拿 `str(status)` 去比 int 期望值会**整表报 ✗**（真值其实全对）；断言前把状态码转 int，
  并留一条已知必过的控制项。白名单要按"页面真正请求的路径"定（先在页面里 grep `fetch(`/`src=`），否则穿过去是残页。

### ② 先量通道，再承诺视频（这一步不能省）
| 通道 | 实测吞吐 | 能承载 |
|---|---|---|
| 本机闸门（局域网） | 497 KB/s ⇒ 10.3 fps | 原始 MJPEG ✓（代理零损耗：10.3 vs 直连 10.2） |
| 免费 ssh 隧道（localhost.run） | **21~66 KB/s ⇒ 0.8~1.5 fps** | 只能"看得见"，谈不上流畅 ✗ |
- **快照轮询不是视频流**：100KB/帧 × 10fps ≈ 34GB/日，ECS 与 4G 都吃不消——别把"轮询快照"当方案交。
- 建隧道前先探可达性（`/dev/tcp/<host>/<port>` + 服务站点 HTTP）：本机实测 **Cloudflare 边缘不通**
  （cloudflared 走不了），localhost.run（ssh 22）与 bore.pub 通 ⇒ **别按网上教程默认选 cloudflared**。
  `ssh -T -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -R 80:localhost:<闸门口> nokey@localhost.run`
  免安装免账号且**自带 HTTPS**（HTTPS 关键：App 内 https 页面取 http 子流会被混合内容拦死）。

### ③ 窄通道要"降码率"，不是"降低体验承诺"
给公网做一路**三相机拼图流**（一张图 = 三个相机，正好对上老倪说的"现场是三个相机"）：
`/wall.mjpg?w=400&q=60&fps=2&layout=v`（`/wall.jpg` 出单张给轮询/云主机）。
实测 400px/格 q60 2fps ≈ **56KB/s**，刚好落在隧道能力内；每格底部必须印 **路名 · 拍照时刻 · 帧龄**
（画面自己要说清是什么，老倪会把画面当结果看）。单路原始流（≈450KB/s）只留局域网。
- 拼图由**代理本地合成**（PIL 解码三张 `snapshot/overlay_*.jpg` 再拼）⇒ **不动在跑的推流服务**
  （改它要重启、会打断现场观看）；代理是独立进程，重启代价为零。
- 顺手出一个 `/live.json` 清单（每个流的地址/码率/参数/口令 + 当前 fps + "哪些路径永不外放"），
  让转发与打包那侧**照单接线、不用猜**。

### ④ 两个把我坑到过的点
1. **慢依赖必须搬进后台线程**（叠加路掉到 3fps 的真因）：叠加线程每 2s 同步读一次 TCP 真值，
   而快路径（容器写的 `tcp_pose.json`）只认**新鲜度 ≤1.5s**，写它的容器没了 ⇒ 每次回退
   `sshpass ssh ... ros2 topic echo`（单次 0.3~8s、timeout=20）⇒ 渲染被拖成 **2.1~4.3fps**（原始流其实 29.9fps）。
   修法：**后台刷新线程**（2s 一刷）+ 渲染循环只取最新值、**永不阻塞**；标签从"实时真值"改成
   **`真值 · N.Ns前`**（缓存值不许冒充实时）。实测 3.0 → **10.0 fps**、最大帧龄 5.8s → **0.08s**。
   排查顺序：**先证伪源端**（Orin 侧 35/35 成功、失败率 0%、延迟中位 3ms ⇒ 不是抖动），再往本机找同步阻塞。
2. **隧道 URL 是易失的**：systemd 里给隧道 unit 写 `Requires=<闸门>.service` 会让"重启闸门"**连带重启隧道** ⇒
   公网 URL 换掉 ⇒ 已烧进 APK 的地址立刻 503（`/wall.jpg` 复现 3/3 失败就是它的症状）。用 `Wants=`（软依赖），
   且**别把易失地址当成客户端的唯一地址**（见 skill `android-webview-shell-apk`）。

## 坑
1. **`tools/record_mjpeg.py` 只在收完帧才写文件** → `pkill` 会丢掉**整个**视频（第一次就这么丢了两段）。
   已加 SIGTERM/SIGINT 处理：收到信号只结束采集循环、正常落盘。**改完记得也让调用方用 `wait` 等自然结束**。
2. **飞书一条消息发多个 MEDIA 可能只到 1 个** → **视频一次发一条**；仍收不到就改发**帧序列图**（图片必显示）。
3. 送飞书前转 H.264：`ffmpeg -i in.mp4 -c:v libx264 -preset veryfast -crf 25 -pix_fmt yuv420p -movflags +faststart out.mp4`
   （体积降 ~10x：3.2MB→2.0MB；合成双面板 5.3MB→0.9MB）。`mp4v` 四cc 有些客户端不播。
4. 老倪会追问"XX视频呢？" —— 收到这句=**媒体没送达**，不是内容不对；先核实文件有效+与另一路内容不同，再单独重发。
5. **某一路帧龄上万秒 = 先查"谁在产它", 别从相机那头往上查**: 第一步是落盘文件的 mtime + 写入方
   在不在(`ps` / `docker ps -a`) —— 写入方常是个容器或守护进程, **栈一重启就整个没了**, 文件停在几小时前,
   而源设备与 ROS 话题一切正常。实测 depth 那路就是这么挂的。
6. **新起的 DDS 读进程会静默起不来（不报错、没输出、文件都不创建）**: FastDDS 报
   `[RTPS_TRANSPORT_SHM Error] Failed init_port fastrtps_portXXXX: open_and_lock_file failed` 时,
   进程可能死在 `rclpy.init` / `create_subscription` 阶段 —— 症状是**连自己那句"开始订阅"日志都没有**。
   修: 起读进程时加 **`FASTDDS_BUILTIN_TRANSPORTS=UDPv4`**（进程能正常进订阅态）。
   ✗ **机器人在役时严禁 `rm /dev/shm/fastrtps_*`** —— 那是栈自己的通信段。
   排查顺序要固定: ① 在 **Orin 本机** `ros2 topic info <话题>` 看 `Publisher count` —— 有发布者就说明驱动在发,
   **不要重启机器人栈**（会掉相机节点、要手工重拉整条 launch）; ② 再查读侧（SHM/发现/容器）;
   ③ `ros2 topic echo` 报 `choose_qos`/无法推断 QoS 也是**发现**没建起来, 不是话题名写错;
   ④ **一次失败不算路线不通**: "同一读进程上午能读到、栈重启后再也读不到"是常态(老 participant 发现状态脏),
   重启读侧进程值得试, 但必须拿**一个非 null 的真值**做判据 —— `ros2 topic hz` 有速率 ≠ 你能读到消息。
   想换 RMW(cyclonedds) 先确认这台机装了（`dlopen … librmw_cyclonedds_cpp.so: cannot open shared object file` = 没装）。
7. **“取到了帧”要用两路端点互证**: 同一相机常有两条独立读取路（Orin 侧 JPEG 桥 `:8792/frame.jpg`
   与推流服务 `/snapshot/<cam>.jpg`）——**同时刻各取一张, 比字节数 + `cv2.imread` 的尺寸/均值**,
   两者一致且均值正常才算真帧（实测两路同为 `200/34214B`、640×480、均值 131.9 ⇒ 链路与渲染都真）。
   均值 <10 或字节数极小 = 全黑/占位图。

## 取证纪律（每次交付）
- **交付前必须证明"目标真的在画面里"**，不能只看帧差。实测教训：笔记本相机**完全没对准机械臂**，
  相邻帧差却让每一步都"看着像在动"（噪声）→ 老倪反馈"两个相机也没看到移动，动作和视频不匹配"。
  **正确判据 = 方向性光流对齐命令方向**：抬升/下降应给竖直主向、左/右给水平主向且符号相反，
  幅值需显著高于噪声底（静止画面 ≈0.00px；真有位移 3~5px）。
  实测手臂流 8 步全部方向+符号正确（dy=-3.04/ dx=+5.19/ dy=+2.96/ dx=-5.19 …）✅；
  笔记本流 8 步全 `(0.00,0.00)` ⇒ 没对准。直接跑
  skill `low-latency-camera-streaming` 的 `scripts/verify_motion_in_video.py`。
  **没对准就先说"这路没拍到目标"并把"把相机对准机械臂"作为用户侧动作提出来，不要当结果交付。**
- 交付前 `cv2.imread` 判真图（`std>5`；黑帧 std≈0）+ 抽帧（起/中/末）目检。
- **用户要摆件演示、而某项真值路还没通时: 先把沟通和录到的部分做好, 再明说哪一项记不到、为什么**
  （例如"图像在录、槽位 3D 真值还没通"），**绝不让他按"会被精确记录"的前提去摆样件、白摆一趟**;
  也不要把"进程活着"说成"记下来了"。需要 3D 而深度/真值缺位时走退路并说明退路是什么
  （用已知物理尺寸的基准物从图像定 mm/像素标尺）—— 退路也要讲清是退路。
- 一切实时数值带**拍照时刻 + 帧龄**（老倪硬要求）。
- 帧率/IP/体积都写实测值，不写"应该"。

## 支持文件
- `references/arm-stream-restore.md` — arm 路帧龄上万时的恢复口径
- `references/public-exposure-gate.md` — 公网暴露闸门的白名单/拒绝表、真值表用例、隧道选型与实测吞吐、`/live.json` 清单形状
- 仓库内实现：`tools/tunnel_proxy.py`（只读闸门 + 拼图流 + 清单）· `tools/verify_tunnel_gate.py`（真值表）·
  `tools/wall_3cam.py`（离线拼图出图）· `tools/probe_ecs_upload.py`（探对方上传口语义）
