# Z-MAX · L4 INTACT 策略化 + 连线设计 (metaworld → INTACT → decoder → L3)

> 2026-09-13 · 老倪指令：「将 INTACT 接入到 L4 层 … 原来已经作了 L4 节点，现在将 L4 节点的 INTACT 代码
> 迁移到 src/lerobot 的 policies 文件夹，你来做好连线连接。数据源直接接入 metaworld，输出接一个
> decoder，再进 L3，你来分析，设计架构，适配提升能力；注意，不能让原有 L2 L3 能力下降，增加 L4
> 只能提升能力。」
>
> 前身文档：`docs/design/zmax_intact_node.md`（节点封装期）、`zmax_intact_alignment.md`（对齐/标定期）

---

## 1. 一句话结论

INTACT 从"一个孤立画布节点（无连线、手工挂载）"变成 **L4 层的可插拔策略**：
代码进 `src/lerobot/policies/intact/`（lerobot 策略契约），数据源直连 metaworld 真环境，
输出经**意图解码器**分两路进 L3（u_ff 先验 / 流形条件），L2/L3 执行路径**逐项零变化**（有实测证明）。

---

## 2. 改动前的真实问题（先诊断，再动手）

| # | 问题 | 证据 |
|---|---|---|
| 1 | INTACT 节点是**孤岛**：画布上有 `ssintact`，但 `links` 里**没有任何连线** | `flows/state_space_obs.json` 断链检查（改动前 80 条连线无一条指向 ssintact） |
| 2 | 实现放在 `src/lerobot/manifold/intact_node/`，**不是** lerobot 策略，无法被 `get_policy_class`/`make_policy` 等标准路径使用 | `policies/factory.py` 无 intact 分支 |
| 3 | 数据源是"官方数据 / 本仓 npz 合成观测"，**不是** metaworld 真环境 | `data_source.py` 只有 `official`/`l4_episode`；合成观测 = 蒙眼做结论 |
| 4 | 输出只到 `u_ff` 槽位（还要先过**未标定**的动作映射，实测 refusal 1172 次 / 真接管 0 次） | `ab_intact_uff_20260912_150943.json` verdict |
| 5 | 没有"L4 → L3"的任何通道 | L3 链路 `ssvlm → ssmani_c/p → ssdec` 与 INTACT 无交集 |

---

## 3. 目标架构（数据流）

```
            ┌────────────── L4 行 (只在 L4 档执行, 档位过滤 cap=4) ──────────────┐
            │                                                                    │
  📦 metaworld 数据源 ──真渲染帧224²+39D──▶ 🎯 INTACT 策略 (零搜索) ──意图/潜空间──▶ 🎯 意图解码器 │
  (MT1 peg-insert-side-v3)   (runtime/metaworld_source.py)   (modeling_intact.py)   (decoder.py)  │
            └────────────────────────────────────────────────┬───────────────────────┘
                                                             │ ① u_ff 先验 4D (量纲逆运算, 无需标定)
                                                             │ ② L3 流形条件 (需标定, 未标定→拒绝)
                                                             ▼
            ┌────────────── L3 行 (L3 档起执行) ───────────────────────────────────┐
            │  🧠 VLM (SmolVLA z∈R⁹⁶⁰) ─▶ 🧮 接触/性能流形 ─▶ 🎯 DiT Action Head ─▶ ⚡ 前馈/执行 │
            └──────────────────────────────────────────────────────────────────────┘
```

* **u_ff 先验**进入的是 L3 的 `ssdec → ssff` **同一个融合槽位**（引擎 `u_ff`），不新增控制通路。
* **L3 条件向量**是"预备通道"：坐标系与 L3 的流形节点（`ssmani_c/ssmani_p`）**同源**，
  但必须先用真实配对数据标定出 `z_INTACT → 流形坐标` 的映射（`models/intact_l3_map.json`），
  未标定则解码器**拒绝返回**（计数 + 记来源），绝不写死映射。

---

## 4. 代码落位（迁移）

```
src/lerobot/policies/intact/
├── __init__.py               # 包出口 (IntactConfig / IntactPolicy / IntactIntentDecoder / MetaWorldSource)
├── configuration_intact.py   # IntactConfig (PreTrainedConfig.register_subclass("intact"))
├── modeling_intact.py        # IntactPolicy (PreTrainedPolicy 外壳, 推理-only, 懒建桥)
├── decoder.py                # IntactIntentDecoder (L4 → L3)
└── runtime/                  # ← 由 src/lerobot/manifold/intact_node/ **整体迁入** (实现一字未改)
    ├── contracts.py  data_source.py  model_adapter.py  node.py  robot_io.py
    ├── action_adapter.py  selftest.py
    └── metaworld_source.py   # 新增: 数据源直接接入 metaworld
src/lerobot/manifold/intact_node/__init__.py    # 仅剩兼容转发 (旧引用零改动)
```

