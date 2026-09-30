---
name: real-arm-motion-control
description: Use when 要对 Z-MAX 真机珞石臂下发运动(关节/末端自转/夹爪) — 解锁序列、闸门、取证口径。
version: 1.0.0
author: hermes-agent
license: proprietary
metadata:
  hermes:
    tags: [robot, rokae, ros2, safety, real-machine]
    related_skills: [orin-lan-direct-access, zmax-cicd, unattended-pipeline-supervision]
---

## 🚨 「原子技能又不好使了」先查这两个 (2026-09-28 现场, 各花 10 分钟定根因)

**① 技能被拒发 ≠ 技能坏了 —— 先看 VL 安全闸判什么。** 拒绝链的顺序是
`chan_send → 慢层(VL 裁决) → 快层(本地反射 5Hz)`; 任一层不安全即 **一律拒发(fail-closed)**。
读 `~/zmax_data/vl_safety_fast.json`(快层) 与 `~/zmax_data/vl_safety.json`(慢层):
`safe=False` 时 `why` 就是原因。日志里 `🛡 VL 安全闸(快层): **遮挡/糊化**` = 快层, 不是网络/相机驱动。

**② 快层判「遮挡/糊化」十有八九是**相机喂错了**, 不是真被挡。** 实测根因: 推流启动参数写死
`--local-dev 2 --local2-dev 0`, 而 `video2` 是笔记本相机的 **GREY(IR) 那一路**(无红外照明 ⇒
mean=6/median=0/96% 像素<20), 被当成「笔记本相机(全局视角)」⇒ 快层永远 unsafe ⇒ **所有运动技能全拒**。
判据: `v4l2-ctl -d /dev/videoN --list-formats-ext` 只有 `GREY 640x360` = IR 路; `MJPG` 才是彩色路。
⇒ **设备号按卡名+能力解析, 别写死索引**(重启后编号会变): `tools/cam_dev_resolve.py` → `LOCAL=<彩色>/LOCAL2=<MAXHUB>`;
`tools/boot_restore.sh local` 已改用它。换后实测快层 safe=True / 慢层 safe=True risk=low / 闸门放行。

**③ 调用方超时必须 ≥ 慢层单轮耗时。** `vl_safety_monitor` 单轮带 2x2 拼图实测 **137~168s**,
单轮上限默认曾是 150s ⇒ 每轮都落「未给出裁决」降级裁决, 现场看到莫名其妙的「从严当不安全」。
已改默认 300s(与 `l2_daemon.VL_INTENT_WAIT_S=300` 同口径)。改完记得重启 monitor 才生效。

**④ 「每次点击都要等 1~3 分钟」= 每次点击都在重跑慢层 —— 要允许「同一动作复用新鲜裁决」。**
`l2_daemon` 原口径是「等**本动作** seq 的裁决才放行」, 慢层一轮 45~190s(空 content 重试再 +55s)
⇒ 现场连点两下同一个「前进」也要等两轮, 老倪看到的就是「前进不好使」。
现口径(`_vl_reuse_ok`): 裁决 `intent_desc` 与本动作**逐字相同** + 裁决 ≤ `ZMAX_VL_REUSE_S`(默认 300s)
+ `safe=True` + `risk_level=low` ⇒ 直接进闸门, 不重跑慢层。
为什么不胿弱安全: 慢层回答的是「**这一类动作**在当前场景能不能做」; 场景**此刻**有没有人/遮挡
由快层(本地 5Hz · 0.1s)在**下发那一刻**实测——复用不越过快层, 手伸进来照样立刻拒发。
复用/重跑都要写日志(写明复用了几秒前哪条裁决), 事后能核。新动作(没判过的方向)首下仍需等一轮;
要当场免等只能开**现场授权**(`_vl_operator_auth`, 只越慢层, 快层永远生效, 带 TTL/次数/审计)。

## 🗣 下发反馈: 点一下必须知道「发出没有 / 为什么没动」(老倪 2026-09-28)

- **执行器侧**: 被拦时受理行要给 **哪一层闸 + 为什么**, 不许写「A 或 B(见日志)」
  (`l2_daemon._note_block/_block_msg`; 分类: 慢层·VL 判断 / 快层·本地反射 / 命令通道)。
- **界面侧**: 技能清单**不能死等回读**(安全裁决动辄十几~上百秒, 死等 8s 只会显示「未回读」)。
  口径: `send_nowait` 立即回「✓ 已下发」→ `_watch_reply` 后台轮询日志把回执/原因补打到**下面的终端**,
  并在下发前先打一行安全闸现状(快层/慢层 safe+age+原因)。同一份反馈同步进 studio 底部日志栏。
- 验证套路(**零运动**): 用 `{"skill": …, "dry": true}` 空跑规格 —— 执行器只算目标位姿不下发,
  真链路(FIFO→受理→回读→终端)整条走通。offscreen `QT_QPA_PLATFORM=offscreen` 直接起真对话框即可测。

# 真机珞石 XMS5-R800 臂 · 运动下发 (解锁序列 + 闸门 + 取证)

## When to Use (触发)
要给现场那台珞石臂(Orin ROS_DOMAIN_ID=0 上的 `/robot_driver`)下发真实运动；
或下发被拒、报 `-18 该操作不允许在机器人当前运行状态下执行` / `实时模式异常: 设置模式错误 … 网络连接错误` 时。

## 硬红线
- Orin 是生产设备：**零自研进程、零自启**；4060 侧只读订阅(Docker tap)。
- 只调用户点名的运动服务；**绝不动** `/execute_external_task`(real_mode=true)、`/hmi/command`、`/state_machine/*`。
- 一次只发一个单步；`operation_state=drag` 时**不下发**(人手可能扶着，会争抢)。

## 🧑🔧 现场人机协同闸门 (2026-09-19 老倪现场: 「每次机械臂的真实输出, 你都要事先请示, 我观察现场安全后, 再进行下一步」)
现场作业时**每条运动指令前必须逐条请示并拿到明确"可以"**，顺序:
1. **三查只读**: `power_state` / `operation_state` / `has_error` (+ `estop_detected` / `collision_detected`)。
   `drag` → 一律不发现场动作指令，请操作员在示教器**关拖动→切自动(idle)**(SDK 侧没有切模式 service)。
2. **确认产线流程已停**: Orin 上除 `robot_driver` 还有**产线 motion 节点**(日志 `[motion-4] 正在执行状态"抓取失败开爪"/"循环结束移动到过渡点"` + `tower_light` 亮灯)。
   它在跑抓取循环时会**抢控制** → 只在其停线窗口做动作，且请对方确认不会自启。
3. **现场安全确认** (操作员口头): 臂活动范围内无人/无遮挡 · 急停在手边 · 速度保持低倍率(驱动 `rt_speed_ratio=0.05`)。
4. **首条动作取最小可见步**: J6 相对 **+1°(0.017453 rad)** → TCP 弧长 ~0.42mm(半径 24.2mm)，比 30° 试探安全得多；
   前后各取 `/real_joint_states` + `/robot/tcp_pose`，算 Δ 与理论核对后再放大步长。
5. 历史报警信号: 控制器日志出现 `set_joint_position rt MoveJ failed ... error_reason=实时模式异常` 或
   `ROBOT_IDLE_TIMEOUT (wait_until_idle)` —— 前者=模式/拖动残留，后者=动作其实**跑了但驱动报超时**(不可凭 success=False 重发，
   会把 1° 叠成 2°)。

## 标定需要"机器人位姿变化", 不是"手移物体"
用「框 + 编码器 TCP 位姿」自监督解手眼的前提是**(框, TCP) 成对变化**:
- 相机**工装固定** + 模块被夹爪夹持 → 让机器人走 ≥10 个不同位姿 (拖动手动拖也算，但手动拖动时我不下发指令)
- 相机**装在腕上(eye-in-hand)** → 上面那套公式不成立，先只做数据核验、别拟合
→ 现场第一件事就是**问清相机装在哪 + 模块是否在夹爪里**。


## 🚨 事故: 点「回点技能」实际跑去 home — 老倪按急停 (2026-09-20 08:42) + 三处加固

**现象**: 点「进入金手指AOI检测区」后机械臂继续下降(实际是去 home, 比当时位姿低 ~375mm) → 操作员按下急停。
**根因(两层)**: ①目标点被做成**可编辑参数**, `l2_skill_dialog.py` 造下拉时 `findText(默认值)` 返回 −1 →
**不设 currentIndex → 静默停在第 0 项 `home`**(实测日志 `已下发 L2.goto_aoi_gold -> home`);
②下发层没有方向守卫, 日志只有 `已下发 X -> home`, 没有 Δ。

**加固(已验证, 全部无动作)**:
1. **示教点类技能一律锁点**: `registry.json` 里 `"point_locked": true` + `"point": "<点名>"`, `param` 留空
   (对话框显示"无参数, 直接开始") → 收到 `spec.point` 一律忽略并告警。**别再做成可编辑参数**。
