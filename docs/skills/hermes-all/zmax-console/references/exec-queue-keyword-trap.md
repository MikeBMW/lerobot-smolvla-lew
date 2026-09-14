# 执行队列 keyword 误匹配陷阱 (2026-08-06)

## 症状
五模型对比「▶ 运行」只训练到第 3 个模型就停, VLA-Touch/AWE 没启动;
或 CICD 主控台 ▶运行 第一个环节是「☑ 训练开关」(打乱语义)。

## 根因
`_canvas_stage_nodes()` 用 **NODE_RUN_ACTIONS 关键字匹配** 决定哪些节点进执行队列:
```python
NODE_RUN_ACTIONS = [("采集","on_collect"), ("训练","on_train"), ..., ("推理","on_infer"), ...]
for kw, meth in self.NODE_RUN_ACTIONS:
    if kw in n.get("name", ""): out.append(...)
```
两个真实踩坑:
1. **「🎥 推理效果对比」含"推理"** → 被匹配成 on_infer 环节, 混进五模型对比队列排最后
   → 它执行时 (Orin 状态查询) 阻塞/失败, 队列卡住, 后续 VLA-Touch/AWE 训练根本没轮到
2. **「☑ 训练开关」含"训练"** → 被匹配成 on_train 环节, CICD 主控台队列第一个就是开关

## 修复 (已在 _canvas_stage_nodes 内)
```python
if n.get("params", {}).get("video"):
    continue   # 🎥 视频显示/推理对比: 观察类, 手动双击播放, 不进执行队列
if n.get("type") == "train_gate":
    continue   # ☑ 训练开关: 控制标志非执行环节, 开关状态由 on_train 内部检查
```

## 通用教训
- 关键字匹配节点名设计脆弱: 新节点名**不能含** NODE_RUN_ACTIONS 关键字 (采集/训练/验证/
  集成/部署/推理/Scope/PDF), 否则被误当执行环节。命名时避开或加排除逻辑。
- 同类问题: video 节点 (含"视频") 和 train_gate (含"训练") 都踩过; 新增节点类型时
  同步检查 _canvas_stage_nodes 排除分支。
- 队列卡住的排查顺序: ① 看日志"⏳ 上一个任务还在跑"重复 ② 检查 _canvas_stage_nodes
  返回的 stage 列表 (offscreen 打印 names) ③ 确认没有观察/控制节点混入。
