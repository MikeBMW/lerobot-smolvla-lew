# ⚔️ ACT vs SmolVLA 对比 + MDI 子窗口 + 浮动画布 + 独立流程窗口 (2026-08-04/05)

> ⚠️ **DEPRECATED 部分内容 (2026-08-05 修订)**: 「⚔️ ACT vs SmolVLA 对比」双模型模板已**删除**
> (commit dacf60b9, 老倪确认双模型是三模型真子集, 单入口铁律), 对比模板终态 = 「🔬 三模型对比」
> **18节点22连线** (ACT 8 + SmolVLA纯 4 + SmolVLA+LEW 6, LEW 为旁路非串行)。下方 13/14 节点
> 双模型描述、ActionHead 双路复用连线、以及「对比评估在途坑: metaworld 维度不一致 (未修完)」
> 均已被后续修复/取代 — 最新架构演进见 `references/subsystem-crossattn-3model.md` (子系统/CrossAttn/
> 数据流标签/8指标对比/去重)。MDI 子窗口/浮动画布/独立窗口 部分仍有效。

## ⚔️ 对比模板「⚔️ ACT vs SmolVLA 对比」(老倪: "对比按钮改造成对比 act 和 smolvla, 统一 metaworld, 你来定模块划分, 同等结构模块复用, 用户清晰感知复用, 增加 scope 图表体现区别")

### 模块划分 (13 节点 15 连线 = 8+5+2)
- ♻ 共用 3: `📦 metaworld 数据`(hardware, source=metaworld, active:True, shared) / `🎯 Action Head 4D`(model, shared) / `📊 对比评估 Scope`(system, shared)
- ACT 6: 🖼 ResNet18 → 🧬 CVAE → 🔤 Encoder → 🔡 Decoder → [🎯ActionHead] → ⏳ Ensemble
- SmolVLA 4: 🧠 SmolVLM2-500M(冻结) → 🌀 DiT-B → 🌐 LeWorldModel → [🎯ActionHead]
- **复用依据 (官方代码)**: ACT.action_head = nn.Linear(dim_model, action_dim); SmolVLA 输出层同为 Linear→action_dim → 同构, 画布只画一次
- ActionHead(索引5) 双路复用连线: 入 (4,5) ACT路 + (10,5) SmolVLA路; 出 (5,6) + (5,11); 数据源 (0,1)+(0,8); 评估 (7,12)+(11,12)
- 模板链接数: ACT-Meta 9节点9连线 / 对比 13节点15连线 — 断言别手滑

### shared 可视化 (用户"清晰感知哪个模块被复用")
- 节点 params 加 `"shared": True` → SimNodeItem.paint: 紫色 #a371f7 粗框 2.8 + st_icon 徽章 "♻"(优先级在 is_active_src "▶" 之后)
- 两训练节点 params 带 `"policy": "act"/"smolvla_lew"`; node_logic.py node_train 可修改区 `policy = p.get("policy", "act")` → `module.on_train(..., policy=policy)`

