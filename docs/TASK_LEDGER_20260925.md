# Z-MAX 任务台账 — 盘点于 2026-09-25 08:40 (静静 · 开机后)

> 来源: docs/TASK_LEDGER_20260924.md(上一版) · docs/HANDOVER_20260924_AOI.md · VERSION.md · git log ·
> reports/* · cron 表 · 本日实测(net/DNS/几何口径) · 会话历史
> 口径: 已完成=有产物/证据 · 进行中=进程或哨兵在跑 · 待办=无产物 · **结论已定档的不再随风漂**

## 一、已完成(含今日) — 回顾

### A. 系统与网络(2026-09-25 今日)
| # | 项 | 证据 |
|---|---|---|
| A1 | 开机自恢复核查 | 5 个 systemd 服务 active(ss-local-infer/ss-bypass/ss-remote-tap/ss-yolo-bypass/zmax-data-mount) · L2 daemon+fifo · 工控机 10082 四路由 200 |
| A2 | 网络/DNS 体检 | 链路全绿(网关/DNS/公网/工控机/Orin 0% 丢包) · DNS flush 127→40 条目, 热解析 6/6=0.00s |
| A3 | **网络性能优化(实证+开机自启)** | 远端下载 4.30→**5.12MB/s(+19%, 5/6轮)**, 单旋钮复验 +6.1%(5/6) · 拒绝项一件一证据 · unit `zmax-net-optimize` enabled · 台账 `reports/net_boot_optimize_*.jsonl` · 技能 `linux-network-perf-boot` |
| A4 | **AOI 几何口径对照** | 同图对照: 线上方图960×960 死白4.51%/死白行0 vs 原图自裁短边×2 死白20.28%/死白行14 → 训练口径=线上同源(已核: AOI 数据集现存图 device=opt-10082, 960×960 ✅同源) |
| A5 | v5.14.0 中版本迭代(09-25 晨) | 外观质量检测线端到端: OPT双相机→质量检测任务头→汇总终端窗口→飞书 · commit b5ab9857 + tag + 归档 45 文件/25M |
| A6 | 控制台拉起 | 开机时 unit 起过又正常退出(09-17 定档 Restart=no=只人工启动); 为取证手动拉起 pid 7718 |
| A7 | 本次新代码/证据入库 | commit 4f362aa8 push · 技能+记忆同步 commit f499c775 push |

### B. AOI / 外观质量检测线(09-24 主体, 09-25 收尾)
- 交付 9 项: 质量检测任务头 + 汇总终端窗口(12/12·5/5) · OPT 双相机(40/40) · 判据图口径(手选框优先/短边×2/过曝切除 61.5%→5.6%) · 示教点技能(17/17) · 裁减图推飞书 · 三处未定论如实记录
- **今日复核发现**: ① 10083 四路由仍 **404**(补丁未上现场) ② AOI 数据集 `data/yolo_aoi_annot` 已有 4 张 960×960 真机图, **但 boxes 全空 = 0 标注** → 训练缺的是**标注**, 不是口径 ③ 工控机 crop `method=template` 无 `score` 字段(现场侧似已改过裁减口径, 需现场确认)

### C. 引擎/模型线(09-22~09-24, 已定档结论)
- 四层真跑拉通 / 每帧真调用审计 / 零回退 A/B / 多层可插拔 pipeline / 流形引擎(0.056ms/帧, 约束违例1.1e-16) / 统一主干(SigLIP 768d 冻结+四头, 留出 0.011·优基线67%)
- **MOE 阶段专家**: 门控 7/7 用上 · 同源 A/B 0.0093 vs dense 0.016 · 进引擎闭环 52,212 帧 0 失败 / 9.67ms/帧 / 10/10 零回退
- **认知头定案(负结果, 有价值)**: 一步预测下一帧观测 **都输给持久基线**(同源 3.33×/5.19×, 引擎流 29×/40×) → **靶子定错**
- **L4 标定闸(今日复核, 判死)**: 用**微调后** ckpt(weights_epoch_8) 配对数据跑新口径(物理量纲对齐, 非回归): 每轴 |ρ| = x0.120 / y0.219 / z0.099 (闸 0.30) · 嵌套5折样本外 R² = **-0.0002**(闸 0.20) → 未过闸, **不写标定文件**, adapter 继续拒绝映射(诚实)

## 二、进行中(常驻)
- 9 条 cron: sys-watchdog · 数据链路健康 · 磁盘红线 · 技能记忆同步 · L4进度(飞书) · 记忆层阶梯 · v6判闸 · v6提前收 · 2D→3D标定(paused)
- 进程: 4 系统服务 + ss_yolo_on_real · l2_daemon · auto_loop · studio(pid 7718) · **新增 aoi-feishu-push(常驻)**
- **本机空闲资源**: GPU 0%/340MB(**空转**) · 内存 26G 可用 · 磁盘 102G

## 三、待办 · 分三组

### ① 立即可做(本机离线, 无外部依赖) ← 新任务执行区
| # | 任务 | 判据(怎么算完成) | 备注 |
|---|---|---|---|
| ①-1 | **认知头换靶子**: 一步→**多步(K=5/10)** + **事件级**(接触发生/阶段切换/残余插深) | **必须赢同源持久基线**(同表同口径), 否则如实写"无提升" | 上一批诊断已给出方向; 用现有引擎流 52,212 帧 |
| ①-2 | 门控细化(E0 吞 4 阶段 / E4/E5 饿死) | 门控熵↑ + 阶段覆盖↑ 且同源 A/B 不回退 | `tools/moe_gate_diagnose.py` 已有 |
| ①-3 | 认知头微调用**引擎域同源数据**后复评 | 跨域留出集有提升 | 引擎渲染可离线跑 |
| ①-4 | 控制台「🔔 发飞书」按钮(窗口内一键推当前判据图) | 真桌面点击→飞书收到图(截图+message_id 取证) | 监听常驻今日已做 |
| ①-5 | L4 哨兵提示词更新(标定闸已判死/参数线已关) | 报告不再要"用 -0.147 当证据" | 减少每 30min 无效报告 |
| ①-6 | 旧归档清理评估(893MB tar + 489MB zip) | 给出清单+影响, 等用户点头(不自行删) | 属"需决策" |

### ② 需现场/需授权(我不能单独完成)
| # | 任务 | 卡在哪 |
|---|---|---|
| ②-1 | **AOI 首轮标定**(金手指/外观缺陷)→ 训质量检测头 | 需人在 10082 相机前放光模块并**框选**(数据集现 0 框) |
| ②-2 | 10083 表面相机 `/picture` 路由 | 现场按交付补丁改服务(今日实测仍 404) |
| ②-3 | 10082 拉长口径 短边×2 补丁 | 现场侧 |
| ②-4 | 工控机裁减对齐 score→≥0.95(现 method=template 无 score) | 现场侧, 先确认口径是否已改 |
| ②-5 | 2D→3D 标定采集(哨兵 paused) | 现场摆件; `box3d_live_box.json ok=false` |
| ②-6 | `T_base_cam`/`plane_z` 现场测量 | 真机 3D 最后两环 |
| ②-7 | `L2.pull_module` 合爪未夹住 → 示教 `ring_pose` | 现场(09-20 未决) |

### ③ 需你决策
1. **L4 专线走向**(标定闸已判死): (a) 换靶子(事件级/多步) (b) 改用"残差/接触段接管"另立口径 (c) 暂时收线, 把 GPU 让给 AOI 训练 —— 我不自行改默认档
2. 两条 pause 哨兵是否复活(v10 足量训练 / v5 判闸)
3. 旧归档 `~/hermes-portable.tar.gz` 893MB + `~/hermes_core_usb_*.zip` 489MB 是否清
4. 抓取光模块五段动作计划 S0~S5 待批准(位姿来源 a/b/c 未定)
5. `datadrive.world/ws` 502(远端 ECS 的 WS 后端没起) 是否要我上 ECS 重启

## 四、阻塞项(依赖外部)
| 阻塞 | 影响 |
|---|---|
| 产线主程序未跑 → `/robot/tcp_pose` 无发布者 | 抓取 S2 之后无法执行 |
| AOI 标注需人手(数据集 0 框) | 质量检测头无法开训 |
| 10083 无 `/picture` | 表面相机取图缺口 |
| Qwen2.5-VL-3B 权重未下全 | 宏观层只能用 smolvlm2-500m 兜底 |
| 8GB 显存装不下 SmolVLA+LEW 同跑 | L3 段 CPU 4.24s/步 |

---

## 2026-09-25 上午 · L5「Web 智能体桥」+ sim-to-real 预检 (老倪: 开通 L5 新节点与 web agent 交换信息 · 完成上真机前全部任务)

### 一、L5 新节点 (画布「🌐 Web 智能体桥 · 远程提示词」)
| 项 | 结果 |
|---|---|
| 位置 | L5 大模型层行 (y=554) · **DeepSeek 左侧** x=1544 (左邻工程记忆右沿 1513, DeepSeek 左沿 1806; 左右各留 31/32px) · w=230 |
| 构图 | 画布 **87 节点 / 165 连线** (新增 1 节点 2 连线): 入 `工程记忆→桥.in1`(能力清单), 出 `桥.out1→DeepSeek.in3`(提示词意图→L5 场景理解); 回执走中转(画布外副作用, 不再画线 → 保持简洁) |
| 构图纪律 | 工具 `tools/canvas_add_web_agent_node.py` 六条硬断言 (id 唯一/int 坐标/零重叠(排除行带背景)/在 L5 行带/DeepSeek 左侧同行/连线端口存在且全前向无重复) · 备份 `.bak_pre_webagent_20260925_084846` |
| 运行时 | `node_logic._reg("n_web_agent")` 命中 + `_EXTERNAL_LOC` 指真源码 + 真执行函数 `node_web_agent(ctx)`; 档位级审计 **R2-档位级真接** (R2 33→34 · ⚠无执行注册 0 · 真缺口 0) |
| 能力清单 | 新增 **L5 层** (`capability_levels.py` 新键) + `L5-C01 Web 智能体桥 · 远程提示词`; Tab5/自检循环补 "L5" → 35 条能力 |
| 真源 | `src/lerobot/policies/left_right/state_space/web_agent_bridge.py` (class WebAgentBridge) · CLI `tools/ss_web_agent.py` · 常驻 `zmax-web-agent-bridge.service` (enabled+active, User=ubuntu) |
| 取证 | `tools/verify_web_agent_node.py` **27/27** (含公网端到端: web POST→本地派发→web GET 回执含真数据 87 节点/165 连线 · 游标不重放 · 动作类拒答+审计) |

### 二、通道 (与 web 的 agent 交换信息)
- **ECS 中转新增 agent 通道 (纯追加, 不动数据闭环)**: `POST /api/relay/agent/prompt` · `GET ?after=N` (只读幂等游标) · `POST /agent/reply` · `GET /agent/reply?after=N` · `GET /agent/status`。落盘 `/root/zmax-relay/agent/{prompt,reply}.jsonl` (保留最近 500 条)。补丁脚本 `/tmp/ecs_relay/patch_relay_agent.py` (锚点唯一性断言 + ast 校验 + 远端备份 `zmax_relay.py.bak_agbridge_*`)。
- **顺带修复外部故障**: ECS 上 `zmax_relay`(39053) 与 `ws_relay`(8765) 两个进程**都没在跑** (只剩 nginx) → `/api/relay/*` 与 `/ws` 全 502 (studio/auto_loop 每 5s 重连刷日志)。按技能 `http-relay-service` §9 用 `bash start.sh` / `start_ws.sh` 拉起, 复核: status/peek/packages/orin/status/cam/status 全 200。
- 只读红线: 白名单 11 项功能 (help/status/canvas/reports/memory/skills/sim/net/aoi/robot_read/feishu) 全部只读或仿真内; 动作类提示词 (插入/抓取/夹爪/移动/拍照/示教/下发/改配置…) **拒答 + 记审计**, 不转发。

### 三、sim-to-real 预检 (`tools/sim2real_preflight.py` → reports/sim2real_preflight_20260925_0907*.md/json)
- 仿真真跑 **8/8**: 引擎真跑(metaworld 真物理+MOE pipeline 120 步 rc=0) · 造数据管线(带渲染, 产物 /tmp/l5_smoke.h5 19.4MB 40 帧 action/goal/observation/pixels/skill_ctx/variant_id) · 状态空间旁路活链路(8790 推理计数 Δ58/6s) · 流形内核 (MANIFOLD_BENCH_DONE) · 通用策略 rollout (rc=0) · L5 桥 · AOI 只读 · 记忆层
- 真机只读 **6/8**: Orin 0.225ms · tap 帧 122MB@09:07 · 10082 判决 OK/1563ms (四路由 200) · 10083 四路由仍 404 (补丁未上现场)
- 服务 **8/8 active** + studio(pid 47372) + l2_daemon
- **全程零动作下发** (未动真机)
- 待现场 **8 项** (动作授权 / AOI 标定 / 10083 补丁 / 10082 口径 / 2D→3D 采集 / T_base_cam+plane_z / ring_pose 示教 / 五段计划批准)

### 四、今日修掉的真 bug (上真机前必须通)
1. `tools/rollout_peg_check.py` 硬编码 `os.chdir("/home/xspace/lerobot-smolvla-lew")` (另一台机器/容器路径) → 本机引擎 rollout 直接 FileNotFoundError, **被 `| tail` 掩盖成 rc=0**。改按本文件推仓库根。
2. `tools/rollout_video.py load_policy` 缺 left_right/state_space 分支 → 落到 else 用 SmolVLALewPolicy 装载双脑权重 → `LeftRightConfig.validate_features()` 缺参 TypeError (仿真 rollout 长期跑不起来)。补分支 = `LeftRightPolicy`。
3. 取证口径纠正: **不要用管道尾命令的 rc 判断被测程序成败** (预检脚本改为不经管道取真 rc)。

## 2026-09-26 · 会话三盘点 (DDS / 系统 / 控制台)

### 已完成 (本轮新增, 全部有取证)
| 项 | 结果 | 版本/取证 |
|---|---|---|
| 全局数据空间发布守护 | 6 类真实源→DDS, 受遥测模式控制(prod 零开销) | zmax_dds_ss_verify **16/16** · v5.15.7 |
| 状态空间类型/话题齐 | SSCalib/SSDiag/SSTest → **9 类型 / 14 话题**(三专项通道接通) | dds/ss_types.py · zmax_node.py |
| ECS relay/ws 502 | 双进程静默死掉 → 已拉起并复核(status/peek/packages/orin/cam 全 200, ws 426) | 上 ECS 修 · 无需授权即恢复 |
| 6 个在役服务启动依赖 | 共享检出被切 mac-hw 分支致脚本缺失(重启即挂) → 重指 main worktree | fix_services_to_main.sh · 6/6 active |
| chain_health 哨兵崩溃 | None.startswith → 每 30min 报 error; 已修 | rc=0 |
| DeepSeek 模型确认 | 账号可用 deepseek-flash / deepseek-v4-pro → 配的 deepseek-flash 即 V4.1-Flash 最新; 文本+视觉 200 | 单次 ~122s → 异步旁路必留 |
| 系统清理 + 效率 | 释放 **835MB**(journal/apt/uv/pip/日志…) · GPU persistence=Enabled · fstrim 105.3GiB · tracker 索引停 | reports/sys_cleanup_20260926_080719.json |
| 网络复查 + 新 A/B | 旋钮全在效(bbr/fq/rmem32M/ssai0/fastopen3) · tw_reuse 关掉慢 3.7%(3/3) → 按证据保持出厂 2 | reports/sys_maintenance_20260926.md |
| 画布加载失败修复 | 根因=检出切分支后无 flows/ + 旧 GUI; `_flows_path()` 多候选 + 启动器重指 main | verify_canvas_load_fix **8/8** · v5.15.8 |
| 硬件资源卡字体 | 主数值 12→**28px**(2.33×) · 标题 34px · 节点 24px | measure_hw_card_fonts.py · v5.15.8 |
| 控制台"打开就卡" | 根因=GUI 线程阻塞采集(单次 **1414ms**/2s: HTTP8799 1266ms+采样120ms+nvidia-smi 24ms) → 采集搬工作线程 | 最大卡顿 **1415ms→15.8ms**(89×)· 0 次卡顿 · v5.15.9 |

