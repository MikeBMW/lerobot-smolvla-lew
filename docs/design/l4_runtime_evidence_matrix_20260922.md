# L4 端到端运行时证据矩阵 (2026-09-22, 只读探针)

命令 (不动 GPU):
```bash
CUDA_VISIBLE_DEVICES= gui-venv311/bin/python tools/probe_l4_callchain.py L4      30   # 复刻 GUI「运行+L4」(INTACT 直驱)
CUDA_VISIBLE_DEVICES= gui-venv311/bin/python tools/probe_l4_callchain.py L4dec   30   # L4 → 意图解码器 (SS_L4_INTACT)
CUDA_VISIBLE_DEVICES= gui-venv311/bin/python tools/probe_l4_callchain.py L4audit 30   # 逐条边数据流审计
```
日志: `reports/l4_probe_L4_30.log` · `reports/l4_probe_L4dec_30.log` · `reports/l4_probe_L4audit_30.log`

## 一、场景 L4 (INTACT 直驱) — 30 步实测

### 真跑了 (函数级计数 > 0)
| 调用 | 次数 | 含义 |
|---|---|---|
| `IntactNode.step` | **30/30** | INTACT **每帧真推理** (跨 venv 桥) |
| `IntactIntentService.run_once` | 30/30 | L4 编排层 (policy 层入口) |
| `IntactIntentDecoder.decode` | 30/30 | 意图解码 (L4 → 条件/意图) |
| `build_skill_ctx` | **30/30** | **L2 原子技能上下文逐帧构造** (L4 复用 L2 的机制) |
| `IntactRuntime.__init__` | 1 | 跨 venv 桥建立 |

### 没跑 (计数 = 0)
| 目标 | 计数 | 说明 |
|---|---|---|
| `action_head.py` (SmolVLA-LeW DiT) 全部关键行 | **0** | loss 行/L322 forward/L354 predict_action/L355-389 区间 全 0 |
| `modeling_smolvla_lew.py` forward/action_loss/select_action | 0 | SmolVLA 策略未进 |
| `_l4_stats.calls` / `l3_calls` | 0 / 0 | L4 注入槽、L3 模型执行均未接管 |
| `mani_risk` / `mani_eta` (trace 列) | 恒 0 | 流形风险/效率列全零 (形同没接) |

### 关键拒绝 (真根因)
```
_intact_stats = {intact_calls: 0, refused_map: 30, u_ff_src: "analytic(未标定)"}
```
代码位置 `tools/gui/state_space_sim_real.py:1351-1357`:
```python
ad_ok = self._intact_adapter is not None and getattr(self._intact_adapter, "enabled", False)
if not ad_ok and not self._intact_shadow:      # 接管必须已标定; 影子模式才允许未标定真推理
    st["refused_map"] += 1; st["u_ff_src"] = "analytic(未标定)"; return None
```
`enabled` 由 `IntactActionAdapter` 决定: **有 `models/intact_action_map.json` 才 True**
(`src/lerobot/policies/intact/runtime/action_adapter.py:53-55`), 而生成它的工具
`tools/calib_intact_action_map.py` **文档里写明"Step 1 任务, 尚未写"** ⇒ 从未生成 ⇒ **L4 输出 100% 被拒**.

**结论**: 点 L4 时 INTACT 确在本机逐帧真推理 (30/30) 且 L2 技能上下文也在逐帧构造 (30/30),
但**动作适配层未标定** ⇒ 输出被诚实拒绝、引擎回落解析链 (`u_ff_src=analytic`).
⇒ 要"L4 真驱动仿真", 缺的就是 **动作映射标定** 这一步 (不是模型不行)。

## 二、场景 L4audit — 观测到的额外部件

```
🏆 L3 真执行接入: SmolVLA-Lew · 模型 ckpt = outputs/train/smolvla_lew_v10_1h/checkpoints/004000/pretrained_model — xyz 由模型出
③c 纤维丛联络层: ran=4 · ready=True · map_src=intact_fiber_map.json
                contact r²_loso=0.471 · z7 丛映射 r²_loso=0.607 (n=582 真实引擎样本) · cos_geo=0.9877
```
⇒ 引擎里 **L3 SmolVLA 真执行** 与 **纤维丛联络层(已标定)** 都能跑; 与 L4 场景的差异是"哪个槽位接管"。

## 三、任务 4 的缺口清单 (按优先级)

| # | 缺口 | 修法 | 判据 |
|---|---|---|---|
| 1 | INTACT 动作映射未标定 ⇒ L4 输出被拒 (`refused_map=30`) | 写 `tools/calib_intact_action_map.py`, 用同口径配对数据拟合 `models/intact_action_map.json` | `refused_map=0` + `intact_calls>0` |
| 2 | L4 场景下 SmolVLA/DiT 0 次 | L4 档默认挂 L3 SmolVLA (ckpt 用本轮新训 `outputs/train/smolvla_lew_sim/000300`) | `action_head.py:354 predict_action > 0` |
| 3 | YOLO 未在 L4 跑 | L4 档开 `vision=True` (L2 兼容勾选已存在), 每帧真检测 | 检出计数/帧 |
| 4 | VLM(本地 Qwen2.5-VL-3B)/DeepSeek 场景理解未在 L4 链里 | 接环境→场景理解节点 (按周期调用), 结果进 3D 视图 | 调用计数 + 场景 JSON |
| 5 | 3D 视图未反映上述结果 | 3D 读引擎 trace (`ss_dreamview.py` / `ss3d_live.py`), 面板标"来源: 真实模型/解析链" | 面板字段与 trace 一致 |

诚实说明: 本矩阵只列**运行时计数**, 不认"画布上有连线"; 全零行照实标出, 不粉饰。