2. **下发前算 Δ + 方向守卫**: daemon 每条运动必打
   `目标 <技能>: pos=(x,y,z) · Δ=(+0.0,+0.0,+100.0)mm ↑上升|↓下降|→平动`;
   技能可声明 `"guard": {"dz_down_limit_mm": 20}` → 向下超限**拒发**, 需 `spec.allow_down_mm` 显式确认。
   (架构口径: 上层只给意图, 执行由最下层收口 — 底层必须看得见 Δ 并有权否决)
3. `l2_skill_dialog`: 默认值不在候选里时**插入并选中**(不再静默 home), 下拉合并 `taught_points.json` 点名。
4. **流程铁律**: 真机运动前先 `{"skill":"...","dry":true}` 空跑核对目标与 Δ, 再按现场闸门逐条请示。

**现场恢复注意**: 急停后 Orin 侧 `/robot/tcp_pose`、`/robot_status` 会**停止发布**(topic 消失) →
daemon 全部运动技能安全拒绝("位姿缓存未就绪"); 恢复前不要下发任何运动。完整复盘:
`docs/INCIDENT-20260920-aoi-home-move.md`。

## 🎯 L2 原子技能 · 传授点库 · 回点技能 · DRY-RUN (2026-09-20 落地)

- **常驻执行器** `tools/l2_daemon.py` + FIFO `~/zmax_data/l2_cmd.fifo`(写一行 JSON 即下发, 延迟 <1s);
  注册表 `data/skills/l2_atomic/registry.json`(**热加载**, 改完不用重启 daemon);
  保活 = cron `~/.hermes/scripts/l2_daemon_keepalive.sh`(@reboot + 每 5min, 判据用 /proc 精确 argv)。
- **传授点库** `data/skills/l2_atomic/taught_points.json`(`data/` 不入库, 本机生效):
  存"能看清光模块的位姿"这类**现场示教绝对点**。录制工具 `tools/record_l2_point.py`:
  **只读订阅** `/robot/tcp_pose`(走本机 Docker tap 容器, `ROS_DOMAIN_ID=0`)采 6 帧 → 均值 + 极差;
  极差 >1e-4 m 判为"还在动" → **拒绝记录**(不写坏点位)。用法:
  `gui-venv311/bin/python tools/record_l2_point.py <点名> "说明"`
- **回点技能** = registry 里 `"ros": "line_abs"` + **`"quat": "taught"`** → 位置**和姿态**都回示教点。
  ⚠️ 不带 `quat:taught` 的 line_abs 老行为 = 位置用示教点、**姿态沿用当前**(既有 goto_point/home 即如此)
  —— 目标是"复现某个位姿/视角"就必须显式标 `quat:taught`, 否则朝向不会回到原样。
- **已录点**(2026-09-20 08:32:30 实测, 6 帧极差 pos 2.1e-7 m): `aoi_gold_view`
  pos=(0.4595548, 0.1486891, 0.6986801) · quat(xyzw)=(-0.7357474, 0.0114899, -0.6771243, -0.0068155)
  → 技能 `L2.goto_aoi_gold`「进入金手指AOI检测区」(被别的技能带走后一键回点)。
- **方向点动技能 (2026-09-20 老倪: 「前后平移→前进/后退, 左右平移→向左/向右」)**:
  `L2.forward`「前进」=+X · `L2.backward`「后退」=-X · `L2.left`「向左」=+Y · `L2.right`「向右」=-Y
  —— **距离只填正数, 方向由技能内定**(现场不用再填负号)。符号口径: +X=前 · +Y=左 · +Z=上。
  执行层轴向 `x_pos/x_neg/y_pos/y_neg` 一律取 abs; 日志方向标签自解释(`_dir_label`: →前进(+X) 等)。
  ⚠️ 坑(已修): 旧实现把方向放在 `sign` 字段下发, 而执行层**只读 d_mm 取绝对值** → 负步进实际
     往正方向走(`tools/aoi_gold_servo.py` 踩过; 离线测试台自己乘了 sign 所以没暴露)。
     **要反向就换技能名, 别再引入 sign 字段** —— 那条路执行层根本不认。
  定义源 `tools/register_jog_skills.py`(幂等) · 判据 `tools/test_slot_skills.py`「方向点动技能」段。
- **里萨如力控插入 (2026-09-20 老倪: "orin系统里有里萨如力控算法, 先送到插槽口, 再力控搜索插入")**:
  Orin 上**产线自带**两个力控原语(都在 `/robot_driver`, `/lissajous_force_search` 同时挂在 `/motion`):
  | 服务 | 类型 | 语义 |
  |---|---|---|
  | `/lissajous_force_search` | `interfaces/srv/LissajousForceSearch` | 笛卡尔力控 + 李萨如叠加搜索(找孔/找正) |
  | `/rokae_insertion_force_search` | `interfaces/srv/RokaeInsertionForceSearch` | 更上层: 搜索 + press_force 压入 + final_box 终检 |
  参数怎么找(别再猜): **产线状态机配置就是配方**, 只读抄即可 ——
  `resource/config/<项目>/state_machines/抓取放置/motion/尝试插入第一次.yaml`(还有第二次/插入完成)
  + 力值在 `state_machines/抓取放置/state_machine.yaml` 的 `fixture_insert_desired_force`
  (第一次 `[0,0,6,0,0,0]`=6N 沿工具 Z, 第二次 8N)。已抄成 L2 技能 `L2.lissa_insert`「里萨如力控插入」:
  沿工具 Z 退 60mm 到插槽口(`local_mm:[0,0,-60]`, 即产线 `PoseTranslateLocalOffset [0,0,-0.06]`) →
  直线推进到插入位 → 调 `/lissajous_force_search`(frame_type=3 工具系 · plane=0 XY · load 1.51kg ·
  K=[6000,6000,0,300,300,100] · vmax=[0.1,0.1,0.01,5,5,5] · 6N · 李萨如 6mm/3Hz+4mm/2Hz · 盒 ±10mm/8s ·
  以当前位姿为盒原点 · calibrate_force_sensor=true)。定义源 `tools/register_lissa_insert.py`。
  ⚠️ 前置: 力控搜索要先 `setToolset(tool1, wobj0)` —— 控制器侧**工具/工件坐标系不存在**时直接失败
     (`FORCE_CONTROL_CLEANUP_FAILED ... code=-50501 工具工件坐标系设置失败`, 2026-09-17 实测),
     而 SDK 侧只有 `tool_name/wobj_name`(start.launch.yaml) 没有建坐标系的接口 → 属产线侧设置。
     另: 工具负载/质心没标定好还会报 `#41447 力矩传感器与模型偏差较大`(拖动/力控都会受影响)。
  ⚠️ 服务步必须**同步看回执**(`_service_call`): success=False 的原因(如上面那条)只在 message 里,
     只看"已下发"会把失败当成功。
  服务类步的口径: 步骤 `{"op":"service","srv":...,"type":...,"args":{...}}` —— 本机不下发任何运动,
     力控全由驱动做; 回执 success=False → 中止剩余阶段且绝不重发。
