---
name: cross-venv-model-canvas-node
description: "Use when 外部venv模型要封装成画布节点 (跨venv子进程桥)."
version: 1.0.1
author: Hermes Agent
license: MIT
tags: [zmax, canvas-node, subprocess-bridge, venv-isolation, model-integration, paper-checkpoint]
metadata:
  hermes:
    tags: [zmax, canvas-node, subprocess-bridge, venv-isolation, model-integration]
    related_skills: [hermes-agent-skill-authoring, pyqt5-gui-development, zmax-console]
---

# 跨 venv 模型 → 状态空间画布节点封装

## When to Use

老倪给了个外部项目 (如 `zju3dv/INTACT-JEPA`)，要求在状态空间画布某层加节点，
"完全封装在节点中"，输入走数据源层 (数据可再下载)、输出直连机器人硬件 (接口可预留)，
先调试通再适配当前档位。**也适用于**: 任何"外部 venv 里的模型/算法要接进本工程"的场景
(依赖冲突、torch 版本不同、需要特定运行时)。

**核心结论 (先说)**: 依赖冲突时**不要**把外部项目装进 GUI 工程的 venv。
正确形态 = **子进程桥**: 外部项目自己的 venv 里跑常驻 worker，用行式 JSON 协议通信；
节点侧只认协议，不认实现。实测 INTACT (torch+Hydra+stable_worldmodel) 与 GUI venv 不兼容，桥接一次成功。

## 0. 先读源码拿"部署契约" (不要凭 README 想象)

必须从源码挖出这 4 件事，否则接口一定错：
1. **推理入口签名** — 例: `jepa.py::JEPA.get_action(info, horizon)` (不是 `forward`)
2. **输入字典键与形状** — 例: `pixels[T,C,H,W]` / `goal[C,H,W]` / `action[T,D]`；`goal_*` 前缀键会被改写
3. **特殊 reset 语义** — 例: 动作历史必须 **raw 零**初始化 (在 normalizer 之前)，否则静默出垃圾
4. **诊断字段** — 例: `last_direct_diagnostics{intent_norm, forward_calls, candidate_sequences}`；这是"零搜索"类主张的唯一凭据

同时确认**官方加载路径** (别自己拼 hydra): 例 `swm.wm.utils.load_pretrained(policy)` + `set_actor_warmstart(True)`，
见官方 `eval.py:135-146`。自己拼配置会撞 `ConfigAttributeError: Missing key load_state_dict`。

## 1. 节点骨架 (对外只 4 个方法，内部全封装)

```
set_data_source(数据源层) → set_goal(goal帧|waypoint) → step() → action chunk[H,D] → attach_robot(RobotIO)
```
落地文件 (以本仓库 INTACT 为模板，路径可直接抄)：
- `src/lerobot/manifold/<name>_node/contracts.py` — 契约 + `build_info_dict()` (逐键对齐源码) + `zero_action_history()`
- `.../data_source.py` — 注册表 `register(name, factory)` + 官方数据下载器 + 本仓库 episode 读取器
- `.../robot_io.py` — `RobotIO` 抽象(`send_chunk/reset/estop`) + `SimRobotIO`(调试) + `HardwareRobotIO`(**预留**: 构造即 `NotImplementedError`，绝不写假实现)
- `.../model_adapter.py` — 子进程桥客户端 (`start()` 握手 / `get_action()` / `close()`；`trained=False` 时返回零动作**并给 reason**)
- `.../node.py` — 节点本体 (滑窗 + 动作历史滚动 + 诊断统计 + `describe()`)
- `.../selftest.py` — 全链自检 (真断言，含 `trained=False 必给 reason` 一条)
- `tools/<name>_worker.py` — 跑在外部项目 venv 里的常驻 worker

## 2. 子进程桥协议 (行式 JSON)

> 可直接抄的最小 worker/adapter 骨架 + 冻结运行时启动器: `references/bridge-protocol.md`

命令: `hello`(懒加载, 返回 `{ok, trained, dims, reason}`) / `act`(大数组走临时 `.npz`，只传路径) / `reset` / `bye`。
- **大数组不要塞 JSON** — 写 `/tmp/xxx_in.npz` 传路径 (224×224×T 级别的张量)
- `hello` 超时给足 (首次含 HF 下载 + 权重加载，给 30 分钟)

