# 手工改 flow JSON 的安全规程 + 布局代价取证 (2026-09-16 实录)

场景: 给 `flows/state_space_obs.json` 补「L2 行 → L4 行」两条边 (老倪要求 "L2 应与 L4 兼容 …也要连线")。
本次**写坏过一次** JSON, 靠备份回滚 —— 下面的规程就是那次踩出来的, 建议直接照做。

## 1. 写前校验 (本次踩坑点, 一次就够)

```python
src = open(p, encoding="utf-8").read()
anchor = '…唯一锚点…'
assert src.count(anchor) == 1, f"锚点不唯一: {src.count(anchor)}"   # 锚点写错的表现是 count==0, 不是崩
src2 = src.replace(anchor, anchor + NEW_LINKS, 1)
src2 = src2.replace(old_desc, new_desc, 1)
json.loads(src2)                      # 🛡 先验证 JSON 合法, 再落盘 —— 关键一步
open(p, "w", encoding="utf-8").write(src2)
```

事故: 在节点 `desc` 里多打了一个 `"` (把 `**数据源直接接入…` 写成 `"数据源直接接入…`),
写盘后 `json.loads` 报 `Expecting ',' delimiter: line 1354 column 163 (char 33255)` ——
**因为当时校验在写之后**, 直接把文件写坏了。`cp flows/x.json /tmp/flow_backup_$(date +%H%M).json`
(改之前先做) + 校验前置 = 双保险。

## 2. 替换后立即断言零丢失

```python
before, after = json.loads(b_src), json.loads(a_src)
assert {n["id"] for n in after["nodes"]} == {n["id"] for n in before["nodes"]}     # 节点不变
bd = {l["id"]: json.dumps(l, sort_keys=True, ensure_ascii=False) for l in before["links"]}
ad = {l["id"]: json.dumps(l, sort_keys=True, ensure_ascii=False) for l in after["links"]}
print("旧连线逐字段变化:", [k for k in bd if ad.get(k) != bd[k]] or "0 条 (全部原样)")
print("新连线:", sorted(set(ad) - set(bd)), " · 连线数", len(before["links"]), "->", len(after["links"]))
```
本次实况: 节点 77→77 · 连线 95→97 · 旧连线 **0 条**变化 · 新 id = `['lkild_l2a','lkild_l2b']` ·
`ssintact` 入线槽: in1=ssdata(数据源真帧) / in2=sssensor(L2 融合) / in3=ssff(L2 前馈)。

## 3. 布局代价必须与改前基线对比 (同工具, 两次)

- `tools/verify_l4_layout.py` **必须用 `gui-venv311`** (要 PyQt5; `~/lerobot-venv` 会
  `ModuleNotFoundError: ModuleNotFoundError: PyQt5`)。跑法:
  `QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/verify_l4_layout.py > /tmp/layout.log 2>&1`
- **改前跑一次、改后再跑一次**, 相减才敢报数字 (本次):
  | 指标 | 改前 | 改后 |
  |---|---|---|
  | 反向连线 | 2 | 4 (+2 = 本次两条, 均标 ↩) |
  | 方框重叠 | 0 | 0 |
  | 连线穿框 | 44 | 45 |
  | 连线交叉 | 145 | 161 (+16) |
- ⚠️ 该工具报的"连线数"(94) **小于** JSON 里的实际条数(97) —— 别拿它的计数当总数。
- 该工具的输出很长, `tail -16` 会把 ①②③④ 的合计行截掉 → 需要合计就 `> 文件` 再 grep/sed 读头部。
- 语义零回退另跑 `tools/verify_l4_zero_regression.py` (gui-venv311): 档位归属 + L2/L3/L4 执行集
  (55/60/77) + 旧连线 0 丢失 —— 本次全 ✅。

## 4. 跨行连线天生反向, 别硬消

画布右侧的行 (前馈 x≈3826) 连向左侧行 (L4 行 x=387) 必然 `ax > bx`; 传感器融合 (x=387, w=160) → L4 行
也退 280px。连线 label 标 `↩` + 交付里如实报条数; 想真消掉只能重排行/执行器位置 (与
`canvas-forward-layout-2026-09-14.md` 的"闭环在左→右布局中必然留反向线"同源, 且需先问用户)。

## 5. 节点 desc 的多路入线口径声明

一个节点被多路接入时, 在 desc 里逐条声明 `in1 = … / in2 = … / in3 = …` (老倪红线: 画布自解释)。
本次 `ssintact` 补的是「三路入线口径」: in1 数据源真帧+39D / in2 L2 感知融合状态 / in3 L2 前馈 MLP 的 u_ff。

## 6. ⚠️ 画布补线 ≠ 数据流通

补边之前先确认那条边**在代码里真的每帧有数据**: 本次两条边的成立条件是 L4 档 `vision=True` (感知) 与
`SS_USE_MLP=1` (前馈真身), 两个开关默认都不为 L4 打开 —— 只补画布线就宣称"L2 与 L4 兼容"会是假接入。
配套审计见 `integration-level-audit` → `references/l4-l2-compat-audit-2026-09-16.md`。