- **多阶段技能 (2026-09-20 起, 老倪【一号位】需求: 分两阶段、全程不松爪)**:
  registry 技能带 `"steps": [ {...}, {...} ]` → `run_stages()` 逐阶段执行:
  每阶段 ①算目标(点位 pos + `dz_mm` base 竖直偏移 mm) ②守卫 ③下发 ④**用真值等到位**
  (`/robot/tcp_pose` 缓存, 容差 `tol_mm`, 须连续两次落进才认停稳) ⑤才进下一阶段。
  任一阶段被拒/未到位 → **中止剩余阶段且绝不重发**。阶段之间不碰夹爪 —— "全程不松爪"由
  定义里**没有 gripper 步骤**保证(执行层不自己发明动作)。
  技能级字段: `speed_max`(限速上限, 收口在执行层) · `guard{max_lin_mm, dz_down_limit_mm}`
  (阶段级 `guard` 可覆盖技能级) · `point_locked`+`point`(锁点) · `quat:"taught"`(回示教姿态)。
  ⚠️ 下发前会用**实时**位姿**复算 Δ 并复检一次守卫** —— 守卫看的是真实 Δ, 不是定义里的 dz
  (踩过: 从 +50mm 处再降 50mm 实际 Δz=-100mm, 只带 allow_down_mm=60 照样该拒)。
  ⚠️ **"等到位"的时间上限必须按距离算, 不能写死** (2026-09-20 21:09 现场打脸):
     驱动限速 `rt_speed_ratio=0.05` + `speed=30` 实测 ≈ **2.8mm/s**(≈0.093 mm/s 每单位 speed;
     155mm 走 56s)。448mm 斜线回位要走 ~160s, 而超时写死 60s → 60s 时臂还在半路(差 196.6mm)
     被判"未到位"而中止 —— **但已下发的指令不会撤回**, 臂自己走完停在"正上方"没落位,
     现场看起来就是"技能只走了一半"。现在 `_stage_timeout()` = `max(timeout_s, 15 + lin/eff*1.6)`
     (448mm@speed30 → 272s); `timeout_dynamic:false` 才用硬值(自检用)。
  ⚠️ 驱动自身 `wait_until_idle` **只等 30s** → 任何 >30s 的长转移跑完会让 `/robot_status` 带
     `error_code=ROBOT_IDLE_TIMEOUT, operation_state=moving, has_error=true`(动作其实已完成)。
     **别凭 success=False / has_error 就重发**; 练习时把转移距离压到 **200~300mm 内**最省事。
  ⚠️ **关键判定必须直读话题, 别信常驻状态流缓存** (2026-09-20 21:27 现场): 常驻状态流
     (`state_thread` 那条 ssh 流) 的位姿会**滞后整分钟级** → 算出的 Δ 是旧值、到位被误判
     (点二号位时 Δ 报 -87.9mm 其实是旧位姿, 且连判两轮"未到位"而臂正在走到位)。
     `_pose_direct()/_pose_best()` = 经 Docker tap `ros2 topic echo --once` 直读(只读);
     守卫的 Δ 与"等到位"都走它, 常驻缓存只兜底; 日志会打「当前位姿(来源 direct/cache)」。
  ⚠️ **拖到槽位后必须切自动(idle)**, 否则 SDK 下发一律被拒:
     `error_code=-18 setPowerState(false before automatic mode): 该操作不允许在机器人当前运行状态下执行`
     —— 现场表现就是"点了技能没反应"(2026-09-20 21:28 实测)。
  ⚠️ **改 l2_daemon.py 代码必须重启执行器**(kill 精确 pid → `bash ~/.hermes/scripts/l2_daemon_keepalive.sh`);
     只改注册表则热加载(实测 18 个技能)。旧单步技能(无 steps)路径不变。
  已建技能 `L2.slot1`「一号位」: `slot1` = 老倪抓持光模块那一刻的槽位位姿(6 帧极差 7e-7 m, 只读订阅)
     → 阶段1 竖直 +30mm 到"正上方" → 阶段2 竖直 -30mm 回槽位。
     几何依据(务必先算): 工具 X 轴 ≈ base +Z(偏 2.2°) ⇒ base Z 平移 = 纯竖直、不带旋转;
     不确认这条就不知道"正上方"是不是沿爪轴退让方向。
  离线自检(不连真机, 每槽位 15 项 + 全局 3 项): `python3 tools/test_slot_skills.py`(遍历所有 `L2.slot*`)
  新建/更新**任意**槽位技能: `python3 tools/register_slot_skill.py 二号位 slot2 L2.slot2`(幂等, 只加法)
  现场录新槽位点: `python3 tools/record_point_watch.py slot2 "说明" slot1 40 380`
     (盯真值: 距参考点 >40mm 且连续 5 帧极差 <0.5mm → 自动录 6 帧, 全程不下发; 老倪不用喊"到了")
  ⚠️ 注册表热加载有**一格延迟**的老坑 (2026-09-20 21:22 现场): 原实现只在主循环顶部重读注册表 →
     改完注册表后的**第一条**指令仍用旧表(新建的 L2.slot2 被判"未知技能", 第二条才认)。
     已改为**每条指令前重读**。改注册表后如果第一条报"未知技能", 就是踩了这个(现已修)。
  已建技能: `L2.slot1`「一号位」(slot1) · `L2.slot2`「二号位」(slot2, 槽距 ~50mm), 结构完全同构。
- **DRY-RUN 空跑(反复练习前必用)**: FIFO 写 `{"skill":"L2.goto_aoi_gold","dry":true}` → 只算目标 +
  打印将要下发的 `ros2 service call /move_line ...`, **不下发**(实测下发前后 TCP 位姿逐位不变)。
- 🔴 **FIFO 格式红线(2026-09-26 现场踩过, 后果严重)**: FIFO **只认一行 JSON**:
  `{"skill":"L2.forward","d_mm":10,"speed":11}`。
  - 写成纯文本 `L2.forward d_mm=10` → 被**静默判"无效指令"**: 臂纹丝不动、脚本照跑、终端零报错。
    曾因此把"没动"当"动了"对外汇报 → **每次下发后必须核对**:
    `grep -c '无效指令' ~/zmax_data/l2_daemon.log` 与 `grep '受理: 已下发' ...`(受理才算真下发)。
  - **方向 ID**: `L2.forward`(+X) / `L2.backward`(-X) / `L2.lift`(+Z) / `L2.lower`(-Z) /
    `L2.left`(+Y) / `L2.right`(-Y); `d_mm` min 5 max 300, 方向内定只填正数。
  - **不传 `speed` 会用默认 60**(≈5.6mm/s); 要 ~1mm/s 用 `speed:11`(实测 1.17mm/s)。
  - 批量循环时**别用 `pkill -f <脚本名>` 收尾** —— 自己的命令行含该字符串 → 自杀(曾 SIGTERM 掉整条命令)。
    改用 `for p in $(ps -eo pid,cmd | grep <名> | grep -v grep | awk '{print $1}'); do kill $p; done`。
- **取证口径**: 录点看"采样帧数 + 极差"; 回点看"目标 pose 与示教点逐位一致 + 动作前后 TCP 位姿对比"。
- 🔴 **录示教点必须用"页面同源"的真值源, 别用 Docker tap 只读订阅** (2026-09-30 录『侧面点1』):
  `tools/record_l2_point.py` 走本机 Docker tap 的 `/robot/tcp_pose`, **新订阅者常常收不到**,
  会话陈旧时还是**全 0** —— 极差闸挡不住全 0(它"稳定"得很) ⇒ 录下去就是坏点位。
  正解 `tools/record_point_sdk.py`: 读 `~/zmax_data/rokae_sdk/tcp_out/latest.json`(xcoreSDK endInRef,
  **与 8793 页面同一源**), 三重闸缺一不可 —— ① 帧龄 >2s 拒(采样器卡了) ② 位置范数 ≈0 拒(陈旧全 0)
  ③ pos 极差 >1e-4 m 拒(还在动); 写库前留痕 `reports/aoi_points/<点名>.history.jsonl` + `.bak` 备份。
  判据写进回执: `静止(pos 极差 ≤1e-4) · 帧龄 x.xs · 源=rokae_xcoresdk/endInRef`。
- **给 8793/station 加"回点"按钮的铁律** (2026-09-30 『🎯 侧面点1』):
  ① 页面**只送技能 id**, 目标点由 registry `point_locked`+`point` 锁死; ② 新按钮**不要新开通道** ——
  把回点逻辑抽成通用 `gotoTeachPoint(btn,state,skill,label,msgSel,human)`, 旧按钮改成它的薄封装;
  ③ 服务端 `tools/cam_live_stream.py` 的 `_CTL_ABS_SKILLS` **必须同步加技能 id**(白名单, 只加 id),
  漏加 = 按钮点了未识别/被拒; ④ 技能规格与 `L2.goto_gold_pt1` 保持一致: `line_abs` + `quat:"taught"`
  (位置+姿态都回示教点) + `point_locked` + `guard.dz_down_limit_mm`。
  ⚠️ `registry.json`/`taught_points.json` 落在 **.gitignore 的 `data/`** 里(= runtime state, 不入库)
  ⇒ 技能定义必须能用**幂等注册脚本**重建(`tools/register_surface_pt1_skill.py` 式), 点位副本入
  `reports/aoi_points/`。别只在 data/ 里手改, 那等于没存。
- **干跑验收一次要看到三行**(缺一行就是没通): `注册表热加载: N 个原子技能` →
  `目标 <技能>: pos=(...) · Δ=(...)mm →平动|上升|下降 · 位姿来源 direct` → `受理: DRY-RUN(未下发)`。
  另配套两态: `POST /ctl/move {arm:1}` 未授权必须 **403 denied**; `{arm:0}` 回 `演练(未下发)`。
- 🔴 **别用 `pkill -f '<脚本名> --port 8791'` 收尾** —— 自己的 bash 命令行里含同一字符串 ⇒ **自杀**
  (实测 exit -15, 服务与人一起死)。取 pid 用: `ps -eo pid,cmd | grep <名> | grep -v grep | awk '{print $1}'`。
- 回点同样要过上面的**现场协同闸门**(三查/拖动关闭/自动模式/伺服上电 + 逐条请示) —— daemon 不做闸门判断。

## 🕹 网页手动控制区 (2026-09-27, 老倪: 「手动控制机器人 X Y Z 平移 + A B C 绕轴旋转」)

页面 `/station` 上的点动按钮 → `tools/cam_live_stream.py` 的 `POST /ctl/move` → 写 L2 FIFO。
**四道闸门(缺一不下发)**: ①服务级 `--ctl-motion`(不加一律 dry) ②页面勾「授权真动」
③技能白名单(只 12 个点动技能; 点位/多阶段/夹爪一律拒) ④限幅+限流(平移 5~300mm、下降≤100、
旋转 1~30°、speed 1~30、真指令间隔 ≥1.5s, 防连点当摇杆)。