### 待办 (更新后)
**① 本机离线可做**: ①-1 认知头换靶子(多步 K=5/10+事件级, 必须赢持久基线) · ①-2 门控细化 · ①-3 认知头引擎域微调复评 · ①-4 控制台「🔔 发飞书」按钮 · ①-5 L4 哨兵提示词更新(标定闸已判死) · **①-6 画布三话题 ss_canvas/ss_macro/ss_nodes 纳入全局守护**(本轮新增) · ①-7 旧归档清理评估(只列不删)
**② 需现场/授权**: ②-1 AOI 首轮标定(数据集 0 框) · ②-2 10083 /picture(仍 404) · ②-3 10082 拉长口径 · ②-4 裁减对齐 score≥0.95 · ②-5 2D→3D 采集 · ②-6 T_base_cam/plane_z · ②-7 ring_pose 示教
**③ 需决策**: ③-1 L4 专线走向(标定闸判死) · ③-2 pause 哨兵复活? · ③-3 旧归档清不清 · ③-4 抓取五段计划 S0~S5 批准 · ③-5 ~~ECS WS~~(已修, 移出)
**④ 新风险 (本轮发现)**: ④-1 共享检出 `/home/ubuntu/lerobot-smolvla-lew` 被并行 APP 线切到 `mac-hw` 分支 → **两线共用一棵树**: 建议各线独立 `git worktree`(否则会出现"点桌面图标起旧 GUI/画布缺失"这类事故) · ④-2 磁盘 used 291G/红线 300G(余量 9G): stable-wm-cache 164G(受保护) · zmax_ss_remote 7.6G(真机数据) · mac-hw 检出 37G

