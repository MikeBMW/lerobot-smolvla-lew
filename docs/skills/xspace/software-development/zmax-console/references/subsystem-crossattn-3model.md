# Z-MAX Simulink: 三模型对比 / 子系统 / CrossAttn / 数据流标签 (2026-08-05)

本会话 (v1.7.0 前后) 全部 Simulink 架构演进记录。GUI 文件: tools/gui/simulink_module.py, simulink_scope.py;
模型文件: src/lerobot/policies/smolvla_lew/{world_model_le, modeling_smolvla_lew, configuration_smolvla_lew}.py。

## 1. 🎛 Simulink 子系统 (顶层总系统, commit 037ab5e6)

老倪: "参考 Simulink, 用一个模块表示总系统; 双击打开后, 可以看到 ACT, SmolVLA, SmolVLA+LEW 等三条线"。

- **顶层模板** REFERENCE_APPS 加「🎛 总系统·三模型对比」= 3 节点: 📦metaworld数据 → 🔬总系统·三模型对比 → 📊对比评估Scope。
  总系统节点 params 带 `subsystem: "🔬 三模型对比"` + `type_label: "Subsystem"`。布局单行 3 节点。
- **双击展开** `on_node_activated` 最前面加分支 `if params.get("subsystem"): self._open_subsystem(node); return`
  (必须放数据源/Switch/环节匹配**之前** — 子系统节点 type=system, 名字含"对比"会被 NODE_RUN_ACTIONS 误匹配)。
- **_open_subsystem(node)**: 把当前顶层 flow (含节点位置) dict 存进 `self._subsystem_stack` (append) →
  `load_reference_app_by_name(sub_name)` 加载内部模板 → `_subsystem_active=True` → `_update_back_btn()` →
  日志三行引导。加载失败要 `pop()` 回滚栈。
- **返回** `back_to_subsystem()`: 栈非空才动作, `top_flow = stack.pop()` → `load_flow(top_flow)` 恢复顶层 →
  栈空时 `_subsystem_active=False` → `_update_back_btn()`。
- **按钮** 第二行工具栏「⬅ 返回总系统」btn_back, 初始 `setVisible(False)`; `_update_back_btn()` = `btn.setVisible(bool(_subsystem_stack))`。
- **load_flow 末尾必须调 `_update_back_btn()`** — 恢复顶层后按钮自动隐藏, 否则残留。
- 栈式设计天然支持嵌套子系统 (总系统→子系统→再进), 实测往返无损。
- 验证: 顶层3节点 → on_node_activated 展开 18/22 → back 恢复 3 节点; 按钮显隐; 嵌套往返。

## 2. 🌐 LeWorldModel CrossAttention — action K/V 注入 (commit 037ab5e6)

老倪连续三次追问架构: "leworldmodel的z1 z2 z3潜在空间, 不是应该给action有输入么?" →
"ARPredictor Transformer 还能拆解出来么?" → "是 action 与潜在空间做真正的 cross-attention (K/V 注入)"。

- **原实现是 AdaLN-zero 调制** (world_model_le.py ConditionalBlock): `adaLN_modulation(c).chunk(6)` 生成
  shift/scale/gate, 调制帧嵌入后过自注意力。action 只生成调制参数, 不做 attention 键值。
- **新增 lew_attn_mode 配置** (configuration_smolvla_lew.py): `"adaln"` (默认, 兼容旧权重) | `"cross"`。
  modeling_smolvla_lew.py 实例化 LeWorldModel 时 `attn_mode=getattr(config, "lew_attn_mode", "adaln")` 透传。
- **CrossAttention 类**: Q=帧嵌入(潜在空间), K/V=action 嵌入。norm_q/norm_kv + to_q/to_k/to_v +
  scaled_dot_product_attention。输出 (B,T,D)。
- **CrossConditionalBlock**: ①自注意力(帧内) ②交叉注意力(Q=帧, K/V=action) ③MLP, 三个残差 + LayerNorm。
- **Transformer 加 attn_mode 参数**: `block_cls = CrossConditionalBlock if attn_mode == "cross" else ConditionalBlock`,
  循环 depth 层。ARPredictor → LeWorldModel 逐层透传 attn_mode。
- **单测模式 (venv torch)**: CrossAttention 形状 / CrossConditionalBlock / Transformer(cross 每层类型断言) /
  Transformer(adaln 兼容) / LeWorldModel 全链路 forward(videos, actions) loss 标量 / rollout。
  FakeVisionEnc 要输出 config 声明的 hidden_size (32), LeWorldModel.projector 再 32→obs_dim — 输出维度不一致会
  RuntimeError mat1/mat2。
- **ARPredictor 拆解入库**: 模块库加「🌐 LeWorldModel·子模块」分类, 6 节点:
  🖼SigLIP帧编码 / 🎛Action Embedder / 🔤位置编码 / 🔀输入条件投影 / 🧠CrossAttn块×N / 📤输出投影,
  对应 world_model_le.py 官方结构 (encode_frame → Embedder → pos_embedding → input/cond_proj → CrossConditionalBlock×depth → norm+output_proj)。
  节点 desc 写明 "action 作为交叉注意 K/V"。