铁律:
- **速度是相对量, 默认 8 很慢**: 一次 10mm/5° 可能十几~几十秒才停; 停下前驱动会回
  `success=False / ROBOT_IDLE_TIMEOUT`(wait_until_idle 30s 超时) —— **那是超时标记, 不是动作失败**
  (实测动作真跑了)。⇒ 判完成**只看 TCP/operation_state 有没有变**, 绝**不凭 success=False 重发**
  (重发 = 叠加第二个动作)。手动控制页要明写这句。
- **网页按钮"点不动"先查连接名额, 别先怀疑按钮**: `ss -tnp | grep :<port>` 按 pid 数
  **ESTAB**(TIME-WAIT 不算) —— 到 6 就是 HTTP/1.1 的每 host:port 上限被占满, 点动的 POST
  全排在队里 ⇒ 表现就是"按钮灰着/点了没反应"。修法见技能 sim-real-scene-overlay
  (页面去 MJPEG 化 + 该页单独端口 + 按钮/请求超时兜底)。
- **GET 绝不可触发动作**(实测 `GET /ctl/move` → 404)：浏览器预取/爬虫/取证脚本都会 GET。
- **点击必须回执行器原始日志行**(可复制), 不留"已发送"这种自报；实现 = 记 `os.path.getsize(log)` 偏移,
  下发后只读偏移之后的新行(不靠时间戳解析), 最多等 ~9s。
- **验证先走 dry-run**: `{"skill":"L2.rot_c_pos","deg":5}`(不带 arm) → 应回 `dry=true` + 日志行。
  验证完看到 `受理: DRY-RUN(未下发)` 才算链路通 —— 不要用自己的手去测真动。
- 不要发明未验证的**软急停**按钮(`/robot_stop` 存在但本仓未验证过); 页面写明急停走示教器/物理急停。
- 状态显示不要用 `ssh ros2 topic echo --once` 轮询(单次 3~7s 顶不住 1.5s 轮询) →
  容器 `ros_tcp_cache.py` 同订 `/robot_status` 落 `robot_status.json`(20Hz), 宿主读文件(微秒)。

## 🔩 第 6 轴 (J6) 独立自转 · 手动控制台按钮 (2026-09-30 老倪)

需求: `/station` 手动控制台加「让 6 轴独立旋转」的按钮, 分**逆时针 / 顺时针**。

- **先判清「哪个轴」: 现有 A/B/C 转不到 J6。** 那三个走 `pose_rot`(绕**工具**轴旋转, TCP 不动)。
  由 URDF tool0→tool1 的固定位姿算: J6 轴在**工具系**的方向 = `R_off^T·[0,0,1]` = **(-0.6250, +0.0289, +0.7801)**,
  与工具 X / Y / Z 各差 **51.3° / 88.3° / 38.7°** ⇒ 想"只转第 6 轴"必须用**关节语义**, 不能拿工具轴凑。
- **通道: 别用关节通道。** `/target_relative_joint` 是**真关节增量**, 但实测动作后**伺服下电**
  (现场要反复上电, 老倪骂过) ⇒ 用**等效笛卡尔**: 绕 **J6 轴轴线**(法兰原点 + link6 的 z)旋转 θ,
  走 `/move_pose`(不掉电, 与 A/B/C 同一通道已验证)。新算子 `ros: "j6_rot"`
  (`l2_daemon.build_j6_rot` / `run_j6_rot`, 技能 `L2.j6_ccw` / `L2.j6_cw`)。
- **公式(只需 TCP 位姿, 与姿态无关的常数在 URDF 里)**:
  `a_tool = R_off^T·[0,0,1]` · `t_tool = R_off^T·t_off` · `a_base = R_tool·a_tool` ·
  `p_fl = p_tcp − R_tool·t_tool` · `p_new = p_fl + Rot(a_base,θ)·(p_tcp − p_fl)` · `q_new = q(a_base,θ) ⊗ q_tcp`
- ⚠️ **URDF 的 t_off 是 link6(法兰)系向量, 必须先换到工具系再乘 R_tool。** 直接当工具系用 ⇒
  位置差 **11mm/5°** 而**姿态逐位正确** —— 只有位置错, 极隐蔽(我踩过, 靠 FK 对拍才发现)。
- **离线自证(零运动)**: `python3 tools/test_j6_axis.py` → 等效目标 vs `FK(q, J6±θ)` 位置差 **6e-14 mm** ·
  姿态差 **1.7e-06°** ⇒ 公式确为纯 J6 自转。尺度: TCP 沿 **~24.2mm 半径**走小圆弧(1°≈0.42mm · 5°≈2.1mm · 10°≈4.2mm),
  竖直分量 ~±1mm(5°) —— **不是** A/B/C 那种"位置不动"(页面要写明, 否则现场会以为按钮坏了)。
- **方向口径**: `_ccw` = +J6 · `_cw` = −J6 (**由技能名内定**, 页面只填正数); 「逆时针」= 右手定则绕 J6 轴正向。
  ⚠️ **轴随姿态变**(实测当前 `a_base≈(0.61,−0.36,−0.71)`, 朝下偏 +X) ⇒ 与画面顺/逆的对应**必须用 1° 档现场试一次**
  (页面默认步进就是 1°)。
- **三处都要改, 缺一按钮就"未识别/被拒"**: ①`tools/register_j6_skills.py`(幂等注册, `guard.max_deg=90`; 2026-09-30 老倪「放开到 30°/90°」) 
  ②`cam_live_stream._CTL_SKILLS` → `"L2.j6_ccw": ("deg",1,90)` ③`tools/web/station.html`(`.rot2` 两按钮 + 独立步进档 `STEP_J6`,
  `move()` 里 `skill.indexOf('L2.j6_')===0` 用 STEP_J6)。**步进档别和 A/B/C 的 20° 共用** —— 20° 会被执行器守卫拒发,
  现场看到的是"点了没反应"(已踩过)。
- **验证口径(全程零运动, 四条都要过)**: ①`POST /ctl/move` 不带 `arm` → `dry=true` + 日志三行(目标 Δ / 姿态前后 / DRY-RUN)
  ②`arm:1` 未授权 → **HTTP 403**(服务端拦) ③**绕过页面**直接写 FIFO → 执行器「🛑 被拦(真动授权)」且 `grep -c 已下发` = 0
  ④页面点按钮 → 结果栏出执行器**原始行**(可复制)。
- ⚠️ **速度有两道限幅, 提速要同时改两处** (2026-09-30 老倪: 「转速太慢了，加速。别限制，我在现场，安全」):
  ① 服务端 `cam_live_stream._ctl_move` 里 `speed = max(1.0, min(<上限>, speed))` (原写死 60);
  ② 技能级 `registry.speed_max` (`plan_stage` 用 `sp = min(sp, speed_max)` 收口; **`run_rot_chunks`/`run_j6_rot` 不读它**)。
  现口径: 上限 **1000**(相对量), 页面档位 8/60/200/500 + 右侧可自填任意数 ⇒ 真正物理上限交给控制器关节限速。
  **实测基线: speed=60 → 腕部 10° 花 ~10s(≈1°/s)**; 线性实测 ≈0.0999mm/s 每单位 ⇒ 想快 N 倍就把 60 乘 N。
  零动作验收: 发一条不带 arm 的 `/ctl/move`(dry), 看执行器 DRY-RUN 行里的 `speed: <值>` 是否等于你填的值或上限。
- 📐 **单次角度上限 10 → 90** (2026-09-30 老倪: 「放开到 30°/90°」): 三处同口径 —— 守卫 `max_deg` / 白名单 `("deg",1,90)` /
  页面档 `1/5/10/30/90`。圆弧尺度实测(dry 算目标): 30° → `Δ=(-9.7,-6.1,-5.3)mm` 弧长 12.56mm;
  90° → `Δ=(+15.2,-20.2,+23.3)mm` 弧长 34.32mm —— **竖直分量 +23.3mm**, 因为 J6 轴此刻与竖直差得多, 大角度已不是"小圆弧"而是一次真实位移 ⇒ 让现场先看末端周围再点。
  验收样例: `deg=95` 必被白名单拒 `deg=95.0 超出允许范围 [1, 90]`(证明上限真生效, 不是只改界面)。
- ⚠️ **重启执行器的自伤坑**: `~/.hermes/scripts/l2_daemon_keepalive.sh` 内部是 `pkill -f "[l]2_daemon.py"` ——
  **同一条命令行里别出现字面量 `l2_daemon.py`**(例如 `python3 -m py_compile tools/l2_daemon.py`),
  否则自己的 shell 会被 SIGTERM 掉(实测 exit -15, 连带 keepalive 没跑完)。py_compile 单独发一条, 或把名字用变量拼。

## 🔴 现场空间红线: 上方横梁 + 台面标定板 (2026-09-26 老倪明确警告 + 2026-09-21 扎板事故)