## 3. 三处注册 (少一处节点就是死的)

1. `flows/state_space_obs.json` — 加节点条目 `{id, type, name, x, y, w, h, icon, color, params{desc,...}}`
   (文本级插入，保持原缩进风格；**不要** json.load+dump 重写整文件，diff 会炸)
2. `tools/gui/state_space_sim_real.py` — 引擎 io 通道 (数据总线上要有输入/输出两行)
3. `tools/gui/node_logic.py` — 可修改区写 `def node_x(ctx)` (`log = ctx["log"]` … `return True`) + 注册区 `_reg("x", ["关键字"], "说明", node_x)`
- `NODE_TYPES` 若已有合适 type (如 `model`) 就复用，不新增
- 验证: `match_node("<节点名>")` 返回 key + `json.load(flow)['nodes']` 能看到 + `compile_ok`

## 4. 权重解析 (跨会话共用缓存，禁止重复下 GB 级数据)

三级解析，写进 worker：
1. `--ckpt` / `$INTACT_WEIGHTS` 显式路径
2. `$STABLEWM_HOME/checkpoints/<policy>/weights_epoch_*.pt` (别的会话已解包的)
3. HF 资产包下载 + 解包 (默认 `HF_ENDPOINT=https://hf-mirror.com`，国内)
- **先看 HF 仓库树** (`https://hf-mirror.com/api/models/<repo>/tree/<rev>`) —— 实际常是 `*.tar.gz` 包 (~315MB)，
  包内路径用仓库里的 `checkpoints/*MANIFEST.json` 确认，别猜文件名 (猜 = 404)
- **校验两条**: 资产包对 `SHA256SUMS`，包内 `.pt` 对 manifest 的 per-shard sha256 (实测能对上)

## 5. 论文/历史 checkpoint 的冻结运行时 (最容易翻车)

官方发布的研究 checkpoint 常**不能**用当前根运行时加载 (参数布局已变)。判据：
- 仓库有 `paper_runtime/` 或 `compat_runtime/` 目录 → 读它的 `README.md`
- INTACT 原文: *"loading paper checkpoints through the root runtime is not supported"*，
  且**根仓库故意省略 paper launcher，留给"外部适配器"**
- 做法: 该目录置于 `PYTHONPATH` **最前** + `chdir` 到它 + 显式 `import sitecustomize`
  (确定性 Math-SDPA / `CUBLAS_WORKSPACE_CONFIG`)，必要时只**新增** config 文件
- **红线**: `RUNTIME_SHA256SUMS` 钉住的文件一个字节都不许改；跑前 `sha256sum -c`，把它当证据贴出来

**求解器/配置也要跟着换 (实测踩坑)**:
- 求解器可能**不是**根仓库那个: INTACT 根 `direct_solver.py` 检查 `has_intent_actor()`，
  而论文运行时 actor 名为 `inverse_actor` → 抛 `RuntimeError: Direct evaluation requires a
  trained intent actor`。正解 = 用论文运行时自带的 `prior_only_solver.PriorOnlySolver`
  (内部直接 `model.get_action(info, horizon)`，`get_cost_calls/candidate_action_steps/
  configured_rollout_budget` 全置 0 = 论文的零搜索接口)，并**新增** `config/eval/solver/prior_only.yaml`
- 配置键也可能缺: 根配置有 `eval.actor_warmstart`，论文配置没有 → 传了会 `KeyError:
  'actor_warmstart' is not in struct`。别硬传，走 `OmegaConf.select(..., default=True)` 默认
- **数据完成判据**: `size + SHA256` 双核 (HF 的 `lfs.oid` 就是文件 sha256; `/tree` 常不给 `lfs.sha256`)
- 汇总口径: 单训练种子权重 → 对照官方*同训练种子*那一行，别拿"多训练种子均值"当自己的靶子

## 6. 坑 (全部实测踩过)

