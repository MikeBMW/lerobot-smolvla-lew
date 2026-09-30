# 意图/条件通道的可辨识性 + 训练产物落地纪律 (2026-09-14 夜, 直连线专项)

场景: 老倪定原则「上层只提供意图/条件, 执行永远由 L2 收口」, 要把 L4 的意图接进**流形专家预测器**
(`src/lerobot/manifold/predictor_layer.py`) → 流形 6 维 → 动作头 → 融合。本文只记**判定方法学**与
**落地纪律**, 数字均为本机实测。

## 1. 两条候选输入路线, 一条判负一条成立

| 路线 | 输入 | 目标 | LOSO R² | 结论 |
|---|---|---|---|---|
| A latent | INTACT `z_t(192)` + `δ=z_goal−z_t` | 流形 6 维 | 逐折 −0.6 / −8.4e9 / −1.6e10 / −6.6e4 / +0.25 | **不可辨识, 作废** |
| B 几何 | 引擎 `z7(7)` + 动作 + 几何意图 `Δ=target−peg_head(3)` | 流形 6 维 | **0.552(意图关) → 0.638(意图开)**, 中位 0.779 | **成立** |

路线 A 的两个独立佐证: ① 早先 decoder 用线性/CCA 判 `z_t→流形6维 LOSO R²≤0` → 拒绝写死映射;
② 本次用非线性 MLP + 意图口复现同一结论; ③ 线性 ridge `z_t→Δxyz` 逐维 `[0.06, −4.45, −0.31]`。
⇒ **latent 方向不是可用的意图表示**, 别再投入。

路线 B 的逐维 (意图开, 均值/中位): progress 0.964/0.985 · risk 0.780/0.945 · V 0.981/0.983 ·
eta 0.157/0.998 · rem 0.451/0.704 · dperp 0.497/0.671。TOL 成功率 0.463, 动作头 MAE 0.061。
意图增益: **ΔR²=+0.086, 6/8 折赢**。

## 2. 复现命令 (本仓库)

```bash
# ① 采几何同帧数据 (engine 真跑; 10936 帧/24 组, 0.4 分钟)
MUJOCO_GL=egl ./gui-venv311/bin/python tools/collect_mani_geo_data.py --clean 8 --jitter 4
#   → data/manifold_geo_v1.npz: z(7) a(4) m(6) peg(3) target(3) stage split seed

# ② 训练 + LOSO (留一 seed; 意图关/开同 init 同划分 A/B)
OMP_NUM_THREADS=4 ./gui-venv311/bin/python tools/train_mani_geo_predictor.py
#   → checkpoints/manifold_predictor/mani_geo.pt  {predictor, head, scaler, meta{loso_r2_mean,...}}

# ③ 判"latent 里到底有没有任务空间几何"
OMP_NUM_THREADS=4 ./gui-venv311/bin/python tools/probe_intent_identifiability.py
#   T1 z_t→Δxyz: [0.35, −8.35, 0.23] · T2 z_t→mani6: 2/6 维正 · T3 几何9→mani6: 4/6 维强正 · T4 ridge: 失败

# ④ 二态意图 (m_local/m_goal) 对动作预测的价值 (data/intent_pairs_v1.npz)
OMP_NUM_THREADS=4 ./gui-venv311/bin/python tools/probe_intent_action_value.py
#   5折随机: R² 0.980(关) vs 0.972(开) ΔR²−0.0075 赢折0/5 (帧级泄漏=乐观上限)
#   留一阶段: 两边 R² 均负, MAE 0.0284→0.0251 (−12%) 赢折 1/7 ⇒ 不构成证据

# ⑤ 引擎内三档真跑 (关 / 开不注入 / 开注入)
MUJOCO_GL=egl ./gui-venv311/bin/python tools/smoke_intent_line_engine.py
```

## 3. 统计纪律 (踩过的坑)

- **帧级随机划分不可用**: 相邻帧几乎相同 ⇒ R²≈0.98 的假高分 (路线 B 上 0.98/0.97, 看起来"都没问题")。
  必须按**回合组/seed** 留出 (本次 8 折 = 8 个 sim seed; clean 与 jitter 同 seed 同折)。
- **单折爆炸会毁掉均值**: eta 维某折 R²=1.3e11 量级 ⇒ 均值 −2.7e10, 中位 0.998。
  ⇒ 汇报必须**中位 + 逐折**, 并说明哪一维/哪一折退化 (本次 eta 维在当前采集下不稳)。
- **Δ 要配对比**: 同一折、同一 init 的 on/off 相减, 报 ΔR² 与赢折数 (6/8), 不要拿两个均值相减。

## 4. ckpt 落地纪律 (三条, 全部来自本次踩坑)

1. **meta 带质量指标**: `meta.loso_r2_mean` / `loso_r2_median` / `input_kind` / `hidden` / `layers` /
   `intent_kind` / `frames` / `groups`。
2. **推理端先读 meta 再建模型**, 并按 meta 判 ready:
   ```python
   _r2 = (_sd.get("meta") or {}).get("loso_r2_mean")
   if _r2 is not None and float(_r2) >= 0.30:   # 才允许注入执行口; 否则 w=0 + 面板写明原因
   ```
   未过闸的 ckpt 挪到 `checkpoints/manifold_predictor/rejected/` 留证。
   实测症状: 不带闸时"有文件就 ready"⇒ 未训练预测器直接进执行参考;
   建模型顺序错 (后读 meta) ⇒ 首帧 `size mismatch for predictor.mlp.*` + refused=1。
3. **scaler 同源**: 训练用标准化就必须把 `scaler{z_mu,z_sd,a_*,m_*,d_*,u_*}` 存进 ckpt,
   推理端 `(x−μ)/σ` 进去、`·σ+μ` 出来 (流形与动作都要反标准化)。无 scaler ⇒ 直通 (零回退)。

## 5. 引擎级"零回退"不能用 hash 相等判定 (重要)

闭环引擎自身 run-to-run **就有 FP 非确定性** (L4 档的 INTACT CPU 前向 + 闭环放大):
同配置跑两遍, 前 30 帧 `max|Δu_ff| = 2.99e-4`, 全局 3.1e-3, hash 不同。
⇒ 正确判据: **先量噪声基线, 再比"关 vs 开不注入"**:

| 对比 | 前 30 帧 max|Δu_ff| | 结论 |
|---|---|---|
| A1 vs A2 (同配置两遍, 线路全关) | 2.99e-4 | = 引擎噪声基线 |
| A(关) vs B(开, w=0) | 9.2e-5 (< 噪声) | 不注入在执行参考上**等价** |
| B(w=0) vs C(w=1) | 7.09e-2 (≈237× 噪声) | 注入**真的在改执行** |

单元级仍可用严格逐位 hash (预测器 `m=None` / 零初始化门控 → 三方 hash 相同 `713b210b…`)。