**① 上方横梁 —— 抬升不得超 10cm**
老倪原话: 「你标定时不要上升太高, **不能超过10厘米**, 否则会撞到上边的横梁」。
⇒ 需要 Z 向抬升的动作(标定/演示)**上限 90mm**; 优先用【前后/左右】平移代替抬升。

**② 台面标定板 —— 离板只有 ~4.5mm, 禁止向下**
标定板**在手臂相机正前方**(老倪 2026-09-26 确认), 板面 **z≈0.2526**(2026-09-21 扎板事故实测值)。
臂的常用作业位 z≈0.2571 ⇒ **器械离板仅 ~4.5mm**。
⇒ **禁止任何向下 ≥5mm 的动作** —— `d_mm` 最小就是 **5** ⇒ 一个 `L2.lower` 就能撞板
   → J5 力矩越限 22Nm → **报警 + 伺服断电**(2026-09-21 已发生过一次, 是我造成的)。
⇒ 标定/取景只允许【上 / 前 / 后 / 左 / 右】(上 ≤90mm), 想"贴近看板"也只能靠**减小相机到板的姿态角**, 不能下降。

**③ 别把安全警示牌当标定板** (2026-09-26 我认错过)
现场有「禁止触摸」小白牌(安全标识)在**下方**, 与标定板**不是同一个位置**; 标定板在相机正前方。

**④ 标定板是手眼标定的天然靶标** ⇒ 不需要额外打印/贴靶
(但先要确认它的**图案类型**: 棋盘格 / 圆阵列 / ArUco —— 用 `cv2.findChessboardCorners` /
`findCirclesGrid`(对称+非对称) / `aruco.detectMarkers` 全族试一遍, 谁检出就是谁)。

## 🔴 `line_rel` 累积漂移 —— 长循环必须用绝对位姿(2026-09-26 实测)
**现象**: 前进/后退/抬升/下降 交替循环(每步 ±20mm、净位移应为 0)，同相位位置持续跑偏:
```
第1圈 forward  x=0.5614  →  第10圈 x=0.5548      = −6.6mm / 40 步 = −0.165mm/步
再跑一轮(共80步)  → x=0.5337                     = 累积 **−27.6mm(X) / +19.3mm(Z)** ✗
```
**根因**: `build_move()` 里 `line_rel` 的目标 = **真实当前位姿 + 偏移**；伺服到点即停(容差内)，
每步实际少走 ~0.16mm，下一步又以**实际落点**为基准 → 误差滚雪球。
**不是**舍入问题(`_pose_direct` 直读话题、全精度 float；日志里 4 位小数只是显示)。
**判据**: `grep '已下发 L2' l2_daemon.log` 里每步 Δ 都精确 ±20.0mm ✓，但 TCP 同相位位置逐圈单调跑偏 ✗
—— **“每步 Δ 对”不等于“总位姿不漂”**，两者必须分开取证。

**修复(零改 daemon)**: 换成绝对位姿 `line_abs` —— 路点算一次定死，每步到同一绝对点，误差不累积。
```
# ① 由当前 TCP 算 4 个绝对路点(上/后/下/前各20mm) → 写 taught_points.json
# ② registry.json 加 4 个 line_abs 技能: point_locked:true + point:<路点名> + guard.dz_down_limit_mm:30
#    (注册表**热加载**，不用重启 daemon)
# ③ DRY-RUN 逐个验证: {"skill":"L2.loop20_p1","speed":19,"dry":true} → 看日志"受理: DRY-RUN(未下发)"
# ④ 跑法: {"skill":"L2.loop20_p1","speed":19}
```
现成工具: `tools/make_abs_loop.py`(只读采样 + 写库 + 注册，`--dry` 可预览)
⚠️ **下行守卫**: `guard.dz_down_limit_mm` 守的是"相对当前位姿下降多少"，与命令下降 20mm 同值时不拦(严格 `-dz > limit` 才拦)，但**留 30mm 余量**更稳。

## 低帧率相机抓拍：不能直接取"最新帧"(2026-09-26 实测)
手臂相机 1.83Hz(0.54s/帧)。"每步后取最新帧"抓拍时，帧龄在 0.04~**0.81s** 波动(实测超相机周期)，
取到的可能是**运动/收尾相位**的画面 → 同位姿的两张图差异高达 12~27，且**非单调**(圈4-7 仅 1.6)。
**误判风险**: 容易把"取到运动中的帧"当成"位置漂移了"。
**区分法**: 漂移 = 单调递增；帧相位 = 非单调/随机。**照片对比不是干净的漂移判据，位置真值才是。**
**正确抓拍**: 运动停下后**等一个新鲜帧**(帧龄 < 0.2s 且位姿已稳定)再取；判据用 `/robot/tcp_pose` 首尾对比
(绝对位姿循环实测：40 步×20mm 走 800mm 回起点 **0.000mm**；相对位姿同条件漂移 **24.2mm**)。

## 🔴 多阶段技能不能设 `point_locked`（2026-09-26 现场踩过，臂"不动"）
现象: 技能 40 段（前→上→后→下×10）下发后**臂一动不动**，日志却显示每段都"✅ 到位 · 偏差 0.0mm"。
根因（`l2_daemon.py` `_point_name()`）:
```python
def _point_name(sk, st, spec):
    """链接: 技能级锁点(优先) > 阶段 to > ..."""
    if sk.get("point_locked") and sk.get("point"):
        return sk["point"]          # ← 把这个技能的所有阶段都锁到同一点
    return st.get("to") or ...
```
**规则**: `point_locked+point` 只给"所有阶段去同一个点"的技能（如 slot1）；
**多路点循环必须不写这两个键**，否则每段目标 = 技能级 point → 臂已在那个点 → Δ=0 → 看似"停住"。
**安全**: 这种 bug **不会乱动**（目标就是当前位置），只"不干活"，但会让你误报"在跑"。
**验证法**: 下发后立刻查 `已下发 阶段 N/40 ... Δ=(...)` 是否非零且 `点=` 在变化；
或先用 `spec.stages=[1,2,3,4]` + `dry:true` 空跑前 4 段确认目标各不相同。

## 录像/轮询的时长边界
长技能（40 段 ≈ 12 分钟）录制时: 单段耗时含**每次 docker 直读位姿 ~3-7s**，
总时长 ≈ 段数 × 17s（100mm@10mm/s 时），**不是** 距离/速度。按 距离/速度 估会短 30%+ → 视频缺尾段。
**正解（比估时长可靠）**: 录像上限设大（900s），循环里发现**日志出现末段到位**就 `kill -INT` 录像进程
（录制器已带 SIGTERM/SIGINT 处理 + `os._exit(0)`）→ 视频精确收尾、不多不短。
轮询判"完成"**不能 grep 全日志**（会匹配上一条运行的 `40/40` → 假完成提前退出）:
下发前记 `OFF=$(stat -c%s $LOG)`，之后只看 `tail -c +$((OFF+1)) $LOG` 的新行。

## 速度标定表（实测，speed=0.0999 mm/s 每单位，线性）
| speed | 实测 | 对应 |
|---|---|---|
| 19 | 1.90 mm/s | 2mm/s |
| 30 | 3.00 mm/s | 3mm/s |
| 50 | 4.97 mm/s | 5mm/s |
| 100 | 9.99 mm/s | 1cm/s |
需 mm/s 则 `speed = mm/s ÷ 0.0999`（daemon 自带注释写 0.093，偏 7%，以实测为准）。
技能级 `speed_max` 会封顶：要跑 speed=100 则 `speed_max` 必须 ≥100。

## 三条解锁闸门（缺一个必被拒，2026-09-18 现场实测）
1. **关闭拖动功能**（控制器残留的拖动状态会让切自动模式失败 → 控制器报警 `#10011 切换至自动模式失败 | repair: 停止运动/恢复急停/关闭拖动`）
2. **切自动模式**：`/robot_status` 的 `operation_state` 必须是 `idle`（`drag`=拖动示教，SDK 不能下发）
3. **伺服上电**：`power_state` 必须是 `on`（off 时 rt MoveJ 报「该操作不允许在当前上下电状态下执行」）
> 命令前一律只读三查：`power_state` / `operation_state` / `has_error`（外加 `estop_detected`、`collision_detected`）。

## 接口（运动类全是 service，没有 action）
| 服务 | 类型 | 语义 |
|---|---|---|
| `/target_relative_joint` | interfaces/srv/TargetJoint `{bool sim_mode, JointState joint_state}` | **相对关节运动**（6D 偏移量, rad）；单轴小步首选 |
| `/target_joint_state` | TargetJoint | 绝对关节目标 |
| `/move_joint` | TargetPose `{float32 speed, JointState, Pose}` | 绝对关节；内部会 setPowerState(false)→切自动→下发 |
| `/move_line` `/move_pose` `/joint_and_pose` | TargetPose | 笛卡尔 |
| `/move_sequence` | MoveSequence `{move_types[], poses[], joint_states[]}` | 多路点 |
| `/gripper_driver` | GripperSrv `{target_pos,speed,force,acc,push_length,push_speed}` (-1=保持) | 独立电动夹爪 |
| `/lissajous_force_search` `/rokae_insertion_force_search` | 力控/插装原语 | |
| `/robot_stop` `/rokae_recover_estop` | std_srvs/Trigger | 停 / 复位(无运动，可清 has_error) |

