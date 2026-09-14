# row_bg 模型名遮挡 (JSON 画布布局)

## 根因
- JSON flow (`state_space_obs.json` / `atomic_conditions_flow.json` 等) 里 row_bg 的 x 是硬编码 `-20`, 而节点 x 从 40~100 起 → 模型名区实际只有 ~112px。
- 模型名绘制宽度若写死(曾用 230px), 文字伸到节点列被方块盖住 = 用户反复报"背景字被遮挡/要向左移"。
- 同一份 row_bg paint 代码服务所有画布, 但各画布节点起点不同 → 不能统一固定宽度。

## 修复 (通用自适应, 三处一致)
1. **paint 里 avail_w 自适应**: `avail_w = max(80, min(节点x) - row_bg.x - 16)`, 不写死 230px。
2. **load_flow 与 load_flow_file 加载后都要自动左移 row_bg** 到 `minx - 266` (模型名区固定 250px), 同时 `w += (oldx - newx)` 右界不变(不露节点)。⚠️ **两个是独立函数**: `load_flow` (代码模板 load_reference_app 用) 与 `load_flow_file` (JSON flow 加载用) — 只改 load_flow 会漏掉 JSON 画布(状态空间/原子条件走 load_flow_file), 曾因此"背景字还遮挡"二次反馈。
3. **_draw_model_rows 的 x0 同步** `base_x - 266`。

## 字大 / 完整 / 不遮挡 三要求同时满足
- 左移 row_bg 留足 250px + 自适应宽度 + 字体 9pt 起步降 6pt + 拆两行。
- 英文名 "SmolVLA+LEW" 无空格 → 拆分要 `.replace("+"," + ").replace("-"," - ")` 才拆得开。

## 各画布坐标速查
- Model Zoo: `_draw_model_rows` 生成, base_x=120, x0=base_x-266。
- 状态空间 / 原子条件: JSON 硬编码 row_bg x=-20, 节点 x=40~14040。
- 结论: 不同画布节点起点不同 → 必须"自适应宽度 + load 时统一左移", 不能固定绘制宽度。
