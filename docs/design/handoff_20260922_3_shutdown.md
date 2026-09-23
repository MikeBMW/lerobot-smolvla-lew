# 交接：关机前状态 (2026-09-22 15:50) — 第三轮

老倪: 「先关机」。本文是**开机能安全恢复**所需的全部上下文（承接 `handoff_20260922_2_shutdown.md`）。

## 一、本轮已完成（可核验）

| # | 事项 | 证据 |
|---|---|---|
| 1 | **统一迭代 v5.12.1 已发布**（tag 已推，含飞书端并行成果） | commit `fde46a43` + tag `v5.12.1`；版本 6 处同步点 + VERSION.md |
| 2 | **机器人模型单一真源**（DOF/质量/惯量/限位/产线 TCP 反解） | `config/robot/zmax_robot_spec.json` · `tools/robot_spec_sync.py`；FK 与真机 tcp 差 **3.52mm** |
| 3 | **统一标定参数接口**（缺口诚实报） | `tools/zmax_params.py` + `config/calib/zmax_calib.json`（`--check` 有缺口返回码 1） |
| 4 | **仿真↔真机参数桥** | `config/robot/zmax_sim2real.json` · `tools/sim2real_bridge.py` |
| 5 | **LoRA 三层落地（自研引擎，免 peft）** | `tools/lora_inject.py`（5 条断言）· 合并 `tools/lora_merge_ckpt.py` |
| 6 | **L4 LoRA 同口径 A/B（200clips×3）** | `reports/lora_eval200_v6d9.json` / `..._v6lora.json`：MAE 0.03052→0.02859 = **−6.32%**，逐槽赢 **16/16** |
| 7 | **全系统联合训练编排** | `tools/joint_train_all.py`（实跑：L4 rc=0/128.4s · L3 rc=0/471.3s · L2 rc=0/53.6s · LLM rc=1 诚实缺） |
| 8 | **Sim-to-Real 六环闭环** | `tools/sim2real_loop.py`（归档 17/17 落地；硬链接被拒自动回退复制） |
| 9 | **本轮证据归档** | `~/zmax_data/full_system_20260922/`（114 文件 + MANIFEST(sha256) + MODELS.json） |
| 10 | 文档 · 技能 · 飞书 | `docs/design/full_system_dataclosedloop_20260922.md`（含 §5.2 判闸修正）· 技能 `mlops/zmax-full-system-loop` · 飞书两轮已推 |

## 二、关键事实（下次开机直接用）

### 参数/标定真源（一律读这个，禁硬编码）
```bash
R=/home/ubuntu/lerobot-smolvla-lew; cd $R; P=gui-venv311/bin/python
$P tools/robot_spec_sync.py            # 重新同步真机模型参数 (URDF+只读实测)
$P tools/zmax_params.py --check        # 标定就绪度 (缺口返回码 1)
$P tools/sim2real_bridge.py            # 仿↔真参数桥
```
当前：内参 K ✅ · 产线 TCP 反解 ✅ · 控制器负载 1.51kg ✅ ｜ **手眼 T_base_cam ❌ · plane_z ❌ · 示教几何 ❌（待现场人工动作）**

### LoRA（两条引擎，8GB 卡的结论）
- **L4 INTACT**：`ZMAX_LORA=1` 走 `INTACT-JEPA/train.py` 守卫钩子；实测 112 层 / 可训 4.41%。
- **L3 SmolVLA+LEW**：`--l3-lora-engine local`（默认）走自研引擎（`lerobot_train.py` 的 `ZMAX_LORA_LOCAL=1` 守卫）；
  256 层 / 可训 **0.4436%** / batch4 / 2.29s per step / 峰值 6.25GB / 0 OOM。
  **peft 路线在 8GB 卡四档全 OOM**（根因：peft 0.21 把适配器输入强制转 fp32，且 `autocast_adapter_dtype` 已被移除 ⇒ 配置关不掉）。
- 部署/评测前**必须合并**：`$P tools/lora_merge_ckpt.py --ckpt <lora.pt> --ref <起点.pt> --out <merged.pt>`。

### 判闸口径铁律（血泪）
1. **clips 数不同的 MAE 不可互比**（常数基线 60clips=0.07008 / 200clips=0.08303）；A/B 必须同 clips 同 seed 只换权重。
2. 逐轴 `|corr|` 才是 KPI-1；只看 MAE 会误判。
3. 小样本会造假象：60clips 时 p_dy 出现 −0.23~+0.25，200×3 后收敛 **+0.14~+0.30 全正** ⇒ dy 是**弱正相关但 <0.5**，不是"反向/无关"。

