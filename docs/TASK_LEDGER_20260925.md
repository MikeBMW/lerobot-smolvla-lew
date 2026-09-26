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