| 坑 | 症状 | 修法 |
|---|---|---|
| 库日志污染 stdout | 桥返回 `Extra data: line 1 column 3` | worker 启动**最先**做: `_PROTO = os.fdopen(os.dup(1), "w", buffering=1); sys.stdout = sys.stderr`，协议只走 `_PROTO` |
| `HF_ENDPOINT` 设晚了 | 镜像不生效、直连超时 | 必须在 `import huggingface_hub` **之前** `os.environ.setdefault(...)` |
| `pkill -f <pattern>` | 把自己的 shell 也 SIGTERM 了 (模式匹配到自身命令行) | 一律按 PID `kill <pid>` |
| 自己拼 hydra 配置加载权重 | `ConfigAttributeError: Missing key ...` | 走官方 `load_pretrained` 路径 |
| eval 顶层 `get_cost_calls` 是 0 | 被当成"零搜索"证据，其实是**回退默认值** | 报 `solver_timing.get_cost_calls_mean` / `candidate_sequences_mean` (实测 0 才算) |
| tar 包解压路径 | 找不到 `.pt` | 包内路径相对**缓存根** (含 `checkpoints/` 前缀)，解压目标 = `$CACHE` |
| 官方脚本 `python: command not found` | preflight 直接挂 | `export PATH=<repo>/.venv/bin:$PATH`；`STABLEWM_HOME` 要**导出**(脚本不读 `.env`) |
| 数据集只差几百 MB 却慢 | 镜像/直连都 ~100KB/s (本机国际带宽瓶颈) | 先测国内源确认是全局慢；换 source 无用 → 等或切网络 |
| **hf-mirror 回 308 重定向** | Python 3.10 `urllib` 报 `HTTPError 308`；`hf_hub_download` 卡在 0 字节 | 自定义 `HTTPRedirectHandler` **两处都要补**: `http_error_308 → http_error_302` **且** `redirect_request` 里把 308 当 307 (3.10 白名单只有 301/302/303/307) |
| 多连接下载的"文件大小"不可信 | 报"剩 500MB"实际剩 6.9GB；按大小判完成会解压出**截断的假数据** | 完成判据 = aria2 自有账本/退出码 + `size` + `SHA256` 双核；空洞可用 `dd ... \| tr -d '\0'` 抽样验证 |
| 两个下载进程抢同一文件 | 聚合速率暴跌 (2MiB/s → 40KB/s)，还有写坏分片风险 | 单写者纪律: `pgrep -x aria2c` 只留一个; 多会话在共享目录写 `README_COORD.md` 协商归属 |
| 大资产装不下 | 例如 cube 46GB/reacher 24GB 压缩包 | 流水线加**磁盘闸门** (需 2.6×压缩包+余量) → 不足就诚实跳过并记录, 不硬下 |
| 模型返回带 batch 维 | 节点侧 `[1,H,D]` 与 2D 动作历史 `concatenate` 报维度错 | 统一裁成对外契约 `[H,D]` |
| 目标帧维度不足 | ViT `batch_size, num_channels, height, width = pixel_values.shape` → `expected 4, got 3` | 目标帧给 **5 维** `[B,T,C,H,W]` (模型内部会把 goal 直接喂编码器) |
| 节点输出恒定 | 每步 chunk 完全一样 | **动作历史必须由节点持有并滚动注入** (数据源每次给的是 raw 零 reset 语义) |
| **零动作回退冒充成功** | `trained=True` + chunk 形状对 + 全零, 自检只看形状/有限性就通过了 | 节点层**硬闸**: adapter 标 `act_failed`/`trained=0` 时**必须 raise**; 自检加"非零 + 非常量 + 随观测变化"判据 |
| **计数 > 0 冒充"真接入"** | A/B 影子臂 `calls=60` 看着像"真推理 60 次", 实际每帧抛 `ValueError` 空转 (计数照涨) | 判据必须**同看** `err` / `reuse` / `u_ff_src` / `goal_src`: `reuse≈calls×(chunk−1)` 才是真按 chunk 节拍推理; `err` 非空 = 全废 |
| **未设 `STABLEWM_HOME` 时桥退回 `<repo>/.cache`** | 本工程权重 (`$SHARED/checkpoints/*`) 全部 `FileNotFoundError: Checkpoint not found` (引擎/桥都显式导出了该变量 → 只有"直接跑节点"才踩到) | adapter 启动 worker 时: `STABLEWM_HOME = $STABLEWM_HOME or (<共享缓存> if isdir else <repo>/.cache)`, 别默认 repo 内 `.cache` |
| **`goal_displacement` 无 goal 帧** | 引擎"直喂帧"路径 (`step(fr, obs_source=...)`) 每帧 `ValueError: goal_displacement 模式需要 goal 帧` | 节点加 `ensure_goal()` 三级兜底: 已 `set_goal` > 数据源自报 goal > 默认目标帧文件; 兜不到才显式报错 (别静默出垃圾) |
| worker 异常原因不可见 | adapter 丢弃 stderr, 只看到一句 message | worker 失败时把 **traceback 尾部**拼进 `reason` |
| **`--device` 默认值吃掉调用方的 env** | adapter `device="cuda"` 且**总是**传 `--device` → 调用方设 `INTACT_DEVICE=cpu` 无效, 探针去抢训练显存 | `device: str\|None = None`;**只在显式设置时**才加 `--device`, 否则让 worker 读 env |
| **hf_rev=paper-* 时默认走 paper 运行时** | 本地微调权重 (根运行时训的, action_dim=8) 加载报 `InstantiationException: Error locating target 'module.IntentActionActor'` (论文运行时没有这个类) | adapter 里定规则: `$INTACT_RUNTIME` 优先 → 否则"设了 `INTACT_POLICY`(本地 ckpt) → root" → 都没有才 None (官方 HF paper 资产走 paper) |
| 评测结果文件名逐任务不同 | 成功的评测被误报"未产出结果" | 从 `config/eval/<task>.yaml` 的 `output.filename` 取, 不要猜 |
| sidecar 被下一个 seed 覆盖 | 丢 per-seed 结果 | 每次跑完**立刻**复制到自己的结果目录; 补救 = 从运行日志恢复并标 provenance |

