# 状态空间工程 → Orin 旁路部署（2026-09-16 实测逐条）

目标形态：代码与推理服务在 Orin 就地更新，另加一个**只读影子运行器**与产线共存。全程**不需要重启 Orin**
（部署是文件覆盖；服务是 kill+重启；影子是普通进程）——别为部署付"拉断产线栈"的代价。

## 1. 打包（本机做，小体积）
```
tools/state_space_sim_real.py        → 包内 tools/state_space_sim_real.py   （Orin 是 tools/ 平铺，不是 tools/gui/）
src/lerobot/policies/left_right/state_space/*.py （六层：perception/dynamics/cognition/parallel/safety/execution/planner）
src/lerobot/manifold/*.py · src/lerobot/memory/*.py · src/lerobot/calibration/*.py
models/l4_mani_predictor_v5.pt · l4_yaw_head_grasp_dz_v2.pt · l4_align_map.json · lie_intent_map.json · intact_fiber_map.json
flows/state_space_obs.json
```
实测三件套 tar.gz ≈ **3.7MB**。引擎的六层是靠 `_load()` + `ZMAX_REPO_ROOT` 动态加载的，所以目录布局必须对齐。

## 2. 就地覆盖（带备份，可一条 mv 回滚）
```bash
cp -a /home/tashan/zmax_state_space /home/tashan/zmax_state_space.bak-<date>   # 先备份(小芳那版)
cd /home/tashan/zmax_state_space && tar -xzf /tmp/<pkg>.tar.gz                  # 覆盖 tools/ src/ models/ flows/
```
⚠️ **必须原地覆盖而不是建新目录**：Orin 上有些脚本只在现场有（`tools/ss_infer_service.py`、`ss_verify_orin.py`、
`run_ss_once.py`、`ss_start.sh`），新建目录会把它们丢掉。

## 3. 推理服务重启 + 验证
```bash
pid=$(ps -eo pid,args | awk '/[s]s_infer_service\.py/ {print $1; exit}'); kill $pid
bash /home/tashan/zmax_state_space/ss_start.sh          # 幂等, 内部 setsid nohup + 端口自检
curl -s http://127.0.0.1:8767/health                    # {"online":true,"device":"cuda","models":[...],"load_ms":165.8}
curl -s -X POST http://127.0.0.1:8767/infer/mani -H 'Content-Type: application/json' -d '{"state":[0]*11}'   # → 6D action
curl -s -X POST http://127.0.0.1:8767/infer/yaw  -H 'Content-Type: application/json' -d '{"obs":[0]*12}'     # → dz/ok
```
注：`ss_start.sh` 自检可能打印"8767 未监听"（它 sleep 4 就查，模型加载 165ms~1s），**以 `ss -tlnp | grep 8767` 和 /health 为准**。

## 4. 影子运行器（只读）
`tools/ss_orin_shadow.py`（本仓库）→ Orin `zmax_state_space/tools/ss_shadow.py`（**scp 保留源名，记得 mv**）
+ `~/.zmax/start_ss_shadow.sh` + `~/.zmax/ss_shadow_daemon.sh`（幂等）+ `crontab @reboot sleep 25 && …daemon.sh`。
自检：`--duration 20 --dry`（15s≈75 帧、5Hz；dry=只落盘不回传）。常驻后看
`~/.zmax/ss_shadow.log` 的"📤 旁路汇总回传 relay #N"、`~/.zmax/ss_shadow/*.jsonl`、`ros2 node info /ss_shadow`。
CPU 旋钮：`SS_SHADOW_MIN=1`（只关节+夹爪）、`SS_SHADOW_NO_PROBE/UPLOAD/STATUS=1`（归因用）。

## 5. 交付时要报的实测项（缺一项就不算验收）
- 影子进程 pid/uptime + 采样帧数 + 真机数据在流（|F|≈10N、夹爪 1000.0、产线阶段字符串）
- relay 回传成功批数（source=orin_shadow）
- **只读证据**：`ros2 node info /ss_shadow` 的 Subscribers/Publishers 清单
- CPU 单核实测（自报 user+sys）与红线对比
- 诚实缺口：TCP 笛卡尔位姿未接 → 引擎 obs 的 `x/_pc/goal` 槽位待 FK + 现场几何标定（代码与回传报文都标 pending，别编造）

## 6. 回滚
```bash
pkill -f "[s]s_shadow";  # 先停影子(单独一条命令, 里面别出现明文进程名)
cd /home/tashan && rm -rf zmax_state_space && mv zmax_state_space.bak-<date> zmax_state_space
bash /home/tashan/zmax_state_space/ss_start.sh
```
