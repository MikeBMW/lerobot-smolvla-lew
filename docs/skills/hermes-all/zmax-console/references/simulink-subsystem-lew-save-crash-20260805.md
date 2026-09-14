# Simulink 子系统 · LEW 语义 · 保存模型 · 崩溃修复 (2026-08-05)

本次会话 (三模型对比迭代 + 架构澄清) 全部新知识。SKILL.md 已超 100KB 上限,
此文件为增量内容, SKILL.md 只需加一行指针。

## 1. 🎛 Simulink 子系统 (commit 037ab5e6, 老倪: "顶层系统用一个模块表示, 双击打开看到三条线")

参考 MathWorks Subsystem 语义:

- REFERENCE_APPS 加「🎛 总系统·三模型对比」顶层模板 (3节点: 📦数据→🔬总系统块→📊Scope),
  总系统节点 `params.subsystem = "🔬 三模型对比"`
- `on_node_activated` 最前加 subsystem 分支 → `_open_subsystem(node)`:
  保存当前 flow (含节点位置) 到 `self._subsystem_stack` → `load_reference_app_by_name(子模板)`
  → 工具栏「⬅ 返回总系统」按钮 (`btn_back`, 子系统内才 visible)
- `back_to_subsystem()`: pop 栈顶 flow → `load_flow` 恢复 (支持嵌套)
- `_update_back_btn()` 要在 `load_flow` / `clear` 后调用 (否则返回按钮状态不对)
- 显眼入口教训 (老倪: "顶层总系统 没有啊"): 参考应用滚动条里不易发现 →
  第二行工具栏加 `btn_topsys`「🎛 总系统」独立按钮 + `_topsys_hint` 金框高亮 + 气泡提示双击展开

## 2. 🌐 LeWorldModel 语义澄清 (老倪连问 z1/z2/z3 和训练/推理差异)

**关键澄清: z1/z2/z3 潜在空间不在 smolvla_lew, 在 zmax_hybrid!**

- `configuration_zmax_hybrid.py`: `wm_latent_dims=(256,256,128)` = z₁空间/z₂物体/z₃语义,
  `LeWorldModelGRU` (GRU 2层) + H-JEPA 能量损失 (wm_energy_loss_weight=0.1)
- 门控注入: `modeling_zmax_hybrid.py:403-407`:
  ```python
  use_wm = training or (self.config.enable_wm_inference and self.world_model is not None)
  for i, layer in enumerate(self.hybrid_layers):
      gate = self.config.hybrid_gates[i] if use_wm else 0.0   # (1.0, 0.1, 0.01)
      x = layer(x, z, gate)
  ```
- **训练/推理差异**:
  - smolvla_lew 的 LeWorldModel **只训不推**: `forward` 算 lew_loss (209-218行),
    但 `predict_action` (271-299行) 只走 `action_model` (DiT-B), `le_world_model` 完全不参与
  - zmax_hybrid 有 `enable_wm_inference` 开关: 默认 False → gate 归零 (世界模型不参与);
    True → 自回归参与 (更慢但可能更准) — smolvla_lew 没有这个能力
- 三模型完整图景: SmolVLA (无LEW, freeze_smolvlm=true 强制关) / SmolVLA+LEW (世界模型只训不推,
  Transformer 型) / zmax_hybrid (GRU 型 z1/z2/z3, 训练门控注入 + 推理可开关)

## 3. 🆕 lew_attn_mode 开关 — 真·交叉注意力 (commit 037ab5e6)

老倪: "action 与潜在空间做真正的 cross-attention (K/V 注入)" — 不是 AdaLN 调制。

- `configuration_smolvla_lew.py` 加 `lew_attn_mode: str = "adaln"` ("adaln" | "cross")
- `world_model_le.py` 新增:
  - `CrossAttention`: Q=帧嵌入(潜在空间), K/V=action 嵌入, norm_q/norm_kv + to_q/to_k/to_v
  - `CrossConditionalBlock`: ①帧内自注意力 ②交叉注意力(Q=帧,K/V=action) ③MLP
  - `Transformer` 加 `attn_mode` 参数, `block_cls = CrossConditionalBlock if attn_mode=="cross" else ConditionalBlock`
  - `ARPredictor` / `LeWorldModel` 透传 attn_mode