## 7. 诚实纪律 (老倪红线，违反=白做)

- 权重/依赖缺失 → `trained=False` + 明确 `reason`，**返回零动作也不返回假动作**
- 引擎侧未接入就写"未接入"，**不许**写占位数值冒充
- 输入是合成/占位数据时，自检里打印"⚠️ 诚实标注: 合成图, 仅链路自检"
- 引用外部数字 (如官方 SR 80.22%) 必须标注来源文件 (`PAPER_E5_GOAL_MANIFEST.json`)

## 8.4 分层原则: 桥 / 节点 / 解码 / **编排服务** (v5.5.43 老倪: "这段应该放到 src/lerobot/policies")

老倪会直接看代码落位: "外部项目引用过来还是沿用? 先封装个桥接?" —— 正确回答是**沿用外部仓库 (一字不改) + 桥**,
但**编排逻辑必须下沉到 policy 层**, 不能在 GUI 里 (否则换数据源/换权重/批量评测都得改界面)。

```
GUI (node_logic.py)                    ← 只留瘦调用: 取单例 → run_once(log=ctx["log"]) → to_panel()
src/lerobot/policies/<m>/service.py    ← 编排: ensure_ready(建桥+接数据源, 兜底要写 note) / run_once(真推理+解码+证据+日志) / bridge_status / describe / close
src/lerobot/policies/<m>/runtime/      ← 桥 (model_adapter: 子进程) + 节点 (node: 滑窗/历史/诊断) + 契约
src/lerobot/policies/<m>/decoder.py    ← 输出 → 下游可消费条件 (标定缺失必须拒绝并计数)
```
判据: 编排层要有 `IntentReport` 这类**唯一结果对象** (带 `to_dict()/log_lines()/to_panel()/evidence()`),
面板/日志/报告/证据全从它出 → 不会出现两套数字。E2E 必须能**不经 GUI** 跑通 (一条命令 + 断言表)。

## 8.5 潜空间导出 + 真实性前置 (Step 0, 2026-09-12 实测)

要"把外部模型的潜空间接出来"时按这套做 (INTACT 已验证):