### 在役指针（**本轮一个都没动**）
- L4：`stable-wm-cache/checkpoints/intact_l4_current`（仍指 v6r11 系）
- YOLO：`models/yolo_peg_live.pt` 软链（仍指原 best.pt）
- 判闸逐轴 corr 仍未过 0.5 ⇒ **按纪律不切**；要过闸需改数据配方（episode 加模块/槽 y ±5~10mm 错位或加大 yaw 扰动）后重训。

## 三、下一步（按优先级）

1. **现场标定三项**（零运动人工动作即可）：手眼 `T_base_cam`（拖 10+ 位姿，`tools/board_handeye_solve.py`）· `plane_z`（量一次台面）· 示教几何（`tools/ss_geom_calib.py --record peg_head|goal|aoi`）→ 补完即通真机 3D（2D→3D 深度）。
2. **dy 数据配方**：`tools/intact_insert_dataset_v5.py` episode 生成加横向错位 → 采集 → `ana_l4_dy.py` 验收 → 续训。
3. **确认 v5.12.1 桌面包**：CI 在 GitHub 上跑（**不受本地关机影响**），产物页
   https://github.com/MikeBMW/lerobot-smolvla-lew/releases/tag/v5.12.1
   ⚠️ **落地哨兵 cron 在本地**（job `dad014a524d8`）⇒ 关机期间不会推飞书；开机后它或手动查该页即可。
4. **Console Docker 镜像 CI**：失败根因 = `Log in to Alibaba Cloud ACR`（阿里云 ACR 凭据缺失/失效），属既有基础设施问题，补 GitHub Secret 后可重跑。
5. 大模型层：Qwen2.5-VL-3B 权重本机未下全（0MB），要用需下载 + 与训练错峰显存（3B VL 约需 8GB）。
6. 真机 J5 力矩：上次已修（示教器回零 + 力矩传感器清零）；每次碰撞/急停/下电后需重标一次（3 秒）。

## 四、红线（本轮遵守情况）

- **真机零运动指令**：全程只读（ROS2 远程只读订阅 + 控制器只读回读）；未调 `/move*` · `/hmi/command` ·
  `/execute_external_task` · `/gripper_driver` · `/state_machine/*`。抓取/插拔类动作仍等现场确认。
- **不干扰生产**：训练只在空闲 GPU 跑（跑前查显存）；未 kill 非本会话进程；Orin 保持零自研零自启。
- **未标定项不编造**：一律 `null` + 原因，`--check` 缺口返回码 1；在役软链本轮一个未动。

## 五、关机影响

- **已优雅停止**（避免断电时写盘半行）：`ss-remote-tap` 容器（只读订阅）· `ss_yolo_on_real` ·
  `ss_bypass_run` · `auto_loop` · `box3d_live_box`。
  停止时刻真机只读落盘 `~/zmax_ss_remote/state_20260922.jsonl` 定格在 **15:48**（累计 **1.93 GB**，
  下次开机建议归档/轮转）。
- **仍在跑（关机自然停）**：`hermes gateway` · `ss_local_infer_server(8790)` · `l2_daemon` ·
  GUI `studio.py`。
- **@reboot 会自动拉起**（crontab 已备份到 `~/zmax_data/shutdown_20260922/crontab_backup.txt`）：
  `auto_loop`（采集链）· `l2_daemon_keepalive`（+ 每 5 分钟保活）· `hermes_cron_reclock` ·
  `disk_redline`（每 2 小时）。
- 训练/判闸/长任务：**本轮已全部结束**（无遗留进程）——下次若在日志里看到
  `DataLoader worker ... killed by signal: Terminated` 或 `exit code 143`，那是**主动停**不是崩溃。

## 六、开机核对清单

```bash
# 1) 版本与代码
cd /home/ubuntu/lerobot-smolvla-lew && git log --oneline -1 && git status --short | wc -l   # 期望 fde46a43 / 0
# 2) 参数与标定
gui-venv311/bin/python tools/zmax_params.py --check                                         # 缺口 3 项 (待现场)
# 3) 真机只读链路 (开机 1-2 分钟后)
systemctl is-active ss-remote-tap        # 或 sudo docker ps | grep ss-remote-tap
cat ~/zmax_ss_remote/status.json | head -20        # 看 recv.tcp 是否在涨、帧龄是否新鲜
ls -l ~/zmax_ss_remote/cam_rs.png                  # 帧龄 = 是否有实时画面
# 4) GPU / 磁盘
nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader
df -h / | tail -1                                  # 红线 300G, 当前 251G/396G
# 5) v5.12.1 桌面包是否已出
bash ~/.hermes/scripts/zmax_release_watch_5121.sh   # 有输出=已出包, 空=还没好
```
