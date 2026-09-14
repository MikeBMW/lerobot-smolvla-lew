# INTACT 的 action 输出在哪 + 画布接线 (2026-09-14 会话, 用户直接问过这三个问题)

归属说明: 画布接线/节点源码定位属本 skill (flow JSON 工程化);
INTACT 策略与跨 venv 桥的更深细节原本属于 `cross-venv-model-canvas-node` —— 但该 skill 是
**user-owned** (curator 无权写), 需要时由用户执行 `hermes curator adopt cross-venv-model-canvas-node` 才能被自动维护。
本文件把这次核对到的**可直接引用的事实**留在本 umbrella 下。

## 1. "INTACT 的 action 输出在哪里? 代码是哪个?"

| 层 | 位置 | 说明 |
|---|---|---|
| 模型原始 chunk | `src/lerobot/policies/intact/runtime/node.py:204` `actions, diag = self.runtime.get_action(info, horizon=self.horizon)` | 节点侧拿到 `chunk (H,D)`; 动作历史滚动在同文件 `:218` |
| 模型内部真正出动作 | `/home/ubuntu/INTACT-JEPA/jepa.py:200 get_action(...)`, horizon 循环 `:275-277` | 论文权重与本域权重都在这出 action_sequence |
| 下发机器人 (env 级动作) | `tools/intact_direct_rollout.py:237` `raw = chunk[min(chunk_step,len(chunk)-1), slot*4:(slot+1)*4]` → `:238` `act = raw*a_std + a_mean` → `:239` `np.clip(act,-1,1)` → `:245` `s._direct_act` | 引擎 `tools/gui/state_space_sim_real.py:1268` 取 `_direct_act` 当 env 动作 → `env.step` |
| 引擎 u 空间先验 (解码器产物) | `src/lerobot/policies/intact/decoder.py:126-128` | `u[:3]=clip(a0[:3],-1,1)*k_act` · `u[3]=1.0 if a0[3]>0.5 else -1.0` |

## 2. "连线连接的是 L3 的 Flow-Matching 吗?" — 是

```
ssintact(INTACT 策略) --[意图/潜空间/动作块(零搜索)]--> ssintact_dec(意图解码器)
ssintact_dec --[L4 条件 → L3 DiT (未标定则不注入)]--> ssdec 的 in2
```
`ssdec` = 🎯 Flow-Matching Action Head (DiT); 四路输入: `in1` 潜空间 z (来自 `ssvlm`)、**`in2` L4 条件 (INTACT 解码器)**、
`in3` 接触流形 (`ssmani_c`)、性能流形代价 (`ssmani_p`); 输出 → `ssff`(前馈加速器) + `ssact`(执行器)。
另一条**独立** L4 光模块链: `swintact → swworld`(动作块直接 `env.step`), 与 L3 那支不同源。

## 3. "点运行 + L4" 实际走哪条 (断点能不能进就取决于此)

- L4 档装配 (`tools/gui/simulink_module.py:11427-11462`): 建 `IntactNode` → `intact_direct_rollout.install_direct_act(sim, node, ...)`
  → `sim.attach_intact(node, None)`; 勾选生效时设 `SS_INTACT=1` (每 `SS_INTACT_EVERY=8` 步一次真推理)。
- **模型直驱是真正的执行路径** (每帧模型动作 → `s._direct_act` → `env.step`), `service.run_once` **不在这条链上**
  (它只被"双击节点" `node_logic.node_intact(_dec)` 与 `tools/intact_service_e2e.py` 调用)。
- 结论: "右键源码断点打上却不进" 先查**调用路径**, 别怀疑断点 (先 `grep -rn "run_once\|get_service(" tools/ src/` 列全部调用点)。
- v6+ 权重 (`skill_dim=24`) 缺 `skill_ctx` 会被模型侧硬闸拒绝:
  `ValueError: checkpoint was trained with a skill channel (skill_dim>0) but info['skill_ctx'] was not provided — refusing to silently degrade`
  → 现象是"跑不动 / 真推理 0 次"。修法: 直驱每帧走 policy 层编排并逐帧构造 24 维 `skill_ctx`
  (单一构造器 `src/lerobot/policies/intact/skill_ctx.build_skill_ctx`; L2 字段来自 `MemoryLayerBridge.from_real_data`;
  `x` = 引擎 `self.x` = 夹爪真实位置 `obs[0:3]`; `grip` = 引擎控制向量 `u[3]`)。
  实证: 修后 60/60 (另一次 80/80) 真推理 0 错误 · `u_ff_src=intact(chunk×K_ACT=0.5)` · `skill_ctx` 24 维非零 8 项
  · 证据落 `reports/intact_l3_cond.json`。

## 4. 证据要能溯源到具体权重

直驱路径上桥报的 `ckpt` 字段可能是空的 → 证据看不出用的是哪份权重。`service.run_once` 已补写
`diag["ckpt_env"] / ["ckpt_realpath"] / ["ckpt_mtime"] / ["ckpt_bytes"]`。
配套坑: 服务 root 解析曾多跳一层 (`"..",".."`) → 证据被写到 `/home/ubuntu/reports/` (工程外);
**判据里要带路径**, 不能只看"有没有产出 json"。
权重用**稳定指针**而非写死轮次: `checkpoints/<稳定名>/` = `config.json` + 恰好一个 `weights.pt` 软链
(官方 `load_pretrained` 的文件夹格式, 多个 `.pt` 会 `ValueError: Ambiguous checkpoint`), 换模型只换软链。
