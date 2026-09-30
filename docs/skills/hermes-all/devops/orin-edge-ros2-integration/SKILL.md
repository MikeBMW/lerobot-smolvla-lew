---
name: orin-edge-ros2-integration
description: "Use when 接 Z-MAX Orin 真机链路: LAN直连/ROS2影子/跨机推理。"
version: 1.0.0
author: Hermes Agent
tags: [zmax, orin, ros2, edge, shadow, hardware-toolbox]
platforms: [linux]
---

# Orin 真机链路接入（LAN 直连 · ROS2 影子运行 · 跨机推理）

2026-09-16 一整套实测沉淀：本机(ThinkBook, 4060)↔ Orin 同网段直连后，
把「硬件工具箱真机按钮」和「状态空间工程旁路运行」打通，并把模型推理拆到 4060 的目标架构定下来。

## When to Use
- 要在本机控制/观测 Orin 上的真机（塔灯、夹爪、关节、力、相机、状态机）。
- 要把某个工程（状态空间/策略）"旁路/影子"部署到 Orin（只读、不接管产线）。
- 要做 Orin 采集 + 4060 推理 的跨机 ROS2 节点架构。
- 出现「无法连接 Orin」「发现硬件点一下就崩」「塔灯点了不变色」「硬件按钮反应慢」。

## 系统事实（不要猜）
| 项 | 值 |
|---|---|
| Orin 账号/地址 | **tashan@192.168.23.66**（`nvidia@192.168.23.10` 是废弃账号，仓库里仍有残留 → grep 后修） |
| ROS | Orin = JetPack/Ubuntu 22.04 + **ROS 2 Humble**；**现场全栈 `ROS_DOMAIN_ID=0`**（用 23 查只有 /rosout，会误判"驱动没起"） |
| 本机 | Ubuntu 24.04，**未装 ROS2** → 要当 ROS2 节点用 `docker run --network host ros:humble`（同版本零互操作风险；直装 Jazzy 属跨发行版"能用不保证"） |
| 网络 | 同网段 RTT ≈0.5ms；交换机上跑着产线（robot_driver/motion/HMI/vision）→ **带宽和 CPU 都要省** |
| 现场红线 | 我方服务合计 **<8% 单核 CPU**；产线进程绝不触碰；执行永远在 Orin 侧收口 |

关键端点（读）+ 控制路径：
- Orin Gateway `:8765`（/health /record/start|stop|status|latest|download /disk/guard）· 产线 HMI `:8000` · 状态空间推理服务 `:8767`（POST /infer/mani 11D、/infer/yaw 12D）
- 塔灯控制 = 话题 `/tower_light/command` (std_msgs/String) + 回读 `/tower_light/status`
- 夹爪 = 服务 `/gripper_driver` (interfaces/srv/GripperSrv)

## 连通性排查顺序（"无法连接 Orin" 一律按这个序）
1. `ssh -o BatchMode=yes tashan@192.168.23.66 'echo OK'` —— **免密是前提**：GUI/脚本全是无密码 ssh；
   本机无 `~/.ssh/id_*` 就一律连不上。修：`ssh-keygen -t ed25519 -N ''` + 公钥写入 Orin `~/.ssh/authorized_keys`；
   需要 `ControlPath=/tmp/orin-ssh.sock` 的路径再建一条 ControlMaster 复用通道。
2. grep 代码里的 `ORIN_USER` / `nvidia@` —— 旧账号残留是"无法连接"的头号原因。
3. `export ROS_DOMAIN_ID=0` 再查图 —— 域错只会看到 /rosout。
4. 最后才是网络/端口（`ping`、`/dev/tcp` 探 22/8000/8765）。

## 旁路（影子）运行器配方（已跑通）
只读铁律：**只 create_subscription，绝不 create_publisher 控制话题、绝不 call 服务**。对外写入只有三处：
本地 jsonl、relay 回传（POST `datadrive.world/api/relay/upload`，`meta.source=orin_shadow`）、遥测 `/zmax_shadow/status`。

- 高频话题 **`raw=True`** + 反序列化挪到 5Hz tick（Python 逐条解码很贵）；关节用 **`/robot/joint_states`(49.5Hz)** 而不是 100Hz 那条。
- 启动 `~/.zmax/start_<name>.sh`（`export ROS_DOMAIN_ID=0; source /opt/ros/humble/setup.bash; exec python3 …`）
  + 幂等守护 `~/.zmax/<name>_daemon.sh`（`pgrep -f "[x]xx.py"` 命中就"已在运行, 跳过"；否则 `setsid nohup … &`）
  + `crontab @reboot sleep 25 && ~/.zmax/<name>_daemon.sh`。