### 运行链路
- `btn_compare`("⚔️ 对比", #a371f7) → `open_compare()`: 确认清空 → load_reference_app_by_name("⚔️ ACT vs SmolVLA 对比") → 日志讲解模块划分/复用/操作
- ▶ 运行 → `_canvas_stage_nodes()` 拓扑序 = 仅 2 个训练节点(「📊 对比评估 Scope」含 "Scope" 被排除, 观察节点手动双击)
- 双击「📊 对比评估 Scope」→ NODE_RUN_ACTIONS 匹配: **("对比评估", "on_compare_scope") 必须排在 ("Scope","on_scope") 之前**(顺序遍历第一个命中, 节点名含两关键字)
- `on_compare_scope`: 检查 reports/train_curve_{act,smolvla_lew}.json 都存在 → 后台跑 compare_models.py → `_start_worker(..., stage="compare")` → `_done` 里 `if stage=="compare" and ok:` 弹 ModelCompareDialog(自动弹图表 = 用户"点击运行即可看到结果对比")

### on_train 双策略扩展
- 签名加 `policy="act"`; smolvla_lew → config_smolvla_metaworld.yaml / ts_dir=smolvla_<ts>; act → config_act_metaworld.yaml / act_<ts>; tmp_cfg = f"config_{policy}_runtime.yaml"; 日志 pname=ACT/SmolVLA
- 训练完: `_parse_loss_curve` + `_parse_step_s`(正则 `([\d.]+)\s*(?:step/s|it/s)` 平均) → 落盘 `reports/train_curve_<policy>.json` {policy,name,ts,curve,step_s,ckpt:"outputs/train/<ts_dir>/checkpoints"}

### tools/compare_models.py (统一 metaworld 评估)
- find_ckpt(policy): 读 train_curve_<policy>.json 的 ckpt → glob `ckpt/*/pretrained_model` 按 mtime 取最新
- 加载: ACT → ACTPolicy.from_pretrained + make_pre_post_processors; SmolVLA → SmolVLALewPolicy.from_pretrained + `postprocessor = getattr(policy, "postprocessor", None)`(可能无, None 跳过反归一化)
- 数据: data/metaworld_act/train.npz 均匀抽 120 帧 (observations 3×128×128 / states 4D / actions 4D — **以 npz 为准, info.json 是旧 pusht 模板残留 2D 别信**)
- ⚠️ **两模型 batch 格式不同**: ACT NCHW `(1,3,128,128)` /255; SmolVLA **NHWC** `(1,128,128,3)` 0-255 — modeling_smolvla_lew._prepare_model_inputs: `t.permute(0,3,1,2)` 期望 NHWC, `if t_np.max() <= 1.0: *255`
- ⚠️ **SmolVLA select_action 有状态动作队列** (_queues, populate_queues + popleft): 每帧评估前必须 `policy.reset()`(SmolVLALewPolicy.reset 清队列), 否则后续调用直接从队列取不重新预测 → 延迟/动作全失真; ACT 无队列不需要
- 指标: 动作MSE / 成功率(MSE<0.05) / 延迟ms / **鲁棒性 = 同状态重复推理 5 次 action std 均值(小=稳定)** / 训练速度 step_s(来自曲线文件)
- 输出 reports/model_compare_<ts>.json {ts, dataset:"metaworld_act", frames, models:{act:{...}, smolvla_lew:{...}}}
- 耗时: 120帧×(1+5)次推理 × 500M VLM(冻结)forward ≈ 分钟级 → GUI 后台 CICDWorker 跑

### ModelCompareDialog (simulink_scope.py 末尾追加)
- ScopeWidget 双 loss 折线: series {"ACT loss": (ys,"act",False), "SmolVLA loss": (ys,"smolvla",False)} — **COLORS dict 必须加 "act":#58a6ff / "smolvla":#d29922**(ScopeWidget.set_series 用 COLORS.get(cname, base) 缺键落红色)
- BarCompareWidget 自绘五指标条形图(每指标两模型横条 + ✓胜出方标绿): 训练速度(高好)/MSE(低好)/成功率(高好)/鲁棒性std(低好)/延迟(低好)
- 表格 QTextEdit 维度对比表 + 💾导出 PNG(grab().save 到 reports/, 深色 QMessageBox, 不用 QFileDialog)
- 无数据 → "⚠️ 无对比结果 — 点「▶ 运行」依次训练两模型"

## ⚠️ 性能坑: 批量加载模板卡顿 (老倪反馈 "点对比按钮好长时间才打开")
- **根因**: load_reference_app 循环 add_node, 每个 add_node 调 `_sync()` → POST datadrive.world/api/comfy/task (web comfy mock 常挂 → 每次超时 8s); 13 节点 = 13 次串行网络 = 100s+
- **修**: load_reference_app 加载期间 `old_sync = self._sync; self._sync = lambda: None`(try/finally 恢复), 末尾 `self._sync()` 一次; 配套 studio.py on_flow_sync 改 `threading.Thread(target=_post, daemon=True).start()` 后台 POST
- 验证: monkeypatch _sync 计数 == 1; 13 节点加载 1ms; 语义验证(等价实现 + mock 挂 6s, 主线程返回 <100ms)
- 通用教训: **任何"循环内触发网络/重活"的代码都要批量收集+末尾一次提交, 或后台线程**

## 🖥 MDI 子窗口 (2026-08-05 老倪: "主要操作窗口首次打开嵌在主窗口里, 参考 Vector CANoe / MATLAB Simulink UI, 有缩小/最大化/关闭常规功能")
- 主体布局: QSplitter(库面板 | QMdiArea); canvas = QMdiSubWindow.setWidget(SimCanvas) → mdi.addSubWindow → show
- 子窗口默认带 最小化/最大化/关闭 按钮(标题栏 Qt 自绘); 关闭 = 隐藏(WA_DeleteOnClose False) 内容不丢
- 深色 QSS: QMdiArea{background:#0a0e14} / QMdiSubWindow::title{background:#161b22;color:#e6edf3} / ::close-button:hover{#f85149} / ::minimize-button:hover{:#1f6feb}
- 「🪟 画布窗口」恢复按钮: `if win.isMinimized(): win.showNormal() elif win.isHidden(): win.show()` + `mdi.setActiveSubWindow(win)`
- **⚠️ 嵌窗露白 (2026-08-05 老倪: "中间的嵌入窗口也得是暗色调, 你现在是白色, 不协调", commit 60ec47c9)**: MDI QSS 深色 ≠ 全深色 — **canvas viewport / QMdiArea viewport 的 palette Base 默认白色**, 缩放/滚动条/边缘间隙露白。修 (switch_theme 里统一): `pal.setColor(pal.Window/Base, 主题色); viewport.setPalette(pal); viewport.setAutoFillBackground(True)` — canvas viewport 用 canvas 色, mdi viewport 用 bg2 色。验证断言: `cv.palette().color(cv.palette().Base).name() == "#0a0a0f"`。**任何 QAbstractScrollArea 容器深色化都要连 viewport palette 一起设**。

## ⛶ 浮动画布 (MDI 适配)
- 浮动: `mdi.removeSubWindow(win); win.hide()` → FloatingCanvasDialog(self, canvas)(lay.addWidget(canvas) 自动 reparent 从 subwin 移除)
- 还原(dialog closeEvent → _restore_canvas): 旧 subwin deleteLater → 新建 QMdiSubWindow + setWidget(canvas)(reparent 回) + addSubWindow + show + setActiveSubWindow
- 验证 6/6: 子窗口在 MDI / close→isHidden / show_canvas_win 找回 / showMaximized+showMinimized 往返 / 浮动→还原 parent 链正确 / 渲染不崩

## 🧠 ACT-Meta 引导 → 独立浮动窗口 (老倪: "点击后主屏幕没切换, 应该再打开一个独立窗口直接打开新流程, 用户自主决定是否关掉")
- ⚠️ **2026-08-05 当日即被老倪回滚 (commit 2884f047: "取消打开独立窗口功能,不对…还是在原来的嵌入式窗口里显示")** — btn_actmeta 已改回 `self.open_act_meta`(嵌入式主画布引导, 清空主画布走搭建)。**最终铁律: 引导/新流程默认跑在嵌入式主画布 (MDI 子窗口内); 用户说"独立窗口"要先确认是 MDI 子窗口还是真独立 QDialog, 优先嵌入式/MDI, 别擅自翻盘交互模式**。以下实现保留供复用 (若用户再次明确要独立窗口):
- 通用方法 `_open_float_workflow(title, setup_fn)`: `new_w = self.__class__()`(独立实例自带库+画布+日志) → `new_w._acq_timer.stop()`(浮动实例不轮询采集) → QDialog(可最大化, 深色) 1280×840 → lay.addWidget(new_w) → `dlg.finished.connect(_on_close)`(停 timer + deleteLater) → setup_fn(new_w) → show
- `open_act_meta_float` = _open_float_workflow("🧠 ACT-Meta 引导 · 新流程窗口", lambda w: w.open_act_meta()) — 新实例画布空, open_act_meta 直接开始无确认
- 主画布完全不动(offscreen 断言主画布节点数不变)

## SmolVLA-LEW 训练 (metaworld)
- ⚠️ 缺依赖: `ImportError: 'transformers' is required` → `.venv/bin/python -m pip install -i https://mirrors.aliyun.com/pypi/simple/ "lerobot[smolvla_lew]"`(装 transformers 5.x; .venv 无 pip 可执行文件, 必须 `python -m pip`)
- ⚠️ 权重下载: hf-mirror.com **没有** HuggingFaceTB/SmolVLM2-500M-Video-Instruct(308 转直连 huggingface.co)→ 用 `huggingface_hub.snapshot_download` 直连(可后台跑); transformers 的 HF_ENDPOINT=hf-mirror.com 会失败
- config_smolvla_metaworld.yaml 关键字段: policy.type=smolvla_lew / smolvlm_name / freeze_smolvlm:true / action_model_type:DiT-B / action_hidden_size:256 / action_num_layers:1 / num_inference_timesteps:2 / chunk_size:7 / n_action_steps:7 / n_obs_steps:1 / siglip_image_size:64 / num_vision_tokens:64; batch_size:1(显存)
- 结构: SmolVLALewPolicy(smolvla_lew/) = SmolVLALewModel(SmolVLM2-500M 冻结 + action_head.py DiT + world_model_le.py LeWorldModel)

## ⚠️ 对比评估在途坑: metaworld 数据维度不一致 (2026-08-05 实测, 未修完)
- **现象**: 两模型都训完 (ACT 300步 13step/s · SmolVLA 300步 2:29 2.0step/s, checkpoint 000150/000300 齐全), 但 compare_models.py 评估报 `RuntimeError: mat1 and mat2 shapes cannot be multiplied (1x4 and 2x256)`(SmolVLA ActionEncoder.layer1 = Linear(action_dim, hidden) 期望 2D 输入, 评估给 4D)。
- **根因链**: `data/metaworld_act/meta/info.json` 是旧 pusht 模板残留 — observation.state [2] / action [2] / image 96×96; 但 `train.npz` 实际是 states/actions 4D + image 3×128×128。**LeRobotDataset(root=data/metaworld_act) 的特征定义来自 info.json → 训练时两模型 output_features.action.shape 都写成 [2]** (train_config.json 可查), 评估脚本直接读 npz 4D → 维度冲突。
- **排查定位**: `python3 -c "import json; d=json.load(open('<ckpt>/config.json')); print(d['output_features']['action']['shape'])"` — 是 [2] 就中了此坑。
- **修复方向 (下次接续)**: ① 评估输入对齐训练特征 (按 checkpoint config 的 input_features 构造 2D batch, 而非 npz 4D) — 两模型同口径对比仍成立; ② 或重生成 metaworld_act 的 info.json (features 改 4D/128×128) 再重训 — 数据侧治本, 但 300 步 ×2 重训成本 ~3min 可接受。**别让评估脚本与训练走不同数据口径**。
- 训练速度对比 (可先用于口头汇报): ACT ~13 step/s vs SmolVLA ~2 step/s (同机 4060, 差 ~6.5x — SmolVLM2-500M 冻结前向是瓶颈)。

## PyQt5 API 坑 (本会话实测)
- **QSplitter 没有 removeWidget / takeAt**(AttributeError) — 移除 splitter 里的 widget 靠 reparent: `new_parent_layout.addWidget(w)` 时 QWidget setParent 自动从旧 QSplitter 布局移除
- **QMdiArea 没有 indexOf** — 判断子窗口归属用 `win in mdi.subWindowList()`
- **QMdiSubWindow 没有 isClosable/isMinimizable/isMaximizable** (PyQt5) — 按钮能力用行为验证(close→isHidden / showMaximized→isMaximized)
- patch 工具写多行 Python 字符串时 new_string 里 `\n` 会落盘成字面 `\\n` → SyntaxError; 写完必须 read_file 确认(老坑复现)