`joint_name` 必须用**驱动自己的名字**（实测 `XMS5-R800-W4G3B4C_joint_1..6`，param `joint_name`；写错会映射错轴）。

## 标准字节（J6 相对 +30°，已成功验证）
```bash
ssh tashan@192.168.23.66
source /opt/ros/humble/setup.bash
for ws in /home/tashan/0810/*/install/setup.bash; do [ -f "$ws" ] && source "$ws" && break; done
export ROS_DOMAIN_ID=0
ros2 service call /target_relative_joint interfaces/srv/TargetJoint \
 "{sim_mode: false, joint_state: {name: [XMS5-R800-W4G3B4C_joint_1, XMS5-R800-W4G3B4C_joint_2, XMS5-R800-W4G3B4C_joint_3, XMS5-R800-W4G3B4C_joint_4, XMS5-R800-W4G3B4C_joint_5, XMS5-R800-W4G3B4C_joint_6], position: [0.0, 0.0, 0.0, 0.0, 0.0, 0.5235987756]}}"
```
- 速度由驱动参数定：`rt_speed_ratio=0.05`(5%)、`final_joint_move_speed=0.1`、`move_timeout=30`
- 30° = 0.5235987756 rad；+ 号 = 右手定则绕该轴(与 FK 的轴方向一致，现场视角顺/逆由装配决定，下发前跟人对齐)
- 失败信息对照：`-18 + setMotionControlMode(RtCommand)` = 模式不对(drag)；`setPowerState(false before automatic mode)` = 同样被状态挡；`实时模式异常…网络连接错误` = 拖动残留/未就绪(查控制器日志)

## 上层「点了不动作」先查授权/演练开关, 别先怀疑链路 (2026-09-27 老倪提了两次)

页面/APP 上的方向键点了臂不动, **第一件事是看执行器日志里那行是 `已下发` 还是 `DRY-RUN(未下发)`**:
DRY-RUN = 上层只算了目标没真下发(演练/未授权), 链路本身可能是通的。诊断顺序:
1. 日志 `DRY-RUN` → 开关问题(页面的「授权真动」/`arm:0`), 不是 ROS/服务/机械臂的问题;
2. 日志 `已下发` 但 TCP 不动 → 才去查 `/move_line` 服务、`wait_until_idle`、报警;
## 🔐 «授权真动» —— 默认必须未授权, 闸门必须服务端强制 (2026-09-27 老倪定调: 「现场安全, 授权」)

上了一版「页面默认就是真动」(为了让“点了不动作”不再发生) → 老倪当场纠回: **现场安全优先, 默认必须未授权**。
两边都要满足的做法(已验证):
- **默认未授权**(读页面时永远是演绵/amber); 真动要**两步确认**: 点「🔓 授权真动」→ 再点一次
  「⚠️ 现场确认无人」(6s 内不作废) → 授权成立。**绝不写 localStorage/localStorage 记住授权**,
  刷新/换人/断网都是未授权。
- **授权有时限** 自动失效(默认 300s, `--ctl-auth-window`), 到期自动回未授权并提示; 撚销按钮永远在(撚销不需要授权=安全方向)。
- **只写前端开关是假闸门**: 服务端必须再拦一次(实测 `POST /ctl/move {"arm":1}` → **HTTP 403**
  `{"ok":false,"denied":true}`, 机械臂 TCP 一字不动); 授权/撚销都记 **IP+时刻到审计日志**(与动作日志同一时间线)。
  ⚠️ 自写 HTTP 服务要在发送处真发 `out["code"]` —— 只把 403 写进 JSON、状态码却发 200, 上层/监控看不到拒绝。
- **“未授权”不等于“点了没反应”**: 点方向键照样回一个结果 —— 「🧪 演练(未下发): 未授权真动(只算目标, 不下发)
  · 用时 x.xs」+ 执行器原始行 + 旁边一个**授权入口按钮**(不是“绕过闸门”按钮)。防呆与安全不矛盾。
- 未授权时把方向键调淡(`body.locked`, opacity .55)但仍可点 —— 视觉上就知“现在不会动”。

验证口径(缺一不可): ①未授权 arm=1 → 403 且 TCP 不变 ②页面两步授权 → armed=true+倒计时+IP
③授权后页面点一下 → TCP 真变(本次 +10.0mm) ④撤销后再点→403 ⑤离开时把臂退回原位, 并核对审计日志。

### 🔴 授权只活在“页面进程内存”里 = 假闸门 (2026-09-29 老倪:「我都取消授权了, 手臂怎么还在动」)
实测两条并存的真因, 只做"服务端 403"会漏掉后面两条:
1. **会动臂的路不止一条**: `grep -rl l2_cmd.fifo tools/` 实测 **18 个文件**会直接写执行器 FIFO
   (GUI 原子技能弹窗 / `back_to_slot1.sh` / `auto_insert.sh` / `aoi_gold_servo.py` / 视觉抓取 …)。
   只要授权状态只存在 8793 那个进程的内存里, 这些路径**完全绕开**它 ⇒ 用户以为的"闸门"不存在。
2. **执行器下发前不校验授权** ⇒ 点授权 → 命令排队等 VL 慢层(上限 300s) → 期间人点撤销 → 照样下发。
3. 已经下发给控制器的慢速动作(speed=8, 实测 30~90s 才到位)**不会因为点撤销就停** —— 用户看到的"还在动"就是它。

改法(已在 v5.16.27 落地, 可照搬):
- 授权状态**落文件做单一真源** `tools/ctl_auth.py` → `~/zmax_data/ctl_auth.json`
  (armed = until>now 到期自动失效 + **单调 epoch**: 每次授权/撤销都 +1)。页面与执行器共用同一份。
- 页面写 FIFO 的命令**带上签发时的 auth_epoch**; 执行器在**下发唯一收口**处校验:
  ①此刻必须有授权(不是"签发时有") ②命令 epoch 不旧于当前 epoch(撤销即作废)
  ③等慢层期间**每 2s 复核**, 一撤立即作废本条(日志写「⏹ 本条立即作废(未下发)」)。
  运动收口不止一处: 实测要同时堵 `chan_send`(运动) + `_service_call`(力控/服务步) + `_call_remote`(夹爪/力控)。
- **带外叫停在途动作**: 撤销只拦新命令, 落地的动作要靠主动停止 —— 机器人上 `/robot_stop`(`std_srvs/srv/Trigger`,
  实测回执 `success=True … stop: {'ec': 0, '操作成功完成'}`)。写一个小 systemd 常驻 `tools/ctl_revoke_stop.py`:
  轮询授权文件的 epoch, 一旦"epoch+1 且未授权"= 有人显式撤销 ⇒ 若近 180s 有真下发留痕
  (`~/zmax_data/l2_last_dispatch.json`, 由执行器每次过闸后写) ⇒ 立即调 `/robot_stop`, 全程审计。
  (授权**自然到期**不 bump epoch ⇒ 不叫停, 只记录。)
- `ctl_auth` 缺失时执行器 **fail-closed 一律拒发**(现场安全优先); 停/复位类白名单永不挡(闸门不许挡急停)。

取证要三条都跑(缺一条就会被现场当"没修"):
- 未授权 + `arm=1` 点技能按钮(如「回到金手指点1」) → HTTP 403 且执行器日志**零新增行**;
- **绕过网页**直接 `printf '{...}' > ~/zmax_data/l2_cmd.fifo` → 执行器回 「🛑 被拦(真动授权): … 拒发」;
- 授权 → 写真动命令 → 等它进入"等慢层" → 点撤销 → 日志 1s 内出现「⏹ 本条立即作废」且 `grep -c 已下发` = 0,
  同时看门人日志出现「⏹ 已在途停止 /robot_stop success」。



端到端取证口径(缺一不可): 动作前 TCP → POST 回执 + 受理时刻 → 动作后 TCP 差值 → 执行器原始日志三行。
反向走一次(把臂退回原位)是最省事的「页面按钮真的能用」证明。

## 取证纪律（每次动作都要）
1. 命令前：`/real_joint_states` 全 6 轴 + `/robot/tcp_pose`（Orin 的 header.stamp 比本机墙钟慢~26h，别当墙钟）
2. 命令后：同样两项 + `/robot_status`(power/operation/has_error/controller_error_logs)
3. 算差值并与理论核对：J6 +10° → TCP 只挪 ~4.2mm（绕 24.2mm 半径圆弧）；30° → ~12.5mm
4. 用 `tools/ss_fk_xms5.py` 复算 FK（URDF: `.../sr5_guangmokuai_100gAOI/robot/urdf/xms5_r800_w4g3b4c.urdf`）+ 姿态差分反算旋转轴，核对该轴 ≈ J6 轴
5. 留档到 `~/zmax_data/arm_*_<date>.md`（原始返回/前后真值/控制器日志）

