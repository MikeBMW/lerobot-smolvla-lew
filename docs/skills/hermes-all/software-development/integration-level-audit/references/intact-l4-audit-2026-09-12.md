# INTACT 节点 L4 集成审计快照 — 2026-09-12

场景: 老倪问「INTACT 单独可以运行了, 那集成到状态空间的 L4 功能了么?」
答 (分级): **节点级已集成; 档位级未接 (差 S3 适配)。** 下面全部可复现。

## L0/L1 — 已达成 (证据)

```
注册      tools/gui/node_logic.py: _reg("intact", ["INTACT 意图-动作","INTACT"], …, node_intact)
          node_intact(ctx): 真跑一步 → log "action chunk{shape} · 策略={policy}(零搜索) ·
          candidate_sequences={n} · 延迟 {ms} · 数据源={src} · 输出={robot.name}"
          未就绪时 log "⚠️ 模型未就绪 (trained=False) — 原因: {reason}" (绝不返回假动作)
封装      src/lerobot/manifold/intact_node/{contracts,data_source,model_adapter,node,robot_io,selftest}.py
          + tools/intact_worker.py (跨 venv 常驻 worker)
自检 A    PYTHONPATH=src ./gui-venv311/bin/python -m lerobot.manifold.intact_node.selftest
          → "✅ 防假成功闸生效: stub 被拒 → INTACT 推理失败/未训练, 拒绝返回零动作"
          (自检还诚实标注: 观测为合成运动序列, 该 npz 无渲染帧, 不是相机图)
真权重单步 (提交 9ba6951b, 07:05 实测): chunk(4,10) · nonzero=40 · std 0.229/0.239/0.247 (逐步随
          观测+动作历史变化) · forward_calls=4 · candidate_sequences=0 · 平均 316ms/步
          · RobotIO 逐步下发 12 = 3×4
```

## L2 — 未达成 (四处都指向"没进执行链")

```
① 工程图 70 节点中 ssintact 连线数 = 0  ← 孤岛 (节点在位, 与 ssmani_p/ssmani_c/ssmani_exp 同排 y=-815)
② capability_levels 里没有 intact → L4 档 ▶运行/⏭单步 不会调用它 (只有双击/右键节点才真跑)
③ 3D 面板输出列原文: "action chunk [H,D] (零搜索) → (S3 前未接入引擎; 双击节点真调)"
   源码注释同款: "引擎侧在 S3 适配前**诚实标未接入**, 不写假 chunk"
④ robot_io 只有 SimRobotIO; HardwareRobotIO 构造即 NotImplementedError (预留)
```

## L3 — 未达成

RobotIO 硬件侧仍是预留接口 (未接 Orin 真机)。

## S3 适配的已知约束 (动手前先量化)

- 单步 316ms (paper 权重/GPU) vs 引擎帧率 → "每帧真调"必须先算延迟预算, 别直接许愿。
- 建议序列: ① 只读旁路 (每帧真调, 发数据总线/3D, 动作不参与下发) → ② 接管某段 (如标准抓取/插入, 同口径 A/B + 不回退) → ③ 硬件。
- 红线: 接入不得让插拔成功率回退; 未接入就写"未接入", 不许占位数值冒充。

## 复用要点 (下次同类问题照这个走)

1. 先跑 `selftest` (A 闸) —— 30 秒内能给出 L1 结论。
2. 数连线 (links) —— 一条命令就能分辨"画上去了"与"接上了"。
3. 读代码自己的诚实标注 (grep 未接入/S3) —— 比任何推断都可靠。
4. 汇报必须分级 + 报数字, 并给出下一级的具体动作与约束。