1. **截获, 不要重推**: worker 里包裹 `model.encode` (实例属性遮蔽), 调 `get_action` 时它会内部
   调 encode (obs 一次 / goal 一次) → 拿到 `info["emb"]` 原值, 与动作律实际吃到的潜变量**逐位一致**;
   `finally: del model.encode` 恢复。重推一遍 = 多一次前向 + 可能与内部路径不一致。
   ```python
   _rec, _orig = [], self.model.encode
   def _spy(inf):
       out = _orig(inf)
       if isinstance(out, dict) and torch.is_tensor(out.get("emb")): _rec.append(out["emb"].detach())
       return out
   self.model.encode = _spy
   try: actions = self.model.get_action(info, horizon=H)
   finally:
       try: del self.model.encode
       except AttributeError: pass
   ```
2. **通道顺序**: 引擎渲染帧是 **HWC**, 模型要 **[T,C,H,W]** → 不转置会报
   `ValueError: ... Expected 3 but got 224`。在契约构造函数里加防御 (末维∈{1,3,4} 且第 1 维不是)。
3. **观测来源必须可溯源**: 外部节点的数据源常是"依 meta 合成的运动序列"(本仓 npz 只有 `meta`,
   无渲染帧)。拿合成观测喂模型 = 蒙眼 = 假结论。做法: `step(obs_frame, obs_source=...)`,
   传真实渲染帧标 `engine_render`, 走数据源则取数据源自报的 `obs_mode` (如 `synthetic_from_trace`),
   **逐帧带在输出里**并显示在面板/报告。
4. **引擎帧数 ≠ 步记录数**: 渲染帧只在渲染步追加 (1630), 而 tr 每步都记 (4692) → 不可按下标对齐;
   按比例映射阶段名并**标注"估算"**, 不要假装逐帧对齐。
5. **动作空间不是截取是标定**: 官方动作维 (如 10) ≠ 本工程动作维 (4D)。适配层默认
   `enabled=False`, 未标定 (`models/<name>_action_map.json`) 时**拒绝返回数值**只给 reason;
   标定要用真实数据拟 (同 L3 的 `u_ff = act × K_ACT` 口径), 不许写死。
6. **推理设备**: 与同机训练共存时 `INTACT_DEVICE=cpu` (实测 ViT-tiny 单步 ~330ms, 够做取证);
   GPU 是稀缺资源, 别为探针抢训练显存。
7. **验收闸 (五道, 全过才算)**: chunk 非零 且非常量且随观测变 / 潜空间维度对且非零 /
   |z_goal−z_t| 与进度的 Spearman ρ<0 / 观测来源全 = 引擎渲染 / `candidate_sequences==0` (零搜索)。
   注意**退化点**: 若 goal 帧取的就是末帧, 末点 |Δ|≡0 是构造性的 → 判据要用剔除末点的 ρ,
   并如实说明"弱负相关/非单调"而不是宣布"单调下降"。

## 8.6 外部模型输出接本工程动作/流形 (Step 1/2, 实测两负一正)

外部论文权重是**别家任务**训的 (INTACT = pusht/cube), 接进本工程前必须过两道拟合闸:

1. **配对数据必须"同帧四路"**: 一帧同时记 (外部模型输出 + 潜空间) × (本工程真值: 参考动作/流形/观测)。
   用 `_frame_sink` 采引擎真渲染帧, 跑完再逐帧喂外部模型 → 保证时间对齐; 别拿两次不同跑的数据拼。
2. **拟合口径 (踩坑修正)**: 192 维潜空间 + 几百样本 = p≈n → 岭回归 train R² 0.4~1.0 / test 全负 /
   CCA≈1.0, 全是过拟合假象。正确做法: **训练折内 PCA(16) → 岭 → 留一轮交叉验证 (LOSO) → 打乱标签
   null 对照**; 近常值维 (如 eta 恒 1.0) 会算出 −1e7 的假极端值 → R² 加双闸 (绝对 std + 相对 std·|mean|)。
3. **闸值裁决**: 动作映射中位 R² ≤ 0.05 → **不写映射文件** (写不出来还硬用 = 假接入);
   流形可解码性逐维判 (R²>0.3 且 null<0.1 才算真信号) → 只有通过维允许进流形, 其余维先做
   z→本工程潜空间对齐映射 (Procrustes/蒸馏)。实测 INTACT: 动作映射 −0.147 (失败), 流形 rem/dperp
   0.65/0.63 通过、progress/risk/V 不可解 ⇒ "部分可解码"才是常见真相, 别期待全通。