## 「技能点了没反应」先查安全闸, 别查链路 (2026-09-27 实证)
- 现场问「一号位技能怎么没反应」时, 真因是 **守卫拒发**: daemon 日志
  `🛡 阶段 1/2 拒绝: 直线距离 562mm > 守卫 500mm` —— 技能注册表有、执行器活着、指令到了, 全链路正常。
- 诊断顺序(**全程只读, 别动机器人**): ① `pgrep -f tools/l2_daemon.py` ② 尾 `~/zmax_data/l2_daemon.log`
  ③ 算**当前位姿 vs 示教点**的差(实测 562mm 里主要是 +Y 541mm) ④ 最后才去看注册表/界面。
- **拒答必须指路**: 只说"太远/被拒绝", 现场就等于"没反应"。守卫分支要把**方向 + 各轴差量**报出来
  (`+Y 左移(朝槽位) 541mm · −Z 下降 149mm`) —— 注意报的是**该阶段目标**(如 slot1 +30mm 上方),
  所以 −Z 是 149mm 而不是到槽位点的 179mm; 别把"超出守卫 62mm"和"要走的 541mm"并列(会被误读)。
- 客户端回执机制: 技能对话框 = **写 FIFO `~/zmax_data/l2_cmd.fifo` + 回读 `~/zmax_data/l2_daemon.log` 里含 `受理:` 的行**
  ⇒ 改拒答文案会自动出现在界面上, 不用改 UI; 验收就发一次 FIFO 再回读(拒发类技能可放心测: 机械臂零动作)。
  改完 l2_daemon.py **必须重启执行器**(注册表是热加载, 代码不是)。
- 守卫 max_lin_mm(500mm) 是**故意的**: 技能只是"到槽位正上方/下降"的精细段, 不是长距离回位。
  要让臂靠近, 用点动(+Y/−Z)把臂移到目标附近再点技能 —— 别为了让技能能跑就放宽守卫。

## 已知坑
- **要"姿态旋转"时别用 `/target_relative_joint`，改用 `/move_pose`** (2026-09-21 实测):
  `/target_relative_joint`（rt 关节通道）**动作后驱动会把伺服下电**（老倪现场："怎么又下电了？我还没看清动作呢"）,
  需要人工反复上电 → 只适合单次验证过的标准字节。要连续走多个姿态(标定/示教)用 **`/move_pose`**
  (`interfaces/srv/TargetPose`, 与 `/move_line` 同族): 实测 `power_state` 一直 on。
  脚本: `tools/l2_pose_rot.py --axis z|x|y --deg N --send`（位置不动、只绕**工具自身轴**旋转姿态）。
  **注册技能路径 (2026-09-27 起, 网页/画布/技能库都走这条)**: 执行算子 `pose_rot`
  (`l2_daemon.build_pose_rot`, 数学与 `l2_pose_rot.py` 同源 `q_new = q_cur · q_axis(θ)`),
  技能 `L2.rot_{a,b,c}_{pos,neg}` 由 `tools/register_rot_skills.py` 注册
  (a=绕工具X·俯仰 b=绕工具Y·倾侧 c=绕工具Z·自转; 度数只填正数, 方向由技能内定; 单次 ≤`guard.max_deg`, 默认 10°)。
  判据: 日志必须打两行 —— `目标 L2.rot_*: Δ=(+0.0,+0.0,+0.0)mm`(位置必须不动)+
  `🔄 绕X/Y/Z(...) ±N°: 姿态 quat [..] → [..]`(姿态确实变了), 且 call 是 `/move_pose`。
  ⚠️ `pose_rot` **不能带 steps**(多阶段会把点位逻辑绕进去算错落点) → `plan_stage` 里已硬拒。
  ⚠️ 大角度会报 `ROBOT_IDLE_TIMEOUT`（假失败，动作已完成，按目标四元数比对即可；该标志在下一次成功动作后自动清）。
  单步 ≤10° 可避开。
- **绕轴旋转"点了没反应/转的角度不对"的三条现场实证 (2026-09-28)**:
  ① 页面角度档可以大于技能守卫 `max_deg`(现场档位 20° vs 守卫 10°) ⇒ 直接被拒。**拒绝文案必须写真因**
    (原先把这类拒发统一写成「位姿缓存未就绪」, 把人带到"位姿/通道坏了"的错误方向; 现场实测 5° 完全正常)。
  ② 要转更大角度就**分次**, 但分次必须**从"起转前姿态 q0"算绝对目标** `q_i = q0 ⊗ R轴(i·per)`,
    绝不能"每段重新读当前姿态再转一次": 腕部自转是慢动作(单段 10° 实测数十秒), 段间读到的还是
    **没动**的旧姿态 ⇒ 两段目标重合, 点 20° 实际只转 10°(实测日志两段目标四元数逐位相同)。
    相邻两次下发之间仍只差 `per ≤ max_deg` ⇒ 守卫意图不变。
  ③ **"没反应"先量真值再定性**: 腕部慢转要几十秒才落地, 页面只回"已下发"时用户必然判"坏了"。
    正确做法 = 下发后起后台线程按姿态真值回报「✅ 实测转过 X.X° (目标 Y°)」;
    定性判据 = 相邻两次"当前姿态"**逐位相同**即命令尚未落地(不是没发出去)。
    实操: 连点多次会把命令塞进控制器排队 ⇒ 看到的是滞后+串味的合成动作, 先停下等落地再判。
- **动臂前先看台面上有没有标定板/工装** (2026-09-21 事故，我造成的): 标定板留在台面(板面 z≈0.2526)时把臂往低处回,
  工具扎到板面(TCP 停 z=0.2296, 低 23mm) → 腕部 **J5 力矩 22.01Nm > 22Nm 限值 → 报警 + 伺服断电**。
  识别信号: 相机到板距离骤降(0.45m→0.364m) + 该关节力矩顶到限值 + `power_state: off`。
  恢复顺序: 人工清报警 → 手动拖到低载安全位(工具离台面远、腕部收拢) → 拿走标定板 → 切自动+上电。
  ~~另: 控制器 `tool_load` 全 0(末端质量/质心未设) → 动力学不带负载, 腕部力矩长期贴着限值。~~
  **2026-09-22 更正**: 用 SDK 直连读到 `toolset.load = {mass: 1.51 kg, cog: [16.2,12.9,31.2] mm}` +
  工具末端偏移 258.7mm (= URDF `tool0→tool1` 逐位一致) ⇒ **负载是设了的**, 之前"全 0"是读错了对象
  (`toolsInfo` 里 18 个 `g_tool_*` 大多是空壳, 别拿它当当前工具)。

### 🔬 腕部力矩"总超限"的定量诊断法 (2026-09-22, 全程只读, 一次问到底)

现场报「5 轴总超过限制扭矩」时, 别猜也别急着重发动作 —— 按下面三步拿数:

1. **读六轴力矩真值** (SDK 直连, 不经 Orin; `jointTorque` 有效, 而 Orin 的
   `/real_joint_states` **effort 全是 0**, 别指望它):
   `sudo docker run --rm --network host -v ~/zmax_data/rokae_sdk:/sdk -w /sdk ros:humble-ros-base python3 /sdk/probe_torque_alarm.py`
2. **用现场 URDF 算同一姿态的重力模型力矩** (`~/zmax_data/rokae_sdk/gravity_torque_check.py`,
   纯离线): 取 `<inertial>` 的 mass/com 逐个连杆算 τ_i = Σ[(p_cog−p_i)×m·g]·axis_i, 再把
   toolset 的负载也算进去。**FK 必须自校**(脚本算的末端 vs 控制器 `cartPosture` 差 ≤ 几 mm 才可信)。
