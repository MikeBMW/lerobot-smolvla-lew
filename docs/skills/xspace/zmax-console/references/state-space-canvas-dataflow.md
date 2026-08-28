# 状态空间画布连线 = 引擎真实数据流 (2026-08-28 触觉感知漏连线)

## 症状
老倪「触觉感知的数据源, 也应该是 metaworld」— 状态空间画布 (flows/state_space_obs.json)
里「🖐 触觉感知」节点**入度=0 孤立**, 没有任何上游连线。

## 根因
引擎 `state_space_sim._build_obs` 的 `tactile4=[gripper, contact, 0, 0]` 里:
- `gripper` = metaworld 夹爪开度真值
- `contact` = metaworld 物理接触检测 (销钉触指垫/孔沿)

即触觉数据**真实来源就是 metaworld**, 但画布上没画这条线 → 因果缺失:
单步执行时孤立节点反而排拓扑第一 (因果倒置), 观众看不出"触觉依赖 metaworld"。

## 修法 (commit 7db9b211)
`flows/state_space_obs.json` links 追加:
```json
{"id": "lktactile1", "f": "ssdata", "t": "sstactile",
 "f_port": "out1", "t_port": "in1", "label": "触觉数据"}
```
节点 sstactile params.desc 注明: "夹爪开度+接触力 (metaworld 真值) → 4D 触觉 [grasp/contact/dir]"
拓扑验证: 排序第一可执行节点应变为「📦 metaworld 数据源」。

## 检查法 (任何画布节点排查, 别猜)
```python
import json
d = json.load(open('flows/state_space_obs.json'))
for n in d['nodes']:
    if n['type'] == 'row_bg': continue
    ins = [next(x['name'] for x in d['nodes'] if x['id']==l['f'])
           for l in d['links'] if l['t']==n['id']]
    print(n['name'], '入度源:', ins or '(无上游)')
```
数据源类节点 (📦metaworld / 🎯YOLO / 🖐触觉 / 📡传感器) **必须都有 `ssdata ->` 入边**。
**引擎内部直接取数 ≠ 画布有连线, 两处必须一致** — 老倪工程真实性零容忍:
画布拓扑必须如实反映数据来源, 不许画了节点但源头没接线 (同族教训: 写死conf0.99/
真值投影冒充检测结果/解算模块写了没接, 都是被老倪戳穿的假链路)。

## 同类参考
- 单步执行链路: step_sim (simulink_module.py) → _sim_node → node_logic.execute_node_logic → node_xxx(ctx)
- 拓扑排序: _topo_sort 对有环连线走「剩余(有环)追加」, 不卡死只排末尾