4. **引擎侧三档接线 (可复用写法)**: `SS_X` 不设=现状 / `SS_X_SHADOW=1`=真推理真记录不接管 /
   `=1`=接管; 接管前先查适配层 `enabled`, **未标定 → 保持原动作但计数 + 记录来源** (静默回退=假接入);
   阶段白名单默认排除敏感相位 (如"插入"), gripper 等离散维仍交回状态机。
5. **两个必踩的坑**: (a) 目标帧必需 —— goal_displacement 意图不给 goal 帧 → 节点每帧抛
   `goal_displacement 模式需要 goal 帧`, 影子臂 0 次真推理; 解法: 先跑基线轮取**末帧**(任务完成态)当 goal。
   (b) 影子档不应依赖标定 —— 否则未标定时影子臂什么数据都拿不到 (实测 1172 次"未标定拒绝"、0 次真推理);
   影子允许未标定真推理, 只是不接管。
6. **A/B 裁决必须看"真接管次数"**: 若 C 臂 success 与 A 相同但 `intact_calls=0`, 那只是"管线通+守卫生效",
   **不构成"接管不回退"的证据** —— 报告里要这么写, 不要写成红线通过。

## 8.7 调试跨 venv 模型 (VSCode 断点必读, v5.5.45 实测 · v5.5.53 补权重指针)

**debugpy 只停它自己 launch 的那个进程** —— 桥是子进程, 所以:
- 调试**本工程侧** (编排/解码/节点): 用本工程 venv 起脚本 (如 `tools/intact_service_e2e.py`), 断点打在 `policies/<m>/**` ✓。
- 调试**外部仓库模型侧**: 必须换 **外部 venv 的 python** 起一个 **in-process** 驱动器 (import 外部 venv 里的 worker 模块,
  直接 new 它那个 Runtime 类并调 `load()/act()`), 断点才命中 `/home/ubuntu/<外部仓库>/**`。
  驱动器模板: `tools/intact_worker_debug.py` (同一 Runtime 类, 不重写推理)。
- **真输入不造假**: 桥侧支持 `INTACT_KEEP_INPUT=1` → 把 worker 收到的真实输入 (真渲染帧 + goal + 动作历史) 留档成
  `reports/intact_last_input.npz`, 驱动器重放它。**没有留档就只单步 load(), 并如实说"没跑 forward"**。
- VSCode 配置文件 (`.vscode/launch.json`) 若由 GUI **右键重写**: 新的调试配置必须同时写进那个生成器模板,
  否则下次右键就被抹掉 —— 加回归 (打桩 Popen 调一次 `open_in_vscode`, 断言配置条目全在)。

### 权重别写死轮次 —— 用「稳定指针」(v5.5.53 实测踩坑修)

症状: 4 个调试配置把 `INTACT_POLICY` 写死成 `..._v4_s3072/weights_epoch_2.pt` → 续训换名 (v5→v6→v6r2) 或被磁盘守护
清掉旧轮后, 配置**静默指向过期模型**, 你调试出来的数字根本不是当前的 (老倪: "把调试配置先改好")。

做法 (利用官方加载器的"文件夹"格式):
1. `checkpoints/<稳定名>/` 放 `config.json` + **恰好一个** `weights.pt` (软链 → 当前权重)。依据官方
   `stable_worldmodel.load_pretrained` 解析规则: ①`*.pt` 文件(同目录要 config.json) ②**文件夹**(恰好一个 .pt + config.json,
   多个 .pt → `ValueError: Ambiguous checkpoint`) ③否则当 HF repo id —— 相对路径都相对 `<cache>/checkpoints/`。
2. 配置里只写 `<稳定名>`; 换模型 = 换软链 (`bash tools/l4_use_ckpt.sh [轮次关键字] [epoch]`, 默认最新轮次最新 epoch)。
3. **上线前必须验等价**: 指针 vs 显式路径跑同批帧, 逐维 MAE/std 必须**逐位相同**才算指针有效 (不能只看"加载成功")。
4. 自检闸: `tools/check_debug_cfg.py` —— 查 4 个配置都指指针 + runtime/device 对 + 指针目录符合官方文件夹格式 +
   软链不断 + **模板与 launch.json 一致且无写死轮次**。