## 3. 🏷 连线数据流标签 (commit f8334840)

老倪: "为什么 metaworld数据, 有直接链接 VAE编码器的连线呢? 有什么直接输入呢?" — 数据节点是多信号源,
一条线没标注类型会误解。

- **官方 ACT 数据流** (modeling_act.py:460-493): Encoder 输入 = latent(VAE潜变量) + robot_state(状态) + 图像特征(ResNet18)。
  CVAE 输入 = **动作序列 + 状态** (不是图像!); ResNet18 输入 = 图像。
- **add_link(src_item, dst_item, label=None)**: link dict 加 `"label"` 键。
- **模板 link_specs 支持 3 元组** `(fi, ti, label)`: load_reference_app 里 `for fi, ti, *label in link_specs` →
  `label=label[0] if label else None`。双/三模型模板的 metaworld 出线都标注:
  (0,1,"图像")→ResNet18 / (0,2,"动作")→CVAE / (0,3,"状态")→Encoder / (0,8,"图像+状态")→SmolVLM2。
- **SimLinkItem.paint 画标签**: 贝塞尔 `path.pointAtPercent(0.5)` 中点, 半透明黑底 QRectF + 白字 Consolas 7pt,
  不干扰连线。QRectF 顶部已 import, 别在函数内重复 import。
- **三模型模板补 (0,3) 状态连线**: 原模板漏了 state→Encoder (官方 encoder 拼接 latent+图像特征+state), 补后
  ACT 路 9 条, 总连线 22 (原 20)。

## 4. 🔬 性能对比扩展 — 8 指标 (commit dfe153e0)

老倪: "除了loss曲线, 还有什么能对比模型的性能呢? 也需要增加"。

- **compare_models.py eval_policy 新收集**: `traj_pred/traj_gt` (逐帧动作轨迹, 限120帧),
  `frame_err` (逐帧MSE), `mse_p50/mse_p90` (误差分布分位), `smoothness` (相邻预测动作差分 std, 小=真机抖动小)。
  res dict 全部落盘。
- **ModelCompareDialog 通用 N 模型** (simulink_scope.py): MODELS 表 `[("act","ACT","act"), ("smolvla","SmolVLA","smolvla"), ("smolvla_lew","SmolVLA+LEW","smolvla_lew")]`,
  `present = [(k,tag,c) for k,tag,c in MODELS if k in m and m[k]]` 过滤; loss 折线/指标条形/表格全按 present 动态列。
- **新增「📉 逐帧误差曲线」err_scope** (第二个 ScopeWidget): 每模型一条 MSE over frames; 无数据分支也要
  `err_scope.set_series({})` 否则旧数据文件崩。
- **bars 5→8 指标**: 训练速度/MSE/成功率/鲁棒性/延迟/P50/P90/平滑度; BarCompareWidget.set_data(rows, names)
  数据形变 `[(name, [n模型值...], lower_better)]`, COLORS=[蓝/橙/紫]。
- **⚠️ BarCompareWidget.paintEvent 坐标必须 int** (commit 53164e6a): `y0 = int(i * row_h)`, `yy = y0 + 6 + int(j * (bar_h + 2))`
  — PyQt5 drawText/fillRect 严格 int, float 崩 (TypeError: arguments did not match any overloaded call)。
  原双模型版就有此隐藏 bug, 三模型渲染对话框时才暴露。
- **旧数据兼容**: 缺新字段的 model_compare_*.json 显示 "-" 不崩 (m[k].get(key, float("nan")) + v==v 判断)。
- **重跑评估**: 对话框读 reports/ 最新 model_compare_*.json — 旧脚本生成的文件没有新字段, 必须
  `.venv/bin/python tools/compare_models.py --frames 60` 重新生成才有 8 指标。数据文件新旧决定界面显示。

## 5. 双模型对比删除 — 去重铁律 (commit dacf60b9)

老倪: "那对比, 和 三模型对比, 是不是重复了?" → 确认重复, 删「⚔️ 对比」只留「🔬 三模型对比」。

- **双模型是三模型真子集** (双模型的 SmolVLA 分支 = 三模型的 SmolVLA+LEW 分支), 单入口铁律适用。
- **删除点 4 处**: REFERENCE_APPS 模板 / LIBRARY 模块库条目 / btn_compare 按钮+addWidget / open_compare 方法。
  `_compare_load_hint` 保留 (三模型对比共用)。
- **残留检查要用代码级**: `grep 'open_compare\b'` 会漏掉注释里的 "open_compare3" 子串误报;
  正确 = 过滤注释行 (`l.strip().startswith('#')`) 后 join, 断言 `"def open_compare(" not in` 和 `"self.btn_compare = " not in`。
  注释里的 "ACT vs SmolVLA" 是描述性文字, 合法残留。
