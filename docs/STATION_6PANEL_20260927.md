# 🛰 工位总览 · 6 路同屏 + 手动控制机器人 (2026-09-27, v5.15.15 → v5.15.16)

老倪需求原文:
> 「三个摄像头的图像，要同时显示，还有深度图，加上工控机 OPT 相机 金手指检测和表面检测，
>   就是 6 个窗口同时显示；窗口要留出控制区，可以控制机器人 X Y Z 平动以及绕轴旋转的 A B C 操作，
>   这样我就可以手动控制机器人了」

---

## 0. 第二轮修复 (老倪反馈: 「10082/10083 没有图像；控制区前进后退等按钮无法操作」)

三个真根因, 都实测到证据后才改:

**① 控制区按钮"点不动" = 浏览器连接名额被占满 (不是按钮坏了)**
`ss -tnp` 实测老倪那个 chromium 进程对 `8791` 恰为 **6 条连接**(HTTP/1.1 对同一 host:port 上限),
之前 6 格里有 2 格是长连接 MJPEG, 加上状态/快照请求 ⇒ 满格; 按钮的 POST 一直排在队里,
表现就是"点了没反应/按钮灰着"。修法:
  · 总览页 **一格 MJPEG 都不用**: 6 格全走**串行单帧快照**(全局一次只发一条请求) ⇒ 常占 1 条;
  · 总览页挪到**自己的端口 8793**(`--station-port`), 主端口 `/station` 一律 **302** 过去 ⇒
    与其它本机页面(叠加页/画布)**各占各的 6 条名额**, 互不饿死;
  · 按钮加 15s 兜底放开 + 请求超时(18s)后明写"请求没发出去/超时", 不再无声无息。

**② 金手指 10082 "没有图像" = 工控机内存里当时没有照片**
实测 `GET /picture?kind=origin` 在它闲着的时侯返
`404 {"code":404,"msg":"尚无照片: 先 POST /capture_detect 或 GET /picture?grab=1"}` ——
OPT 只在检测/拍照时留图, 我们只 GET 不拍照 ⇒ 取了个空。修法:
  · 面板按这句话(**不猜**): 明写"工控机内存里当前没有照片", 并给 **📸 拍一帧**
    (走 `GET /picture?kind=origin&grab=1`, 实测 HTTP 200 / 4.9MB / 1.4s) ;
  · **🔁 自动取景**(默认开, 页面上可关): 发现 404 就替它现拍一张, 最快 30s 一次;
  · 判据图之外再存一张 **整板原图**(2048×2448 → 缩到 1400×1171), 面板上「判据图(一条区域) /
    整板原图」一键切换 —— 之前只有一条区域的判据图, 看着像"没图";
  · 拍过之后 90s 内即使 OPT 又没照片, 面板也按**在线**报(画面确实是新拍的), 不写"取图失败"
    把好图说成坏的。

**③ 表面检测 10083 "没有图像" = 那台服务根本没有取图路由(本机侧无解)**
实测 10083 的 `/picture`、`/image`、`/last_result` 等 GET 全 404, 只有 `POST /capture_detect`
(`{"success":true}` = 只受理不带图)。所以这一格如实写"该路没有取图路由"+ 给「📸 拍帧」;
要真画面必须在工控机上加一条取图路由, 补丁: `docs/patch/opt_surface_10083_add_picture_route.md`。

**验证口径(离屏真跑, 不猜)**
  · 页面/端口: `8791/station` → 302 → `8793/station` 200 (19150B, 6 个 `data-mode="snap"`, 0 个 `.mjpg`);
  · 同浏览器里叠加页(3 条 MJPEG)开着时, 总览页仍在刷: 11s 内 5 格 `src` 全部推进、状态帧龄 0.01s、
    看门狗未报警 (`ss` 实测 8791/8793 各占各的);
  · 按钮端到端: 点「⏩前进」→ 页面出执行器原始三行 `Δ=(+10.0,+0.0,+0.0)mm → DRY-RUN /move_line`;
    点「↺+C」→ `🔄 绕C(工具Z·自转) +5.0°: 当前位置不动, 姿态 quat […]→[…] → /move_pose`(演练);
  · 自动取景分支: `tools/verify_aoi_autograb_branch.py`(假 404 → 断言补发 grab=1 且两路帧槽落地) **PASS**;
  · 桌面取证图: `/tmp/station_6panel_v3.png` (3840×2086, 5 格有内容 std 73~104, 第 6 格是那路无路由的面板)。

