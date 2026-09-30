---
name: zmax-multilayer-pipeline
description: Use when 要把 L5/L4/L3/L2 多层模型组成可插拔 pipeline 做组合推理。
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [zmax, pipeline, multi-layer, composition]
    related_skills: [zmax-joint-training-deploy, layered-capability-stack]
---

# Z-MAX 多层级 Pipeline（可插拔 · 可组合）

## When to Use
- 要把 L5/L4/L3/L2 + 记忆层组成**一条推理链**，且需要**换模型不改上下游**
- 要支持**多种组合策略**（串联 / 并联仲裁 / 消融开关）
- 要做**模型级 A/B**（如 L4 用 unified 还是 intact，或两者并联投票）
- 要在同一次调用里拿到**全层输出 + 中间量 + 每层耗时**（取证/调试）

工具: `tools/multi_layer_pipeline.py` · 演示: `tools/pipeline_demo.py`

## 契约（三层）
```python
Layer.infer(ctx) -> NodeOut(name, ok, src, latency_ms, data, conf, err)
注册表: @register("impl.name") → build(impl, **kw)
Pipeline(spec).run(**ctx) -> {层名: NodeOut};  .report(out) 出可读报告
```

## 已注册实现
```
L5  : planner.rules(自带零依赖) / planner.taskplanner(真包)
MEM : memory.json
L2  : detect.yolo / detect.stub
L4  : node.unified(统一主干SigLIP) / node.intact(在役JEPA)
L3  : dispatch.engine(act×K_ACT 量纲逆运算)
旁路 : null
```

## 组合策略
```python
{"L4": {"impl":"node.unified", "on":True, "combine":"vote", "peers":["node.intact"]}}
```
- `on:false` → 自动换 NullLayer（消融）
- `combine:"vote"` → 并联跑多实现，按 `conf` 选优（conf 用 out.diagnostics['intent_norm']）

## 实测（2026-09-23）
| 组合 | 结果 |
|---|---|
| L5→MEM→L2→L4(unified)→L3 | 5/5 层 · 134.7ms · L4 conf=3.056 |
| L4=vote[unified,intact] | 5/5 · 仲裁选 intact (9.81>3.01) · 190.5ms |
| L4 off | 正确降级，L3 报"无上游 chunk" |

## 闭环挂载（零引擎改动）
```python
from multi_layer_pipeline import PipelineNode, build_default_spec
spec = build_default_spec(L2="detect.stub", L4="node.unified")
spec["L4"] = {"impl":"node.unified","combine":"vote","peers":["node.intact"]}
sim = RealStateSpaceSim(seed=104, vision=False, log=lambda *a: None)
sim.attach_intact(PipelineNode(spec=spec, sim=sim), None)
tr = sim.run(max_steps=1200)
```
运行需 `SS_L4_INTACT=1`（否则全走解析链, calls=0）。
**实测（seed 104）**: calls=33 · refused=0 · **w=0.3 真接管** · done=True · 347 步。
PipelineNode 自动把 obs39 从 `sim._last_obs39` 取、把 CHW 帧转 HWC、提供
`diagnostics['intent_norm']`（否则 w=0 假接入）。
spec 也可用 `SS_PIPELINE_SPEC=<json 文件路径 或 json 串>` 注入。

## 画布穿线 + 闭环可视化（2026-09-23 落地）
```bash
python tools/gen_pipeline_closure_flow.py      # 生成 flows/pipeline_closure.json (6节点7连线, 含2闭环回边)
python tools/pipeline_closure_run.py           # 真跑: 逐节点落状态 → 画布高亮 → 全绿=闭环完成
python tools/calib_closure_run.py --views 6    # 人机在环标定闭环 (6节点+迭代回边)
```
**双层状态落盘（这是"高亮"的实现）**:
```
① flows/*.json 的 node.params.status → 画布直接上色
② docs/PIPELINE_STATE.json 的 stages[*].status → CICD 控制台**每 2s 轮询**
状态色: pending #57606a · running **#00d4aa(高亮)** · success #3fb950 · failed #ff4444
闭环完成判据: 全部节点 success → flow.sim.closure = 'done'
```
**坑**: 逐节点只装配一次 Pipeline（`Pipeline.stages[name].infer(ctx)`），不要每节点重建（会重载模型）。
下游层要拿**上游 NodeOut 对象**（不是 `.data`），否则报 `'dict' object has no attribute 'data'`。

## 记忆层有效联络（原为全 0 假记忆）
```
问题: data/memory_layers.json = {"L2":0,"L3":0,"L4":0,"assembly":0} → 记忆向量退化 → 对控制零贡献
工具: tools/memory_link_build.py  → 填充五层 + 每条带 links 跨层指向 + 连通性验证
判据: 无空层 · 无悬空链接 · **无孤儿(每条有入边)** · 跨层链接占比 100%
实测: 16 条 / 31 链接 / 跨层 100% / 零孤儿
```

