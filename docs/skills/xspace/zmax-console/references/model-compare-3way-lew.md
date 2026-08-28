# 三模型对比 / LEW 拓扑 / 连线标签 / 性能扩展 (2026-08-05 会话全记录)

## 1. LEW 拓扑两次修正 (老倪连续质疑, commit dfe153e0)

### ① LeWorldModel 是旁路, 不是串行在 DiT-B 之后
官方 world_model_le.py `LeWorldModel.forward(videos, actions)`:
```python
frame_emb = SigLIP(videos)          # 视频帧 → CLS embedding (用 SmolVLM 的视觉编码器)
act_emb = self.action_encoder(actions)  # 动作序列 → embedding
pred_emb = self.predictor(input_emb, input_act)  # ARPredictor(x=帧嵌入, c=动作嵌入)
lew_loss = F.l1_loss(pred_emb, target_emb)       # 预测下一帧 vs 真值下一帧
```
- **LEW 的两个输入 = 视频帧 + 动作序列**（训练时 = 数据集真值动作），**与 DiT-B 输出无关**。
- 正确画布连线（三模型模板）:
  - 主链: 数据→SmolVLM2·LEW→DiT-B·LEW→ActionHead·LEW→训练
  - LEW 旁路: 数据→LEW（标签"视频+动作"）→ActionHead·LEW（标签"世界预测"）
- ❌ 错误画法: DiT-B→LEW→ActionHead 串行（LEW 不收 DiT 输出）。
- 连线总数: ACT 9 + SmolVLA纯 4 + LEW主链 4 + LEW旁路 2 + 评估 3 = **22条**。

### ② action 确实输入了 LEW 潜在空间 — 机制是 AdaLN-zero 调制
ConditionalBlock (world_model_le.py:87-110):
```python
def forward(self, x, c):  # x=帧嵌入, c=动作嵌入
    shift_msa, scale_msa, gate_msa, shift_mlp, scale_mlp, gate_mlp = self.adaLN_modulation(c).chunk(6)
    x = x + gate_msa * self.attn(modulate(self.norm1(x), shift_msa, scale_msa))
    x = x + gate_mlp * self.mlp(modulate(self.norm2(x), shift_mlp, scale_mlp))
```
- action 经 action_encoder → 作为条件 c → **贯穿全部 lew_num_layers=6 层**（DiT 同款条件注入）。
- **不是 cross-attention**（action 不做 K/V，只生成 shift/scale/gate 调制参数）。

### ③ z1/z2/z3 命名在代码/文档里不存在
全仓库 grep 无 z1/z2/z3。近似物:
- zmax_sys12 `latent_vae`（latent_num_layers=3 层编码, **不收 action**）
- zmax_sys11 Z潜空间（vae_encoder 编码 features, `z = mu + σ·ε`, **不收 action**）
- LeWorldModel ARPredictor（6 层, 全层收 action 调制）

若用户坚持"action 做 K/V 交叉注意"或"latent_vae 每层收 action" = 架构改动需重训，先确认再动。

## 2. freeze_smolvlm 与 LEW 互斥 (configuration_smolvla_lew.py __post_init__)
```python
if self.freeze_smolvlm and self.enable_lew_world_model:
    self.enable_lew_world_model = False   # 强制关!
```
- config_smolvla_metaworld.yaml (freeze=true) = 实际训练**纯动作版**（无 LEW）。
- LEW 版必须 `freeze_smolvlm:false + enable_lew_world_model:true`（config_smolvla_lew_metaworld.yaml）。
- 三模型模板 SmolVLM2·LEW 节点 params.freeze:False 标注。

## 3. 连线数据流标签 (commit f8334840)
- `add_link(src_item, dst_item, label=None)` → link dict 加 `"label"` 键。
- SimLinkItem.paint: `lbl = self.link.get("label","")` → 贝塞尔 `path.pointAtPercent(0.5)` 中点画半透明黑底 (QColor(0,0,0,160)) + 白字 (Consolas 7pt)。
- 模板 link_specs 支持 3 元组 `(fi, ti, "标签")`, load_reference_app 用 `for fi, ti, *label in link_specs` 解包。
- metaworld 数据节点三路输出（官方 modeling_act.py forward）:
  - (0,1) 图像 → ResNet18
  - (0,2) 动作 → CVAE（**VAE 编码器输入是 action+state，不是图像**! action_embed = vae_encoder_action_input_proj(batch[ACTION])）
  - (0,3) 状态 → Transformer Encoder（encoder_in_tokens 拼接 latent + state + 图像特征, encoder_robot_state_input_proj(batch[OBS_STATE])）
  - (2,3) 潜变量 → Encoder; (1,3) 图像特征 → Encoder
- SmolVLA 分支: 数据→SmolVLM2 标签"图像+状态", SmolVLM2→DiT-B 标签"多模态embeds"。