- 验证: 参考应用列表无双模型 (`not any('⚔️' in n ...)`), btn_compare3 点击加载 18/22, ACT-Meta 回归 9 节点。

## 6. ⚠️ 验证脚本环境坑 (execute_code 误用 venv python)

- execute_code 的 `sys.executable` 是 **Hermes venv python, 没有 PyQt5** → GUI 验证脚本 ModuleNotFoundError。
- 系统 python3 有 PyQt5 但**没有 torch** (torch 在项目 .venv)。
- **正确姿势: 分两个脚本跑** — 机制类 (CrossAttn/torch) 用 `.venv/bin/python`, GUI 类 (PyQt5) 用 `python3`。
  都通过 tempfile.mkstemp 创建 hermes-verify-*.py, 跑完 os.remove, 避免 /tmp 残留 (残留会被 curator 当 changed paths)。
- os.write(fd, b'''...''') 字节字面量不能含中文 → 用普通字符串 + .encode()。

## 7. 工具栏按钮必须 addWidget (commit 6a3ef710)

btn_compare3 创建后漏 `tl2.addWidget(...)` → 按钮对象存在但界面上看不到 (老倪: "没有三模型对比啊")。
第一行按钮过多会被 QHBoxLayout 挤压隐藏 → 放第二行 (🎯控制台/🧠ACT-Meta/🔬三模型)。
**新建按钮铁律: mk_btn → addWidget → 验证 `b.parent() is not None` + 点击能触发**。

## 8. 📜 参考应用条按钮挤压 → QScrollArea 横向滚动 (commit 93013c03)

老倪两次 "没有总系统啊" — 根因不是模板缺失, 是**按钮被挤压看不见**:
- 参考应用条单行 QHBoxLayout fixedHeight 38, 9 个模板按钮 (CICD/流水线/取料/力控/闭环/AOI/ACT-Meta/总系统/三模型),
  后面的 (总系统/三模型) 溢出窗口 → 视觉不可见。
- ⚠️ **offscreen 断言 hasattr/_ref_btns 全过 — 对象存在 ≠ 用户可见**。验证必须渲染采样像素
  (offscreen QPixmap render 参考应用条 QFrame, 找按钮背景色; 注意深色主题按钮色是 dark btn 色 #21262d 不是 #e9edf2)。
- 修复: 参考应用条改 QScrollArea 横向滚动 —
  ```python
  ra_scroll = QScrollArea(); ra_scroll.setWidgetResizable(True); ra_scroll.setFixedHeight(32)
  ra_inner = QWidget(); ra_inner_lay = QHBoxLayout(ra_inner)  # 按钮全部 addWidget 到 inner
  ra_scroll.setWidget(ra_inner); ral.addWidget(ra_scroll, 1)
  ```
  QScrollArea 已在文件顶部 QtWidgets import 里, 别在函数内重复 import。
- **通用教训: 任何"按钮/条目多于一屏"的条状区 (参考应用/工具栏/环节), 用 QScrollArea 或双行,
  别指望单行 QHBoxLayout 硬塞; 用户反馈"没有X"先怀疑挤压不可见, 再怀疑代码缺失。**

## 9. 💾 保存模型固化 — 训练产物 → 应用模型 (commit 6c023def)

老倪: "当前训练的模型可以保存, 下次直接应用"。

- **模型生命周期分层**: `outputs/train/<ts>/checkpoints/` = 训练产物 (每次训练新目录, 易混);
  `models/saved/<policy>_<ts>/` = **固化应用模型** (registry 管理, 推理面板下拉选)。
- Simulink 工具栏「💾 保存模型」→ `save_trained_model()`:
  1. `glob reports/train_curve_*.json` → policy + ckpt 路径 (d["ckpt"])
  2. checkpoint 取 `checkpoints/last/pretrained_model` (回退 000300)
  3. `shutil.copytree(pm_path, models/saved/<policy>_<ts>/pretrained_model, dirs_exist_ok=True)`
     (safetensors + config + pre/postprocessor 全量复制)
  4. **追加写** `models/saved/registry.json`: [{policy, name, path, step_s, ts}] (保留历史, 不覆盖)
  5. 气泡提示路径
- 推理服务端 (studio.py InferencePanel 模型行) 加「已保存模型」下拉:
  - `saved_combo` (QComboBox) + 🔄 refresh_btn
  - `_refresh_saved_models()`: 读 registry.json, `reversed(reg)` 新的在前, `addItem(label, path)` (itemData 存 path)
  - `_on_saved_model_selected(idx)`: idx<=0 忽略 (0 是占位提示项) → itemData → `ckpt_edit.setText(path/pretrained_model)`
  - `_saved_registry_path()` = `<repo>/models/saved/registry.json`
- 验证 (真实执行): 有 ACT+SmolVLA 训练产物时 save_trained_model → registry 2 条 + pretrained_model 含 safetensors;
  测试后清理 (shutil.rmtree + 删 registry)。
