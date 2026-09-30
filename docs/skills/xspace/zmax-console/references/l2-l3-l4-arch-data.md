# ArchitectureModule L2/L3/L4 数据结构参考

## levels 数组结构

```python
levels = [
    (title, model_name, accent_color, [
        (sys_id, desc, color, items),  # SYS 2
        (sys_id, desc, color, items),  # SYS 1
        (sys_id, desc, color, items),  # SYS 0
    ]),
    ...
]
```

## items 的两种形态

**SYS2 / SYS0** (字符串列表 — 显示为多行文本):
```python
items = ["行1", "行2", "行3"]
```
→ 在 `_level_card` 中走 `_layer_box` 渲染

**SYS1** (子盒子元组列表 — 显示为 SYS11/SYS12 并列):
```python
items = [("SYS 10", "ACT", C_CYAN), ("SYS 12", "—", C_GRAY)]
```
→ 在 `_level_card` 中用 `isinstance(items[0], tuple)` 判断，走 `_sys1_box` 渲染

## 常见错误

| 错误 | 原因 | 修复 |
|------|------|------|
| `ValueError: not enough values to unpack (expected 4, got 3)` | SYS1 层只有3个字段 `("SYS 1", color, [...])` 缺 desc | 加 desc: `("SYS 1", "边缘推理", color, [...])` |
| `KeyError: 'folder'` | Phase 数据字典中删了 folder 但代码还在引用 | 删 PhaseCardButton._build path_lbl + _on_phase_clicked 中所有 folder/config_file 引用 |
| 控制台与PPT不一致 | 自己发明了配色/布局 | 严格按照PPT第24页手绘复现，用取色器提取原色 |

## 当前有效数据 (v1.0.6)

**L2 基线** — `SYS0_COLOR`
- SYS2: 离线训练 / 轻量模型
- SYS1: [SYS 10 ACT] [SYS 12 —]
- SYS0: 固定工位 / 力控1kHz / 视觉定位

**L3 增强** — `C_YELLOW`
- SYS2: 远程下发 / 模型热更新
- SYS1: [SYS 11 VLA-T]
- SYS0: 多工位移动 / OTA升级 / 多模态感知

**L4 旗舰** — `ROI_ACCENT`
- SYS2: 全自动训练 / 5090 GPU / 100K+数据集
- SYS1: [SYS 11 VLA-T] [SYS 12 Z-Flow]
- SYS0: 全自主移动 / 双臂协同 / 触觉反馈