- `modeling_smolvla_lew.py` 实例化 LeWorldModel 时 `attn_mode=getattr(config, "lew_attn_mode", "adaln")`
- 单测 6/6: CrossAttention / CrossConditionalBlock / Transformer(cross+adaln) / LeWorldModel 全链路 / rollout

## 4. 🧩 ARPredictor 拆解 (老倪: "ARPredictor Transformer 还能拆解出来么")

模块库加「🌐 LeWorldModel·子模块」6 节点 (照 ACT 子模块模式):
1. 🖼 SigLIP 帧编码 (encode_frame)
2. 🎛 Action Embedder (Embedder: Conv1d+MLP SiLU, 作交叉注意 K/V)
3. 🔤 位置编码 (pos_embedding)
4. 🔀 输入/条件投影 (input_proj + cond_proj)
5. 🧠 CrossAttn 块 ×N (CrossConditionalBlock)
6. 📤 输出投影 (norm + output_proj)

对应 world_model_le.py 官方结构 (LeWorldModel 248-415行)。

## 5. 💾 保存模型链路 (commit 6c023def, 老倪: "当前训练的模型可以保存, 下次直接应用")

- Simulink 工具栏「💾 保存模型」(`btn_save_model`) → `save_trained_model()`:
  - 遍历 `reports/train_curve_<policy>.json` 的 `ckpt` 路径
  - 复制 `last/pretrained_model` (兜底 000300) 到 `models/saved/<policy>_<ts>/`
  - 写 `models/saved/registry.json` (name/path/step_s/ts)
- studio.py `InferencePanel` 加「已保存模型」下拉 (`saved_combo` 读 registry.json, 新在前)
  + 🔄 刷新按钮; `_on_saved_model_selected` 填 `ckpt_edit` 指向 `.../pretrained_model`

## 6. 🛡 QThread 崩溃修复 (commit aedf09fb, exit 134 SIGABRT)

症状: "QThread: Destroyed while thread is still running", 退出控制台时崩溃。

根因: `SimulinkModule.closeEvent` 只停 `_timer`/`_remote_timer`,
没停 `_acq_timer` (5s 采集轮询 QTimer) 且没等 `_acq_worker` (CICDWorker);
退出时 worker 还在跑 → 析构 QThread → SIGABRT。

修复模板 (closeEvent 里):
```python
acq_timer = getattr(self, "_acq_timer", None)
if acq_timer is not None:
    acq_timer.stop()
aw = getattr(self, "_acq_worker", None)
if aw is not None and aw.isRunning():
    try:
        aw.wait(3000)
    except Exception:
        pass
self._acq_worker = None
```
规则: **closeEvent 必须 stop 所有 QTimer + wait 所有还在跑的 worker**。

## 7. ⚙️ 验证工具链坑 (实测)

- **execute_code 的 sys.executable = Hermes venv python (无 PyQt5!)**:
  GUI 验证必须用系统 `python3` (有 PyQt5), torch 机制验证用 `.venv/bin/python` — 分开跑。
  误用 venv python 跑 GUI 脚本 → ModuleNotFoundError: PyQt5 / 超时, 且会被系统记为 stale 验证。
- **PyQt5 严格类型**: paintEvent 坐标必须 int (float 会崩 drawText/fillRect);
  `BarCompareWidget.paintEvent` 的 `y0 = i * row_h` float 隐藏 bug 是三模型渲染测试才暴露的。
- **按钮不可见坑×2**:
  ① 创建按钮但漏 `addWidget` (btn_compare3 按钮对象存在却从未挂布局 → 用户看不到) —
     验证必须查 `btn.parent() is not None` + 点击行为;
  ② 参考应用条 9 模板挤单行 QHBoxLayout → 后面按钮 (总系统/三模型) 被挤压隐藏 —
     改 QScrollArea 横向滚动 (`ra_scroll.setWidget(ra_inner)`, fixedHeight 32,
     ra_inner_lay 装按钮 + addStretch)。

## 8. 🔬 对比去重 (commit dacf60b9, 老倪: "对比 和 三模型对比 是不是重复了?")

- 双模型对比 ⚔️ (ACT + SmolVLA+LEW) 是三模型 🔬 (ACT + SmolVLA纯 + SmolVLA+LEW) 的真子集
- 按铁律 "一个功能一个入口, 绝不重复" 删除: REFERENCE_APPS 模板 / btn_compare / open_compare 全删
- grep 验证零残留注意: `grep "open_compare\b"` 用词边界, 否则 open_compare3 也算命中 (但它是三模型, 合法)
