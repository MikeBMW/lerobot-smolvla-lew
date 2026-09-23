# Z-MAX 任务台账 — 盘点于 2026-09-24 07:20 (静静)

> 数据来源: docs/HANDOFF-20260924-shutdown.md · docs/design/handoff_20260922*.md ·
> .hermes/plans/*.md · git log · reports/* · cron 表 · 会话历史 (feishu「静静接受任务」1023 条 + 本会话)
> 状态口径: 已完成=有产物/证据 · 进行中=进程或哨兵在跑 · 待办=无产物

## 一、已完成

### A. 数据闭环与引擎 (09-22~09-23)
| # | 任务 | 证据 |
|---|---|---|
| A1 | L5→L4→L3→L2 四层真跑拉通(全绿) | `docs/PIPELINE_STATE.json` closure=success · done=True 345~348 步 · 最小插入距 0.4~1.4mm · 6/6 节点 success |
| A2 | 引擎每帧真调用审计(拒绝假接入) | L4 真推理 33 次 · 融合 84 帧 · L2 收口否决 146(方向 130) · frame_std 55.5(真帧) |
| A3 | 零回退 A/B | 基线 342 步/最小距 2.2mm vs 挂 pipeline 348 步/0.5mm |
| A4 | 画布「状态校正器」断头修复 | 恢复 校正器(out1)→动作调制器(in8) · RESTORE 移到 purge 后 · 复跑保边实测 |
| A5 | 画布穿线 6 节点 7 连线 + 闭环运行器 | commit f8b80e54 · 逐节点高亮 · 全绿=完成 |
| A6 | 多层级可插拔 Pipeline(注册表/vote/消融) | commit f4876f45 + d26fd74a |

### B. 模型产物(全部落盘并校验, 均在磁盘)
| # | 产物 | 关键数字 |
|---|---|---|
| B1 | L5 生数据 `l5_gen_v4.h5` | 11.9GB · 78,992 帧 · 200 变体 · 2601s |
| B2 | L4 INTACT v6lora_200 (原始 88MB + merge 后可部署 84MB) + 指针目录 | worker 自证 trained=True · action_dim=8 |
| B3 | L3 `smolvla_lew_lora_200r4/000200` | 200 步/3670s · loss 0.192 · 显存 3.75GB |
| B4 | MoE 阶段专家 `stage_moe/moe.pt` | s1 2500 步(留出观测 0.0106@1500) → s2 600 步(best 0.0091@150) · 基线 0.0366 |
| B5 | 统一 backbone `unified_siglip_big/unified.pt` | SigLIP 768d 冻结主干+四头(113 万可训) · 留出 L4 0.011 / 动作 0.048 → 优基线 67%/49% |
| B6 | 严格跨域 A/B(统一主干) | 仅 v6: 0.011/0.048 · v6+L5: 0.011/0.051 (同域持平) |
| B7 | L2 YOLO 域适应 `annot_lora_.../best.pt` | 持平/回退 → 未上默认档(软链未动) |
| B8 | 表面 AOI v4 脚本 + 离线契约 | `surface_10083_work_v4.py` · 契约 5/5 通过 (未部署) |

### C. 标定与真机链路
| # | 任务 | 证据 |
|---|---|---|
| C1 | 手眼在环标定(人机在环 6 位姿) | 最小二乘 19.45→1.73mm(+91.1%) · verify 判据 ≤2.0mm 通过 · 已入库 |
| C2 | eye-in-hand 手眼外参 | `models/handeye_state.json` · 14 视图 · 残差 0.06mm / 0.0046° |
| C3 | 真机链路在役 | tap(ROS domain0 10Hz) → infer:8790 → yolo 0.5s · l2_daemon(+5min keepalive) · 四个 systemd 服务 enabled+active |
| C4 | 真机示教点入库 | slot1/slot2/insert_pose/aoi_gold_view(6 帧极差<1e-6m) |
| C5 | L2 技能库 | slot1/2 · forward/backward/left/right · lift/lower · lissa_insert/lissa_search · pull_module · 9 条 AOI |

### D. 判闸/审计结论(已定档, 不会随风漂)
- **L4 LoRA 3seed×4臂 A/B → 未证明提升, 不切在役指针**(u_ff hash 与解析链逐位相同)
- **今日深挖根因(新)**: 新 LoRA 原始意图确实变了(Δu_raw 1.75~1.85) → 被 **L2 收口闸逐帧否决**(direct 臂 180/180 帧与解析链逐位相同); 闸门内部量: **幅值比中位 5.17~5.83×(红线 1.5×, 89/90 帧超标)** · cos<0 占 22~64/90 → 量纲不对齐, 不是"没学会"
- **统一主干是被证实的泛化解药**: 旧 from-scratch 主干留出 18.1→45.2 崩; 换预训练 SigLIP 后 0.011 且不过拟合
- **评估铁律固化**: 平凡基线(观测 0.0366/动作 0.0947) + 同源留出 + 口径校验

### E. 系统与工程
| # | 任务 | 证据 |
|---|---|---|
| E1 | 关机前数据存档 + 交接单 | `docs/HANDOFF-20260924-shutdown.md` · commit 2c2eae26 已 push |
| E2 | 重启自愈核查(今日) | 4 服务+gateway 自愈 · 飞书 connected · 数据完好(152G/11G/36G) |
| E3 | 系统清洁 + DNS + 网络检查(今日) | 释放 7.18GB(274G→267G) · DNS 解析 0.00~0.02s · 工控机 0.9ms 可达 · WiFi -42dBm/573Mbps |
| E4 | 性能实测(今日) | 三组交错 A/B: governor 无收益(0.90~1.013×) → 已回滚; GPU persistence 开启; tracker 索引器停 |
| E5 | 技能/记忆 GitHub 同步 | cron `dbcf680f3b8a`(6h) last ok |

## 二、进行中(常驻)

- **12 条 active cron 哨兵**: sys-watchdog(15m) · 数据链路健康(30m) · 磁盘红线(2h) · zoo 远程训练(20m) · 静界公告(10m) · 技能同步(6h) · v9 完成验证(15m) · INTACT 四任务(20m) · L4 进度报告(30m) · 记忆层阶梯(20m) · v6 判闸(20m) · v6 提前收哨(10m) · v5.12.1 桌面包(10m) · 全量 pipeline(20m)
- **进程**: studio GUI(06:57 启动 → 昨日 GUI 改动已生效) · 四采集/推理服务 · gateway · l2_daemon keepalive · auto_loop(@reboot)

## 三、待办

### ① 立即可做(本机, 无外部依赖)
1. **LoRA 量纲收口**: 让对齐层把幅值比收到 ~1 再提交闸门(或按训练集同源 stats 归一) → 同口径重跑 3seed×4臂 A/B 看 direct 臂过关率/成功率【老倪定"第一件事", 诊断阶段已完成】
2. **MOE 验证链**: ①门控分化诊断(`tools/moe_gate_diagnose.py` 已写好, ~3 分钟) ②同数据密集基线严格 A/B ③接进 pipeline/引擎闭环 n=10【已在群里请你选 A/B/C, 未回】
3. **统一主干接进引擎闭环**(端到端验证; 目前只离线留出集验证; 代码里无引用)
4. **画布"所见即所得"逐连线对账**(老倪点名硬要求, 未开工)
5. **提交今日新增**: `tools/diag_lora_du.py` + 4 份诊断报告 + 维护报告 + 台账(工作树 15 项未提交, 未推送提交 0)
6. **v9 哨兵整理**: v9 训练完成自动验证 cron 的 monitor 自 09-10 无变化(早已跑完) → 建议 pause

### ② 需现场/需授权
7. 表面 v4 部署到工控机(先停 V2 → 起 v4 → `tools/aoi_health.py --grab` 验收)
8. 10082 金手指相机 D265250070: 关占用程序/重插/查供电(否则 10082 仍 500)
9. 2D→3D 标定采集: 现场摆光模块——当前帧 0 检出(`box3d_live_box.json` ok=false, conf<0.4) → 采不到就落不了 `models/box3d_state.json`
10. `T_base_cam` / `plane_z` 现场测量(preflight 缺项, 真机 3D 的最后两环)
11. `L2.pull_module` 合爪未夹住 → 需示教 `ring_pose` 后重建(09-20 未决)

### ③ 需你决策
12. 抓取光模块五段动作计划 S0~S5 待批准(`.hermes/plans/2026-09-21_grasp-module-approval-plan.md`)· 位姿来源(a 起产线主程序/b 新栈 cartesian_pose/c 你指定)未定
13. 两条 pause 哨兵是否复活: v10 足量训练哨兵(09-20 停) · v5 判闸(09-14 停)
14. `~/hermes-portable.tar.gz` 893MB + `~/hermes_core_usb_20260822_1609.zip` 489MB 是否清
15. 今日 box3d 采集保活哨兵仍 pause(你不在场, 我故意停的) — 要现场采集时 resume

## 四、阻塞项(依赖外部)

| 阻塞 | 影响 |
|---|---|
| 产线主程序未跑 → `/robot/tcp_pose` 0 发布者 | 光模块位姿来源未定 → 抓取计划 S2 之后无法执行 |
| AOI 判决只在工控机终端(HTTP 只回"已受理") | 本机拿不到 OK/NG, 需另开结果通道 |
| Qwen2.5-VL-3B 权重未下全 | 大模型层只能用 smolvlm2-500m 兜底 |
| 8GB 显存装不下 SmolVLA+LEW 同跑 | L3 段 CPU 4.24s/步(实时性受限) |
| 三框架三 venv(torch 2.6/2.7 · py3.10/3.11/3.12) | 真联合脚本只能用 INTACT venv; 跨 venv 已用子进程桥 |