**踩坑(已写进技能)**
  · `pkill -f cam_live_stream.py` 连**同一条命令行里出现的文件名**都会匹配到 ⇒ 把自己的命令 SIGTERM;
    改成**按端口找 pid**(`ss -tlnp | grep :8791`)再 kill。
  · MJPEG 页面**永远不触发浏览器 load 事件**, 自动化浏览器 `navigate` 会超时(页面其实已加载)⇒
    取证改成读 DOM。

---

## 0.5 第三轮 (老倪: 「10083通道还是没有信号；控制区域不好用；修」)

### A. 10083 表面相机 "没有信号" —— 已穷举到不能再穷举, **结论: 本机侧无解, 必须动工控机**
不是"没试", 是三条路都试到底了(全部零副作用/只读):
| 试法 | 结果 |
|---|---|
| 10083 上 **55 条候选路径** 逐个 `OPTIONS`(含 /picture /image /snapshot /stream /static /surface_images /拼音名…) | **只有 `/capture_detect` (Allow: POST, OPTIONS)**, 其余全 404 |
| 工控机**其它端口**(1~65535 全扫 + 常用 web 口) | 没有第二个 HTTP 服务; 10081 的 /picture 也 404 |
| 文件共享取它落盘的 `./surface_images/` | 445/139 开着, 但 `smbclient -N` = `NT_STATUS_ACCESS_DENIED`(无匿名共享, 本机也没有那台机器的凭据) |
⇒ 工控机那套程序**根本没实现取图口**。唯一修法 = 上补丁 `docs/patch/opt_surface_10083_add_picture_route.md`
(约 30 行 + 现场 4 步自测)。**补丁一上, 本页不用改一行就会自动出图** —— 这一格一直按 0.25Hz 轮询
`GET /picture?kind=origin`, 一有 200 立刻显示真图。面板现在把这条证据和文件路径直接写在画面上(不猜、不编)。
工具: `tools/probe_aoi_routes.py`(单端口穷举) · `tools/probe_10083_deep.py`(深挖+端口清点) ·
`tools/sweep_opt_host_ports.py`(全端口扫描)。

### B. 控制区重做 (老倪: 「不好用」)
| 毛病 | 现在 |
|---|---|
| 6 个方向按钮排两列, 又要滚屏才能看到授权/结果 | **十字 D-pad**(3×3, 按钮 92px 高, 中央显示当前步长) + **键盘**: ↑↓←→ = 前后左右 · PgUp/PgDn = 升降 · A/B/C(+Shift 反向) = 绕轴旋转 |
| 「授权真动」是个小勾选框, 每次都要找 | **顶部一个大开关**(⛔演练模式 ↔ ✅真动已启用), 绿色/黄色大字, 状态记在 localStorage(刷新不丢) |
| 按钮点了不知道有没有下发 | 按钮 0.9s 闪光 + 「下发中…(最多等 15s)」+ 结果带**本次用时**(如 `用时 1.2s`)+ 原始日志 + 「📄 复制原始日志」按钮 |
| 「点了没动」分不清是没下发还是动作慢 | 结果行明写「**对上 X/Y/Z 看有没有变就知道动没动**」; 状态条加 **🔄 移动中** 标记(operation_state≠idle) |
| 速度语义不清, 8 很慢还会报一次超时 | 速度预设 `8 慢·默认 / 20 / 40 / 60 快` + 明写: 8 很慢(可能十几~几十秒), 停下前驱动会报一次
`wait_until_idle` 超时 —— **那是超时标记不是失败**(已实测: 动作真跑了, 只是等待窗口 30s) |
| 布局: 6 格挤占整屏, 控制列要滚动 | `main` 改 2 列(左 6 格 / 右 640px 控制列各自独立滚动), 窄屏自动堆叠(手机可用) |

