# 「这条边真的有数据在传吗?」— 画布边数据通路审计 (2026-09-15 实录)

老倪原话: 「INTACT意图解码器 的输出, 要 到流形专家预测器 节点, 这个代码在哪里? **要有实际的数据传输**」。
注意问题里有两层: ①代码在哪 (静态) ②**有没有真数据在流** (运行期)。只答①会被当假接入。

## 四级判据 (逐级给证据, 缺一级就是\"画布线在、数据停\")

| 级 | 查什么 | 本次实况 |
|---|---|---|
| L1 画布边 | `flows/<主画布>.json` 的 `links`: `{id, f, t, f_port, t_port, label}` — 直接按节点 id 找 | ✅ `lkild_jepa: ssintact_dec → ssmani_exp, out1→in3` (与 `.bak-*` 对比可确认是**新补的边**) |
| L2 传输调用点 | producer 的输出在哪一行被交给 consumer | ✅ 引擎 `state_space_sim_real.py:1203 d = self._l4_dec.decode(...)` → `:1209 self._l4_intent_line(d, out, stage)` (定义 `:1368`) |
| L3 **载体字段** | 输出对象上哪个字段真被搬过去 | ⚠️ 引擎路径用 `d.m_int`(1380) ✅; **`service.run_once` 里 `d` 是局部变量, `IntentReport` 只搬了 u_ff/l3_cond/l4_cond/weight → m_int 断在这里** ❌ |
| L4 执行注入点 | 值最终进哪里, 有没有留痕 | ✅ `:2107-2120` 能力栈 `note_l2/note_l4 → commit → u_ff ← (1−w)·u_ff + w·u_int`; 栈里有 `accepted/reason/hash` 可审计 |

**L3 是这类审计最常漏的一级**: 文件里有调用、函数也真跑, 但字段在中间对象上没被搬 ⇒ 下游永远拿到 None。
`grep m_int` 只看到产出和消费两端, **中间那层的 rep/dataclass 必须逐字段核**。

## 必查的三类门控 (不查就会把\"默认关\"误报成\"没实现\")

1. **开关 env**: 引擎侧第一句就是 `if os.environ.get("SS_L4_INTENT_LINE") != "1": return None` (1376) ——
   默认关 = 零注入零回退 (设计如此)。**GUI 里从不设它** (全库 grep 只有 `tools/diag_*`/`ab_*` 设) ⇒ 生产线上面板看它永远是 0。
2. **质量闸**: `checkpoints/manifold_predictor/intent_line.pt` 的 `meta.loso_r2_mean` 必须 ≥0.30 才 `ready=True`;
   有文件但未过闸 → 线路照跑、w=0、不注入 (带 `ready_src` 说明)。本次 = 0.638 ✅。
3. **口径 (caliber)**: `meta.input_kind` 决定输入怎么组。**活跃口径 z7** 会把 `m` 覆盖成几何 `Δ=target−peg_head`,
   `d.m_int` 在该口径下**只当门控**; 真正 `z_t+δ (m_dim=192)` 的口径已被离线证伪, 权重被移到
   `checkpoints/manifold_predictor/rejected/intent_line_zt_delta_REJECTED_20260914.pt`。
   ⚠️ **标注漂移 (要修不要忽略)**: `st["src"]/info["m_int"]` 在该口径下仍写 `decoder(δ) ← intact(δ 192维)`,
   面板/能力栈读起来像\"在用 INTACT 意图\", 实际喂进去的是几何 Δ ⇒ 审计报告要显式指出, 或改成
   `info` 里分开 `m_true` / `m_used`。

## 两条路径分离 = 审计的第二个必查项

同一个 producer 常有多条路径, **只算 GUI 实际走的那条**:

- 引擎自建路径: `_l4_intact_u_ff` (2058-2060 需 `SS_L4_INTACT=1` + 阶段白名单) → 内含 `_l4_intent_line` ⇒ 真传数据 (已实测)。
- GUI 档位路径: L4 档 = 直驱 `install_direct_act → service.run_once`。GUI **不设 `SS_L4_INTACT`** ⇒ 上面那条根本没被调用;
  而 run_once 又丢了 m_int ⇒ **GUI 里这条边 0 数据** (画布线在)。

## 运行期取证 (可复跑)

`tools/probe_l4_callchain.py` 新增场景 `L4line` (`SS_L4_INTACT=1` + `SS_L4_INTENT_LINE=1` + attach node),
报告多出 ③b 段 (读 `sim.l4_intent_line_summary()`):

```bash
cd /home/ubuntu/lerobot-smolvla-lew
/home/ubuntu/lerobot-venv/bin/python tools/probe_l4_callchain.py L4line 30
# 8 步只够进 1 帧 (z7 历史还没生成) → 30 步才拿到可用数字
```

本次 30 步实测: `frames=4 · ran=3 · applied=22` (by_stage `{'接近': 22}`) · `refused=1` (首帧 z7 历史空) ·
`ready=True (LOSO R²=0.638 ≥0.30)` · `src_last=decoder(δ) ← intact(δ 192维, ‖δ‖=24.89)` ·
`intent_gain_mean=8.986` · `manifold_last=[0.11772,0.00016,0.00705,0.00036,0.27652,0.25913]` (预测流形 6 维真值) ·
栈: `L2 analytic w=1.0 accepted / L4 intent w=0.3 accepted ("采纳: w=0.300")`。
⇒ 判据 = **ran>0 且 manifold 6 维有值且 applied 有计数** (不是看有没有连线/有没有函数)。

## 回答模板 (老倪认这种)

1. 画布边在哪 (文件 + link id + 是否新补);
2. 产出端 (文件:行, 产出哪个字段) / 传输端 (调用点+定义点) / 注入端 (融合点 + 留痕字段);
3. **运行期数字** (正对照: 开启后 frames/ran/applied/manifold);
4. **默认关与口径** (开关 env 默认值、质量闸、活跃口径谁在喂), 有标注漂移就点出来;
5. **缺口 + 修法** (如 run_once 未搬 m_int → IntentReport 加字段 + 直驱路径接同一 `_l4_intent_line`; 注入仍由原闸决定, 默认零回退)。
