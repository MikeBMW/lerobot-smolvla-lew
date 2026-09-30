# 离线判闸口径换代 v3 → v4 (2026-09-14 夜, 老倪授权「补判闸口径」)

## 一句话
离线判闸必须 = **训练同源自监督回放**; 否则"能力不足"的结论可能是"输入喂错"的伪影 —— 本次同一批 7 个权重,
只换判闸口径, 结论从「7/7 输常数 + 记忆条 7/7 负增益」翻成「7/7 赢常数 + 记忆条 6/7 正增益且随训练单调」。

## v3 的四处不同源 (每处都能单独毁结论)
| # | v3 做法 | 训练实际 |
|---|---|---|
| 1 观测窗口 | `--stride 120` 抽样后逐帧喂 → 3 帧 obs 窗口 = 三帧相隔 360 帧的散帧 | 同段轨迹 **stride = frameskip(2)** 的连续帧 |
| 2 动作历史 | 节点用**自己预测的 chunk** 滚动 `action_hist` (闭环) | 该帧前 `frameskip` 帧的**真值动作** (PreviousActionDataset, 边界 raw 补零) |
| 3 goal | 所有帧都用**第 0 回合末帧** | `train.py::construct_intents` → goal = **本窗口末帧** (前视 `frameskip*(num_steps-1)` 帧) |
| 4 覆盖/统计 | 120 帧 (占 9.6% 且全在数据集前段) · 只看 slot 0 · 无重复 | 应: 全回合覆盖 + 多重复 |

附加静默失效: chunk 形状是 `[horizon, frameskip*4]`, v3 的 `chunk[0, slot*4:(slot+1)*4]` 在 `slot≥2`
取到**空切片** → 想扩到多槽时会静默拿到空数组 (必须 `reshape(-1)` 后按 4 维切)。

## v4 的定义 (tools/intact_replay_check_v4.py)
对帧 i (要预测其动作的那帧), 每个样本是:
- obs 窗口 = 帧 `[i-2*(HIST-1) ... i]` (stride=2, HIST=3) — 与训练 frameskip 同节奏, 末帧=当前帧
- `action_history` = 该帧前 2 块真值 raw 动作 (每块 = frameskip 帧 × 4 维 = 8 维), `[3, 8]`
- goal = 帧 `i + goal_ahead`, `goal_ahead = frameskip*(num_steps-1) - frameskip*(HIST-1)` = **+10 帧** (训练口径)
- 目标 = 帧 `[i ... i+15]` 的 raw 动作 (模型 8 块 × 2 帧) → 与预测 `reshape(-1)` 的 16 个 4 维槽逐槽对照
- 采样: **全部 2982 回合均匀** + 回合内均匀; `--repeats R` 独立重复 → 逐槽 mean±std; 每槽附常数基线 (教师均值)
- 可选 `--goal-mode terminal` = 部署口径 (回合末帧, 与 `reports/intact_goal_frame_optical.npy` 同类目标)

参数语义: `--clips` 每次重复抽多少段 · `--repeats` 独立重复次数 · `--lens 0 4 8 15` 汇总用的帧偏移槽 ·
`INTACT_POLICY=<family>/weights_epoch_<n>.pt` 选权重 · `INTACT_RUNTIME=root` 走真前向。

成本: 200 段 × 3 重复 ≈ 30 s/模式 (RTX 4060); on+zero 一轮 ≈ 60 s。线程数用 `OMP/MKL_NUM_THREADS` 钉死 (默认 8)。

## 同批权重的翻转数字 (v6 记忆条件链, skill=on)
| 权重 | v3 MAE_on / 常数 | v3 Δ(on−zero) | v4 MAE_on / 常数 | v4 Δ(on−zero) | v4 pearson_dx |
|---|---|---|---|---|---|
| v6r2 ep3 (死锁锚点) | 0.0400 / 0.0325 输 | +0.00000 | 0.0467 / 0.0830 赢 | +0.00000 | 0.621 |
| v6r5 | 0.0402 / 0.0325 输 | −0.00134 | 0.0499 / 0.0830 赢 | +0.00057 | 0.540 |
| v6r6 | 0.0398 / 0.0325 输 | −0.00089 | 0.0464 / 0.0830 赢 | +0.00258 | 0.532 |
| v6r7 | 0.0395 / 0.0325 输 | −0.00356 | 0.0470 / 0.0830 赢 | +0.00293 | 0.557 |
| v6r8 | 0.0387 / 0.0325 输 | −0.00175 | 0.0466 / 0.0830 赢 | +0.00365 | 0.598 |
| v6r9 | 0.0409 / 0.0325 输 | −0.00275 | 0.0477 / 0.0830 赢 | +0.00392 | 0.625 |
| v6r10 | 0.0420 / 0.0325 输 | −0.00151 | 0.0467 / 0.0830 赢 | +0.00497 | 0.627 |

读法: ① v3 的常数基线只有 0.0325 (窄样本 → 教师动作几乎不动, 常数就够), v4 全量样本常数基线 0.0830 (真动作多样);
② v3 的 pearson_dx ≈ 0 ⇒ 输入分布外, 与教师动作零相关; v4 0.53~0.63 ⇒ 真的在跟踪;
③ v6r2 ep3 的 Δ=0 与"skill 通道 0×0 死锁"逐位一致 ⇒ 锚点自洽 (修死锁后 r5+ Δ 转正并随轮数单调上升);
④ 单轮 Δ 幅度 (r10 +0.005) 与单轮重复间波动 (每槽 std ≈0.0045) 同量级 ⇒ **靠 7 轮单调趋势 + 死锁锚点判定**, 单轮不宣称显著; 要更硬的显著性就加 `--repeats`。

## 改判闸时要同步的 4 处
1. `tools/intact_replay_check_v4.py` — 判闸本体 (口径常量 FRAMESKIP/NUM_STEPS/HIST 必须与训练 config 一致)
2. `~/.hermes/scripts/v6_judge_watch.py` — 哨兵: `JUDGE` 指向 v4 + 传 `--clips/--repeats/--goal-mode train`; 判据 = 赢常数 ∧ on<zero ∧ 逐槽 std比均值 ≥0.30
3. `l4_ab/judged/{family}_epoch{n}.json` — 标记 schema **保持不变** (`mae_on/mae_zero/const/std_ratio_on/win_const/skill_gain/no_collapse/verdict`), 否则早收哨兵 `v6_earlystop_watch.py` 读不到
4. 旧结论留证改名: v3 的 `reports/intact_replay_*_skill_{on,zero}.json` 保留但标 `superseded`, 不得与新表混排

## 尚未解决 (下一步线索)
- **直驱过冲 152~331mm**: goal 口径不是原因 (terminal goal 只让 MAE +12%, 预测幅度 0.0215→0.0217 几乎不变)。
  嫌疑转向 framsekip 消费节奏: 模型每个"动作"= frameskip(2) 帧 × 4 维, 部署侧若按"每帧一个动作"消费、
  或按 stride=1 喂观测 ⇒ 等效速度翻倍。查 `runtime/action_adapter.py::map_chunk` 与引擎直驱的消费口径。
- **L3 条件通道未标定**: `models/intact_l3_map.json` 不存在, decoder 诚实拒绝 (不造假映射)。它是 L4 真机档的前置。