实测(离屏真跑): 点「⏩前进」→ `Δ=(+10.0,+0.0,+0.0)mm → DRY-RUN /move_line`, 页面回 `🧪 演练(未下发) · 用时 1.2s`;
按 **Shift+A** → `🔄 绕A(工具X·俯仰) -5.0°: 当前位置不动, 姿态 quat [−0.0918 −0.6938 0.7062 0.1071] → … → /move_pose`;
步长切到 50 → D-pad 中央与六个按钮的提示同步变 `50mm`; 取图仍是 6 格串行单帧快照(0 个 .mjpg), 他那个浏览器对 8793 只占 2 条连接。
取证图: `/tmp/station_console_v3.png`(3840×2086, 控制列 std 86 有内容) / 缩图 `/tmp/station_console_v3.jpg`。

**顺带记一条现场实况**: 三查里 `ROBOT_IDLE_TIMEOUT` 是**我们桥**在 08:23 那次 /move_line 等 idle
30s 记的标记(`controller_error_logs` 为空 = 控制器侧无报警), 与 v5.7.0 记录的驱动行为一致:
**判动作完成要看 TCP/operation_state, 不能凭 success=False 重发**(重发会叠加第二次动作)。页面已把来源写明。

---

## 1. 交付物

**页面: `http://<本机IP>:8793/station`** (本机 `http://127.0.0.1:8793/station`;
主端口 `8791/station` 会 302 跳到这里 —— 8793 是总览专用端口, 独立 6 条连接名额)
入口: 「🧩 场景叠加」页头部有直达链接；8791 服务的启动日志里也打印 URL。

六格 (左 2×3 网格) + 右侧控制列:

| 格 | 源 | 取图方式 | 实测 |
|---|---|---|---|
| 🦾 机器人臂上 D405 | Orin `8792/frame.jpg` | 单帧快照 1s | 640×480 · 3~4fps · 帧龄 0.3~1.8s |
| 💻 笔记本内置 | 本机 `/dev/video2` | 单帧快照 0.4s | 640×480 · 源 15fps · 帧龄 0.01s |
| 📺 MAXHUB 顶摄 | 本机 `/dev/video0` | 单帧快照 0.4s | 1280×720 · 源 22~28fps · 帧龄 0.02s |
| 🌈 D405 深度图 | 容器只读订阅深度话题 → 伪彩 | 单帧快照 1.5s | 640×526(含 46px 真值带) · 源 0.24Hz · 有效 88% |
| 🔍 金手指检测 | 工控机 10082 `/picture?kind=origin` → 去死白判据图 | 单帧快照 3s | 900×900 判据图 · 源图 5.9MB/帧 · 0.24Hz |
| 🔍 表面检测 | 工控机 10083 | 无取图路由(见 §5) | 只能「拍帧」触发, 回执 `{"success":true}` 无图 |

右侧控制列: 三查状态 · TCP 位姿 · X Y Z 平动 6 按钮 · A B C 绕轴旋转 6 按钮 · 步长/角度/速度 · 授权闸门 · 点击结果(原始日志行, 可复制)

---

## 2. 链路与文件 (谁产出什么)