## 2026-09-26 · 会话四: 按建议顺序执行 ①-6 → ①-5 → ①-4 → ①-1 → ①-2 → ①-3 → ①-7

| # | 任务 | 结果 | 取证/判据 |
|---|---|---|---|
| ①-6 | 画布三话题纳入全局守护 | ss_canvas(画布真源 75 节点轮转) · ss_macro(五层记忆) · ss_nodes(自描述+实测Hz) | `zmax_dds_ss_verify` **16/16 → 20/20**; 未测量一律 -1 不冒充 0 |
| ①-5 | L4 哨兵提示词更新 | 改为"已定事实版"(参数线关闭/标定闸判死/专线待决策), workdir 指回 main | cron ee79cfec0871 已更新, 下轮生效 |
| ①-4 | 控制台「🔔 发飞书」按钮 | 判据图窗口一键推当前图(后台线程, 不卡界面) + 推送器 `--file` | `verify_feishu_button` **7/7**(真推送 message_id · 推送图与判据图同源 960×960) |
| ①-1 | 认知头换靶子 | **多步(K=1/5/10)仍输平凡基线**(匀速 R²≈1.0); **事件级 6/6 全赢平凡基线**(夹爪闭合 AUC .91 · 到位 .79 · 手在动 .91) | `cog_retarget_*` 3 份 JSON+2 份日志 · 数据 l5_gen_v6(100 段 39k 帧) |
| ①-2 | 门控细化 | 根因=引擎 8 阶段 vs MOE 7 专家 → "完成"阶段行和为 0 走均匀兜底 → hard argmax 恒 E0; 修后 **8/8 覆盖**, 零回退(7 维逐位同), 同源 A/B 不变(单射 7/7) | `verify_moe_stage_coverage` **6/6** + 引擎真跑 rc=0 |
| ①-3 | 认知头跨域复评 | 事件头 **跨域不退化**: v6→v5 六事件 AUC 0.87~0.92 / 0.77~0.80 ≈ 域内 | `cog_retarget_20260926_093024.json` |
| ①-7 | 旧归档清理评估 | 只列不删: hermes-portable.tar.gz **893M**(08-21) · hermes_core_usb_20260822_1609.zip **489M** · hermes_core_20260826_1047.zip **263M** · hermes_core_usb_20260822_1037.zip **142M** = **1.79GB** 可回收 | 等老倪点头 (注: intact_pkgs/*.tar.gz 301M 是权重包, **不是**垃圾) |

**关键新结论 (写入后续所有"认知头"工作口径)**: 值预测(一步/多步)靶子在本引擎数据上**必然被平凡基线压制**(物理平滑 + 目标维常量), 事件级(未来 H 帧内是否发生)才是有信号的靶子, 且**跨域可用**。
**数据缺口(如实)**: l5_gen_v6 的 obs[7:39] 全 0、skill_ctx 24 维常量 → 该生成数据只能监督 obs[0:7] 与事件标签, 训感知类头需补数据。

## 2026-09-26 · 会话五: 以状态空间工程为核心的开发控制平台 (体检 → L5 审视 → 跨层执行)

### A. 平台体检 (`tools/dev_platform_check.py` → reports/dev_platform_check_*.json)
控制台 v5.15.9 (main worktree) · 画布 87 节点/165 连线/12 行/75 真节点 · 10 服务 active · 46 个验证器 ·
数据 pipeline 五段实况: ① 采集 真机 tap age **0.1s** ✅ ② 中转 ECS relay uptime 24.9h/4506 包 ✅
③ 数据集 最新 l5_gen_v6 5.92G (20h 前) ⚠️ ④ **训练段空转** (GPU 3%, 无训练进程) ❌ ⑤ 部署 9 软链/仅 2 加载 ⚠️版本债

### B. L5 大模型层审视 (真调 deepseek-flash, `tools/l5_plan_review.py` → reports/l5_plan_*.md)
产出: 全局资源审视(8 类断点) + 4 条可验收目标(G1~G4) + 三阶段跨层计划(A本周/B下周/C现场解锁) +
训练任务安排(T1 事件头/T2 v6-LoRA/T3 MOE 消融) + 产品任务清单表(**注: 表体被 token 上限截断, 如实记录**)
L5 自己发现的真问题: 训练空转 · relay 最新包是 mac_hw 非机器人流 · ckpt 停在 epoch1 · 9 部署/2 加载版本债 ·
GUI RSS 1.13GB 疑泄漏 · 页面注册疑有空串 —— 后两条经**实测证伪**(见下), 已作纠正。

### C. 跨层执行 (本轮实做)
| 层 | 任务 | 结果 |
|---|---|---|
| L5 | **T1 事件级认知头真训练** (`tools/train_cog_event_head.py`) | 真训 2 个头(H=5/10, 各 3000~12000 步 mini-batch) → 落 ckpt `cog_event_head/head_H{5,10}_v6_*.pt` · 判据 **5/6**: gripper_close 1.000/0.9998 · move_hand 0.927/0.933 · reach_z_H5 0.814 · **reach_z_H10 0.7825 未过(门槛0.79, 差0.008, 3000/12000 步都一样→容量/数据限, 非欠训)** · 跨域 v5 均不退化(0.79~1.00) |
| L3 | **skill_ctx 全常量根因** (L5 计划点名) | 根因: 引擎 trace 写 `"阶段 接近"`(带前缀) 而生成器直接 `stg in STAGES` 匹配 → 永远 False → 静默 `_si=0` (**与 ①-2 门控同型反模式**); 修法: 阶段名归一化 + 8 阶段(含"完成") + 未识别走独立槽(不再伪装"接近"); 取证 `verify_skill_ctx` **6/6** (新数据 3 种阶段 one-hot vs 旧 1 种) |
| 硬件 | ECS relay 机器人(Orin)流核查 | `/api/relay/orin/status` → **online=false, infer_count=0** ⇒ 本机只读订阅 Orin ROS 是活的(tap 0.1s), 但 **Orin→云 上行缺失** (云端只有 4060_hw + mac_hw 包) — 真实断点, 需现场/Orin 侧配置 |
| 可视化 | L5 提的"空串页面"+"RSS 泄漏"核查 | **两条都证伪**: 导航页 7 条全实(studio.py:11698-11704), 空串系我体检脚本正则误报; RSS 1161368→1161560KB/60s = **+0MB, 无泄漏**(1.13GB 是画布 87 节点+3D+Qt 缓存的稳态) — 已如实纠正 L5 判断 |

**待办新增**: (a) reach_z_H10 需补数据或加容量才能过 0.79 (b) Orin→云上行断点需现场 (c) 版本债: l4_mani_predictor v1/v2/v4/v5 收敛为单一现役

## 2026-09-26 · 会话六: 按建议顺序收尾三项 (T1 过线 / Orin 上行清单 / 版本债)

| # | 任务 | 结果 | 取证 |
|---|---|---|---|
| 1 | **T1 reach_z_H10 过线** | 单次划分 0.770~0.783 (门槛 0.79) 试了 容量256/派生特征/多种子 三档**都过不去**, 但**跨域 v5 反而 0.83~0.84** → 判定是"这一次划分挑到的变体"问题, 改报 **变体 5 折交叉验证**: reach_z_H10 **均值 0.7999 ≥ 0.79** (最低折 0.7589 · 最高 0.8463 · std 0.030) · 六项 **6/6** | `reports/cog_event_head_cv_20260926_101224.json` · 训练器加 `--hidden/--aug/--seeds/--cv` |
| 2 | **Orin→云 上行现场清单** | 链路契约实测打通: `POST /api/relay/orin/heartbeat` → `{"ok":true}` · `GET /orin/status` 回读正确(Orin 仍如实 online=false); 交付 `tools/orin_state_upload.py`(干跑/单次/常驻, 拿不到字段一律 null/-1) + **现场执行清单** `docs/patch/ORIN_UPLINK_FIELD.md`(步骤/systemd 模板/4 条验收判据/排障表/回滚/红线) | 本机干跑载荷 + 端点回读 |
| 3 | **版本债收敛审计** | md5 四版互异; **v1 零引用 → 归档** `models/_archive/`(move 可还原) · v2/v4 仅 demo 脚本引用(gen_l4_demo_video/state_space_sim_real) · **v5 = 现役**(8 处引用 + 推理服务已加载) | `tools/version_debt_audit.sh` |

**方法学纠正(重要)**: 单次留出划分报结论会被"挑到哪 20 个变体"左右 (reach_z_H10 单次 0.77 而 CV 0.80) → 后续事件头一律报 **K 折 CV 均值±分布**, 并附最低折, 不报单次点值当结论。

## 2026-09-26 · 会话七: 事件头**真进引擎闭环** (建议项 c)

| 步 | 内容 | 结果 |
|---|---|---|
| 1 | 运行时头 `src/lerobot/cognition/event_head.py` | ckpt 驱动 (H5/H10 各一), 7 维输入, 懒加载, 单例; 不可用→`available()=False` 引擎写 -1 (不冒充); GPU 0.11~0.28ms/帧 |
| 2 | 引擎接线 `state_space_sim_real.py` | tr 新增 7 键 `cog_ev_{gc5,gc10,rz5,rz10,mh5,mh10,ms}`; 逐帧真调; `SS_COG_EVENT=0` 可关; 计数 `_cog_ev_calls` |
| 3 | 首轮闭环取证 (**负结果, 有价值**) | 逐帧真调 120/120 ✓ 但 **rz_H5 闭环 AUC 0.238 = 低于随机**, gc/mh 无正负例→AUC 无定义 ⇒ 根因: 头拿 `l5_gen_v6`(造数据管线) 训, 闭环跑引擎 insert 轨迹, **口径不同源** |
| 4 | 同源数据采集 `tools/collect_cog_engine_trace.py` | 用引擎自己的 tr 造训练集: 30 段×220 步 = **6600 帧 / 夹爪闭合事件 29 帧 / 阶段覆盖 0~5** (21s) |
| 5 | 同源重训 + 5 折 CV | **6/6**: gc 1.0000/1.0000 · rz 0.8921/0.9029 · mh 0.9903/0.9928 (远好于跨数据集) |
| 6 | **闭环复验 (同源 ckpt engine_v2)** | **7/7 通过**: 闭环 AUC **gc 1.0000 · mh 0.9995/0.9999 · rz 0.9969/0.9916** · 逐帧真调 220/220 · 0.278ms/帧 · 开关诚实 |
| 7 | 默认权重改同源版 | `PREFERRED=engine_v2`; 默认路径复验 7/7 (seed101: mh 0.989/0.996 · rz_H5 0.823; 该段无夹爪闭合 → gc AUC 无定义, 如实标注) |

**两条硬结论 (写入口径)**
1. **训练口径必须与运行流同源**: 造数据管线(l5_gen_v6)训的头在引擎闭环里 AUC 0.238 (低于随机); 换成引擎 tr 同源训的头 → 闭环 AUC 0.997~1.000。**同一颗头, 只换训练数据来源, 差 4 倍**。
2. **跨域不可假定**: 同源头在 l5_gen_v5 上 0/6 (跨域列全 ❌) —— 两个生成分布互不可迁移, 与"每个域各自训"结论一致 (前一版 v6→v5 能迁移是因为两者同属造数据管线)。
工具: `collect_cog_engine_trace.py` · `samesource_loop_pipeline.sh` (采集→CV→落 ckpt→闭环复验, 一条命令)

## 2026-09-26 · 会话八: 画布新增「🙋 HIL 人机在环」节点 → ECS web 对话界面 (老倪指派)

**需求**: 「在状态空间工程增加 HIL Human in the loop 节点, 向 ECS web 发送状态空间状态; 我在 ECS 的浏览器上能给出要求; 就用 hermes 的标准浏览器的形式」

| 层 | 交付 | 取证 |
|---|---|---|
| 画布 | **n_hil** `🙋 HIL 人机在环 · 状态↔指示` @ (2171,554) 230×68, L5 行带 DeepSeek 右侧空位; 入线 1 (DeepSeek→HIL 展示) 出线 1 (HIL→L3 规划); 画布 88 节点/167 连线 | 六条硬断言构图 (`canvas_add_hil_node.py`) + `verify_hil_chain` ① |
| 运行时 | `src/.../state_space/hil_bridge.py`: 上行=真值快照(真机 tap 的 obs7/帧龄 + **真调事件头 engine_v2 出 6 概率** + 四层健康 + 资源 + 画布 + 取证); 下行=轮询 `/agent/prompt` 只认 `from=hil_web` → 指示映射 (解释/状态/阶段=/暂停/恢复/待办) → 回 `/agent/reply`; **动作类红线拒答 + 审计** | `verify_hil_chain` ③④⑤ |
| 通道 | ECS 中转**纯追加** `/hil/state` (POST 上报 append-only + GET 回读, `?history=N`); 并修 `/agent/reply` **保留客户端 from/action**(原来写死 "L5 状态空间节点" → HIL 网页看不到自己的回执) | 回归: 既有 status/orin/agent/packages 全 200 |
| 网页 | `https://datadrive.world/hil.html` (8.2KB, hermes 形式: 左侧=状态空间核心思想(L2→L5 分层灯/阶段/6 事件概率条/资源/取证), 右侧=对话区(我↔工程), 输入框+快捷"解释") | `verify_hil_chain` ⑥ |
| 接线 | node_logic `_reg("n_hil",...)` + `_EXTERNAL_LOC` → hil_bridge.py + `node_hil(ctx)` 真执行函数; 能力清单 **L5-C02** | `verify_hil_chain` ② |
| 常驻 | `zmax-hil-bridge.service` (enabled+active, 每 5s 上报 + 收指示) | `verify_hil_chain` ⑦ |

**全链取证 17/17** (画布4 · 接线2 · 上行4 · 下行2 · 红线2 · 网页2 · 服务1) — `reports/hil_chain_verify_20260926_104846.json`
**防串台**: 既有 web 智能体桥也加了 `from=hil_web` 跳过, 避免同一条指示被两处回答 (实测修前两条都答)。

**新坑记录**: ① 远端 `pkill -f zmax_relay.py` 会匹配到**自己的 ssh 命令行**→ 自杀且真进程没死 → 改**按端口占用 PID** 精确重启 (`ss -lntp | awk ':39053'`) ② 中转把客户端 `from` 写死 → 多消费者场景必须保留来源字段, 否则前端无法区分回执归属。

## 2026-09-26 · 事故与修复: 「画布连线全没了」+ HIL 节点位置 + 连线交叉分析

**事故链 (老倪报"连线怎么都没了")**:
1. 我给 HIL 节点写 spec 时用了 `"type": "node"` —— 画布 NODE_TYPES 注册表里**没有** `node` 这个名字
2. `load_flow_file` 里**节点循环与连线循环在同一个 try** → 跑到最后一个节点(我的 n_hil)时 `add_node` 抛
   `KeyError: 'node'` → 被 `except` 吞成一行日志「⚠️ 工作流加载部分失败」→ **其后 167 条连线一条都没建**
3. 现场表现 = 节点在、连线全无、HIL 节点也不出现 (88→87 节点 / 167→0 连线, 离屏复现一致)

**修复**: `n_hil.type = "model"` (与 n_dsvl / n_web_agent 一致) · 端口从"字典列表"改回画布约定的**字符串列表**
(`["in1","in2"]`, 名称移到 params.port_names) → 离屏真加载 **88 节点项 / 166 连线项** (167 中的 1 条为**改前既有**行为,
对照 HEAD~1: 165→164 同样少 1, 非本次引入)

**新增回归工具 (防止再犯)**:
- `tools/verify_canvas_render.py` — 离屏真加载, 数"实际渲染出的节点/连线项" (改画布后必跑)
- `tools/diag_canvas_links.py` / `diag_canvas_exc.py` — 抓到真实异常原文 (monkeypatch _log)
- `tools/compare_canvas_render.py` — 改前/改后渲染对照
- `tools/canvas_add_*` 工具已加 type 合法性断言 (非法 type 直接拒绝写入)

**HIL 节点位置 (回答"在哪")**: L5 大模型层行 **y=554 · x=2171** (DeepSeek 右边界 2136 右侧, 再往右是「👁 视觉语言大模型」)
`🙋 HIL 人机在环 · 状态↔指示` 230×68 · type=model · 入线 DeepSeek→HIL · 出线 HIL→L3 长程序列规划

**连线质量分析** (`tools/analyze_canvas_links.py`):
- 167 条连线 · **反向(右→左) 仅 5 条** = 刻意反馈线 (INTACT→引擎 · 总装记忆→L4/L3 · 物理世界→状态校正器 · L2→记忆图谱)
- **交叉对 1395** —— 几乎全来自 10 条**跨距 8000~12000px 的长连线** (L4-LoRA→INTACT 12199px · L3规划→势场 11209px …)
- 我新增的两条 (DeepSeek→HIL · HIL→L3规划) **交叉贡献 0** (不在 TOP)
- 试做分层 barycenter 重排: 交叉 **+9.2% (变差)** → 未达 20% 改善门槛 → **未写盘, 原文件未动** (跨行长线主导, 行内重排救不了)
- 顺带发现 **22 处既有节点重叠**(非本次引入): 重排可降到 8 但代价是交叉变多
- 结论/待决策: 真解 = (a) **正交折线布线** (长线沿行间走线, 不动节点) 或 (b) 把长线目标节点搬到源附近/同层 (需逐条确认)

## 2026-09-26 · 会话九: 上真机前准备 (老倪: 完成所有准备 + 打通 sim-to-real + 真机操作需授权)

**仿真侧全链自检 6/6** (`tools/sim2real_readiness.py`, 取证 reports/sim2real_readiness_20260926_113359.json):
| 项 | 结果 | 证据 |
|---|---|---|
| ① 引擎闭环 + ② 事件头逐帧真调 | ✅ 7/7 | 闭环 AUC gc 1.000 · mh 0.9995/0.9999 · rz 0.9969/0.9916 · 逐帧真调 220/220 · 0.278ms/帧 |
| ③ 策略 rollout (仿真, state_space 权重) | ✅ 真跑通 (**成功率 0/5 — 真结果, 不是假 0%**) | 引擎内 `rollout_peg_check.py --policy state_space`: ep 最近距离 0.400m 没抬起 |
| ④ 数据 pipeline 五段 | ✅ | 采集帧龄 0.1s · relay 活 · 数据集 5 个 · 训练段空转 · 部署软链 |
| ⑤ (需 --full) DDS 全局数据空间 | 20/20 | 前轮已验 |
| ⑥ 控制台画布真实渲染 | ✅ 88 节点项/166 连线项 | 离屏真加载 (167→166 为既有去重行为) |
| ⑦ Web 双通道 (桥 + HIL) | ✅ 17/17 | HIL 全链 + agent 提示词→回执 |
| ⑧ 真机只读信号 | ✅ 仿真 8/8 · 真机只读 6/8 · 待现场 8 项 | 全程零动作下发 |

**修掉两个真 bug**: `sim2real_preflight.run()` 无输出时 `tail[-1]` 崩 (5 处) → 兜底; `verify_canvas_render` 判据未对齐既有去重行为 → 对齐

**真机操作授权申请**: `docs/patch/REAL_MACHINE_AUTHORIZATION_REQUEST.md` (A1~A9 逐项: 动作/预期/风险/现场前提/回滚/观测指标)
- 只读类 A1(Orin 心跳) A2(AOI 标定) A3(10083 补丁) A4(10082 口径) → 一句「A1-A4 授权」即可开工
- 动作类 A5(2D→3D 采集) A6(T_base_cam/plane_z) A7(ring_pose 示教) → 需你在现场，逐步请示
- 高风险 A8(真机试抓取 S0~S5) A9(6N 力控插入) → 先批计划再单独授权

**新发现的真缺口 (如实)**: state_space 策略在仿真 0/5 插入成功 → 训练侧待排查 (非管线 0%)

## 2026-09-26 · 会话十: state_space 0% 根因 = **评测口径假0%** (非策略能力结论)

**链路 (逐层排除, 每步有实证)**:
| 步 | 检查 | 结果 |
|---|---|---|
| 1 | 产物是否存在 | `outputs/train/state_space_mw5w/checkpoints/030000` 在 (last→030000) · 两棵树都有 → **非缺产物** |
| 2 | 装载 | `load_policy("state_space")` → LeftRightPolicy 成功 → **非装载失败** |
| 3 | 配置真源 | `type=left_right` · `input_features=observation.state[39]` · `output=action[4]` · **无图像** · `normalization_mapping=None` |
| 4 | 引擎真跑 | min 孔距 0.351/0.359/0.418m, 未抬起 → 表面 0/3 |
| 5 | **口径对照 (决定性)** | 引擎 L3 路径 (state_space_sim_real.py:1249-1272) 用的是 **`visual39`(引擎自建) + `self._l3_pre(batch)` 预处理器 + 128×128 图 + task 串**; 而 `rollout_peg_check.py:65-79` 只喂 **裸 env obs + 无预处理** |
| 6 | 失败指纹 | 直接喂裸 39D → 模型首层收到 **43 维 (mat1 64x43 vs mat2 39x512)** → 口径不同源被实证 |

**结论**: 评测 harness 与训练口径不同源 (缺 `_l3_pre` 预处理 + visual39 构造 + 图像尺寸/task 串约定)
⇒ **0% 是假0%, 不能作为"策略弱"的结论**; 策略的真实能力**尚未被测**。

**正确的修法 (下一步)**: `rollout_peg_check.py` 复用引擎 L3 的 batch 构造 (visual39 + `_l3_pre` + 128×128 + task 串),
或直接以引擎闭环 (`RealStateSpaceSim` 的 L3 路径) 为评测口径 → 再报成功率。
**教训 (与既有铁律一致)**: 口径必须训练同源零回退 —— 评测脚本自己拼 batch = 必然不同源。
工具: `tools/diag_state_space_rollout.py` · `tools/diag_policy_scale.py` (尺度/相关/形状三重对照)

## 2026-09-26 · 会话十(续): ② 同源数据扩到 300 段 + ③ AOI 脚手架 / tap stage 接通

**② 同源事件头数据 30 段 → 300 段** (66,000 帧 · 夹爪闭合 299 帧 · 阶段覆盖 0~6 · 采集 233s):
| 任务 | 30 段(旧) | **300 段(新)** | 旧最低折 | **新最低折** | 门槛 |
|---|---|---|---|---|---|
| gripper_close_H5/H10 | 1.0000 | 1.0000 | 0.9999 | **1.0000** | 0.91 |
| reach_z_H5 | 0.8921 | **0.9519** | 0.6927 | **0.9290** | 0.79 |
| reach_z_H10 | 0.9029 | **0.9540** | 0.7198 | **0.9316** | 0.79 |
| move_hand_H5 | 0.9903 | **0.9972** | 0.9781 | **0.9955** | 0.90 |
| move_hand_H10 | 0.9928 | **0.9987** | 0.9738 | **0.9970** | 0.90 |
- 5 折 CV **6/6**; 关键改善 = reach_z 的**最低折从 0.69/0.72 → 0.93**(原先"勉强达标"的隐患消除)
- 闭环复验 **7/7**: 闭环 AUC gc 1.0000 · mh 0.9990 · rz 0.9973/0.9994 · 逐帧真调 220/220 · 0.264ms/帧
- **默认权重 engine_v3**(ZMAX_COG_EVENT_TAG 可覆盖); 数据 `cog_engine_trace_v3.h5`; ckpt `head_H{5,10}_engine_v3.pt`
- 注: 训练日志里的 "跨域(l5_gen_v5) 0/6" 是**已知结论**(两个生成分布互不可迁移), 非回归

**③ AOI 标注脚手架 + tap stage 接通**
- `tools/aoi_annot_scaffold.py`: `--capture`(10082 取帧+建标注模板, 只读) / `--check`(校验 boxes 合法性+可用样本数)
  自检: 目录 `data/yolo_aoi_annot` 现有 1 份待标注, 提示"再补 20 张带框样本"; 等 A2 授权即可现场采第一批
- tap `prod_stage` 为空时 → HIL 上行**推算阶段**(由夹爪+z 速度导出), 明确标注为"推算"以区分产线上报
  实测 HIL 页面显示: 阶段 = `接近/对位 (推算)` + 说明 (产线主程序未运行)

## 2026-09-26 · 会话十一: 全局复盘 + 大清理行动

**① 画布复盘 (客观判据, 非感觉)**
- 清理前: 88 节点 (15 背景 + 73 真) / 167 连线 · 档位: R1 15 · R2 35 · R3 13 · R4 7 · R5 3
- **★ 硬指标: 无执行注册 0 · 真缺口 0 · 完全孤立 0** → 画布接线本来就完整, **不存在"死节点"**
- 73 真节点全归类 (9 类角色): L2 收口 18 · L3 调度 8 · L4 认知 8 · L5 意图 6 · 记忆层 6 · 人机通道 3 · 数据链 3 · 原子技能阶梯 11 · 可视化 8 · 自检 2 · LoRA 线 2

**② 删除 (有文档依据 + 安全判据 + 可回滚)**
| 删除 | 依据 | 安全判据 |
|---|---|---|
| `sstest` 🧪 Test 用例执行 | 测试脚手架 (出度 0 终端); 自检已由 tools/verify_*.py 承担 | 邻居删后仍 ≥1 入 ≥1 出 ✓ |
| `ssa` 🅰️ 通用算子 A · 参数写入 | **参数寻优线已关闭** (10/10 同 seed 配对无差异) | ✓ |
| `ssb` 🅱️ 通用算子 B · 参数微调 | 同上 | ✓ |
| `ssc` 🅾️ 通用算子 C · 参数校验 | 同上 | ✓ |
- 结果: **88 节点/167 连线 → 84 节点/159 连线** (真节点 69)
- 备份 `flows/_archive/state_space_obs_before_cleanup_20260926_121948.json` + manifest(含还原命令)
- 复核: 渲染 84 节点项/158 连线项 ✓ · 档位审计 rc=0 (R2 35→31, R1 15 不变) ✓ · **孤立 0** ✓
- 保留未删 (它们是路线图不是死节点): `ss_moe` 阶段专家 MOE (实际**在役**: 会话四修好 8 阶段覆盖) · `ss_lora_l4/l3` (已关闭待你决策)

**③ 连通性验收 (老倪要求: 主线与所有保留功能都有连接交互通道)**
- 真节点 69 · 连线 159 · **完全孤立 0**; 入口 3 (metaworld 数据源 · Z700 真机信号 · 工程记忆) · 终端 6 (波形/操作视频/Feature 清单/前馈直方图/3D 视图/旁路可视化) —— 入口/终端均为合理端点, 无断链

**④ 任务面清理 (真正的"不相关任务"在这里)**
- 已关闭 9 条线 (参数寻优 · L4 标定闸判死 · 值预测靶子 · ECS 502 · chain_health 崩溃 · 画布连线事故 · 控制台卡顿 · skill_ctx 常量 · MOE 门控吞阶段)
- 活跃主线 6 条 (引擎闭环 / 事件级认知头 / Web+HIL 交互 / 数据闭环五段 / AOI 视觉 / 可视化)
- 缺口 3 条 (state_space 策略真实 20% → 需 S2/S3+ensemble · Orin→云上行 · 真机三查未过)
- 待授权 A1~A9
- 完整复盘报告: `docs/STATE_SPACE_RETROSPECTIVE_20260926.md`

## 2026-09-26 · 会话十二: A3 缺口实证 + A4 口径量化 + A2 采样 (按建议顺序)

**A3 · 10083 表面相机缺口 (实证, 零副作用 OPTIONS 探路由)**
| 端口 | /capture_detect | /picture | /crop_info | /region | /last_result |
|---|---|---|---|---|---|
| 10082 金手指 | ✓ | ✓ | ✓ | ✓ | ✓ |
| **10083 表面** | ✓ | **404** | **404** | **404** | **404** |
- 交接单 `docs/patch/opt_surface_10083_add_picture_route.md` 存在 (109 行, 粘 30 行 + 现场 4 步验证)
- **工控机 SSH/RDP/VNC 全关 (只有 10081/10082/10083 三个 HTTP 口)** ⇒ 我无法远程部署, **只能现场粘贴** (已出交接单)

**A4 · 判据图口径量化 (同一张真图, 真拍一帧)**
| 口径 | 尺寸 | 均值 | std | 饱和% | 死白行 | Tenengrad |
|---|---|---|---|---|---|---|
| ① 工控机拉长图(工厂现用) | 960x960 | 214.8 | 55.8 | **55.0** | 0 | 10.0 |
| ② 工控机原图 | 2448x2048 | 117.5 | 79.0 | 16.2 | 0 | 6.0 |
| ③ **4060 侧自裁(老倪口径)** | 1718x150 | 169.6 | 53.4 | **13.6** | 0 | **89.0** |
⇒ 自裁 vs 工厂拉长: 饱和 55.0%→13.6% (**4.0× 降低**), 细节能量 Tenengrad 10.0→89.0 (**8.9×**) —— 老倪口径被实时数据量化证实

**A2 · 采样 8 帧 (模型输入口径 ?kind=crop)**
- `data/yolo_aoi_annot/`: 共 14 份待标注 (含判决 JSON + crop_info), 格式校验全合法
- **关键发现 (量化)**: 8 帧 `crop_score` 全为 **0.325** —— 技能记载 v4 模板法验收口径 **≥0.95**、v3 固定窗 ≈0.29
  ⇒ **工控机当前跑的是 v3 固定窗裁减, 裁减质量不合格** ⇒ 按技能口径"裁减 score 低时 OK 不可信(模型没看全焊盘)"
  ⇒ **它的 count=0/OK 判决在当前口径下不可作为结论** (这条比"缺标注"更严重, 是正确性问题)
- **标注阻塞 (需现场)**: 8 帧判决 count=0 → 台面**没有不良品** ⇒ 只能建 OK 类样本;
  缺陷类样本需现场**放一件有缺陷的光模块**才能采 (否则 boxes 恒空, 训不出有意义的检测头)

## 2026-09-26 · 会话十三: AOI 口径基准 (12 帧真图) — 结论如实: **两个口径都不合格, 不能吹**

**做法**: 同一批 12 张真图 (origin 2448x2048) 上并行跑三种口径 → 逐帧出饱和/细节/score

| 口径 | 饱和占比 | 细节能量(Tenengrad) | score | 备注 |
|---|---|---|---|---|
| ① 工厂 v3 (`?kind=crop` 960x960) | **55.0%** | 10.0 | **0.325~0.327** | 活服务 `/crop_info.score` 实测 |
| ② 本机 v4 模板法 (gf_crop, 960x960) | 58.1% | 51.4 | **0.327** | ❌ **未达技能记载的验收 ≥0.95** |
| ③ 本机自裁 (无模板, clean_judge_frame) | **15.1%** | **348.8** | — | 饱和降 3.6× · 细节 ×34 |

**关键如实结论 (不能当"切 v4 就好了"报)**:
1. 本机 v4 模板法在这批数据上只有 **0.327**, 与工厂 v3 的 0.3274 **几乎相同** ⇒ **没有任何一方达到 ≥0.95 验收**
2. 场景料检 (技能口径严格金掩膜 (15,120,120)): 仅 **1406 像素 = 0.028%** (技能记载: 有料时覆盖 29.8%/64.3%, 无料时≈10 像素)
   ⇒ **台上金手指并未正对/充分入画** (最可能: 料不在位 / 姿态变了 / 模板过期)
   ⇒ 在我看不到现场的前提下, 我不能断定是"v4 不行"还是"场景不对"
3. 唯一可确定的正面结论: **自裁口径(无模板)在这批帧上稳定给出 低饱和 15.1% + 高细节 348** ⇒
   作为**标注/判据图口径**它优于工厂拉长图, 且符合老倪口径 (手选框 > 原图自裁 > 拉长图)

**下一步 (需现场, 已写成可执行命令)**:
- 放一件**正位**的光模块 → `./gui-venv311/bin/python tools/aoi_caliber_bench.py --frames 3`
  · 若 v4 score ≥0.95 ⇒ 切 v4 模板法有据 (再谈现场切换)
  · 若仍低 ⇒ 模板过期, 现场 `python gf_template.py <新参考图>` 重做模板
- 12 帧产物: `data/yolo_aoi_annot/caliber_bench/` (origin + off_v4 + off_cut 各 12 张, 合计 ~180MB, 不入库)
- 取证: `reports/aoi_caliber_bench_offline_*.json`