- 退出时用 `resource.getrusage(RUSAGE_SELF)` **自报 CPU**（比外部采样准，还能看出启动开销占比）。
- **只读性取证（比口头声明强）**：`ros2 node info /<node>` → Subscribers 应全是只读话题，
  Publishers 只应有 /rosout /parameter_events + 遥测话题，**没有任何控制话题**。

## CPU 实测（单核口径，60s 稳态，Orin 8 核）
| 配置 | 消息率 | CPU |
|---|---|---|
| 只订阅（100Hz 关节） | 151/s | 14.1% |
| 全量五路（关节+力+夹爪+状态+阶段） | ~115/s | 14.0% |
| 只关节+夹爪 | ~62/s | 10.4% |
| 只订阅、tick 全关 | ~115/s | 13.7% ⇒ **开销全在 rclpy 逐条派发，与业务逻辑无关** |

⇒ Python rclpy ≈ **0.17% 单核 per msg/s**；`raw=True` 比非 raw 省 ~20%；
要真正守住 <8% 红线，Orin 侧采集节点应写 **C++/rclcpp**（同订阅量 ≈1~2%）。
⚠️ 诊断启发：订阅进程 CPU 只有 0.1% **不代表健康** —— 可能在等 HTTP 超时（实测现役采集器全量上报超时到 Mac 端点，那条流其实是死的）。

## 跨机两节点目标架构（老倪 2026-09-16 定）
- **Orin 节点**：传感采集 + **执行指令收口**（唯一允许动硬件处：阶段白名单 + 方向/幅值闸 + 限幅 + 超时回退产线原链）。
- **4060 节点**：跑模型推理，只发"意图/动作提案"，**不直接发布会动硬件的话题**。
- 硬约束：① domain 必须一致(0) ② **相机图像别走原始 DDS 过 LAN**（D405 彩图+深度会压垮共用交换机）——压缩/降频，
  或图像留 Orin 侧做感知只送状态/特征 ③ 执行永远在 Orin 收口（上层给意图、下层收口）。
- 落地顺序：Step1 跨机旁路（Orin 采集 → 4060 推理 → 回传**只记录不下发**）→ Step2 契约定型（状态/动作/心跳/超时）后加执行闸
  → Step3 真闭环 + 同口径 A/B（有提升才进默认档）。

## GUI 硬件工具箱真机链路（studio.py / hardware_simulator.py）
- **⚠️ PyQt 槽里未捕获异常 = qFatal 整个进程中止**：症状是"点一下按钮控制台就没了"——不弹错、journal 只有 `Consumed … CPU time`。
  实例：`_on_discovery_result` 对 `Z700_ROS2_NODES["real"]`（**是 list 不是 dict**）调 `.get()` → AttributeError。
  （旧账号错时发现必失败、永远走不到这行；账号修好下一秒就踩中。）
  **通用防御 = 渲染总闸**：槽拆成 `_on_xxx`（try/except 只记日志）+ `_render_xxx`（真逻辑）；`topLevelItem(i)` 一律判 None。
  取证：offscreen 直接调那个 handler 拿真 traceback，别翻 journal（可能什么都没有）。
- **塔灯旧实现只走 relay→Mac 守护** → Mac 不在线就静默失效（界面还写"指令已下发"）。改**直连优先**：
  `ssh tashan@.66 'export ROS_DOMAIN_ID=0; source /opt/ros/humble/setup.bash; ros2 topic pub --once /tower_light/command std_msgs/msg/String "{data: red}"'`
  + **回读 `/tower_light/status` 的 state** 验证（实测点🔴 state=red / 点🟢 state=green），relay 只作兜底。
- **"按钮反应慢" = 主线程跑 ssh**：实测塔灯命令阻塞 **5.48s**、夹爪 0.39s；100ms 的 `_refresh()` 只 0.1ms（无辜）。
  正解：阻塞体下子线程，结果经 `_oneshot(self, 0, lambda: apply(res))` 回主线程（与 `_cam_apply_later` 同模式），主线程绝不 ssh/HTTP。
- **一批老命令口径过期**：`ROS_DOMAIN_ID=23` + `~/0615/.../install/setup.bash` → 应为 domain 0 + `~/0810/*/install/setup.bash`（/opt/ros/humble 已够）。
  改前先 `ros2 service list -t | grep gripper` 确认服务在。

## 真机位姿真值 → 标注/训练同口径（2026-09-17 老倪: 记录光模块 xyz, 对齐 metaworld）
- **单一来源 = `tools/real_truth.py`**：读采集容器落盘的 `$SS_OUT/state_YYYYMMDD.jsonl` 最后一行
  (尾部 64KB 反向扫, 别整文件 load — 文件几百 MB) / `status.json` 兜底 → TCP/quat/关节/力 + 新鲜度。GUI 不引 rclpy。
