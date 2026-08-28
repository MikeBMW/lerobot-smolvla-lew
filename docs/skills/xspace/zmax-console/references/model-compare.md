# ⚔️ ACT vs SmolVLA 模型对比 — 完整设计与实现 (2026-08-04, commit 5f8ce102)

> ⚠️ **2026-08-05 已废弃**: 「⚔️ ACT vs SmolVLA 对比」双模型模板已被删除 (commit dacf60b9, 老倪: "对比和三模型对比是不是重复了?") — 双模型是三模型「🔬 三模型对比」(18节点22连线) 的真子集, 单入口铁律合并。本文档保留作历史设计参考 (模块划分思路 / SmolVLA 评估坑仍有效); 当前实现见 SKILL.md「🔬 三模型对比」章节 + `references/three-model-compare-v2.md`。SmolVLA 评估关键坑 (reset 队列/图像布局/权重下载) 在下方仍然适用。

老倪需求原话: "simulink功能, 将 对比 按钮的功能, 改造成, 对比 act 和 smolvla模型, 数据集统一用 metaworld数据集, 你来决定模块的划分, 同等结构的模块要复用, 要让用户清晰的感知到, 哪个模块服用了, 你决定增加适当的scope, 图形或图表来体现两个模型的区别。可以是模型训练速度, 精确度, 鲁棒性等, 你是专业的AI模型设计师, 你来设计这个对比的模型。点击 对比 按钮后, 可以直接打开 act和 smolvla的模型对比, 点击运行即可看到结果对比"

## 模块划分 (模型设计师口径)

13 节点 = ♻共用 3 + ACT 分支 6 + SmolVLA 分支 4, 15 连线。

| 索引 | 节点 | 类型 | 分支 | 说明 |
|---|---|---|---|---|
| 0 | 📦 metaworld 数据 | hardware | ♻共用 | source=metaworld, active:True, shared:True, frames 696 4D/4D |
| 1 | 🖼 视觉主干 ResNet18 | model | ACT | ACT.backbone |
| 2 | 🧬 VAE 编码器 CVAE | model | ACT | ACT.vae_encoder |
| 3 | 🔤 Transformer Encoder | model | ACT | ACT.encoder |
| 4 | 🔡 Transformer Decoder | model | ACT | ACT.decoder |
| 5 | 🎯 Action Head 4D | model | ♻共用 | 两模型输出层同为 Linear→action_dim |
| 6 | ⏳ Temporal Ensemble | condition | ACT | ACTTemporalEnsembler (仅 ACT) |
| 7 | 🚀 ACT 训练 | system | ACT | params.policy="act" |
| 8 | 🧠 SmolVLM2-500M | model | SmolVLA | freeze:True |
| 9 | 🌀 DiT-B 动作解码 | model | SmolVLA | hidden 256, timesteps 2 |
| 10 | 🌐 LeWorldModel | model | SmolVLA | world_model_le |
| 11 | 🚀 SmolVLA 训练 | system | SmolVLA | params.policy="smolvla_lew" |
| 12 | 📊 对比评估 Scope | system | ♻共用 | 双击 → 自动评估 + 图表 |

连线: ACT 路 (0,1)(0,2)(1,3)(2,3)(3,4)(4,5)(5,6)(6,7) · SmolVLA 路 (0,8)(8,9)(9,10)(10,5)(5,11) · 评估 (7,12)(11,12)。

**复用依据 (官方代码)**: `ACT.action_head = nn.Linear(config.dim_model, action_feature.shape[0])`; SmolVLA ActionEncoder 输出层同为 Linear→action_dim。同构 → 画布只画一次, 双路连线都过它。

## 复用可视化 (shared 标记)

- 节点 params["shared"]=True → SimNodeItem.paint: `pen = QPen(QColor("#a371f7"), 2.8)` (放在 isSelected 分支之后、hl 分支附近) + st_icon = "♻" (放在 is_active_src "▶" 分支之后)。
- desc 里写 "♻ 两模型共用: ..." 让用户在 tooltip/参数框也能看到。

## 代码改动清单

