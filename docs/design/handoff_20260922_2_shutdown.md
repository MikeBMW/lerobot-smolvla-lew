# 交接：关机前状态 (2026-09-22 09:0x) — 第二轮

老倪: 「保存数据，准备关机」。本文是**关机能安全恢复**所需的全部上下文（承接 `handoff_20260922_shutdown.md`）。

## 一、本轮已完成（可核验）

| # | 事项 | 证据 |
|---|---|---|
| 1 | **真机 J5 力矩超限当场修好**（不需要安全密码/厂家） | `docs/design/arm_j5_torque_FIX_20260922.md` · `rokae_sdk/torque_zero_0922_002605.json`(before/after) · `torque_stability_0922_002634.json`(10s 复读) |
| 2 | **视觉引导抓取技能 `L2.grasp_vision`**（判位双路 + 执行器内 fail-closed 视觉门） | `docs/design/vision_grasp_skill.md` · `evidence_20260922/vision_grasp_result.json` · `slot_occupy_evidence.png` · `test_vision_grasp_skill.log`(30/30) |
| 3 | **离线自检隐患修复**：`test_slot_skills.py` 运动步曾走真通道（能真下发机械臂） | `evidence_20260922/test_slot_skills_hardened.log`(79 ✅/0 ❌) |
| 4 | **L4 卡点定量归因：dy = 数据配方问题** | `docs/design/l4_dy_axis_attribution_20260922.md` · `evidence_20260922/ana_l4_dy.log` |
| 5 | **小版本迭代 v5.11.5 已发** | commit `1d7aa4eb` + tag `v5.11.5`；CI「Build Desktop (Windows .exe + macOS .app)」当时 in_progress |
| 6 | **真机只读 tap 数据归档** | `~/zmax_data/real_tap_20260922/`（22,572 行 · 39.4 min @ 9.55 Hz · 0 解析失败 · 硬链接同 inode 0 额外占用） |

## 二、关键事实（下次开机直接用）

### 真机 J5（已闭环，修法 3 秒）
```
根因 = 力矩传感器零点偏置（不是负载大）→ 修法 `calibrateForceSensor(all_axes=True, axis_index=0, ec)`
一次调用: J5 -22.0031 → +0.5449 Nm（RSC 门槛 22.000，余量 +21.35）· J1 +29.08 → -0.258（竖直轴应≈0）
         10s 复读极差 0.109/0.391 Nm 稳定；随后现场真实点动（L2.forward 50mm）无任何报警
脚本: ~/zmax_data/rokae_sdk/fix_torque_zero.py（--dry 只读）· probe_state_repair.py · probe_torque_stability.py
纪律: 每次碰撞/急停/下电后**重标一次**（3 秒）；标定前 setToolset 负载必须正确（现 1.51kg / cog[16.2,12.9,31.2]mm）
更正: v5.11.4 报告写「SDK 93 接口无任何力矩/碰撞力接口」是错的 —— 接口在 `Cobot_6`，权威清单看
      `xcoresdk_python/Release/linux/xCoreSDK_python/__init__.pyi`，别用 dir() 关键字筛
```

### 视觉引导抓取（技能已上线，**真发待确认**）
```
判位 = 双路独立证据一致才认: ①YOLO peg 框底心 ↔ 槽位手眼投影（Δx≤12px ∧ 框底-投影∈[-5,25]px）
                             ②模块竖直带「棱边能量」列剖面峰列归属（≤20px）
本程实测: slot2 有光模块（Δx=3.3px 峰距 0.0px）· slot1 空槽（43.1px / 46.4px）
执行 = 阶段1 槽正上方(+30mm) → 阶段2 下降到抓取位(禁下压) → 阶段3 合爪 force40 → 阶段4 抬升 50mm
视觉门在执行器内 fail-closed（占位点 slot_vision 解析不出/两路冲突/帧不新鲜 → 拒发）
调用: GUI 点「🎯 视觉引导抓取」（对话框开时实时读注册表, 不必重启界面）
      逐段更稳: echo '{"skill":"L2.grasp_vision","stages":[1,2]}' > ~/zmax_data/l2_cmd.fifo
      编排/零下发自检: gui-venv311/bin/python tools/vision_grasp_skill.py [--apply]
验收只看真值: 夹爪回执 curr_pos ≈185(夹住模块)/≈21(空爪) · 完事复判该槽应变空
⚠️ 若 slot2 那颗是**已插到位锁住**状态 → 走 L2.pull_module（松开→退15mm钩绿环→合爪30→退120mm），别直接夹
```