```
Orin 192.168.23.66
  /realsense/depth/image_rect_raw (16UC1 640x480 step=1280, 实测 0.24Hz)
  /realsense/color/image_raw     /robot/tcp_pose (50Hz)   /robot_status (JSON 字符串)
        │  容器 ss-remote-tap (ROS_DOMAIN_ID=0, 只读订阅)
        ├─ tools/ros_depth_stream.py  → zmax_scene/depth_raw.npy + depth_meta.json   (numpy, 无 cv2)
        └─ tools/ros_tcp_cache.py     → zmax_scene/tcp_pose.json + robot_status.json (20Hz 落盘)
        │  (宿主 /home/ubuntu/zmax_ss_remote 挂的是容器 /out)
宿主 4060
  tools/depth_colorize.py          ← 彩色化口径**唯一真源**(容器/宿主共用, 不各写一份)
  tools/cam_live_stream.py (8791)
        ├─ _depth_worker       读 npy → 伪彩+真值带 → 帧槽 depth
        ├─ _aoi_worker(10082)  GET 取原图(不带 grab) → 去死白 → 帧槽 aoi_gold; 另读 /last_result
        ├─ _aoi_worker(10083)  实测 404 → 如实报"无取图路由", 不假装有画面
        ├─ _ctl_move/_ctl_status  POST /ctl/move · GET /station/status
        └─ 页面 /station (STATION_PAGE)
工控机 192.168.23.23
  10082 金手指 (Flask): GET /picture?kind=origin|natural|crop · /last_result · POST /capture_detect
  10083 表面  (Flask): 只有 POST /capture_detect
```

## 3. 手动控制 (X Y Z 平动 + A B C 绕轴旋转)

**平动**: 复用既有 6 个方向技能 `L2.forward/backward/left/right/lift/lower` (走 `/move_line`)。
**旋转**: 新加**执行算子** `pose_rot` (`tools/l2_daemon.py::build_pose_rot`) + 6 个技能
`L2.rot_{a,b,c}_{pos,neg}` (`tools/register_rot_skills.py` 注册, 现注册表共 54 个技能)。

| 轴 | 含义 | 数学 |
|---|---|---|
| A | 绕**工具 X 轴** 俯仰 | `q_new = q_cur · q_axis(θ)` |
| B | 绕**工具 Y 轴** 倾侧 | 同上, 右手定则, **工具系** |
| C | 绕**工具 Z 轴** 自转(画面原地转) | 同上 |

* 位置**不动**(实测日志 ΔX/ΔY/ΔZ = +0.0mm), 只改姿态; 走 `/move_pose` (与已验证的
  `tools/l2_pose_rot.py` 同一通道 —— 该通道实测不掉电, 免去反复上电解锁)。
* 度数只填正数, 方向由技能内定 (与方向点动同一口径, 现场不填负号)。
* 执行层守卫 `max_deg` 默认 10°(注册时写入, 页面给 1/5/10/20 步长, >30° 直接拒发)。

**四道闸门** (缺一不下发):

1. 服务级: `cam_live_stream.py --ctl-motion` (不加 ⇒ 一律 dry-run)
2. 页面级: 勾「授权真动」(不勾 ⇒ 请求仍打到服务, 但服务强制 dry)
3. 白名单: 只认上面 12 个技能; 其它技能(点位/多阶段/夹爪)一律拒 (`L2.goto_point` 实测被拒)
4. 限幅+限流: 平动 5~300mm(下降 ≤100)、旋转 1~30°、速度 1~30、真指令间隔 ≥1.5s(防连点当摇杆)

* **GET 一律不触发动作**(`GET /ctl/move` → 404): 浏览器预取/爬虫/取证脚本都会 GET, 不能让一次预取动臂。
* 每次点击**必须**返回执行器原始日志行(可复制), 不留"已发送"这种自报。样例:
  `[08:16:38] 目标 L2.backward: Δ=(-10.0,+0.0,+0.0)mm →后退(-X) · 位姿来源 direct` →
  `DRY-RUN L2.backward → ros2 service call /move_line ...` → `受理: DRY-RUN(未下发)`
* **没有软急停**: 不提供未验证的停止指令, 急停走示教器/现场急停按钮 (页面已写明)。

## 4. 实测取证 (2026-09-27 08:1x)

* 六格: 前 5 格的 `naturalWidth/Height` 实测 `640×480 / 640×480 / 1280×720 / 640×526 / 900×900`;
  表面格无帧(如实标注)。像素体检: std 69.7 / 68.3 / 56.8 / 55.7 / 66.0, 近黑占比 ≤7.9%(深度无效区)。
* `/station/status`: 三查 `power=on · operation=idle · has_error=false · estop=false · collision=false`(帧龄 0.26s);
  TCP `X 0.5337 Y 0.2313 Z 0.2271`(帧龄 0.04s); `motion_armed=true`。