5. 同一个坑还有第二处: GUI 里选 L4 档时设的**默认权重** (simulink_module.py 的 `os.environ.get("INTACT_POLICY", <默认>)`)
   往往也是写死的老轮次 —— 它会决定"点运行"实际加载哪个模型。改指针的同时把**写死的判闸标注**一并改成动态
   (读指针实际指向 + 把结论指向 judged/*.json), 否则那些数字会随训练变假话 (老倪红线)。
6. 提醒用户: 调试配置改动**立即生效**, 但 GUI 源码里的默认值要**重启控制台** (GUI 改码必重启)。

### 断点打上却不进? 先看调用路径, 别怀疑断点 (v5.5.53/54 实测)

引擎(画布"运行")与 policy 层服务是**两条并行实现**, 同一个功能各写一份: 引擎侧 `state_space_sim_real.py::_l4_intact_u_ff`
直接 `self._intact_node.step(...)` + 自己 `IntactIntentDecoder().decode(...)`, **完全不经过 `service.run_once`**
(后者只被"双击节点"/E2E 驱动调用)。所以"点运行"永远进不了 `run_once` 的断点 —— 不是断点没生效。
定位手法: `grep -rn "run_once\|get_service(" tools/ src/` 列出**所有**调用点, 对照你点的那个入口走哪条。
顺带结论: 这种双实现会漂移 (一处 cond_dim=6 写死、一处走 decoder 单例) → 面板长期标"未接入"。

### 运行路径必须喂 skill_ctx (skill_dim>0 的 ckpt 会硬闸拒绝, v5.5.54 实测)

现象: 模型直驱/L4 档 "跑不动", 错误 `ValueError: checkpoint was trained with a skill channel (skill_dim>0)
but info['skill_ctx'] was not provided — refusing to silently degrade` → **真推理 0 次** (被吞成"模型能力差")。
真因: 训练数据带 24 维 skill_ctx, 运行路径没构造没传。修法 (老倪 09-14 "让 L4 看到 L2 原子技能"):
1. 构造**只能用一个**入口: `src/lerobot/policies/intact/skill_ctx.py::build_skill_ctx(process, x_hand, stage, grip)`
   (训练数据/闭环必须同口径, 有 `tools/skill_ctx_consistency_check.py` 做逐位回归)。
2. `process` = `MemoryLayerBridge.from_real_data(root=…, seed=…, use_engine_geom=True).process`; **同一份**
   `muscle_memory.json` + 引擎几何。取不到就退化成"相位+夹爪"并**如实打印**, 不假装有记忆层。
3. `x_hand` **必须**是夹爪真实位置 (引擎 `self.x = obs[0:3]`), 不是 `peg_head()`; `grip` = 引擎控制向量 `u[3]`。
4. 链路: 运行侧每帧 `service.run_once(..., node=引擎节点, obs_frame=真渲染帧, skill_ctx=sk)` — 节点/帧/逆归一化口径不变,
   只把编排收归一处; 这样"点运行"也会经过解码器 (u_ff 先验 + L3 条件 + 证据落盘) 与你的断点。
5. 验收判据 (真接入, 不许看形状): 真推理次数 > 0 且 `u_ff_src` 是解码器口径 (如 `intact(chunk×K_ACT=0.5)`)、
   `skill_ctx` 维度=24 且非零项 > 0 (`L2 势场就绪=True`)、证据 JSON 落在**工程内** `reports/`。
   ⚠️ 顺手查一个坑: 服务 root 解析写错层级 (往上跳两级) → 证据被写到 `/home/ubuntu/reports/` (工程外); 判据里带上路径。

## 9. 验收顺序

1. `selftest` (stub): 形状/有限性 / RobotIO 逐步下发步数 / 诊断键 / `trained=False` 有 reason
2. 画布逻辑真调: `node_logic.node_<x>({"log": print, "root": <repo>})` → True + 打印 chunk 形状
3. 真权重 (S2-real): `INTACT_RUNTIME=paper` → `trained=True` + dims (例: `action_dim=10, history_size=3, img_size=224`)
4. 官方评测 (S1): 出 SR + 零搜索计时 → 才谈适配 L4 (S3, 同口径 A/B 不回退)
