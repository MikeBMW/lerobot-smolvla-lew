# 直连线落地实录: L4 意图 → 流形专家预测器 → 动作头 (Z-MAX, 2026-09-14)

老倪原则原文: **「上层只提供意图/条件, 执行永远由 L2 解析链收口; 每层只能收窄可行域、不能扩大
(U_L2 ⊇ U_L3 ⊇ U_L4); 稳定性由 L2 的李雅普诺夫势兜底 (V = 到孔口距离² + 姿态偏差²), 逐层单调下降。」**
本次 = 这条原则的第一次落地 (直连线)。

## 一、先诊断: 这台机器当时是"档位互斥", 不是"栈"

```
grep -nE "SS_L3|SS_L4_INTACT|SS_INTACT" tools/gui/state_space_sim_real.py
  SS_L3=1        → SmolVLA-Lew 出 xyz
  SS_L4_INTACT=1 → INTACT 直驱 (u_ff = act × K_ACT)
  SS_INTACT=1    → 标定映射
```
三档各管一段、互不叠加; L4 直驱**越过 L2 直接给动作** ⇒ 模型不会就直冲:
实测 3 seed 直驱 done 0/3、插入深度 152.8~331.9mm, 解析链同 seed 只有 10.9~62.6mm。
另外运行指针 `checkpoints/intact_l4_current/weights.pt` 当时指着死锁轮 `v6r2/weights_epoch_1.pt`
(判闸 Δ=0 最差那版) —— 诊断"上层不行"之前先确认挂的是哪版权重。

## 二、改动的文件 (4 改 + 1 新 + 1 探针 + 1 文档)

| 文件 | 改动 | 零回退机制 |
|---|---|---|
| `src/lerobot/manifold/predictor_layer.py` | `LatentPredictor/WorldModelPredictor` 加 `m_dim`+`gate`; `z' = mlp([z,a]) + gate·proj(m)`; 记 `last_intent_gain` 供取证 | `m_dim=0` 或 `m=None` 不进分支; `proj` 末层 `nn.init.zeros_` |
| `src/lerobot/policies/intact/decoder.py` | 新增 `m_int / m_int_source / m_int_weight` (δ=z_goal−z_t 单位向量, 免标定) | 老字段 `u_ff/l3_cond/l4_cond/weight` 一字未改; 排除阶段 (插入) 返回 `m_int=None` 并写明原因 |
| `src/lerobot/manifold/capability_stack.py` (新) | `LayerOut` 层语义强制 / `project`+`commit` 收缩投影 / `lyapunov`+`lyapunov_ok` / `summary` 记账 | 纯 numpy, 可单测; `w=0` 逐位返回下层原值 |
| `tools/gui/state_space_sim_real.py` | `_l4_intent_line()` + 融合点 (在 `sched.decide` 之前); `l4_intent_line_summary()` | `SS_L4_INTENT_LINE` 不设 → 调用立即返回 None; 唯一出口 `sched.decide` 计数仍 = 1 |
| `tools/probe_capability_stack.py` | 六查探针 | —— |
| `docs/design/zmax_l2_l3_l4_capability_stack.md` | 契约/不变量/直连线图/验证口径/落地顺序 | —— |

数据流:
```
node.step → out.latent{z_t, z_goal, δ} → decoder.decode()
    ├─ u_ff(4) 量纲逆运算 (现状: 直接当动作, 越权)
    ├─ l4_cond(192) δ → DiT 条件 token
    └─ m_int(192) δ →【新】WorldModelPredictor(m_dim=192)
                        z' = mlp([z_t, a]) + gate·proj(m_int)
                        → ManifoldReadout → m̂(6): [progress, risk, V, eta, rem, d_perp]
                        → StateSpaceActionHead(6→4) → u_int
                        → u_ff ← proj_{U_L2}((1−w)·u_ff + w·u_int)   w = m_int_weight × β × ready
    → sched.decide(u_ff, u_fb, contact_p, r) → u → safety.saturate(u, SS_LIMIT) → env.step   ← 唯一的执行出口
```

## 三、六查探针实测 (2026-09-14 23:11, `reports/capability_stack_probe_20260914_231121.json`)

```
A 零回退: hash_old_impl = hash_m_none = hash_zeroinit_gate = 713b210be8f7051b  (三态逐位相同)
          intent_gain 未训练 = 0.0 · 手工扰动末层后 = 2.6377 且流形读数变化 → 通道是活的
B 收缩性: 5000 组越界参考 (±8) → violations 0 · max_clip_L∞ 6.962 · clipped 4546/5000
          w=0 → 与 L2 原值逐位相同 · LayerOut(kind="action") 抛 ValueError (语义护栏真生效)
C 接口真跑: 流形式 6 维 → 动作头输出 [1,1,4] → u_int 非零 (‖·‖=0.021), gain 未训练 = 0.0
D 判据自检: 单调序列 → True · 注入回升 [1.0,0.64,0.9,0.2,0.1] → False (rise_cnt=1, rise_max=0.26)
E 上层字段: m_int 有值 (范数 1.0, 门控 0.3, 来源含"192维/无需标定"); stage=插入 → 诚实拒绝;
            老字段全在 (u_ff/l3_cond/l4_cond/weight)
F 引擎接线: 方法在位 ✓ 守卫在位 ✓ 调用在 decode 后 ✓ 融合在 decide 前 ✓ 唯一出口计数 = 1 ✓
```

## 四、不变量与检查方式 (可直接搬)

| 代号 | 不变量 | 机器检查 |
|---|---|---|
| I1 | 只有 L2 写执行量 | `grep -c "u, stage = self.sched.decide("` ≡ 1 |
| I2 | 上层参考必须落在 U_L2 | 5000 组越界 → 违规 0, 记 `clip_max` |
| I3 | 层语义 (intent/condition/action) | 构造越权 LayerOut → 必须抛异常 |
| I4 | 唯一执行出口 + 安全限幅 | `safety.saturate` 仍在链尾, 未被绕过 |
| I5 | V 单调不增 / 开两臂 V 不升 | `lyapunov_ok()` + 同 seed 对照 |

## 五、复现命令

```bash
cd <repo>
./gui-venv311/bin/python -m py_compile tools/gui/state_space_sim_real.py \
  src/lerobot/manifold/predictor_layer.py src/lerobot/manifold/capability_stack.py \
  src/lerobot/policies/intact/decoder.py
OMP_NUM_THREADS=4 ./gui-venv311/bin/python tools/probe_capability_stack.py     # 六查, ~10 s
```
引擎侧默认 (不设环境变量) = 逐位零变化; 要开直连线:
`SS_L4_INTENT_LINE=1` (预测器训练好后再让它 `ready=1`, 权重放
`checkpoints/manifold_predictor/intent_line.pt`, 或用 `SS_L4_INTENT_PRED` 指路径)。

## 六、没证的部分 (汇报时必须照实写)

- 预测器**未训练** → `ready=0` → 注入权重 0 (线路照跑出证据, 但不污染执行口);
  readout R²/LOSO、闭环 done 率/插入 mm/过冲 mm 全部**待训练后**按同口径两臂 A/B 判定。
- 引擎 **GUI/GL 运行时联调未做** (本次只到静态接线 + 模块级真跑)。
- 因此不许写"打通了/有提升" —— 只能写"接线已证 + 零回退已证 + 质量待训"。
