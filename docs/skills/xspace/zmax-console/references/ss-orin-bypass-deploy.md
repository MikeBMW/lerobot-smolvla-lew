# 状态空间工程 · Orin 端「旁路(影子)运行」部署 — 2026-09-16 实测

老倪: 「把状态空间工程，旁路运行部署到 orin 上」。旁路 = 与产线共存、**只读、不接管**。
(直连 Orin 局域网/免密/地址表见 orin-lan-direct-access 技能; 本篇只写工程部署与旁路运行。)

## 目标机现状 (Orin 192.168.23.66, 用户 tashan)
```
/home/tashan/zmax_state_space/
├── tools/  ss_infer_service.py(8767 推理服务) · ss_shadow.py(旁路运行器, 本轮新增)
│           state_space_sim_real.py(六层引擎) · state_space_sim.py · run_ss_once.py · ss_verify_orin.py
├── src/lerobot/{policies/left_right/state_space, manifold, memory, calibration}
├── models/ l4_mani_predictor_v5.pt · l4_yaw_head_grasp_dz_v2.pt · l4_align_map.json · lie_intent_map.json · intact_fiber_map.json
└── flows/state_space_obs.json
/home/tashan/.zmax/  orin_gateway.py(8765) · orin_shadow.py(ACT 影子, 旧) · orin_ss_collector.py(真机状态采集上报)
                     start_shadow.sh · start_ss_shadow.sh(旁路启动, 本轮新增) · ss_shadow_daemon.sh(幂等守护, 待授权)
```
- 引擎 `_load(name)` 按 `ZMAX_REPO_ROOT=/home/tashan/zmax_state_space` 定位六层模块 (缺省向上逐级探测)。
- SS 推理服务 = `ss_infer_service.py` 监听 **8767**: `GET /health` · `POST /infer/mani {state:[11]} → {action:[6],infer_ms}`
  · `POST /infer/yaw {obs:[12]} → {dz,ok,infer_ms}` (cuda, 两模型加载 ~166ms)。
- 重启 = 杀旧 python 进程 + `bash ss_start.sh` (幂等: 先查 8767 是否在听) — **换代码后必须重启服务才生效**。
- 目标机现有自启范式: `@reboot /home/tashan/zmax_state_space/ss_start.sh >> ss_start.log 2>&1`。

## 部署手法 (可回滚, 原地升级)
```bash
# 1) 本地打包 —— ⚠️ 本地引擎在 tools/gui/, Orin 侧在 tools/ 根 → 打包时改名
cp tools/gui/state_space_sim_real.py $B/tools/state_space_sim_real.py
cp src/lerobot/policies/left_right/state_space/*.py $B/src/lerobot/policies/left_right/state_space/
cp src/lerobot/{manifold,memory,calibration}/*.py   $B/src/lerobot/<pkg>/    # 引擎 L4 链会用到
cp models/l4_mani_predictor_v5.pt models/l4_yaw_head_grasp_dz_v2.pt models/*.json $B/models/
tar -czf ss_deploy_<date>.tar.gz -C $B .
# 2) 目标机: 全量备份 → 覆盖解包 (保留 Orin 侧非仓库脚本, 如 ss_infer_service.py/run_ss_once.py)
cp -a zmax_state_space zmax_state_space.bak-<date>     # 回滚 = 一条 mv
tar -xzf ss_deploy_<date>.tar.gz -C zmax_state_space
# 3) 重启 8767 并验证
kill <ss_infer_service pid>; bash ss_start.sh; curl -s localhost:8767/health
```
本轮结果: 引擎 3977 行 / 六层 7 模块 / 18 个 src 文件 / 包 3.7MB; /health online(cuda) + 两个 /infer 端点实测有数。

## 旁路运行器 ss_shadow.py 设计 (只读铁律)
- **只订阅**: `/real_joint_states`(6 关节+速度 ~100Hz) `/robot/force_torque`(六维力 ~50Hz) `/gripper_pos`
  `/robot_status`(String JSON: power/operation/error) `/motion/active_states`(产线状态机阶段)。
- **绝不发布控制、绝不调服务** (gripper_driver / robot_stop / motion / tower_light 一律不碰)。
  唯一下行 = 遥测 `/zmax_shadow/status`(1Hz, 命名空间隔离) + 本地 jsonl + relay 回传。
- 10Hz 采样 → 派生量: 关节速度 6 维 / 速度范数 / 夹爪 / |F| / |T| / 力突变(fdev) →
  **运动分类**(按引擎 `STAGE_V_CAP` 速度阈值口径: 静止/微动/运动中/力异常) + **产线阶段原样读**(不二次解释)。
- 每 5s: ① 真调本机 8767 两模型做**探针**(记 infer_ms/输出, 证明部署模型链路活着)
  ② 汇总 50 样本回传 relay `POST http://datadrive.world/api/relay/upload`
  `{"meta":{"source":"orin_shadow","type":"ss_shadow_report"},...}`
  (4060 端 `auto_loop.py` 已按 `source in ("orin_snapshot","orin_shadow")` 过滤, 不会被当训练数据消费)。
- 实测: 20s 采样 **184 帧 ≈ 9.2Hz**; 真机数据在流 (|F|=10.77N, 夹爪恒定 1000.0, 运动分类=静止);
  非 dry 运行 → relay 回传 6 批 × 50 样本成功。
- CLI: `--duration N`(自检) `--dry`(只本地落盘) —— dry 必须同时管住**定时回传**(本轮修过一次: 定时器忘了读 dry)。
- 退出竞态坑: 先 `rclpy.shutdown()` 再 join spin 线程, 最后才 `destroy_node()`;
  顺序反了会在 spin 线程抛 `handler.exception()`(看似崩溃, 其实是关闭竞态)。

## 旁路"只读"怎么取证
```bash
ros2 node info /ss_shadow    # Subscribers 只有那 5 个话题; Publishers 只有 /zmax_shadow/status + /rosout
ros2 topic info -v /gripper_pos | grep -A2 "node name"   # 确认自己不在控制类话题发布者里
ps -eo pid,etime,pcpu,args | grep [s]s_shadow            # CPU 应 <5%
```

## 诚实缺口 (写进代码注释与回传报文, 不编造)
- 引擎 obs 的**笛卡尔槽位**(x / _pc / goal)需要 TCP 位姿 → 依赖 FK + 现场几何标定, 本轮**未接**, 报文标 `pending`。
- 当前旁路 = 真机状态影子流 + 引擎口径运动分类 + 产线阶段对照 + 部署模型探针;
  **不是完整六层闭环影子**。要接实需现场布局参数, 或让 Orin 侧发 TCP 位姿话题。

## 授权边界 (重要)
`@reboot` 自启要写远端 `~/.zmax/ss_shadow_daemon.sh` + 改 Orin `crontab` — 属"改远端 dotfile/crontab",
**会触发审批; 审批超时 = 未授权 → 停下来问用户**(选项: 批准自启 / 只手动跑一次 / 只保留代码部署),
不要绕道重试或换等价命令。
