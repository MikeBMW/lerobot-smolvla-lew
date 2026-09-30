# 交接：关机前状态 (2026-09-22 08:15)

老倪: 「保存数据, 准备关机」。本文是**关机能安全恢复**所需的全部上下文。

## 一、本轮已完成 (可核验)

| # | 事项 | 证据 |
|---|---|---|
| 1 | **数据已保存入库** | 真机 J5 取证 + 厂家问题单 + URDF + 只读探针 → `docs/design/` · `config/robot/` · `tools/rokae/`；真机 tap 数据 2.7GB 归档 `~/zmax_data/real_tap_20260921`(硬链接) |
| 2 | **小版本迭代 v5.11.4 已发 Windows/macOS** | tag v5.11.4 → CI 双平台 success；产物独立核验: `Z-MAX_Console.exe` 156.7MB(头 `4d5a`=MZ) · `Z-MAX_Console-macOS.zip` 122.7MB(头 `504b`=PK)，HTTP 206 可真下载 |
| 3 | **模型节点 ↔ 加载代码 ↔ 权重 对照表** | `docs/design/space_model_nodes_load_map.md` (14 个模型节点两段式: 定义处 + 实际 load 点; 权重逐条在盘核实) |
| 4 | **L4 运行时证据矩阵** | `docs/design/l4_runtime_evidence_matrix_20260922.md` (逐函数计数; 只认运行时, 不认"画布上有连线") |
| 5 | **修掉 L4 口径 bug** | `docs/design/l4_stats_caliber_fix_20260922.md` — 反归一化统计原来读 `zmax_action_stats.json`(源 zmax_insert.h5)，与 v5/v6 权重都不同源(幅度差 2 倍)；现改为按 ckpt 训练集自动同源 |
| 6 | **L4 卡点定量归因 + KPI** | 同文档: 逐轴 corr dx .37 / dy -.26 / dz -.35 / gripper .67 → L2 收口闸 veto_dir 200/200 → 模型动作未进 env；工具 `tools/fit_intact_action_frame.py` |

## 二、关键事实（下次开机直接接着用）

### L4 真实状态 (运行时计数, seed=0, 200 步)
```
真跑了: IntactNode.step 200/200 · IntactIntentService.run_once 200/200 · decode 200/200
        build_skill_ctx 200/200 (L2 原子技能上下文逐帧构造) · u_ff 先验可用: "intact(chunk×K_ACT=0.5)"
没跑:   SmolVLA/DiT action_head.py 全 0 (L4 档未挂 L3) · YOLO 未开(vision) · 本地 Qwen-VL 未入链
被拒:   L2 收口闸 veto_dir 200/200 (模型 xyz 与教师弱相关/反相) · sim._direct_act=False (模型动作未进 env)
⇒ env 执行的是参考(解析)链; 模型每帧在算, 但输出不被采纳 = **模型能力问题, 不是接线问题**
```

### 反归一化口径纪律 (新, 会反复踩)
```bash
# 权重 → 训练集 → 统计, 三者必须同源; 用 resolve_stats() 自动解析 (会打印理由)
#   在役 intact_l4_current/weights.pt → intact_goal_optical_insert_v6r11_s3072 → optical_insert_v5_disturb.h5
#   → reports/optical_insert_v5_action_stats.json
#   本轮新训 v6d5 → optical_insert_v6_disturb.h5 → reports/optical_insert_v6_action_stats.json
# ★ 坑: intact_l4_current 是「目录 + weights.pt 软链」形态, 不跟随软链读不到 train_config.yaml
```

### 优化 KPI (代替"感觉好点没有")
```
KPI-1 逐轴 |corr|(dx/dy/dz) ≥0.5   (现状 .37/.26/.35)   → 闸才会按 cos 融合
KPI-2 闸采纳率 blend/总步 > 0      (现状 0/200)
KPI-3 sim._direct_act = True       (模型动作真进 env)
KPI-4 仿真插入成功 + 3D 视图可见"插拔成功"
测量: tools/fit_intact_action_frame.py <steps> <seed>   (换权重必同 seed 重测)
```

## 三、下一步 (按优先级, 未开工)

1. **训练侧拉 KPI-1**: 用 v6 数据(4.1GB/1743 回合/87150 帧)续训 INTACT，每轮测一次 corr；参考 `tools/v6_newdata_chain.sh`(1ep×1000步/轮, 从在役权重续, 记忆通道不零化)。
2. **L4 档补齐部件**: 挂 L3 SmolVLA(ckpt `outputs/train/smolvla_lew_sim/checkpoints/000300`) + 开 YOLO 每帧 + 本地 Qwen2.5-VL-3B 场景理解 + 3D 视图标"来源: 真实模型/解析链"。
3. **URDF 驱动仿真**: 现场 URDF 已入库 `config/robot/xms5_r800_w4g3b4c.urdf`(含连杆质量/质心/额定力矩) → 建真实几何仿真。
4. **YOLO 微调前置**: episode 相机是工作台全景(模块仅 7.2~8.6px@640²) → 先加**近景/眼在手相机重渲染**(对齐 cam_rs 口径), 再微调。
5. **Qwen-VL 微调**: 权重本机已有(HF 缓存 Qwen2.5-VL-3B-Instruct)；接法见 skills `local-vlm-scene-understanding`。

## 四、红线与待办（真机）

- **真机 J5 力矩未闭环**: 静止 J5 ≈ -21.93 Nm vs RSC 限值 22.000000(差 0.02~0.07) → 一动就报 #30400/#13036；硬重启无效；SDK 无关节力矩清零接口 → **必须厂家/安全密码介入**（问题单 `docs/design/rokae_j5_issue_report_for_vendor.md`，可直接转发）。
- 真机侧**全程只读**（本轮零控制指令）。产线相机须手动只起 `camera/realsense_source`；Orin 零自研零自启。
- 关机前已优雅停止: 真机 ROS tap 容器、ss_yolo_on_real、box3d_live_box、ss_bypass_run、auto_loop（机器人侧未动）。

## 五、关机影响

- cron 播报任务 (`f25c2b8365d4`, 每 20 分钟, deliver=local) 关机即停; 开机后自动恢复（如需停掉: `cronjob remove`）。
- 飞书网关 (`99991663` token 过期) 仍只能靠 `hermes send` 直发。
- 本机 GPU 空闲(12%/835MiB)，无残留训练进程；根分区 311G/396G (余 66G，已超 300G 红线，注意清理)。