* 迁移动用 `git mv`（保留历史），包内相对导入不变，因此**桥/自检/引擎的 import 全部照旧**。
* 新增 `MetaWorldSource` 并注册为数据源名 `metaworld`（`registry.names()` 实测 `['l4_episode','metaworld','official']`）。
* 策略注册三处：`policies/__init__.py`（导出配置）、`factory.get_policy_class("intact")`、`PreTrainedConfig` 子类注册。
* **诚实边界**：`IntactPolicy.forward()` 显式 `NotImplementedError` —— INTACT 权重训练在
  INTACT-JEPA 的冻结运行时（`paper_runtime`）里做，本仓库不假装能训；`get_optimizer_preset()` 返回 `None` 同理。

---

## 5. 连线实现（画布 + 引擎）

### 5.1 画布（`flows/state_space_obs.json`，文本级编辑，节点 76→77 / 连线 80→83）

| 连线 | 来源 → 目标 | 语义 |
|---|---|---|
| `lkild1` | `ssdata` → `ssintact` | metaworld 真渲染帧 224² + 39D（**数据源直接接入**） |
| `lkild2` | `ssintact` → `ssintact_dec` | 意图/潜空间/动作块（零搜索） |
| `lkild3` | `ssintact_dec` → `ssdec` | L4 条件 → **L3** DiT（未标定则不注入） |

新增节点 `ssintact_dec`（🎯 INTACT 意图解码器）**与 `ssintact` 同在 L4 行内（cap=4）**，
所以 L2/L3 档根本不会执行它们 —— 这是"不回退"的结构性保证，不是靠代码里 `if`。

### 5.2 引擎（`tools/gui/state_space_sim_real.py`）三档，与既有 `SS_INTACT` 同一纪律

| 环境变量 | 行为 |
|---|---|
| （不设） | **现状路径**：整段代码不进入 → 与改动前逐位相同 |
| `SS_L4_INTACT=1 SS_L4_INTACT_SHADOW=1` | 影子：真渲染帧 → INTACT 真推理 → 解码器真解码 → 记录（不接管） |
| `SS_L4_INTACT=1` | 接管：`u_ff = (1−w)·analytic + w·L4`，`w=0` 时**恒等**（原值不变） |

* 阶段白名单默认与 `SS_INTACT` 一致（默认排除「插入」——精插段保持既有 mm 级解析伺服）。
* 计数与来源全记录（`l4_intact_summary()`）：`calls / reuse / refused / blend / w_zero / frame_std / shift / u_ff_src /
  l3_cond_ready / l3_cond_src / err`，**每一种失败都有计数，不做静默回退**。
* 与 `SS_INTACT` 的**关键差别**：本路径用解码器的量纲逆运算 `u = act × K_ACT`
  （`K_ACT` 现读引擎源码，单一事实来源）→ **不需要标定文件**即可生效；
  `SS_INTACT` 走的是学习型映射（`intact_action_map.json`），实测 R²<0 判死。

---

## 6. 零回退论证（三层，全部有实测/静态证据）

1. **画布执行集**（脚本 `tools/verify_l4_zero_regression.py`，拿 `git HEAD` 版本对比）：
   * L2 档：改动前 55 个节点 → 改动后 **55 个，逐 id 相同**
   * L3 档：60 → **60，逐 id 相同**
   * L4 档：76 → 77（只多 `ssintact_dec`，符合"只增不减"）
   * 原有节点除 `ssintact` 的名称/路径字段外，位置/类型/名称**逐字段相同**；原有 80 条连线全部仍在。
2. **引擎代码**：`os.environ.get("SS_L4_INTACT")` 门控 2 处，新增 tr 键（`l4_w` / `l4_u_ff_vec` / `l4_cond_vec`）
   全部写在门控 `if` 内 → 不设变量时**一行都不执行**。
3. **节点级真跑**（非模拟）：`node_intact` / `node_intact_dec` 经 `node_logic` 真实调用
   （metaworld 数据源 + 真权重）成功；画布节点名 → 注册 key 匹配 `intact` / `intact_dec` ✅。

---

## 7. 迁移实测（本次，真数字）

