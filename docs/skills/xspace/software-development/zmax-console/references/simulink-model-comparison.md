# Simulink 模型对比管道 & 模型节点开发 (2026-08 五模型对比)

## 新模型/新节点接入清单 (漏一个就出 bug)
1. `NODE_TYPES` (cn/color) — 缺了 add_node 直接 KeyError
2. `add_node` 内联 icon 字典 (`"train_gate": "☑"` 那种) — 缺了 KeyError
3. `node_logic.py`: `_reg()` 匹配键 + `node_<name>` 函数 — **用户明确抱怨过"很多节点右键没有源代码"**, 所有模型节点必须注册
4. `REFERENCE_APPS` 模板 + 多行 layout (网格: 行=模型分支, 列=功能角色; 同名节点跨行出现→垂直对齐; 空串=占位跳过)
5. `LIBRARY` 完整模型条目 (`"template": "🔬 五模型对比"`)
6. `NODE_RUN_ACTIONS` (若为可执行环节)
7. `_start_canvas_flow` 的 `_speed` 字典 (训练节点必加, 否则 key=9 排最后)
8. `compare_models.py` load/eval (若 Scope 对比要支持)
9. `open_compare5` 里 `_draw_model_rows` 背景行

## ▶运行队列关键字误匹配 (五模型对比卡在 VLA-Touch 根因)
`_canvas_stage_nodes` 用 NODE_RUN_ACTIONS 关键字 in 节点名匹配:
- "🎥 推理效果对比" 含 "推理" → 误匹配 on_infer → 混进队列排最后 → 阻塞后续训练 (用户看到"训练到第3个就停了")
- "☑ 训练开关" 含 "训练" → 误匹配 on_train → 成了 CICD 主控台第一个环节
修复: 匹配前先排除 `params.video` 节点和 `type=="train_gate"` 节点。
排查线索: 队列卡住时先打印 `_canvas_stage_nodes()` 输出看有没有"杂鱼"。

## row_bg 背景行节点 (五模型对比 5 行彩色背景)
- 真节点类型 (可编辑: name + params.bg; BlockParamsDialog 里 bg/bg_color/color 参数渲染成 QComboBox 预设色)
- z=1 (低于节点 z=10) → 点击空白命中背景, 点节点命中节点
- **坑1 (黑色块)**: add_node 后 node 字典的 w/h ≠ SimNodeItem.w/h — boundingRect 用 item.w/h, 不同步 → 只渲染 150×50 深色小块。必须 `it.w = n["w"]; it.h = n["h"]`
- **坑2 (≈黑)**: 单层 alpha=40 填充在 #0a0a0f 画布上≈黑; 用深色底 (13,17,23,alpha120) + 色相薄层 (alpha90) 叠加
- **坑3 (叠字)**: 大字区与第一列节点 (x≥120) 重叠 → 视觉"重复/叠字"。row_bg x0 = base_x-140, 大字去 "🎨 " 前缀, 名字含 "+" 拆两行, 绘制区 ≤126px

## 真交叉注意力 (用户当场抓假实现)
假: 三层 z 拼接 → 单 token K/V + gates.sum() 标量乘整个输出 → 1×1 attention = 恒等, 非真注意力
真: `nn.ModuleList` 每层独立 K/V 投影 + 逐层 MultiheadAttention + 每层独立门控参数
验证 (写进测试): 门控全 0 → 输出 == dec (纯残差); 开 z₁ 门控 → z₁ 变化影响输出; z₂ 变化不影响 (隔离)。
用户铁律: "机制要真 cross-attention (每层独立 K/V + 独立门控), 假实现当场被抓"

## 术语口径 (用户概念拷问)
- **世界模型** = 能预测"世界接下来会怎样"的环境动态模型 (当前状态+动作 → 未来状态), 不是字面"世界的模型"
- 五模型对比的世界模型列: LeWorldModel(帧级) / Interpolant(动作级) / zFlow(潜状态级) — 都是预测未来, 粒度不同
- **交叉注意力** = Q 来自解码隐层, K/V 来自未来潜状态 → "用未来预测做决策"; 节点名已改为「🔀 未来决策交叉注意力」

## PDF 技术选型报告 (tools/generate_report.py)
- 栈: reportlab (PDF) + matplotlib (曲线/评分图) + PIL (视频帧拼图)
- **CJK 字体 (中文方块修复)**: matplotlib 需 `font_manager.addfont(Noto CJK .ttc)` + rcParams font.sans-serif; reportlab 需 `TTFont(name, path, subfontIndex=0)` 注册 .ttc, 且所有 ParagraphStyle/Table 的 FONT 用注册字体名 — 默认 Helvetica 中文全方块
- 数据底座: MODELS 注册表 (arch/params_m/train_cost/gpu_mem/strengths/weaknesses) + `train_curve_*.json` ({policy,name,ts,curve:[[step,loss]],step_s,ckpt}) + `reports/rollout_<policy>/frame_*.png`
- 科学选型: Scope 归一化 (前3点均值=1) 看下降斜率 (ACT MSE 与扩散噪声 MSE 绝对值不可比); 加权矩阵: 收敛20% 世界模型15% 触觉20% 部署15% 吞吐10% 显存10% 数据5% 视频5%; 性价比 = 分/(1+调参难度惩罚)
- 缺数据容错: curve=None → 标"无曲线数据"不崩 (VLA-Touch/AWE 常无曲线)

## 视频对比节点
- 推理效果对比 (video=all) 之后接 5 个「🎥 视频对比 · <模型>」(params.video_policy=act/...), 双击只放该模型
- `InferenceVideoDialog`: POLICIES 参数化, POLICIES_5 五模型版; on_infer_video 自动探测画布有无 VLA-Touch/AWE 训练节点决定 3/5 模型
- 训练→视频 连线 + 推理对比→5视频 连线 + Scope/推理/5视频→PDF 连线 (数据支撑链)

## 工具栏显眼按钮 (用户 ×2 次找不到)
参考应用条 12 模板横向滚动, 新模板排末尾不可见 ("没有 VLA-Touch管道啊") → 新模板必须同步加第二行工具栏按钮 (mk_btn 模式, 同 ACT-Meta/总系统处理)
