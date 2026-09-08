# 12 列布局实录: 训练 → 仿真推理 → 仿真视频 (2026-08-07)

老倪: "重新改一下布局, 将仿真推理的节点放在训练的右侧, 然后视频对比再放在右侧, 而且每个视频要对应着相应的模型, 这样看着比较清晰"

## 需求
旧布局把 7 个「🎮 仿真视频 · X」横排在独立视频行 (列1-7), 与模型行不对应。新布局: **每模型行内** 训练(列9) → 🎮仿真推理·X(列10) → 🎮仿真视频·X(列11)。

## id 分配机制 (关键澄清)
`load_reference_app` (simulink_module.py ~L2879):
```python
pos = {}  # layout 名 → [(x,y), ...]  (同名节点多个位置)
for r, row in enumerate(layout):
    for c, nm in enumerate(row):
        if nm: pos.setdefault(nm, []).append((base_x + c*200, base_y + r*230))
used = set()
for i, (ntype, nm, params) in enumerate(node_specs):   # ← id 按 specs 顺序!
    xy = next((p for p in pos.get(nm, []) if p not in used), None)  # 无位置 → 兜底
    n = self.add_node(ntype, nm, xy[0], xy[1], params)  # add_node 用 gen_id() 递增
```
- **id = specs 顺序**, layout 只是摆放 (按名字找坐标)
- 改 layout 行不改变 id; 新 spec 追加到 specs 尾部 → id 追加 (51-57), 旧 links 全保留
- 同名节点 (📦数据×7 / 🎯YOLO开关×7 / 🔌SA×6) 是**同一 spec 复用**, 所以节点总数 = specs 数 (66), 不是 layout 非空格数 (84)

## 新 specs (追加到「🎮 仿真视频 · 专家」之后, id 51-57)
```python
("system", "🎮 仿真推理 · ACT", {"video": True, "video_policy": "act", "infer": True,
    "desc": "🎮 ACT 本地仿真推理: metaworld rollout 评估 (非 Orin 真机) → 生成该模型视频, 双击执行"}),
# ... SmolVLA / SmolVLA+LEW / VLA-Touch / AWE / MLP / 专家 同款 (video_policy 分别对应)
```

## 新 links (links 段末尾追加, 旧 86 条零改动)
```python
(11, 51, "仿真推理"), (15, 52, "仿真推理"), (20, 53, "仿真推理"),
(26, 54, "仿真推理"), (32, 55, "仿真推理"), (44, 56, "仿真推理"), (48, 57, "仿真推理"),
(51, 35, "rollout"), (52, 36, "rollout"), (53, 37, "rollout"),
(54, 38, "rollout"), (55, 39, "rollout"), (56, 49, "rollout"), (57, 50, "rollout"),
```
训练 id: 11=ACT / 15=SmolVLA / 20=LEW / 26=VLA-Touch / 32=AWE / 44=MLP蒸馏 / 48=专家基准
视频 id: 35-39=ACT/SmolVLA/LEW/VLA/AWE, 49=MLP, 50=专家 (specs 中部/尾部定义, 不变)

## 新 layout (12 列, 每模型行尾加推理+视频)
```python
["📦 metaworld 数据", "🎯 YOLO 感知开关", "🔌 State Adapter", "🖼 视觉主干 ResNet18", "🧬 VAE 编码器 CVAE",
 "🔤 Transformer Encoder", "🔡 Transformer Decoder", "🎯 Action Head 4D · ACT", "⏳ Temporal Ensemble",
 "🚀 ACT 训练", "🎮 仿真推理 · ACT", "🎮 仿真视频 · ACT"],
# ... 其余 6 行同构: 训练在列9, 推理列10, 视频列11
# 评估行: ["📊 对比评估 Scope (仿真)", "", "", "", "", "", "", "🎮 仿真推理对比", "", "", "", ""]
# PDF 行: ["", "", "", "", "", "", "", "📄 PDF 技术选型报告", "", "", "", ""]
```
背景行: `self._draw_model_rows([...8 行...], n_cols=12)` (open_compare5 调用处)

## 验证 (offscreen 真跑, tempfile 脚本即用即删)
```python
mod.open_compare5()
# 7 模型: 训练.x(1920) < 推理.x(2120) < 视频.x(2320) 且 y 同行 (310+230r)
# 三列各自 x 集合 len==1 (列对齐)
# links 全部 f/t ∈ 节点 ids (无悬空)
# 背景行 8 条, bg[0].w >= 120 + 12*200 (2660)
# (11→51), (51→35) link 存在
```
节点数断言 = 66 (specs 数), 不是 84 (layout 非空) — 数错会误报失败。

## 坑
- 改完重启 GUI 生效; 重启前确认训练类型 (closeEvent pkill 只杀 lerobot_train/cicd_pipeline, 独立脚本安全)
- 重启后 auto_run **默认不再自动训练** (ZMAX_AUTO_TRAIN=1 才训) — 见 SKILL.md auto_run 节
