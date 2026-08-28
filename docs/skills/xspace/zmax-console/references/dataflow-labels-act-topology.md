# 连线数据流标签 + ACT 数据流拓扑 (2026-08-05 实测)

老倪问题: "为什么 metaworld数据有直接链接 VAE编码器的连线? 有什么直接输入?" — 引出了两个交付: 连线标签功能 + ACT 数据流拓扑实证。

## 1. 连线标签功能 (commit f8334840)

模板连线元组支持第3元素 label: `(fi, ti, "图像")`。

- `load_reference_app`: `for fi, ti, *label in link_specs:` 解包 → `self.add_link(..., label=label[0] if label else None)`。老模板 2 元组 `(fi,ti)` 兼容 (*label 空)。
- `add_link(self, src_item, dst_item, label=None)`: `if label: link["label"] = label`。
- **SimLinkItem.paint 画贝塞尔中点标签**: `mid = path.pointAtPercent(0.5)` + `QRectF(mid.x()-lw/2, mid.y()-lh/2, lw, lh)` 半透明黑底 `QColor(0,0,0,160)` + `QFont("Consolas", 7)` 白字 `#e6edf3`, `painter.drawRoundedRect(lr,3,3)` + `drawText(lr, Qt.AlignCenter, lbl)`。QRectF 顶部已 import (QtCore 第9行), 别在函数内重复 import。
- 验证 (offscreen, LABEL-VERIFY-PASS):
  ```python
  labels = {l.get("label", "") for l in w.links}
  assert "图像" in labels and "动作" in labels and "状态" in labels
  mw = next(n for n in w.nodes if "metaworld" in n["name"])
  outs = [(l.get("label",""), w._by_id(l["t"])["name"]) for l in w.links if l["f"] == mw["id"]]
  assert len(outs) == 5  # ACT 3路 + SmolVLA纯 1 + SmolVLA+LEW 1
  ```
  无标签手动连线渲染不崩 (paint 的 `lbl = self.link.get("label","")` 空串跳过)。

## 2. ACT 数据流拓扑 (官方 modeling_act.py forward 实证)

回答"为什么状态直接进 Transformer Encoder":

**Transformer Encoder 输入 = 三路 token 拼接** (modeling_act.py:460-493):
1. `encoder_latent_input_proj(latent_sample)` — CVAE 潜变量 (461行)
2. `encoder_robot_state_input_proj(batch[OBS_STATE])` — **机器人状态直接进 Encoder** (465行, 架构设计: 条件生成器必须看到当前关节位姿)
3. `backbone(img)["feature_map"]` — ResNet18 图像特征 (475行)

**CVAE (vae_encoder) 的输入是 action 序列 + state, 不是图像** (415行):
```python
action_embed = self.vae_encoder_action_input_proj(batch[ACTION])  # (B, S, D)
vae_encoder_input = [cls_embed, robot_state_embed, action_embed]  # 训练时编码真值动作
```
训练时把真值动作序列编码成潜变量 → 供 Encoder 条件生成。

**metaworld 数据节点 = 多信号源**, 三路输出:
| 连线 | 标签 | 去向 |
|---|---|---|
| 数据→ResNet18 | 图像 | backbone 视觉编码 |
| 数据→CVAE | 动作 | vae_encoder 编码真值动作 |
| 数据→Encoder | 状态 | encoder 条件 token |
| CVAE→Encoder | 潜变量 | latent 投影 |
| ResNet18→Encoder | 图像特征 | backbone 输出 |

**连线计数**: 数据节点出线数 = ACT路 3条 + 每个 SmolVLA 分支 1条「图像+状态」。三模型模板: metaworld 共 5 条出线, 总连线 21 = ACT 9 + SmolVLA纯 4 + LEW 5 + 评估 3。双模型模板: 16 连线。

## 3. 排查顺序教训

用户质疑画布连线语义时, 先查官方 forward 代码 (grep `vae_encoder|def forward|batch[ACTION]`), 用代码行号回答, 别凭直觉。连线正确但语义不直观 → 加标签让数据流可见, 而不是改拓扑。