## 几何流形不变性（"性能不变形"的判据）
```bash
python tools/geom_invariance_check.py --ckpt <unified.pt> --n 24
```
口径: 等变性 `f(T·x) ≈ T·f(x)`。测四类变换下的预测变化 + 四态流形一致性。
```
判据: 单变换相对变化 ≤35% · 流形一致性 ≤30%
实测(backbone_cont): 平移33.8% · 缩放25.9% · 旋转26.2% · 一致性22.5% → 通过(平移贴线)
对策: 训练加 --aug 1 (平移±8px/尺度0.95-1.05/旋转±5°, 留出集不加) → 治几何敏感性
```

## 拉通审计 (2026-09-23, seed 104 · mode=insert · 全真件)
一键: `./gui-venv311/bin/python tools/pipeline_closure_run.py --seed 104 --vote`
(真输入=引擎渲染帧+真 obs39; L5=planner.taskplanner; L2=在役 yolo_peg_live.pt; L4=vote[unified,intact];
 exec 节点=把整条 Pipeline 挂引擎跑一轮) → 6/6 success · flow.sim.closure='done' · 15.7s
| 取证项 | 实测 |
|---|---|
| 每帧 pipeline 调用 | 33 帧 × 5 层全 ok (L5/MEM/L2/L4/L3) · 引擎 `_l4_stats.calls=33 reuse≈197 refused=0` |
| L4 接管 | blend 80 帧真融合 · L2 收口否决 151 (方向 127/幅值 24) · vote 选 node.unified (2.71>0.93) |
| 闭环结果 | done=True · 348 步 · 最小插入距 **0.5mm**; 基线不挂 pipeline: done=True · 342 步 · 2.2mm → **零回退** |
| 单层耗时 | L5 0.1ms · MEM 0.1ms · L2 8–18ms(暖) · L4 10–25ms · L3 0.01ms → 全链 ~20–35ms/帧 |
| 消融 | L4=null → L3 报 "无上游 chunk" (断链可测) |
辅助审计脚本: `tools/audit_l5_l2_pipeline{,2,3}.py` → `docs/pipeline_audit*_<ts>.json`

**引擎每帧链的真实分层** (老倪问"拉通没有"必答这个): `state_space_sim_real.py` 只 `_load` 六模块
perception/parallel/dynamics/cognition(sched.decide)/safety(saturate)/execution —— **没有 planner.py**
→ L5 只在 pipeline 层/画布/GUI 级, 不在引擎每帧回路; L4 靠 `attach_intact`+`SS_L4_INTACT=1` 进 u_ff
槽位; L2 收口闸 (sched.decide+safety.saturate) 是每帧真跑的**唯一执行出口**。

## 坑
0. **L2 默认权重 = 假件 (已修)**: `YoloPerception(weights=None)` 退到通用 `yolov8s.pt` (COCO 80 类),
   检到的不是光模块。`L2DetectLayer.load()` 现默认 `_default_live_weights()` = `models/yolo_peg_live.pt`;
   若该软链缺失才回退 (日志 `✅ YOLO 实际加载: ...` 会写明类数, 2 类=在役, 80 类=假件, 必核对)。
1. **VoteCombiner 只有 `.run(ctx)`**, 没有 `.infer(ctx)` —— 逐节点装配时按层调 `infer` 会 `AttributeError`;
   统一写 `st = so.run(ctx) if hasattr(so,'run') else so.infer(ctx)`。
2. **exec 回放步数**: seed104 插入任务约 347–349 步完成, `max_steps<350` 会 done=False (假失败)。
3. **仿真域 0 检出**: 在役检测器在 metaworld 渲染帧上 `det=[]` (训练域=产线真机); 产线实时帧当前也
   0 检出 (`~/zmax_data/ss_bypass/yolo_detections.json` n=0, 需现场摆件核对) —— L2 的"检测"与
   "收口闸"是两件事, 汇报时必须分开说, 别说成 L2 全无效。
4. **venv 选择**: `node.intact` 需要 `lerobot` 包 → 用 `gui-venv311`（有 metaworld+torch+lerobot src）
   `node.unified` 只需 transformers → INTACT venv 也可
2. **L5 真 TaskPlanner 会拖整条 lerobot 依赖链**（draccus 等）→ 默认用自带 `planner.rules`
3. 引擎的 L4 路径要求 `out.diagnostics['intent_norm']` 非零，否则 w=0（假接入）→ 节点须提供
