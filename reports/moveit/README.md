# reports/moveit/ — MoveIt「只规划」的现场取证与证据

老倪 2026-09-29: 「轨迹线，应该是状态空间工程里 moveit 节点规划出来，对不@xspace」
⇒ 架构上对（画布 `sslimit → sssk1..8 → n_moveit → ssact`），但**用之前必须过同源闸**。
本目录就是那次闸门的**原始证据**（不是结论截图，是可复算的 JSON）。

| 文件 | 是什么 | 怎么来的 |
|---|---|---|
| `real_state.json` | 真机**当前**状态：6 个关节角 + `/robot/tcp_pose`（base 系, xyzw）+ 实际生效的 QoS | `tools/moveit_real_state_probe.py` 在 **domain0 容器**（只读）抓 |
| `plan_slot7.json` | MoveIt 的 plan-only 产物：起/终点、127 个路点、`tcp_path`、终点误差、`plan_code` | `tools/moveit_plan_only.py` 在 `zmax-moveit`(domain42) 里跑；起状态=**真机关节角** |
| `same_source_check.json` | **决定性校验**：`FK(真关节)` vs 真 `/robot/tcp_pose` | `tools/moveit_same_source_check.py` |

## 结论（判据：位置 <5mm 且姿态 <2° 才算同源）
```
FK(真机关节角) = [0.39899, 0.28764, 0.45305]  姿态 (0.90345, -0.33428, 0.25806, -0.07372)
真 /robot/tcp_pose = [0.51268, 0.27060, 0.21822]  姿态 (-0.02314, 0.99795, -0.04317, -0.04113)
⇒ 位置差 261.5 mm · 姿态差 137.48° ⇒ **不同源**
```
⇒ **MoveIt 能规划（`plan_code=1`、127 路点、终点误差 4.55mm），但它现在出的不是真机轨迹**，
不能贴到真机画面上。差的是**关节零位/符号口径**（珞石 xCore SDK 报的 `joint_1..6` ≠ CAD URDF 的零点），
不是"图纸拿错"（URDF 就是从产线工作空间 `/sdk/urdf/xms5_r800_w4g3b4c.urdf` 拷的，meshes 也是从产线只读拷回）。
修法（下一步）：采真机 50Hz 的 `(关节角, TCP)` 配对，拟合 6 个关节零位偏移（+必要时基座变换），
复验 `FK < 5mm` 后才把 MoveIt 轨迹替换掉那条手画折线。

## 复算方式（两步，都在容器里跑，见技能 robot-grasp-path-planning/references/moveit-plan-only.md §2b）
```bash
# ① 真机状态(domain0, 只读)
sudo docker exec ss-remote-tap bash -lc 'source /opt/ros/humble/setup.bash && \
  python3 /repo/tools/moveit_real_state_probe.py --out /tmp/real_state.json --seconds 14'
sudo docker cp ss-remote-tap:/tmp/real_state.json reports/moveit/real_state.json
# ② 同源闸(zmax-moveit, domain42; 退出码 5 = 不同源)
sudo docker cp tools/moveit_same_source_check.py zmax-moveit:/ws/
sudo docker cp reports/moveit/real_state.json zmax-moveit:/ws/real_state.json
sudo docker exec zmax-moveit bash -lc 'mkdir -p /ws/out; source /opt/ros/humble/setup.bash && \
  python3 /ws/moveit_same_source_check.py --state /ws/real_state.json \
    --rename-prefix XMS5-R800-W4G3B4C_ --out /ws/out/same_source_check.json'
sudo docker cp zmax-moveit:/ws/out/same_source_check.json reports/moveit/same_source_check.json
```

安全：`plan_only.launch.py` 里 `allow_trajectory_execution: False` ⇒ 上述任何一步都**不可能**让真机动；
规划容器另起 `ROS_DOMAIN_ID=42`，与产线 domain0 隔离；真机状态是**只读订阅**。