- **metaworld 39D 段位 (权威 = `yolo_3d/yolo_state_aligner.py:317-328`)**：
  `[0:3]=hand` · `[4:7]=光模块(peg)` · `[7:11]=peg_quat` · `[18:21]=prev_hand` · `[22:25]=prev_peg` · `[36:39]=hole`。
  真机对齐规则：hand=TCP 真值；光模块=TCP+R(quat)·夹具偏移(**未标定填 null + 原因, 绝不编造**)；hole=示教 goal 点。
- **样本自带真值**：视频流窗口保存标注时把 `real_truth.snapshot()` 写进
  `annotations.jsonl.truth` + 侧车 `sessions/<会话>/truth.jsonl`；`--build` 聚合出 `dataset/truth.jsonl`
  (每行 stem/boxes/truth{TCP,quat,obs39_segments,dist})，与仿真 `data/yolo_peg` 的"真值投影标签"同口径。
- **要用仿真 YOLO 权重还得补两件**：①现场几何示教(`ss_geom_calib --record peg_head/goal`)→ 才有 z7/距孔口；
  ②相机 K + 手眼外参(`calib_real_cam.py`)→ 才能把真值投影成 2D 自动标注。缺任一项时相关字段一律 null+原因。
- 删样本/清会话必须同步 `truth.jsonl`（`delete_sample` / `clear_session` 已带），否则训练读到不存在的图。

## 仿↔真就绪度怎么查、怎么报（口径纪律）

```bash
P=gui-venv311/bin/python
$P tools/sim2real_readiness.py   # 上真机前 7 判据 (引擎闭环/DDS数据空间/画布渲染/Web桥/策略rollout/数据pipeline/真机只读)
$P tools/sim2real_preflight.py   # 仿真链路真跑 8 项 + 真机只读信号 + 在役服务; 全程零动作下发
```
两份落 `reports/sim2real_*_<ts>.json|md`，报进展直接引这两份文件当证据（比口头结论强）。

读数以 `config/robot/zmax_sim2real.json`（`sim2real_bridge.py` 生成）为准，逐字段带 `_src`/`_reason`：
`frames.engine_hand.real_fk_residual_mm`（手部同源残差）· `frames.control_tcp_offset_m`（产线 TCP 口径，
取它不取 URDF 名义值）· `scale_action.act_to_mps` · 以及 `T_base_cam`/`plane_z`/`cell_geometry.points`
—— 三者 `value=None` = **真机 3D 未闭环**，`_reason` 写明缺哪次现场标定（手眼拖位姿/量台面/示教几何）。

**铁律：代码通道等价 ≠ 标定正确。** 证据里「仿真/真机两条路径 3D 最大差 2.22e-16」证明的是**同一份反投影、
同一组参数结构**（口径同源），**不**证明真机几何准 —— 标定项还是 `None` 时，真机侧实际走的是 plane_z
光线回退/感知直给。报进度必须把「口径已同源」与「精度已达标」分两层说，别把口径等价讲成精度达标。

**自检判据会假红**：判据报 ❌ 时先读它自己的明细行再下结论 —— 实测「画布渲染 ❌」实为判据里写死的基线数
（88 节点/166 连线）与当前画布（86/169）对不上，而明细行自己写着「渲染正常」(节点全出，连线差 1 是既有去重行为)。
**判据基线过期 = 假红，不是回归**；报进展前先分辨，别把假红当事故报上去。

## 坑：长跑采集容器 DDS「假死」(2026-09-17 实测)
症状：`ss-remote-tap` 容器 Up 数小时、日志在刷、jsonl 在长，但**所有话题收包全是 0**
（`count_publishers` 也返回 0），而**新建一个容器订阅同一话题立刻 49.6Hz**。
根因：容器启动时系统时钟被 NTP 拨走（本机已知 8h 偏移）→ RTPS 发现/租约被打乱，participant 再不自愈。
判据（一条命令分真假）：`sudo docker logs --tail 3 <容器>` 看 `收包={'tcp': 0, ...}` 且**样本数一直在涨** = 假活。
修：`sudo docker restart <容器>`，25s 后日志应见 `收包={'tcp': ~250, 'joint': ~500, ...}`（tcp≈50Hz）。
⇒ 采集容器不要跟开机自启捆绑在同一次时钟跳变窗口里；跑前先 `tail state_*.jsonl` 确认 tcp 非空。

