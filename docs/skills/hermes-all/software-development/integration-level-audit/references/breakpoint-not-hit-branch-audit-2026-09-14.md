# 「断点没进来」分支级取证实测 (2026-09-14) — Z-MAX L4 / SmolVLALewActionHead

问题原文 (老倪): 「**运行 L4 的时候**, 这个断点 `return (loss * valid_mask).sum() / num_valid.clamp_min(1)`
**没有进来**, 查」

结论 = **两个原因叠加**, 都用运行期计数坐实 (探针 `tools/probe_l4_callchain.py`, 可复用模板见
`templates/probe_runtime_callchain.py`):

## 结果表 (同口径数字)

| 计数 | 场景 L4 (复刻 GUI「运行+L4」= INTACT 直驱, 40 步) |
|---|---|
| `IntactNode.step` (INTACT 真推理) | **40** |
| `IntactIntentDecoder.decode` / `intact/decoder.py:126` | **40** |
| `SmolVLALewActionHead.__init__` | **0** ← 类**根本没被实例化** |
| `SmolVLALewActionHead.forward` / `.predict_action` / `DiT.forward` | **0 / 0 / 0** |
| `action_head.py` 已执行行 | **(无, 一行没跑)** |
| `SmolVLALewPolicy.*` (含 select_action) | **0** |

微对照 (本进程直接调微型 DiT-test 头, 证明打桩有效):
`forward()` → 行 307 命中 **1** 次; `predict_action()` → 行 307 增量 **0** (推理分支走 315+, 不碰 307)。

## 原因一: 那行是**训练 loss 行**, 任何推理路径都不会执行

- `action_head.py:307` 在 `SmolVLALewActionHead.forward` 内 (flow-matching MSE); 推理走 `predict_action`。
- 全库唯一调用者链: `action_head.py:307` ← `modeling_smolvla_lew.py:319`
  (`action_loss = self.action_model(...)`, 在 `SmolVLALewPolicy.forward:234` 内)
  ← **`tools/gui/training_backend.py:132`** (画布「🚀 SmolVLA+L EW 训练」节点**生成**的训练脚本)。
  `grep -rn "policy.forward("` 只有这一处 ⇒ loss 行只在**训练**时跑。
- 命令: `grep -rn "valid_mask).sum()\|num_valid.clamp_min" --include=*.py .` 一次列出同族 loss 行
  (act / diffusion / multi_task_dit / vla_jepa ... 全是各自的**训练**分支)。

## 原因二: L4 档装配**主动关掉** L3, 该模型的代码整条不在链上

- `tools/gui/simulink_module.py` (~11340-11443): L4 档装配里
  `os.environ.pop("SS_L3", None)` (勾「🧠 模型执行」时设 `SS_L3=1`; 勾「🤖 L4 用 INTACT 节点执行」时
  又 pop 掉) + `attach_intact()` + `intact_direct_rollout.install_direct_act(sim, nd, ...)` 直驱
  (每帧「模型动作 → env.step」, **无解析控制器**)。
- 所以断点不是"没进", 是**这条链上没有这份代码**; 面板/画布把 DiT 画在 L4 链上 ≠ 运行期调用它 (典型
  "画了没接", 属本 skill 第 2/3 类假接入)。

## 断点该打哪 (运行 + L4 实测会命中的位置)

- `src/lerobot/policies/intact/runtime/node.py::step()` — 40/40
- `src/lerobot/policies/intact/decoder.py:126` (`IntactIntentDecoder.decode`) — 40/40
- 想在 L4 里真进 DiT 头: 需先产出 `models/intact_l3_map.json` 标定 (否则
  `L3条件就绪=False(拒绝(未标定))`), 且不再 `pop SS_L3`。

## 顺带挖出的相邻缺口 (同一次取证发现)

- 另一条「L4 → 解码器」槽位 (`SS_L4_INTACT=1`) 实测 40 次**真推理全被模型硬闸拒绝**:
  `ValueError: checkpoint was trained with a skill channel (skill_dim>0) but info['skill_ctx'] was not
  provided — refusing to silently degrade` ⇒ 引擎自有 u_ff 槽位没喂 `skill_ctx`, 只有直驱路径
  (`install_direct_act`) 逐帧 `build_skill_ctx(...)` 喂了。判据: `_l4_stats.err` + `u_ff_src=analytic`。
- 教训: **不要用槽位计数器判断"模型跑了"** —— 必须先区分是"模型没跑"还是"跑了但被硬闸拒绝"。

## 复现探针的命令形状

```bash
# 复刻 GUI 的 L4 装配 (同一份 install_direct_act) + 函数级/行级计数
CUDA_VISIBLE_DEVICES= nice -n 10 gui-venv311/bin/python tools/probe_l4_callchain.py L4 40
CUDA_VISIBLE_DEVICES= nice -n 10 gui-venv311/bin/python tools/probe_l4_callchain.py L4dec 40
CUDA_VISIBLE_DEVICES= nice -n 10 gui-venv311/bin/python tools/probe_l4_callchain.py micro   # 正对照
```
探针在跑时用 `nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader` 盯一眼,
确认训练未被扰动 (本次训练全程 98% / ~5975 MiB 未变)。
