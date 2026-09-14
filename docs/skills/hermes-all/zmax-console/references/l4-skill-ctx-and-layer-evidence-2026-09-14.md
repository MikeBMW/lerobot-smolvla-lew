# L4 INTACT 记忆条件 (skill_ctx) + 分层架构取证 (2026-09-14)

老倪三条要求: ①确认「L2 可单独跑 / 可扩 L3 / 可升 L4」的架构 ②看 **L4 INTACT 与 L2 原子技能共同运行** 的证据
③看升级后的视频。本文 = 三条各自的**取证配方** + 本次踩到的新坑 (SKILL.md 里只留指针和铁律)。

## 1. 分层架构取证: tools/layer_stack_evidence.py (同一引擎跑三格)

```
./gui-venv311/bin/python tools/layer_stack_evidence.py --seed 1     # 约 2.5 分钟, 出 reports/layer_stack_evidence.json
```
| 格 | 参数 | 判据 | seed1 实测 |
|---|---|---|---|
| A. L2 单独 | `mode=insert cap=l3` | `sim._mm_hits > 0` 且日志有「肌肉记忆快通道 … 小脑接管前馈」 | done ✅ 670 步 · **命中 194** |
| B. L3 扩展 | `mode=full cap=l3` | 阶段轨迹覆盖 插入/拔出/AOI转移/AOI检测/回程/放下 | done ✅ 1193 步 · **6/6** |
| C. L4 升级 | `mode=insert cap=l4` | `sim._jitter_meta` 有真值 (dx/dy/dz/yaw/shell90) | done ✅ 344 步 · 真注入 dx−3.2cm yaw+9.4° |

**逐层开关 = `data/memory_layers.json`** `{L2,L3,L4,assembly}` — 三层不是三套系统, 是同一引擎的三个独立开关
(这是回答「能不能单独跑/逐步升级」的正面证据; 反例说法「要重启/换文件才能切层」是错的)。

### ⚠️ 坑: 阶段轨迹不能读 `sim.stage_hist` (实测恒空)
`sim.stage_hist` 是空列表 → B 格覆盖率会误报 0/6 (功能其实走全了)。正解 = 挂帧 sink 逐帧取:
```python
stages = []
def _sink(s, act, o, _st=stages):
    try: _st.append(str(s.sched.stage()))
    except Exception: pass
sim._frame_sink = _sink
tr = sim.run(max_steps=..., cap=...)
```
**通用教训: 向用户证明「某条链走完了」时, 从帧 sink 取阶段序列, 别信聚合属性。**

### 干扰轮的 L2 语义 (必须主动说明, 别当卖点)
`cap=l4` 注入后引擎**主动旁路 L2 快通道** (`🧠 L4 干扰: 肌肉记忆旁路关闭 (摆放已变无标杆) — 全精算伺服适应`,
该 seed `_mm_hits=0`)。原因: L2 标杆按原始摆放固化, 来料移位/转向后标杆失效, 旁路是**正确降级**
(不旁路会把光模块推飞)。所以阶梯表里干扰档 L2 介入下降 = 预期, 不是回退。
**「干扰下仍复用 L2 技能」正是 v6 skill 通道要补的那一环** —— 用技能语义 (相位/技能权重/到管距离/进度)
替掉「布局绑定的标杆」。

## 2. L4 INTACT ↔ L2 势场「共同运行」取证

```
INTACT_POLICY=intact_goal_optical_insert_v6_smoke/weights_epoch_1.pt INTACT_RUNTIME=root INTACT_DEVICE=cpu \
./gui-venv311/bin/python tools/intact_sw_optical_bridge.py --seeds 0 --mode insert --cap l4 --max-steps 400 \
    --model-episodes 1 --slot 0 --stats reports/_probe_v5_action_stats.json \
    --baseline-full 0 --video-dir reports/evidence_joint_l4l2
```
证据形态 (同一帧三样东西同时在场):
```
🧲 记忆层介入 step=0 技能=SK01 w=0.5 conf=1.0
     模型=[-0.0211,-0.0004,0.0194,0.6]  场=[0.2951,-0.3668,-0.518]  合成=[0.137,-0.1836,-0.2493,0.3]
status: 真推理 80 次 / 0 错误 · 阶段=接近 · 帧std=55.98 · memory_layers {L2:1}
```
**「每帧真推理 N 次且 0 错误」本身就是 skill_ctx 在每帧都被送进去的硬证据** ——
因为 `jepa.get_action` 有硬闸: `skill_dim>0` 却缺 `info["skill_ctx"]` → 直接 ValueError, 不许静默降级。
所以「没报错」= 通道每帧都通, 不需要再翻内部张量。