## 坑：标定写出路径 ≠ 采集器读取路径（示教完不生效）
`ss_geom_calib.py` 原默认写 `~/zmax_state_space/models/real_cell_geometry.json`，
而 `ss_remote_tap.py` 读的是 `$SS_OUT/real_cell_geometry.json`（容器内 `/out/..` → 宿主 `~/zmax_ss_remote/..`）
⇒ 示教完 tap 仍报「无示教几何, z7 拒算」。已修：工具改为 SS_GEOM_PATH 优先 → 有 SS_OUT 就跟随 → 才退回旧默认。
在容器里跑示教时务必带 `-v <宿主SS_OUT>:/out -e SS_OUT=/out`，`--show` 打印的「文件:」一行必须落在同一处再录点。

## 坑（都真踩过）
- **pkill/pgrep 自杀（含远程）**：`[x]` 方括号技巧**不够** —— 只要同一条命令行里别处出现明文进程名（后面还有 `python3 tools/xxx.py`），
  `pkill -f "[x]xx.py"` 仍会匹配到自己 → 杀本地 shell，甚至把**远程 ssh 会话**一起杀掉（表现为命令无输出 / exit -15）。
  正解：kill 与 start/measure **分成两条独立命令**，且 kill 那条里不得出现明文进程名。
- **`ssh host 'bash -lc "… echo （中文括号）…"'` 语法错**：双引号里的 `(` `)` 会被远端 bash 解析 → 提示文案别用括号。
- **scp 保留源文件名**：`scp a/ss_orin_shadow.py host:.../tools/` 落地是 `ss_orin_shadow.py`，启动脚本里写 `ss_shadow.py` → FileNotFoundError；传完 `mv`。
- 手动测试进程与常驻进程**同名节点**互相干扰 → 测前先 pkill，测完再走 daemon 拉起。
- `netplan apply` 会顺带弹一下 WiFi（改完记得 `nmcli connection up <原 SSID>`）；同一 LAN 上本机静态 IP 别设默认网关，否则打断上网/relay。

## 相机实时视频流（压缩推流给人看，2026-09-26 实测）

老倪要「把实时视频流发过来 + 视频流要压缩」时的现成配方：`tools/cam_live_stream.py --port 8791 --quality 70`。
两路合成一张看板（手臂相机 = Orin 来；笔记本内置相机 = 本机驱动），JPEG→MJPEG，绑 `0.0.0.0` 供手机/PC 同网直接开。
端点：`/`(看板) · `/arm.mjpg` · `/local.mjpg` · `/snapshot/arm.jpg` · `/stats`。

- **压缩口径实测**：手臂 640×480 帧 PNG 420KB → **JPEG q70 29KB（14.6x）**；笔记本原始 900KB → 38KB（23.4x）。
  推流端只发「最新帧」（订阅端 seq 落后就丢），不做队列/不积压 ⇒ 天生低延迟。
- **先量再压，别假设带宽是瓶颈**：用 `ros2 topic hz` + `ros2 topic bw` 量源头。实测 Orin 彩图
  **1.92Hz / 0.92MB 每帧 = 1.77MB/s**，只占千兆链路约 1.4% ⇒ 延迟瓶颈是**相机自身帧周期**，压缩救不了它。
  同理「上真机前先确认瓶颈在哪一环」比盲调参数值钱。
- **`ss_remote_tap.py` 故意按 1Hz 解码落盘**（raw 订阅 + 低频反序列化省 CPU）⇒ 落盘帧率约 0.5-1fps，
  比相机还低一截。要真实时必须绕开它直接订阅话题，别指望压它的产物。
- **Orin 只有 raw 图像话题**（无 `/compressed`）；`ros:humble-ros-base` 里既无 `image_transport` 也无 cv2（只有 numpy）。
  想在源头压得靠 Orin 侧只读 republish，属现场授权范围，别默认能做。
- 本机相机低延迟三件套：`CAP_PROP_FOURCC=MJPG` + `CAP_PROP_BUFFERSIZE=1` + 固定分辨率。
- **交付前先证帧不是黑帧**：读图算灰度 `std`，`std>5` 才算真图（黑帧 ≈ 0）；再用 `cv2.putText` 把源/尺寸/
  字节数/时间打在图上再发飞书——老倪会把画面当结果，画面自己要能自证。
- **实时面板必须标帧龄**：`/stats` 出 fps·每帧KB·压缩比·帧龄，MJPEG 每帧带 `X-Frame-Age-S` 头。
  没有帧龄的「实时」画面不可信，也无法判断延迟出在哪一段。

完整配方（代码形状/端点/测量口径/排查顺序）见 `references/camera-live-stream-mjpeg.md`。

## 相关
- `zmax-console`：studio.py/硬件页 VEH 编号与 UI 纪律。
- `linux-chinese-input`：新机中文输入法（GNOME 输入源要注册 libpinyin）。
- 状态空间工程旁路部署细节（打包清单/服务重启/验证）见 `references/ss-bypass-deploy.md`。