## 4. 性能对比扩展 — 除 loss 曲线外的 6 维度 (commit dfe153e0, 老倪: "除了loss曲线, 还有什么能对比模型的性能")
compare_models.py eval_policy 新增收集:
- `traj_pred/traj_gt` 逐帧动作轨迹 (限120帧, 归一化空间)
- `frame_err` 逐帧 MSE 曲线
- `mse_p50/mse_p90` 误差分布中位/长尾 (`np.percentile`)
- `smoothness` 动作平滑度 = `np.mean(np.std(np.diff(traj_pred, axis=0)))`（相邻预测差分 std, 小=真机抖动小）
对话框 ModelCompareDialog:
- 新增 `err_scope` (ScopeWidget) 画逐帧误差曲线（每模型一条）
- bars 5→8 指标: 速度/MSE/成功率/鲁棒性/延迟/P50/P90/平滑度
- 表格加 误差P50/误差P90(长尾)/动作平滑度 3 行
- 旧数据文件缺新字段 → 显示 "-" 不崩（.get(key, nan) + `v == v` 判 nan）
- 实测 (4060, 60帧): ACT MSE 1.40 P90 2.63 平滑度 0.036 | SmolVLA+LEW MSE 1.07 P90 2.31 平滑度 0.204
- **⚠️ 对话框读 reports/ 最新 model_compare_*.json — 旧脚本生成的报告没有新字段, 必须重跑 compare_models.py 才会出新指标**。用户反馈"还是只有loss"时先查报告文件时间戳/字段。

## 5. 功能重复必须合并 (老倪: "对比和三模型对比是不是重复了" → 删双模型)
- 双模型「⚔️ ACT vs SmolVLA 对比」(14节点) 是三模型「🔬 三模型对比」(18节点) 的**真子集**（三模型含 ACT + SmolVLA纯 + SmolVLA+LEW）。
- 删除: REFERENCE_APPS 模板条目 + LIBRARY 模块库条目 + btn_compare 按钮 + open_compare 方法。
- **验证删除干净**: grep 用词边界 `open_compare\b`/`btn_compare\b`（`open_compare3` 里的子串不算）; 排除注释行 (`startswith("#")`) 后 join 检查 `def open_compare(` / `self.btn_compare = `。
- _compare_load_hint 保留（三模型复用）。

## 6. 布局: 多行展开网格 (老倪: "不要排成一条直线, 要展开; 类似功能如 Action Head 垂直对齐")
- REFERENCE_APPS 模板可选**第4元素 layout** = `[[节点名...]每行]`:
  - 行 = 模型分支 (y = base_y + r*230), 列 = 功能角色 (x = base_x + c*260)
  - 空串 = 占位跳过; **同名节点跨行 → 垂直对齐**（三模型 Action Head 共 x=1420）
  - load_reference_app(layout=): 名字→候选位置列表, used 集合去重（共享节点如 metaworld 只画一次取首个位置）
- ⚠️ REFERENCE_APPS 变 4 元组后, 所有 3 元组解包处必须改 item[0]/item[1]/item[2] 兼容（3处: 参考应用按钮循环 / _act_build_link_existing / _act_build_finish），漏改 → "not enough values to unpack" 崩。
- ⚠️ load_reference_app 批量加载必须禁用 _sync（每次 add_node 会 POST web, 13+节点串行超时卡死）: `old_sync = self._sync; self._sync = lambda: None` try/finally 恢复, 末尾 `self._sync()` 一次。

## 7. 工具栏按钮必须 addWidget (commit 6a3ef710)
- btn_compare3 创建后**漏 addWidget → 按钮对象存在但界面看不到**（用户: "没有三模型对比啊"）。
- 第一行工具栏按钮过多会被 QHBoxLayout 挤压隐藏 → 放第二行。
- 铁律: mk_btn → tl2.addWidget → offscreen 验证 `parent() is not None` + 点击触发。

## 8. 验证脚本坑 (2026-08-05 多次踩)
- **offscreen 下 QMessageBox.exec_() 模态阻塞 → 脚本卡死超时**: 必须 monkeypatch `SimulinkModule._qmsg = lambda *a,**k: None` + `_qmsg_yes = lambda *a,**k: True` 再实例化/加载模板。
- **execute_code 的 sys.executable 是 Hermes venv python（无 PyQt5）**: subprocess 跑 GUI 验证必须显式 `["python3", path]`，别用 `sys.executable`。
- scene.render 的 target 参数必须是 **QRectF**（QRect 报 `unexpected type 'QRect'`）: `sc.render(p, target=QRectF(pm.rect()), source=r)`。
- BarCompareWidget.paintEvent: `y0 = int(i * row_h)` — PyQt5 drawText/fillRect 严格 int, float 崩。
- 连线 dict 里有 id/f/t/f_port/t_port/label 多个键, 遍历时用 `l["f"]`/`l.get("label","")`, 别 3 元组解包。
- link_specs 是 `(fi, ti, *label)` 变长, 模板连线写 `(0, 1, "图像")` 与 `(3, 4)` 混用都合法。