* 金手指 `/last_result`: `count=0 · detect_type=gf · ms=1637 · n=246`(真检测结果, 不是编的)。
* 旋转空跑: `L2.rot_c_pos deg=5` → Δ=(0,0,0)mm · quat `[0.8114 0.0545 0.5814 -0.0250]` →
  `[0.8130 0.0191 0.5797 -0.0504]` · `/move_pose` 已受理(DRY-RUN 未下发)。
* 深度物理核对: `step=1280=640×2` 行主序 ✓; 有效 88%; 最近 0.196m / 中位 0.376m / 中心 0.444m;
  同一时刻深度 vs 彩色 **边缘相关 +0.05~+0.07**(正相关; 幅值小是 D405 深度未与 RGB 对齐的视差所致,
  传感器特性, 不是布局错 —— 布局若错会掉到 0 附近并出现花图)。
* 页面 JS 错误 0 条; 浏览器到 8791 的并发连接 **5 条**(≤6 上限)。

## 5. 已知边界 (如实, 未藏)

1. **10083 表面检测没有取图路由** → 那一格没有实时画面, 只有「📸 拍帧」按钮;
   实测 `POST /capture_detect` 返回 `{"success": true}`(200=受理) 且**回执里不带图**,
   所以点完也只有回执。要真正出图必须在工控机侧加一条取图路由
   (`docs/patch/opt_surface_10083_add_picture_route.md` 已备), 本机侧无解。
2. **臂上相机 3~4fps**: Orin load 7.7~10 时 `8792` 单帧要 1.8s; 帧龄如实标, 没藏。
3. **深度图 ~4s 一帧**: 源话题实测 0.24Hz(不是我们限的速), 页面上标的就是真帧龄。
4. **浏览器 HTTP/1.1 每主机 6 连接**: 6 格全用 MJPEG 会把连接占满 → 状态请求永远排队(页面卡"读取中…")。
   现方案: 高速两路留 MJPEG + 其余 4 格串行单帧快照 + 状态合并成 1 条请求 ⇒ 常占用 ≤5。
   页面自带卡顿自诊断提示(>7s 没更新就提示关掉其它 8791 页面)。
5. 服务**无鉴权**(局域网/产线网工具); 「授权真动」勾选后点击是真动臂 —— 现场请确认工作空间无人/无障碍。

## 6. 运维

```bash
# 起/重启 8791 (含 6 窗 + 手动控制; 真动授权只需去掉 --ctl-motion)
bash /home/ubuntu/.hermes/cache/scratch/restart_stream6.sh
# 执行器 (手动控制的下发口) 保活
bash /home/ubuntu/.hermes/scripts/l2_daemon_keepalive.sh
# 容器内两个常驻源 (深度 / 位姿+三查)
sudo docker exec -d ss-remote-tap bash -lc 'source /opt/ros/humble/setup.bash && export ROS_DOMAIN_ID=0 && \
  python3 /repo/tools/ros_depth_stream.py --hz 5'
sudo docker exec -d ss-remote-tap bash -lc 'source /opt/ros/humble/setup.bash && export ROS_DOMAIN_ID=0 && \
  python3 /repo/tools/ros_tcp_cache.py --hz 20'
```

坑 (都实打实踩过):

* `pkill -f "cam_live_stream.py"` 会**杀掉自己**(调用它的那条命令行里含同名字符串) → 用 `[c]am_...` 中括号技巧, 且别在同一条命令里再写全名。
* 容器(`ros:humble-ros-base`)**有 numpy 没 cv2**, 往里装重启即失 ⇒ 容器只落原始数组, 彩色化在宿主做。
* `aoi_exposure_fix.clean_judge_frame` 吃 **RGB**(内部按 RGB 加权算灰度), 喂 BGR 会判错 → 进出各转一次。
* ROS 头时间戳与宿主墙钟**不同源**(差~26h) ⇒ 帧龄只能取相对量(首帧对齐)。