```
① 数据源 (metaworld 直连): MT1(peg-insert-side-v3) · camera corner2 · obs_mode=metaworld_render
   goal_frame=intact_goal_frame_optical.npy (解析链末帧 = 任务完成态) · state_dim=39
② 策略真推理: action chunk(8,8) · candidate_sequences=0 (零搜索) · 延迟 1396ms/步 (CPU)
   动作维自动对齐 4 → 8 (以模型实测为准, 不写死)
③ 解码器: u_ff 先验 [-0.0458, 0.2683, 0.266, 1.0] ← intact(chunk×K_ACT=0.5)
   L3 条件: 拒绝(未标定) → 证据落盘 reports/intact_l3_cond.json
④ 迁移期发现并修掉的真 bug: 未设 STABLEWM_HOME 时桥退回 <repo>/.cache → 权重全部找不到
   (FileNotFoundError) → 改为优先共享缓存 /home/ubuntu/stable-wm-cache
```

### 7.1 A/B 首轮暴露的第二个真 bug（已修）：引擎直喂帧时没有 goal 帧

首轮 `tools/l4_intact_ab.py` 影子臂实测 `calls=60 · reuse=0 · err="ValueError: goal_displacement
模式需要 goal 帧"` —— 即 **60 次"真推理"其实全部失败**（只是计数在涨，`frame_std=55.92` 真图是真的，
但模型那一步根本没跑）。这正是技能 `cross-venv-model-canvas-node §8.6` 记过的坑：
`goal_displacement` 意图必须给 goal 帧，而"引擎直喂帧"路径（`step(fr, obs_source=...)`）没人设 goal。

修法（在迁移后的 `runtime/node.py`，对所有调用方生效）：新增 `ensure_goal()` 三级兜底
「已显式 set_goal > 数据源自报 goal（metaworld 源内置本域真实目标帧）> 默认目标帧文件」，
`step()` 在 goal_displacement 且无 goal 时自动兜底，兜不到才**显式报错**（不静默出垃圾）。
修后同条件实测：`calls=8 · reuse=52`（chunk=8 → 60 步恰好 8 次真推理）、
`u_ff_src=intact(chunk×K_ACT=0.5)`、`goal_src=默认目标帧(intact_goal_frame_optical.npy)`、
`err=null`，且影子臂 `dist_final=0.0362` 与修复前**逐位相同**（不接管 → 行为不变，符合预期）。

> 这条也说明为什么"计数 > 0"不能单独当"真接入"的证据：必须同时看 `err`、`reuse`、
> `u_ff_src`、`goal_src` —— 否则会把"每帧报错的空转"读成"真推理"。

---

## 8. "提升能力"的路怎么走（诚实说明现在的边界）

* **现在就生效的**：L4 把"世界模型专家"的前馈先验送进 L3 的 u_ff 融合槽位，且**不需要标定**；
  引擎/画布已有三档开关与取证计数。
* **还没生效、需要标定的**：L3 条件向量通道（流形坐标）。标定路径已定：
  用"同帧四路"配对数据（INTACT 输出 + 潜空间 × 引擎流形 6 维真值）→ 训练折内 PCA(16)+岭回归 →
  LOSO 交叉验证 + 打乱标签 null 对照 → 闸值 R²>0.3 且 null<0.1 才写 `models/intact_l3_map.json`。
  （`decoder.py` 已按此闸值判读，低于 0.3 直接拒绝。）
* **尚未证的提升**：需要"同 seed 配对复验（净胜 ≥2）"才能说"有提升"。单臂结果一律写"疑似/待复验"。
  A/B 工具已就位：`tools/l4_intact_ab.py`（A 关 / B 影子 / C 接管，逐臂子进程隔离，同 seed 同 cap）。

---

## 9. 复现命令

```bash
# 节点级真跑 (数据源=metaworld, 权重=v4 epoch2)
cd /home/ubuntu/lerobot-smolvla-lew
MUJOCO_GL=egl INTACT_RUNTIME=root INTACT_DEVICE=cpu \
  INTACT_POLICY=intact_goal_optical_insert_v4_s3072/weights_epoch_2.pt \
  gui-venv311/bin/python -c "
import sys; sys.path[:0]=['tools/gui','src']; import node_logic as N
N.node_intact({'log':print,'root':'.'}); N.node_intact_dec({'log':print,'root':'.'})"

# 三臂对照 (A 关 / B 影子 / C 接管)
INTACT_RUNTIME=root INTACT_DEVICE=cpu \
  INTACT_POLICY=intact_goal_optical_insert_v4_s3072/weights_epoch_2.pt \
  gui-venv311/bin/python tools/l4_intact_ab.py --seeds 0,1 --max-steps 700 --cap l4

# 零回退证明
gui-venv311/bin/python tools/verify_l4_zero_regression.py
```