### L4 卡点（门闸逐轴）
```
KPI-1 要求逐轴 |corr|≥0.5；实测 p_dx 0.56~0.84 · p_dz 0.61~0.91 · p_grip 0.63~0.96
                            **p_dy -0.16~+0.31（唯一不过轴 ⇒ 门闸必然 veto）**
归因: dy 活跃帧仅 12%（dx 48%）、最优单维观测 R²=0.02~0.03 ⇒ **数据里横向纠偏行为缺失**
⇒ 修法 = **改数据配方**（episode 加模块/槽 y ±5~10mm 仓内错位 或 加大 yaw 扰动），改完先验收 p_dy≥0.5 再续训
   加轮次无用；真机两槽 y 间距 50mm，槽间转移天然带 dy
判闸跑法: CUDA_VISIBLE_DEVICES= INTACT_POLICY=<ckpt>/weights_epoch_1.pt \
          gui-venv311/bin/python tools/intact_replay_check_v4.py --skill on --clips 60 --repeats 1
   （无 GPU 自动回退 cpu；逐轴 pearson 已内置）
```

### 训练产物（本轮）
```
intact_goal_optical_insert_v6d6..d9_s3072 / weights_epoch_1.pt（各 84 MB, 1ep×1000 步, 2.0 it/s）
在役软链 intact_l4_current **仍未替换**（仍指 v6r11 ep2）
```

## 三、下一步（按优先级，未开工）

1. **抓取技能真发**（等老倪现场确认；建议先 `stages:[1,2]` 到位核对，再 `[3,4]`）
2. **改数据配方拉 p_dy**：`tools/intact_insert_dataset_v5.py` 的 episode 生成加横向错位 → 采集 → `ana_l4_dy.py` 验收 → 续训
3. L4 档补齐部件：挂 L3 SmolVLA(`outputs/train/smolvla_lew_sim/checkpoints/000300`) + 每帧 YOLO + 本地 Qwen-VL + 3D 视图标来源
4. URDF 驱动仿真（`config/robot/xms5_r800_w4g3b4c.urdf` 已入库）
5. YOLO 微调前置：episode 换近景/眼在手视角重渲染（模块现在只有 8px@640²）→ 再微调
6. Qwen-VL 微调（权重本机已有，见技能 `local-vlm-scene-understanding`）

## 四、红线（本轮遵守情况）

- **真机零运动指令**：本轮对真机的动作只有 `calibrateForceSensor`（传感器标定, 非运动）与只读探针；
  抓取技能只跑了 dry-run。**未发任何 move/jog/rt 指令**；产线相机只起只读订阅。
- 抓取/拔模块类动作一律**等老倪现场确认**后发（本程他明确: 「等我确认安全了再实际发送」）。
- 未碰 `/hmi/command` · `/execute_external_task` · `/state_machine/*`。

## 五、关机影响

- 已优雅停止：真机 ROS tap 容器（只读订阅）· `ss_yolo_on_real` · `ss_bypass_run` · `auto_loop` ·
  `box3d_live_box`；训练接力链在 **v6d9 完成后**停止（未启动 d10）。
- **训练链的退出是"主动停"不是崩溃**（下次看日志别误判）：后台进程以 **SIGTERM / exit 143** 结束，
  报错尾是 `RuntimeError: DataLoader worker (pid ...) is killed by signal: Terminated` ——
  那是我 kill 掉 d10 那轮的 dataloader 子进程造成的，属预期。
  停后核验：训练进程 0 · GPU 空闲 · **d1..d9 的 `weights_epoch_1.pt` 各 84,066,084 B 全在位** ·
  未完成的 `intact_goal_optical_insert_v6d10_s3072` 目录已清（不留没有权重的目录，免哨兵认坏权重）。
- 仍在跑（关机自然停）：`hermes gateway` · `ss_local_infer_server(8790)` · `l2_daemon`（cron @reboot + 5min keepalive 会拉起）·
  GUI `studio.py`（在跑，关机即关）。
- cron 播报任务（磁盘红线/链路巡检/L4 进度/INTACT 四任务…）随关机停，开机自动恢复。
- 磁盘根分区 312G/396G（余 65G，仍超 300G 红线，开机建议清一轮）。
