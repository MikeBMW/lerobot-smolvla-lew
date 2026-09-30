# 实测记录：Orin(ss_edge) ↔ 4060(ss_bridge + venv infer) — 2026-09-16

一次性细节（契约字段、实测数字、文件/端口清单、闸门验证结果），供复现与排障对照。

## 1. 报文契约（std_msgs/String 装 JSON）
state（边缘 → 主机）:
```json
{"t":1789550065.04,"seq":1234,"src":"orin_edge",
 "joints":[6],"jvel":[6],"sp_norm":0.0,"gripper":1000.0,"ft":[6],
 "robot_state":"{...power_state/operation_state...}","prod_stage":"","scope":"readonly"}
```
- `jvel` 优先取话题自带 `velocity`，为空则用位置差分补（`dt = max(1e-4, t - prev_t)`）。
- `ft` 为六维力/力矩（WrenchStamped）；`gripper` 原样（现场实测恒 1000.0，疑为占位值，别当语义解释）。

action（主机 → 边缘）:
```json
{"t":...,"seq":...,"src":"host4060","mode":"shadow_only","stage":"<回带产线阶段>",
 "action":[6],"yaw":{"dz":..,"ok":..},"model_ms":0.45,"e2e_ms":1.13,
 "input_map":"placeholder_v0","note":"结果仅记录, 不下发"}
```

## 2. 实测数字（真机在线，产线栈同时在跑）
| 项 | 值 |
|---|---|
| Orin ↔ 4060 LAN RTT | 0.51ms（同 192.168.23.0/24） |
| DDS 跨机发现 | 两边 `ros2 node list` 同时见 `/ss_edge` 与 `/ss_bridge` |
| 上行 | 20Hz 稳定；桥 in=1140 / err=0 |
| 模型前向 | 4060 GPU 0.3~1.7ms（warm），首次 ~110ms（含 CUDA 预热） |
| 端到端 | 桥内中位 3.7ms；单帧报文 e2e_ms 1.13ms |
| 下行记录 | 提案 1340+ 条全部落 `action_*.jsonl`，`executed=False` |
| 产线影响 | `/robot/joint_states` 仍 49.8Hz，未被扰动 |
| CPU（Orin 单核） | 全量5路+20Hz 18.2% / MIN+20Hz 12.9% / MIN+10Hz 10.0%（只订阅 13.7%） |

## 3. 文件 / 端口 / 自启清单
| 组件 | 仓库文件 | 现场位置 | 自启 |
|---|---|---|---|
| 边缘采集+闸门 | `tools/ss_edge_node.py` | Orin `zmax_state_space/tools/ss_edge.py` | crontab `@reboot ... ss_edge_daemon.sh` |
| 主机 ROS 桥 | `tools/ss_bridge_node.py` | 容器内（挂载 `tools/` 到 `/work:ro`） | `ss-bridge.service` |
| 主机推理服务 | `tools/ss_local_infer_server.py` | 本机 venv，`127.0.0.1:8790` | `ss-local-infer.service` |
| 闸门判据注入器 | `tools/ss_gate_test_inject.py` | 容器内跑（只发 action 话题） | — |
| 判决汇总 | `tools/ss_gate_report.py` | 任意（读 gate jsonl） | — |
| systemd 单元 | `tools/systemd/*.service` | `/etc/systemd/system/` | `enable --now` |

启动 / 运行（关键命令，抄用）:
```bash
# 主机：两个服务
sudo install -m 644 tools/systemd/ss-local-infer.service tools/systemd/ss-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now ss-local-infer ss-bridge
# 主机：桥（手工等价写法，调试用）
sudo docker run --rm --name ss_bridge --network host -e ROS_DOMAIN_ID=0 \
  -v <repo>/tools:/work:ro ros:humble-ros-base \
  bash -lc "source /opt/ros/humble/setup.bash && python3 /work/ss_bridge_node.py"
# 边缘：起节点（注意 source ROS，且别和 pkill 写在同一条命令里）
ssh <edge> 'cd <base> && source /opt/ros/humble/setup.bash && setsid nohup \
  env ROS_DOMAIN_ID=0 python3 tools/ss_edge.py --rate 10 > ~/.<proj>/edge.log 2>&1 < /dev/null &'
# 边缘：闸门确定性测试（武装 + 仅在测试时注入参考速度）
#   SS_GATE_ARM=1 SS_GATE_REF_VEL=0.20,-0.15,0.10,0,0,0 python3 tools/ss_edge.py
#   然后主机侧在容器里跑注入器喂 6 类构造提案，再用 ss_gate_report.py 汇总
```
`ros:humble-ros-base` 镜像拉取约 5 分钟（1 次性）；容器 `--network host` 才能把 DDS 组播送到 LAN。

## 4. 闸门验证结果（真机落盘，逐用例命中）
| 注入用例 | 期望 | 实测 verdict |
|---|---|---|
| ok（方向一致、幅值合理、阶段在白名单） | 过闸 | `pass_no_exec` ×4 |
| dir_rev（取负） | 方向否决 | `veto_dir` ×4 |
| mag_big（×20） | 幅值否决 | `veto_mag` ×4 |
| stale（t 回溯 5s） | 超时否决 | `veto_stale` ×4 |
| stage_out（阶段=插入） | 阶段否决 | `veto_stage` ×4 |
| shape（动作只有 2 维） | 维度否决 | `veto_shape` ×3 |
| 真实提案（现场静止 + 测试参考） | 方向不符 | `veto_dir` 5897 条（cos=0.882 < 0.9）；未武装期 `disarmed` 1030 条 |
每条记录含 `verdict/detail/executed=False/real_jvel/prod_stage/armed`，可直接复核。

## 5. 现场事实（排障时先看）
- 产线栈本就跑在 **ROS_DOMAIN_ID=0**；`/motion/active_states` 空、关节速度范数恒 0 = **现场机械臂没在动**
  （这也是"边学边练闭环拿到的数据全是静止/IDLE"的上游原因）。
- 部署的采集器把状态 POST 到某台 Mac 端点：若该端点不在线，日志会是
  `URLError: <urlopen error timed out>` **且 CPU 极低**（在等超时）——"CPU 低"不代表设计好。
- 相机类话题（`/realsense/*`）发布者=0 时要先分清"设备层没插"还是"驱动层没起"：
  `lsusb` + `/dev/video*` + `ros2 topic info -v` 三件套对照，别急着改代码。