3. **对照判读**: 残差 ≫ 模型值 ⇒ 传感器与模型不符(控制器 #41447 的定性), 不是"负载太大"。
   ⚠️ **竖直轴(本机 J1)的重力力矩在任何姿态恒为 0** —— 它若读数非 0(实测 +28.98 Nm), 物理上
   只可能是**传感器零点/外部持续力**, 是最快的一条判据: 上电后换 2~3 个差异大的姿态各读一次,
   读数不随姿态变 ⇒ 零点问题; 随姿态明显变 ⇒ 外部力(线缆/工装)。
   实测: J5 传感器 −21.96 Nm vs 重力模型 −2.03 Nm (11×), 现场报警线 22 Nm ⇒ 静态就占 99.8%,
   所以**任何动作都必然越线**(J3/J6 模型与实测吻合 → 说明不是"模型整体错")。

**修法 = SDK 一条调用就够: `calibrateForceSensor(all_axes=True, axis_index=0, ec)`**
(2026-09-22 实况修好 ✅ 一次调用: J5 −22.0031 → **+0.5449** (距 22.000 门槛余量 **21.35 Nm**) ·
J1 +29.08 → **−0.258** · 全部六轴与现场 URDF 重力模型量值吻合 · 10s 复读极差 0.39 Nm)
- ⚠️ **本节之前写的「SDK 没有关节力矩清零接口」是错的** —— `Cobot_6`(xMateRobot 的基类) 有
  `calibrateForceSensor`(力/力矩传感器标定, ~100ms 非阻塞) · `enableCollisionDetection(sensitivity[DoF],
  behaviour, fallback_compliance)`(灵敏度 0.01–2.0) · `disableCollisionDetection` · `enableDrag/disableDrag`。
  判接口存在与否: 读 `xcoresdk_python/Release/linux/xCoreSDK_python/__init__.pyi`(**权威**, 含逐接口中文文档),
  **别用 dir()+关键字筛** (会漏; `calibrateForceSensor` 就不含 torque/collision 关键字)。
- 官方口径 (docs.rokae.com 力矩控制页): *"通过 HMI 界面或者 SDK 的 `calibrateForceSensor` 接口执行力传感器标定;
  通过 SDK 控制机器人运动时建议程序中调用 `calibrateForceSensor`, 每次运动前标定一下"* ⇒ 标定是**常规操作**,
  任意静止姿态即可, **不需要安全密码, 也不需要先回机械零位**。
- 前置: ①`setToolset()` 负载必须正确(本机 `mass 1.51kg / cog [16.2,12.9,31.2]mm` 已设) ②机器人静止
  (先断言 `jointVel` 全 0) 且**末端无外力**(标定会把当前残余当零点, 有外力会标歪)。
- 顺序: 读 before → `calibrateForceSensor(True, 0, ec)`(看 `ec='0'/success`) → 等 3s → 读 after →
  **逐轴对照重力模型**(判据 J1≈0 · J5≈2Nm 量级) → 再 10s 复读看是否漂回(漂回 = 传感器/参数侧 → 转厂家)。
- 脚本: `~/zmax_data/rokae_sdk/fix_torque_zero.py`(加 `--dry` 只读) · `probe_torque_stability.py` ·
  `probe_state_repair.py` · `probe_torque_alarm.py` · `gravity_torque_check.py`
- 相关错误码(C# 手册): `-10005 标定中/标定时重置负载失败` · `-10040 开始拖动失败, 正确设置负载并标定力矩传感器`
  ⇒ 拖动打不开、力控飘、碰撞误报, 第一件事都是"设对负载 + 标定力矩传感器"。
- ❌ 别用 `setSoftLimit` 抬限值"绕过"(拆安全边界); ❌ 别常关 `disableCollisionDetection`;
  ❌ 静态读数贴限值(占 99.8%)时别让产线跑自动。
- 判据/取证: `~/zmax_data/arm_j5_torque_diagnosis_20260922.md` · `torque_zero_*.json` · `torque_stability_*.json`
- ⚠️ **每次碰撞/急停/断电后都要重标**: 力矩传感器零点丢失是这类事故的典型后遗症; 标定后立刻读六轴验证。
- **「原子技能 松开夹爪/其它技能 点了没反应」先查执行器通道，别改技能定义** (2026-09-21 实证):
  L2 常驻执行器 (`tools/l2_daemon.py`) 用**两条常驻 ssh 通道**(命令/状态)。没有存活检测时,
  开机竞态(网卡地址晚于自启服务)会让命令通道**建完即死** → 子进程变僵尸 `Z`, 之后每条下发
  都 `Broken pipe`, **所有技能**静默失效(不止夹爪), 而 keepalive 只判进程在不在 → 永不恢复。
  一步取证: `tail ~/zmax_data/l2_daemon.log` 见到 `执行异常: [Errno 32] Broken pipe` +
  `ps -o pid,stat --ppid <daemon_pid>` 里有 `Z`/defunct 的 ssh。
  已修(v5.11.4): 下发失败自动重建通道+重试一次、15s 看门狗自愈、启动前等链路+ssh 探针确认真能登录、
  keepalive 增设"通道健康"判据(通道死但日志在动=交给看门狗, 日志也卡死才重启)。
  "点了不动"的排查顺序: ①日志有无 Broken pipe ②`ros2 service list` —
  **只有 `/gripper_driver` 在 = 运动栈没起**(/move_line /move_joint /robot_stop 全无), 移动类技能必失败
  ③`ros2 service type /gripper_driver` 必须是 `interfaces/srv/GripperSrv`(对不上=调用类型错)。
- **服务"在图里"≠服务端活着 —— 必须实测一次调用能不能匹配** (2026-09-21 教训, 我因此误判过一次):
  `ros2 service list` / `service type` 走的是**图缓存**, 驱动进程死后名字和类型还能查到(幽灵条目)。
  判活的硬证据: 该驱动的**话题 publisher 数**(如 `/gripper_pos` Publisher count=0 → 夹爪驱动不在) +
  `ros2 node list` 里有没有该节点 + Orin 上有没有驱动进程; 最直接的是发一次带 `timeout` 的真调用,
  看它是"秒回回执"还是卡在 `waiting for service to become available...`。
  另: **服务调用一律带 `timeout N`**(夹爪 30s / 阶段运动 阶段超时+10 / 单步运动 90s) ——
  否则服务端缺席会把常驻命令通道永久卡死, 后面所有技能排队(2026-09-21 实况, 已修 v5.11.5)。
  客户端超时 ≠ 动作没下发: 判完成仍只看真值/回执, 绝不重发。
- **rt 动作结束后驱动会把伺服下电**（`power_state=off`）→ 下一次动作前要再上电一次
- 控制器报警历史在 `/tmp/tashan_robot_run.log` 的 `[robot_status]` 行里（含 repair 建议），是找根因最快的地方
- `collision_detection_enabled=false`（默认关）→ 多做动作前先开
- `tool_load` **不是**全 0 (2026-09-22 更正): SDK `toolset.load = {mass 1.51kg, cog [16.2,12.9,31.2]mm}`;
  报 #41447/拖动力学偏差时查的是**传感器零点**(先 `calibrateForceSensor`), 不是负载设没设
- 生产的"上下电/模式"是示教器侧操作；SDK 侧没有切模式的 service

## 已核验基线（2026-09-18 13:2x）
`/target_relative_joint` J6 +0.5235987756 rad → `success=True`，实测 ΔJ6 = +29.99975°（误差 4.4 µrad），
其余五轴 |Δ|≤0.0014°，TCP 走 12.71mm 圆弧（理论 12.53mm），姿态相对旋转 30.0027°，
旋转轴 (0.0907,0.2401,-0.9665) 与 FK 的 J6 轴夹角 0.180°。取证：`~/zmax_data/arm_j6_first_test_20260918.md`

## 夹爪 + 抓取验证 (现场实测 2026-09-19)

- `/gripper_driver` GripperSrv: 只改 `target_pos`(0~200, 0=全合, 与 /gripper_pos 同量纲 0~1000), 其余给 `-1`
- **一步 1000→0 可能静默 no-op**(回 490 不动) → 走**分步** 400 → 100 → 0
- `operation_state=drag` 时夹爪可能不执行 → 先回 `idle`
- **抓取成功判据(无需视觉)**: 空载合爪到 21; 夹住模块停在 ~311; **抬升 100mm 后仍 311** ⇒ 模块在指间 ✓
- 视觉验证缺口: 模块被抓时离镜头几厘米且被画面边缘切半 → 老权重 0 检出;
  **标注"抓在手中的半个模块"重新训练 → 同口径实机 16 帧 命中率 0.0→1.0 (conf 0.72)** 才换权重

### 补充 (同日实测, 重要)
- **夹持力**: srv 只回 `curr_pos`(开度), **没有力反馈**; `target_force=-1`(保持驱动默认)只能合到 250~311(偏松) ⇒
  **要夹牢必须显式给 `target_force`**: 实测 `target_pos=0 + target_force=40` → 开度 **185**(空载 21) = 夹紧 ✓
- **抓取验证判据**: 抬升 100mm 前后**开度不变(185→185)** ⇒ 未滑移 ✓; 若开度掉到 ~21 ⇒ 掉了 ✗
- 空载回程先**先退后放**(老倪现场纠正): 不在插入位直接下降 ✗

### 从演示学来的低位作业点, 回放必须留余量 (2026-09-19 实测)
- 回放演示点 grasp(z=0.10941) 时**到位误差 0.2µm**(精度完美) 但现场**触底碰撞** ✗ —— 因为演示点本身贴底, 且 `collision_detection_enabled=False`(撞了不停)。
- 定式: ① 低位点(z 最小那几个)**统一抬高 3~5mm** ② 下降分两级(先 z+5mm 停 2s) ③ 到位即停禁下压 ④ 回放全程人在旁。
- 技能 JSON 里加 `contact_guard` 字段固化这条, 别靠记忆。