### 桥的两条设计规则 (本次为取证新增)
- `--model-episodes -1` = **只要解析链/抗干扰证据视频, 不做模型直驱**; 此模式下"模型未就绪"**不许整轮失败**
  (只记 `model_skip_reason` 继续) —— 否则一个不需要模型的证据轮会被模型拖死 (首次跑就这么死的, exit 3)。
- `--cap` 除 l2/l3(l4) 外也参与证据命名 (`..._解析链_{cap}_seed{n}.mp4`), 免得 l3/l4 视频混在一起。
- ⚠️ `INTACT_POLICY` 不设时适配层回落**论文 HF 资产 (paper 运行时)** → `InstantiationException: Error locating
  target 'module.InverseTransitionActor'` (paper 运行时没有这个类)。跑本域权重必须显式
  `INTACT_POLICY=<ckpt>` + `INTACT_RUNTIME=root`。

## 3. 训练侧两条 Hydra/加载坑 (v6 冒烟实测)

- `prefetch_factor` 只在 `num_workers > 0` 时合法: `loader.num_workers=0` + `prefetch_factor=2` →
  `ValueError: prefetch_factor option could only be specified in multiprocessing`。小样本冒烟就带上
  `loader.num_workers=2 loader.prefetch_factor=2`。
- 配置里**不存在的键**必须用 `+` 前缀: `+trainer.limit_train_batches=6`
  (直接写 `trainer.limit_train_batches=6` → Hydra `ConfigAttributeError` / "To append to your config use +…")。
- 数据集加载: `swm.data.load_dataset(name, cache_dir=...)` 的 `cache_dir` 是 **datasets 目录的父目录**
  `<cache>/datasets/<name>`; 且 `name` 要带 `.h5` 后缀 (train.py 按字面文件名解析)。写错报
  `FileNotFoundError: Cannot resolve '<name>': not a local path or HF repo id.`。
- 通道消费的训练侧证据: 加一行日志打 `batch["skill_ctx"].shape` + `metrics["skill_ctx_used"]` +
  非零占比 (Lightning 的 `log_dict` 里加 `skill_ctx_used` 键, 进度条会显示 `fit/skill_ctx_used: 1.000`)。
  ⚠️ `intact_forward(self, batch, stage, cfg)` 的 `stage` 实测是 **"fit"/"validate"**, 不是 "train" ——
  按 `stage == "train"` 写的打印永远不触发。

## 4. 闭环口径: 反归一化 stats 必须与训练同一份

桥的 `--stats` 必须指向**训练那个 h5 现算出来的**统计 (`tools/action_stats_from_h5.py --h5 <训练h5>
--action-space u --out reports/<同名>_action_stats.json`)。用 A 数据集的 stats 去反归一化 B 数据集训的权重
= 静默量纲错误 (动作整体缩放/偏移, 视频里表现为"乱走"). 冒烟权重就用它自己那套 stats
(`reports/_probe_v5_action_stats.json`), 全量 v6 用 `optical_insert_v5_action_stats.json`。

## 5. v6 判闸口径 (有提升非仅不回退)

同一权重、同一批真帧, 只改**看不看得见 L2 技能**:
```
tools/intact_replay_check_v3.py --h5 <v5disturb.h5> --stats <同源 stats> --n 120 --stride 120 \
    --device cpu --task pusht --horizon 8 --skill {on|zero|off} --out reports/intact_replay_v6_ep{N}_skill_{on,zero}.json
```
三判据全过才算过闸: ①`mae(on) < const` ②`mae(on) < mae(zero)` (记忆条件真有提升) ③`std比 ≥ 0.30` (不塌缩)。
哨兵 `/home/ubuntu/.hermes/scripts/v6_judge_watch.py` (cron `every 20m`, no_agent, 静默无新 ckpt,
投递飞书静界群)。`--skill off` 只对 `skill_dim=0` 的旧 ckpt 合法 (v6 ckpt 缺 skill 会报错, 这是设计)。

## 6. 新抗干扰数据集 (v5) 采集要点

`tools/intact_insert_dataset_v5.py` (`--disturb mixed` = 按 seed 轮转 light/med/heavy,
heavy 的 yaw 仍钉在 ±15° 可成功域 —— 再大长条盒物理夹不住, 强灌只会造出假成功):
- 干扰是**引擎真改 peg qpos + mj_forward** (`--cap l4`), 每回合 `_jitter_meta` 记进 part meta 的 `ep_jitter`;
- 专家口径 `--success-only 1`; 全相位覆盖 `--coverage all --stride 75`;
- 速率实测 ≈ **6.7~11 s/seed** (1600 步上限, mode=full) → 300 seed ≈ 35~55 分钟; 30000 帧/part ≈ 1.4GB。
- 落盘后必验三样: keys 里有 `skill_ctx` · 帧 std > 5 (真图) · `meta.ep_jitter` 有真值 (干扰真注入了)。
