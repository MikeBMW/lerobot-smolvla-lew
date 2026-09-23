# 交接 / 关机前存档 — 2026-09-24 06:40 (静静 CLI 会话)

> 老倪指令: 「保存数据，准备关机」。本文件是**关机前的数据与结论清单**，含产物绝对路径、判据、未完成项。
> 全部数字取自当日真实运行日志（reports/ 与 /tmp/*.log），无估算。

## 1. 今日真跑产物（都在磁盘上，已核对存在）

| 层 | 产物 | 路径 | 关键数字 |
|---|---|---|---|
| L5 生数据 | `l5_gen_v4.h5` (11.9 GB) | `/home/ubuntu/stable-wm-cache/datasets/l5_gen_v4.h5` | **78,992 帧 / 200 变体 / 2601s**（对位偏差 dy±20mm·dz±10mm · 阶段组合 · 夹紧力 30/40/50 · 速度 0.8/1.0/1.2） |
| L4 意图 | `intact_goal_optical_insert_v6lora_200/` | `/home/ubuntu/stable-wm-cache/checkpoints/intact_goal_optical_insert_v6lora_200/` | 训练 243s；`weights_epoch_1.pt`=547 键(LoRA 包装) · **`weights_merged_clean.pt`=323 键(已 merge, 可部署)** |
| L4 指针 | `intact_l4_v6lora_200/` | `/home/ubuntu/stable-wm-cache/checkpoints/intact_l4_v6lora_200/` | config.json + 唯一 `weights.pt`→merged_clean；worker 自证 **trained=True · action_dim=8** |
| L3 流程 | `smolvla_lew_lora_200r4/checkpoints/000200` | `/home/ubuntu/lerobot-smolvla-lew/outputs/train/smolvla_lew_lora_200r4/` | 200 步/3670s · **loss 0.192 · action_loss 0.2368 · lew_loss 0.0007 · 显存 3.75GB**（LoRA, batch2） |
| L2 动作 | `annot_lora_20260923_222406/weights/best.pt` | `/home/ubuntu/lerobot-smolvla-lew/runs/detect/outputs/yolo_annot/annot_lora_20260923_222406/` | 域适应 111s；**新权重 vs 在役 同为 peg 0/16 → 持平/回退 → 未上默认档**（软链未动） |
| MoE 主干 | `stage_moe_s1/moe.pt` (351 MB) | `/home/ubuntu/stable-wm-cache/checkpoints/stage_moe_s1/` | **2500 步 / 1249s**；留出 best 观测 0.0106@1500（基线 0.0366）· 动作 0.0497（基线 0.0955） |
| 表面 AOI v4 | `surface_10083_work_v4.py` | `/home/ubuntu/aoi_v4/`（副本 `/home/ubuntu/zmax_data/aoi_v4_20260920/10083_v4/`） | 离线 HTTP 契约 5/5 通过（见下） |
| 闭环验收 | `reports/fullpipe_20260923_214043/` + `flows/pipeline_closure.json` | 同左 | **done=True · 347 步 · 最小插入距 0.4mm · L4 真推理 33 次 · 融合 80 帧 · L2 否决 151 · 6/6 节点绿** |

## 2. L4 LoRA A/B 结论（口径: 3 seed × 4 臂，两边均真加载）

| line_w1 注入臂 | 在役 intact_l4_current | 新 intact_l4_v6lora_200 |
|---|---|---|
| done | 0/3 | 0/3 |
| 最小 peg-target | 61.8 mm | 61.8 mm |
| 末端插入 | 20.6 mm | 14.6 mm |

**硬证据（u_ff 轨迹 hash）**: 在役 direct 臂 `af8e42fd…` ≠ 解析链 `49f52646…`（注入**改了指令**）；
新 LoRA direct/line_w0 hash **与解析链逐位相同** → 注入**对指令零影响**(inert)。
**判定: 未证明提升 → 不切 `intact_l4_current` 指针**（在役权重原样保留）。
原始数据: `reports/ab_l4_policy_ms_20260923_235000/`、`reports/ab_intent_line_closedloop_20260923_2351*.json`。

## 3. 今日修掉的真问题（含踩坑链，供复现）

1. **tap 图像解码被时钟回拨冻死**（症状: 画布"摄像头连接失败"，而采集看似在跑）
   rclpy 定时器按墙钟调度 → NTP 回拨 7.14h 后其触发时刻落到未来 → 像素永不落盘。
   修: `tools/ss_remote_tap.py` 图像解码/发布者计数改由**主循环 + 单调钟**驱动（`tick_monotonic()`）。已验证帧龄 1.9s、画面 mean=104。
2. **表面检测不可视/无判决**: 10083 只有 `POST /capture_detect`。已写 v4（异步队列 + `/picture` + `/last_result` + `/crop_info`，
   规范图 1280 letterbox 对齐 config imgsz=1280，**不改 V2 任何文件**）。离线契约 5/5、技能清单预览按技能自身 URL 出图已验证。
3. **画布「🧪 状态校正器」断头**: commit 13632919 的 post_layout_fix 把右→左边全剔了（含语义关键边），
   且原顺序"先 RESTORE 后 purge"导致重跑补不回。修: 恢复 `状态校正器(out1)→动作调制器(in8)` + 把 RESTORE 移到 purge 之后（复跑保边已实测）。
4. **LoRA 产物不可部署（伪装成"没提升"）**:
   ① 产物目录多 .pt → `Ambiguous checkpoint`；② **适配器未 merge**（547 键包装命名）→ `Missing key` → `trained=False` → **零动作**。
   修: `tools/merge_lora_ckpt.py`（W=W_base+(α/r)·B@A, r8/α16, 112 层）+ `tools/post_lora_merge.sh`（merge→指针目录→worker 自证），
   已挂进 `tools/fullpipe_chain.sh` ②b；判假 A/B 指纹 = **各臂逐位相同 + action_dim=4**。
5. **飞书发送 99991663**: 凭据/网络都好（手动换 token+发消息 code=0），是 gateway 进程内 token 缓存过期。
   **需用户在自己终端跑一次 `hermes gateway restart`**（agent 被守卫禁止重启 gateway）。
   兜底: `~/.hermes/scripts/feishu_notify.py` 直连开放平台（每次自换 token），哨兵用它推送 —— 已验证 code=0。

## 4. 未完成 / 下次接手第一件事

1. **查"新 LoRA 为何不改指令"**: 候选①归一化 stats 不同源 ②直连线 scale/阈值把增量压没 ③只训 200 步+基座冻结增量近零。
   → 先加 **‖Δu‖ 动作增量诊断**（每帧动作相对解析链的范数）再决定提步数/提 lr/改训 actor 头。
2. **表面 v4 部署到工控机**（先停 V2 → 起 v4 → `tools/aoi_health.py --grab` 验收：10083 端口✅、①②⑤200、④mean 60~200）。
   金手指相机 D265250070 仍需现场处理（关掉占用程序/重插/查供电），否则 10082 仍 500。
3. **画布"所见即所得"逐连线对账**（代码+运行时双证）—— 老倪点名的硬要求，尚未开工。
4. GUI 待生效改动（需重启 studio）: 技能清单「双击=看图 / 开始=真下发」+ 预览按技能 URL。

## 5. 关机前已停/保留

- 停: 训练与采集类（MoE 已自然完成并落盘 moe.pt；采集中转/推理服务/守护脚本按需停）
- 保留: `studio.py`（老倪 GUI，未动）、VSCode
- 数据一致性: 关键产物均为"写完即关"的文件（h5/pt/npz），停止进程后可直接断电；无内存驻留的未落盘状态
