# 🧭 MoveIt plan-only → DDS `ss_plan` 镜像 (2026-09-29)

老倪: 「起 plan-only 的 move_group 容器，把 /plan_kinematic_path 返回的关节轨迹也镜像成 DDS 一条
（ss_plan），能在独立窗口里逐帧对。」

## 链路（每一级都是真跑，不留手写替代）
```
真机只读 tap  ~/zmax_ss_remote/state_*.jsonl   (jpos 6 关节 + tcp, 50Hz 真值, domain0 只读容器)
   │  tools/moveit_plan_req.py  (systemd: zmax-moveit-plan-req.service, 每 1s 刷新)
   ▼  ~/zmax_moveit_plan/plan_req.json     ← 真机当前 jpos/tcp + 目标(示教点 slot7)
容器 zmax-moveit (镜像 zmax-moveit:humble, ROS_DOMAIN_ID=42, allow_trajectory_execution=False)
   │  tools/moveit_plan_live.py (容器内常驻, 每 3s 一轮)
   │    ① IK(goal) → ② /plan_kinematic_path(真机关节角=起状态, RRTConnect) → ③ 逐路点 FK
   ▼  ~/zmax_moveit_plan/live_plan.jsonl   ← 逐轮追加一行(含 joints_path n×6 / tcp_path n×3 / 同源闸)
zmax-dds-ss.service (tools/dds/ss_daemon.py::pub_plan)  → DDS topic **zmax/ss_plan** (SSPlan, QoS state=latch)
   ▼  zmax-dataspaces-probe.service → /home/ubuntu/zmax_data/dataspace/{live.json,trace.jsonl}
控制台 数据空间页 / 独立「数据空间窗口」(🌐 按钮) 逐帧对
```

## 实测证据（本轮真跑，非估算）
| 项 | 实测值 |
|---|---|
| 容器就绪 | `You can start planning now!` (≈7s) · 服务含 MotionPlan/Kinematics/StateValidation |
| 逐轮规划 | 每 3.0s 一轮；**63–128 个关节路点**；终点误差 **1.08–4.76 mm**；轨迹时长 7.6–12.6s |
| DDS 载荷 | `joints_path` = n×6（实测 600 = 100×6）· `tcp_path` = n×3（300）· 每帧 ≈18KB |
| 第三方订阅实测 | 独立订阅者 10s 收到 **6 条**（≈0.6Hz，设计 0.5Hz）· frame_age **0.64s** |
| live.json | `hz=0.5 · count=19 · matched_pubs=1 · bytes=339440 · age=1.93s · verdict=ok · lamp=绿` |
| trace.jsonl | `ss_plan` 帧 **19** 条 |
| busdb (DBC) | 报文 **14 → 15**（`zmax/ss_plan` = `zmax::SSPlan`, hz_design 0.5, qos state） |
| 独立窗口 | Trace 里 `zmax/ss_plan` 行（Group=state · Tracking Id 逐帧递增） |
| 页面左树 | 「报文」树 `ss_plan` 排第 **5/15** 行（活跃在前，不用滚动即见）|
| 页面详情 | 选中它 → 「🧾 最近一帧摘要」一行给全：`n=123 · 时长 12.11s · 终点误差 2.967mm · FK起点差 261.351mm · 同源闸=0 · age 0.50s` |
| 命令行 | `python3 tools/ss_plan_show.py`（DDS 侧 hz/count/帧龄 + 规划侧 n/终点误差/时长 + 链路健康）|

## ⚠️ 同源闸（必须写在明面上，不许糊过去）
`gate_same_source = 0`：
```
FK(真机关节角) = [0.399, 0.288, 0.453]   真机 /robot/tcp_pose = [0.597, 0.143, 0.642]
⇒ 位置差 261.4 mm  ⇒ 不同源
```
原因 = 珞石 xCore SDK 报的 `joint_N` 零点/符号 ≠ CAD URDF 的零点（**不是图纸拿错**，URDF/meshes 都是从
产线工作空间拷的）。所以：
- 这条 `ss_plan` 是 **MoveIt 真算的轨迹**（服务真调、路点真在、FK 真算），但 **不是真机能执行的轨迹**；
- 独立窗口里它带 `gate_same_source=0` + 原因文字，**不许**把它当"真机轨迹"贴到真机画面上；
- 修法（下一步，尚未做）：采真机 50Hz `(关节角, TCP)` 配对 → 拟合 6 个关节零位偏移(+必要时基座变换)，
  复验 `FK < 5mm` 后 `gate_same_source` 才会自动翻 1（判据就是这么写的，不用改代码）。

## 复现/运维
```bash
bash tools/moveit_live_up.sh up      # 起: 容器 + 容器内规划器 + 宿主机请求器 + 重启守护/探针
bash tools/moveit_live_up.sh status  # 看: 容器/请求器/最近一条规划/规划器日志
bash tools/moveit_live_up.sh down    # 停: 规划器 + 请求器 + 容器
GOAL_POINT=金手指点1 PLAN_INTERVAL=2 bash tools/moveit_live_up.sh up   # 换目标点/改周期
```
改目标点后无需重启容器：`plan_req.json` 一变，容器内规划器下一轮就换目标（IK 只在目标变化时重算）。
