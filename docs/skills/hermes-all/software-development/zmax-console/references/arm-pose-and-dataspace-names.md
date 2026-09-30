# 臂位姿口径与数据空间里的名字 (显示/汇报必须与示教器一致)

**规则: 报/显臂位姿一律用「世界系 x y z (m) + a b c (度)」——不用四元数、不换欧拉序。**
用户对照的是示教器上的 x y z a b c; 他明确要求"你的输出要跟这个值一样"。

## 真源(位姿)
- `~/zmax_data/rokae_sdk/tcp_out/latest.json`(容器 `rokae_tcp_sampler`, `/sdk/tcp_direct_sampler.py`, ~5Hz)。
- 直连珞石 xCore SDK `CoordinateType.endInRef`(工具系在参考系 base_link), **不经 DDS/Orin** ⇒ 跨机链断了它照样有值, 位姿不因此串台。
- 字段: `x,y,z`(m) · `rx,ry,rz`(即 **a,b,c**, rad, SDK 原生 `p6[3:5]`) · `qx,qy,qz,qw`(派生) · `joint[6]` · `frame` · `src`。
- 同口径产线话题 `/robot/tcp_pose`(PoseStamped, BEST_EFFORT, 只给四元数)。要 abc 就用 SDK 那份。

## 关键: abc 原生, 四元数派生
- 采样器读 SDK 原生 `p6[3:5]`(示教器显示的就是这三个数), 四元数由脚本 euler→quat 推出。
- **页面/接口透传原生 `rx,ry,rz`**(页面给度); 反算只用于核对。
- 核对(与原生差应 ≤1e-6 rad): 合成序 **ZYX**, `R = Rz(rz)·Ry(ry)·Rx(rx)`; 等价: 角名按轴 X→Y→Z, 分解 = yaw(rz)/pitch(ry)/roll(rx)。
- 对不上时排查顺序: ① 是否从四元数反算 ② 是否用了 XYZ 合成序 ③ 帧龄。

## 数据空间里搜什么名字
- `ss_plan` / `zmax/ss_plan`(`zmax::SSPlan`)= **MoveIt 规划输出**(由 `zmax_dds_ss_daemon` 镜像 `~/zmax_moveit_plan/live_plan.jsonl`): `joints_path(n×6)`/`tcp_path(n×3)`/`plan_code`/`n_points`/`end_err_mm`/`gate_same_source`。
- `ss_action` / `zmax/ss_action`(`zmax::SSAction`)= 状态空间引擎自己的动作, **不是** MoveIt 的。
- 搜 `moveit` 会同时命中报文与画布节点(「🧭 MoveIt 运动规划 · SDK 直驱桥(Orin)」)与连线, 适合不确定名字时先用它定位。
- MoveIt 链起停/体检: `tools/moveit_live_up.sh up|down|status`(容器 `zmax-moveit`, plan-only, `allow_trajectory_execution=False`)。**MoveIt 侧只有四元数, 没有 abc** ⇒ 别拿 `goal_quat` 反算当"真机位姿"。
- 一个搜索/筛选控件只能有一个写手: 拉起脚本自己又起了一个 `moveit_plan_req.py` 时会有两个进程写同一份 `plan_req.json`, 保留 systemd 管的那个(用 `systemctl show -p MainPID` 认)。