1. **simulink_module.py**:
   - REFERENCE_APPS 追加 "⚔️ ACT vs SmolVLA 对比" 模板 (13节点15连线, 上面表格)。
   - LIBRARY ACT 分类追加 template 条目 {"name": "⚔️ ACT vs SmolVLA 对比", "template": 同名} → 一键加载。
   - SimNodeItem.paint: shared 紫框 + ♻ 徽章。
   - btn_compare 改 "⚔️ 对比" (#a371f7) → open_compare()。
   - open_compare(): 有节点先 _qmsg_yes 确认清空 → load_reference_app_by_name → 日志 4 行 (模块划分/复用/操作路径/对比维度)。
   - on_train 加 policy="act" 参数: 配置模板按 policy 选, ts_dir 前缀 act_/smolvla_, 训练完 `_parse_step_s(out_lines)` (tqdm "12.68step/s" / "it/s" 正则, 取平均) + 曲线落盘 `reports/train_curve_<policy>.json` {policy,name,ts,curve,step_s,ckpt}。
   - `_parse_step_s(lines)` @staticmethod: `re.compile(r"([\d.]+)\s*(?:step/s|it/s)")` 平均。
   - NODE_RUN_ACTIONS: ("对比评估", "on_compare_scope") 插到 ("Scope", ...) 之前 (顺序遍历, 长关键字优先)。
   - on_compare_scope(): 校验 reports/train_curve_act.json + train_curve_smolvla_lew.json 都存在 (缺则 _qmsg_info 提示先▶运行) → _start_worker 跑 compare_models.py --frames 120, stage="compare"。
   - `_start_worker._done` 加 `if stage == "compare" and ok:` → 延迟 import ModelCompareDialog → exec_ (queued 信号主线程, 安全)。_cicd_state 对未知 stage 键 dict 直接赋值不崩 (只影响 _cicd_panel._refresh 若开着)。
2. **node_logic.py** node_train: 可修改区加 `policy = p.get("policy", "act")`, return 传给 module.on_train(policy=policy)。节点 params 是 ctx["params"], 模板节点已带 policy。
3. **tools/compare_models.py** (新): 读 train_curve_*.json 的 ckpt 字段 → glob `outputs/train/<dir>/checkpoints/*/pretrained_model` 按 mtime 取最新 → 加载 ACTPolicy/SmolVLALewPolicy → 统一 metaworld_act train.npz 抽样 120 帧 → 每帧构造 batch 预测 → 指标: action_mse/mse_std/success_rate(阈值0.05)/latency_ms/robustness_std (同一状态重复推理 n_repeat=5 次的 action std 均值) → 输出 reports/model_compare_<ts>.json。
4. **simulink_scope.py**:
   - COLORS 加 "act": #58a6ff, "smolvla": #d29922。
   - BarCompareWidget: 横向条形, 每指标两模型, lower_better 判胜出标绿 "✓ ACT/SmolVLA", 图例底部。
   - ModelCompareDialog: 头部 note (数据集/帧数/时间) + ScopeWidget 双 loss 折线 + BarCompareWidget 5 指标 + QTextEdit 对比表 + 💾导出PNG (reports/compare_scope_<ts>.png, 深色 QMessageBox 提示, 不用 QFileDialog)。

## SmolVLA 评估关键坑 (实测)

1. **select_action 有状态队列**: `_queues = {ACTION: deque}` — 首次调用 predict_action_chunk 生成 7 步全进队列, 之后 popleft。评估循环**每帧前必须 `policy.reset()`**, 否则:
   - 帧间动作重复 (队列消费), MSE 失真;
   - 鲁棒性重复推理全部取队列同一值 → std=0 假象。
   - ACT 的 select_action 无队列 (直接 predict), 不需要 reset。
2. **图像 batch 布局不同**: SmolVLA `_prepare_model_inputs` 里 `t.permute(0, 3, 1, 2)` → batch 是 **NHWC** (B,H,W,C) 或 (B,T,H,W,C), 0-255 或 0-1 均可 (max<=1 自动 *255); ACT 是 NCHW 0-1 (act_compare.py 既有模式)。评估脚本 is_act 分支分开构造。
3. **batch state**: SmolVLA state 支持 (B,D) 或 (B,T,D) (ndim>2 取 [-1], ndim==2 unsqueeze(1)); task 缺失时兜底指令 "push red block to target"。
4. **transformers 依赖**: `lerobot[smolvla_lew]` extras, 缺则 `ImportError: 'transformers' is required but not installed`。装法: `export TMPDIR=/home/xspace/pip-tmp && .venv/bin/python -m pip install -i https://mirrors.aliyun.com/pypi/simple/ "lerobot[smolvla_lew]"` (装完 transformers 5.5.4)。
5. **模型权重**: SmolVLM2-500M-Video-Instruct 首次训练/评估从 HF 下载 (~1GB+, 38 文件)。**⚠️ 2026-08-05 实测: `HF_ENDPOINT=https://hf-mirror.com` 对该模型没用 — hf-mirror 无此仓库, 直接 308 重定向回 huggingface.co, transformers 下载失败 (OSError: couldn't connect to hf-mirror to load files)**。正确做法: 训练前先 `huggingface_hub.snapshot_download("HuggingFaceTB/SmolVLM2-500M-Video-Instruct")` 直连 HF 下到 ~/.cache/huggingface (后台跑, ~1GB 几分钟; HF 直连 curl 200 可达), 之后训练/评估走缓存无需网络。**训练命令本身也别设 HF_ENDPOINT** (设了反而让缓存检查去请求 hf-mirror)。

## 用户操作路径 (设计目标)

1. 点「⚔️ 对比」→ 画布自动铺开 13 节点 (3 个紫色♻)。
2. 点「▶ 运行」→ 依次真实训练 ACT + SmolVLA (各 300 步, 日志显示 step/s)。
3. 双击「📊 对比评估 Scope」→ 自动跑统一评估 (~1-4min) → 完成自动弹图表:
   - 双 loss 折线 (训练速度/收敛);
   - 五指标条形图 (训练速度 step/s · 动作 MSE · 成功率 · 鲁棒性 std · 推理延迟, 胜出标绿);
   - 对比表。
4. 💾 导出 PNG → reports/compare_scope_<ts>.png。

## 验证 (offscreen 10/10)

模板 13/15 · shared==3 (metaworld/ActionHead/Scope) · ActionHead 双路连线 · load_reference_app_by_name 加载 + 摆放 x=120+5*260 · 两训练节点 params.policy 断言 · NODE_RUN_ACTIONS 索引对比评估<Scope · _canvas_stage_nodes==2 训练 (Scope 排除) · node_logic 透传 ['act','smolvla_lew'] (FakeMod.on_train 捕获) · paint 渲染不崩 (QPixmap+QPainter) · ModelCompareDialog 无数据提示 + demo JSON 渲染。

测试注意:
- `_canvas_stage_nodes()` 返回 (node, meth, kw) 元组 → `[n['name'] for n,_,_ in stages]`。
- ModelCompareDialog 无数据断言要放 demo 文件写入之前 (残留 demo 会让断言失败)。
- scene.render 只能传 QPainter (`render(self, painter, ...)`), 传 QWidget 报 TypeError。
