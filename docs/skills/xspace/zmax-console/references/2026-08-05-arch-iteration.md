# 2026-08-05 架构大迭代记录（三模型对比 + 子系统 + CrossAttn + 训练提速）

## 🔬 三模型对比（取代 ⚔️ 双模型，单入口铁律）
- 老倪确认："对比和三模型对比是不是重复了" → 双模型是子集，**删除 ⚔️ 双模型入口**（模板/按钮/open_compare 方法零残留）
- 三模型 = ACT / SmolVLA 纯动作 / SmolVLA+LEW；模板 18节点22连线，3 分支行 + 共用节点（metaworld 数据 ♻ + 评估 Scope ♻）
- 布局规则（老倪硬性要求）：**节点不要排成一条直线，多行展开；同功能节点（Action Head）垂直对齐同一列** —— REFERENCE_APPS 第 4 元素 layout 网格，行=模型分支、列=功能角色、空串占位对齐
- SmolVLA 纯动作 = freeze_smolvlm:true（LEW 强制关）；SmolVLA+LEW = freeze:false + enable_lew:true（**2026-08-05 下午改为两者可共存**，见下）

## 🎛 顶层总系统（Simulink Subsystem 语义）
- 顶层模板 3 节点：数据 → 总系统块（params.subsystem="🔬 三模型对比"）→ 评估 Scope
- 双击子系统节点 → `_open_subsystem`：保存顶层 flow 到 `_subsystem_stack`（栈式可嵌套）→ 加载内部模板
- 工具栏「⬅ 返回总系统」按钮（`back_to_subsystem` 恢复栈顶 flow），`_update_back_btn` 按栈深显隐
- 参考应用条按钮被挤压教训：**9 个模板挤单行 QHBoxLayout，后面的按钮不可见** → 改 QScrollArea 横向滚动（ra_scroll + ra_inner）→ 老倪还是找不到 → **再加显眼工具栏入口 btn_topsys「🎛 总系统」**（open_topsys + _topsys_hint 高亮气泡）
- 教训：功能入口要放工具栏，不能只藏在滚动条/深层；用户反馈"没有XX"时先查按钮是否被布局挤压（对象存在≠可见）

## 🌐 LeWorldModel 真相（老倪连环追问澄清）
- LEW 输入 = **视频帧 + 动作**（world_model_le.py forward(videos, actions)），**不接收 DiT-B 输出**；画布最初连错（串行在 DiT 后）→ 改为旁路（数据→LEW）
- LEW 训练/推理差异：训练时 `lew_loss = le_world_model(videos, actions)` 辅助训练；**推理时 predict_action 只走 action_model（DiT-B），LEW 完全不参与**
- ARPredictor 可拆解：SigLIP帧编码 → ActionEmbedder → 位置编码 → 输入/条件投影 → ConditionalBlock×N → 输出投影（模块库「🌐 LeWorldModel·子模块」6 节点）
- z1/z2/z3 潜在空间 = **zmax_hybrid 的 LeWorldModelGRU**（wm_latent_dims=(256,256,128) + H-JEPA 能量损失），不是 smolvla_lew！zmax_hybrid 用 enable_wm_inference 开关控制推理时世界模型是否参与（自回归）；SmolVLA+LEW 无此开关

## 🆕 CrossAttention K/V 注入（lew_attn_mode="cross"）
- 老倪："action 与潜在空间做真正的 cross-attention（K/V 注入）"（明确否掉 AdaLN 调制）
- world_model_le.py 新增：CrossAttention（Q=帧嵌入 norm_q/to_q，K/V=动作嵌入 norm_kv/to_k/to_v，scaled_dot_product_attention）+ CrossConditionalBlock（自注意 + 交叉注意 + MLP）
- Transformer 加 attn_mode 参数（"adaln"|"cross"），block_cls 按模式选；ARPredictor/LeWorldModel 透传
- 配置：SmolVLALewConfig.lew_attn_mode（默认 "adaln" 兼容旧权重）；modeling_smolvla_lew.py 初始化时 `getattr(config, "lew_attn_mode", "adaln")`

## ⚡ 训练提速（老倪："每次训练不要超过5分钟"）
- steps 300→150（模板 7 处 + config_act_metaworld / config_smolvla_metaworld / config_smolvla_lew_metaworld + node_logic.py p.get("steps", 150)）
- SmolVLM2-500M 每次 subprocess 加载 ~40s 是固定开销（无法省），训练步数减半是主要手段
- **SmolVLM2 冻结**（老倪："SmolVLM2的参数要冻结，不要训练"）：
  - configuration_smolvla_lew.py __post_init__ **移除** freeze+enable_lew 互斥（原 freeze:true 强制关 LEW）
  - 依据：LeWorldModel.encode_frame 用 `with torch.no_grad()`（冻结 SigLIP 提特征），predictor/action_encoder 独立训练
  - config_smolvla_lew_metaworld.yaml: freeze_smolvlm false→true
  - 实测：VLM 0/778 可训练（全冻结）、LEW 89 组 + DiT 52 组可训练、可训练仅 28.2M/634M (4.4%)

## 🐛 共存路径暴露的 2 处属性 bug（freeze+LEW 之前从未执行过这段代码）
- modeling_smolvla_lew.py ~98 行 + world_model_le.py ~364 行：`vision_encoder.config.vision_config.hidden_size` 崩（SmolVLMVisionConfig 无嵌套 vision_config）
- 修复：`getattr(config, "vision_config", None)` → hidden_size，兜底 1152
- 教训：**配置开关从未组合过的代码路径是隐藏 bug 温床**；开新组合先跑单测构建模型

## 🐛 SmolVLA+LEW 训练必失败 — 3 处 bug（freeze+LEW 共存后第一跑，老倪报"SmolVLA+LEW 训练失败"）
- 症状：三模型对比流程中 SmolVLA+LEW 训练失败（曲线 0 点、outputs/train/ 无 smolvla_lew 目录 = 早期就炸）；SmolVLA 纯训练正常（LEW 分支不执行所以没暴露）
- **调试方法（比猜快）**：直接 `nice -n 10 .venv/bin/python -m lerobot.scripts.lerobot_train --config_path config_smolvla_lew_metaworld.yaml 2>&1 | grep -E "Error|RuntimeError|Training:" | tail` 抓真实报错，每次 ~1-2 分钟（模型加载），改一处重跑一次直到 150/150 步跑完
- **Bug 1（布局，错误链第 1 层）**：`modeling_smolvla_lew.py` 358 行 `t_np = t.permute(0, 3, 1, 2)` —— lerobot 图像 tensor 已是 **CHW `[T,C,H,W]`**，permute 打乱成 `[T,W,C,H]` → SigLIP patch_embedding 报 `Given groups=1, weight of size [768,3,16,16], expected input[2,96,96,3] to have 3 channels, but got 96 channels`。修：**不 permute**（`t_np = t.detach().cpu().float().numpy()`）
- **Bug 2（布局，错误链第 2 层）**：207 行 `batch_videos.transpose(0,1,2,5,3,4)` —— videos 构造后已是 `[B,V,T,C,H,W]`，再 transpose 打乱成 `[B,V,T,W,C,H]` → 报错形状变成 `[2,96,3,96]`。修：**删掉整行 transpose**
- **Bug 3（dtype）**：`videos_tensor = torch.from_numpy(...).float()`（float32）但 LEW 内部权重 dtype 混合（vision_encoder bf16 + predictor float32）→ 依次报 `Input type (torch.cuda.FloatTensor) and weight type (CUDABFloat16Type)` → `mat1 and mat2 must have the same dtype, but got BFloat16 and Float`。修：**整个 lew_loss 计算包进 `torch.autocast(device_type=..., dtype=torch.bfloat16)`**（别手动转 dtype，LEW 内部组件 dtype 不统一，autocast 自动处理）
- 修复后实测：150/150 步 1分18秒，loss 0.464→0.357，action_loss 0.256，显存仅 1.8GB（0d30f558）
- 教训：**训练失败"见上方日志" = 看 worker 输出的真实 traceback**；SmolVLA 系图像链路全程 CHW（lerobot 标准），任何 permute/transpose 都要先确认输入已是什么布局——"96 channels"类报错 = C 维位置错（H/W 被当 channel）；**布局类报错先查 permute/transpose/reshape，dtype 类报错用 autocast 包裹而不是手动 cast**

## 💾 保存模型（老倪："训练好的模型保存，下次直接应用"）
- Simulink 工具栏「💾 保存模型」→ save_trained_model()：读 reports/train_curve_<policy>.json 的 ckpt → 复制 last/pretrained_model 到 models/saved/<policy>_<ts>/ → 写 models/saved/registry.json
- 推理服务端「已保存模型」下拉（_refresh_saved_models / _on_saved_model_selected）：读 registry，选中即填 ckpt_edit 指向 .../pretrained_model

## 🛡 QThread 崩溃修复（exit 134 SIGABRT）
- 症状：`QThread: Destroyed while thread is still running` + exit 134
- 根因：closeEvent 只停 _timer/_remote_timer，没停 _acq_timer（5s 采集轮询）且没等 _acq_worker → 退出时 worker 还在跑 → 析构 QThread 崩
- 修复：closeEvent 停 _acq_timer + `_acq_worker.wait(3000)` + 置 None
- 教训：**所有 QTimer/QThread 成员都要在 closeEvent 清理**；CICDWorker 用 finished 信号置 None 只解决引用，不解决析构时序

## 🏷 连线数据流标签
- add_link(label=) + SimLinkItem.paint 贝塞尔中点半透明标签（QRectF + drawText，主题色）
- metaworld 数据节点三路输出标注：图像→ResNet18 / 动作→CVAE / 状态→Encoder（官方 modeling_act.py 证实 CVAE 输入是动作不是图像！encoder 拼接 latent+图像特征+state）
- 模板连线升级为三元组 (fi, ti, label)，load_reference_app 用 `for fi, ti, *label in link_specs` 兼容

## 📊 Scope 训练中实时波形（老倪："训练都开始了，为什么scope没有波形"）
- 根因：曲线原本训练**结束后**才落盘（on_train 在 _run_cmd 返回后 parse）→ 训练中 Scope 无数据
- 修复（三处）：
  1. `_run_cmd` 加 `line_hook(ln)` 参数（每行 stdout 回调，collect 之外）
  2. on_train 训练中：`_line_hook` 解析 loss 行 → 增量更新 `cur_dict[step]=loss` → 实时写 `reports/train_curve_<policy>.json`（step_s=0 占位）；训练结束最终落盘补全 step_s + 完整曲线（覆盖实时文件）
  3. FlowScopeDialog：`_load_data` 优先读**最新 mtime** 的 train_curve_*.json（不再只读内存 `module._train_curve`）+ `QTimer 2s` 自动刷新 + closeEvent 停定时器
- 教训：GUI 显示"训练中"数据时，后台 worker 要**流式落盘**（文件是最简单的跨线程共享），对话框 QTimer 轮询文件——比信号直连简单可靠
- 验证套路：模拟训练中写 5 点 → Scope 读 5 点 → 追加 1 点 sleep 2.3s → 刷新到 6 点

## 📊 Scope 三曲线同名覆盖 bug（老倪："怎么就一条曲线，不应该是3个曲线对比么"）
- 症状：reports/ 下明明有多个 train_curve_*.json，Scope 只显示 1 条
- 根因（双层）：① 改完代码**没重启控制台进程**，用户跑的是旧代码（先查进程启动时间 vs git 提交时间！PID 启动早于提交 = 旧代码）② smolvla/smolvla_lew 两个曲线文件的 `name` 字段都是 "SmolVLA"（旧代码生成的 lew 曲线 name 错），dict 同名 key 互相覆盖 → 只剩 1 条
- 修复：series key 用 **policy 显示名映射**（2026-08-05 老倪："SmolVLA(smolvla_lew)分开写, 这是两个模型"——policy 标识不显示给用户）：`_DISPLAY = {"act": "ACT", "smolvla": "SmolVLA", "smolvla_lew": "SmolVLA+LEW"}`，key = `f"{disp}{tag}"`（tag = 训练中标注）；颜色仍按 policy 区分（act 蓝/smolvla 橙/smolvla_lew 紫）
- 教训：**"还是XX/没有XX" 反馈排查顺序 = ①进程是不是旧代码 ②数据同名/键冲突 ③布局挤压**；GUI 改完必须重启（pkill -f "[s]tudio.py" 防自杀 + 后台重启），否则用户永远看到旧行为；图例/标签永远用用户可读显示名，别把内部 policy 标识暴露给用户

## 📈 对比评估扩展维度（老倪："除了loss曲线，还有什么能对比模型性能"）
- compare_models.py eval_policy 收集：traj_pred/traj_gt（逐帧动作轨迹，限120帧）、frame_err（逐帧 MSE）、mse_p50/mse_p90（误差分布）、smoothness（相邻动作差分 std）
- ModelCompareDialog：8 指标条形图（速度/MSE/成功率/鲁棒性/延迟/P50/P90/平滑度）+ err_scope 逐帧误差曲线 + 表格加新指标行
- BarCompareWidget paintEvent 坐标必须 int 化（PyQt5 严格类型，float y0 崩 drawText）

## 🎯 典型场景轨迹对比（traj_scope，老倪："一个典型场景，用3个模型分别跑，对比效果"）
- 同一帧序列（同一典型场景）下各模型 traj_pred vs 专家真值叠加：多通道动作取通道均值曲线，真值用 "grid" 色虚线（dashed=True）
- 各模型取最小公共帧数 n_frames_min 对齐；traj_scope 放 err_scope 之后、表格之前
- ⚠️ 状态：traj_scope 代码已加（simulink_scope.py ModelCompareDialog），本会话被新需求打断**未验证未提交**——下次动对比对话框先跑 traj 渲染测试

## ⏱ 训练时长铁律（老倪："每次训练不要超过5分钟"）
- steps 300→150→**100**（8e6586ab 傍晚，老倪"训练时间太长"；模板 10 处 + 3 个 metaworld 配置 + node_logic.py `p.get("steps", 100)`）；实测 ACT 100 步 26s（6.9 step/s，loss 5.3）
- SmolVLM2-500M 每次 subprocess 加载 ~40s 是固定开销（无法省），只能减训练步数
- eval_freq 若 ≥ steps 则训练中不触发评估（省时）；save_checkpoint 保持 true（训练后要取 last）

## ▶ 运行三模型训练顺序优化（老倪："应该是3条曲线同时生成"）
- 老倪对串行训练中途状态不满："一个大点和一个曲线是什么意思"——那是**串行训练中途观察**（正在训的模型仅 1 点、已训完的是完整曲线、没轮到的没文件）
- 澄清后老倪确认走**串行自动连续方案**（8GB 显存并行 3 个 SmolVLA 系模型会 OOM，不现实）
- 优化：`_start_canvas_flow` 里训练节点按 policy 耗时升序排序（`_speed = {"act":0, "smolvla":1, "smolvla_lew":2}`，其余环节保持拓扑序）——ACT 最快先训完，3 条曲线尽快在 Scope 齐
- 拓扑序默认是 SmolVLA→LEW→ACT（最贵的中间、最便宜的殿后），不排序用户等最久才见第 3 条
- **教训：多模型串行训练时，把耗时最短的排前面让曲线尽快齐；用户看 Scope 中途状态会误以为缺曲线，需在指标行标注「(训练中)」+「⚠️ 缺: XX」**

## 📊 Scope 1 点曲线「(训练中)」标注
- series key：`f"{disp}{tag}"`，`disp` = policy 显示名映射（act→ACT / smolvla→SmolVLA / smolvla_lew→SmolVLA+LEW），`tag = " (训练中)" if len(cv) < 2 else ""`——训练中实时写盘只有 1 点，标注清楚避免老倪误以为异常
- 配套：`_load_data` 门槛 `len(cv) < 1` 才 skip（1 点也显示），ScopeWidget 1 点画圆点
- 验证套路（真实数据 3 文件：act 3点 + smolvla 1点 + smolvla_lew 6点）→ 断言 3 条、含「训练中」key、无「缺:」提示

## 📉 loss 口径不同：SmolVLA 的 loss 为什么比 SmolVLA+LEW 下降快（老倪追问）
- 根因：**两条曲线的 loss 构成不一样，不可直接比**
  - SmolVLA 纯：`total_loss = action_loss`（modeling_smolvla_lew.py:417）
  - SmolVLA+LEW：`total_loss = action_loss + lew_loss`（多一项世界模型损失，lew_loss = 预测下一帧嵌入 L1）
- 所以 LEW 版曲线数值天然更高、下降更平缓：① 多一项损失成本 ② LeWorldModel 随机初始化从零学，lew_loss 前期大收敛慢 ③ 起点就高（LEW 版 0.844 vs 纯版 0.757，差值 ≈ 初始 lew_loss 贡献）
- **教训：对比评估最终裁决用「动作 MSE」（预测 vs 真值，口径统一），不用训练 loss**——不同模型 loss 构成不同（多 LEW 项/多 KL 项）时训练 loss 是混频信号
- **解读 loss 数值的答法**（老倪 2026-08-05 连续问「MSE 66 意味着啥」「4.27 啥物理含义」）：MSE 是对 batch×动作维所有元素取平均 → **每维 RMSE ≈ √MSE**（66 → ~8 单位/维 = 起步瞎猜误差大；4.27 → ~2.07 rad/s ≈ 115°/s 每关节速度平均偏差）。要点：① 数值大小取决于动作单位尺度（metaworld 关节速度 rad/s 量级 ±5~10，MSE 60+ 是正常起点）② 绝对值不能跨任务/跨模型直接比，同任务内 ↓90%+ 才是学习有效的信号 ③ 收敛没完成时（150 步快速验证）loss 还在下降，别拿最终值下结论 ④ 真机精度（±0.02mm）靠 S3 真机微调，不是仿真 MSE 能直接对应的
- 旧曲线数据是 300 步的（steps 已改 150），新训练后自动更新

## 📊 loss 口径统一（已实现：只画 action_loss）
- 老倪定案：\"loss 曲线改成只画 action_loss（对 LEW 模型剔除 lew_loss 项），三模型口径统一、直接对比\"
- **训练侧**（lerobot_train.py log_step 分支）：`logging.info(train_tracker)` 之后额外 `logging.info(f"action_loss:{_al:.4f} lew_loss:{_ll:.4f}")`——output_dict 里有 action_loss/lew_loss（modeling 的 logs），但原来只进 wandb 不进 stdout；train_tracker 行只有混频总 loss（`loss:2.259 grdn:...` 无 step 字段）
- **GUI 侧**（simulink_module.py）：`_parse_loss_curve(lines, prefer_action=True)` 优先正则 `action_loss[:=\s]+([\d.eE+-]+)`；该行无 step → 用已有最大 step + 5 递增推断（**log_freq 最终定 5**，50→10→5：2 点显示门槛出现在 10 步=6.7%，训练 12% 时已有 3-4 点，用户不再报"训练到12%为什么还没显示"）；无 action_loss 的行回退旧 pat1/pat2（需含 step，train_tracker 行无 step 自然被跳过不会混入）；`_line_hook` 透传 prefer_action=True
- 验证套路：真实流 3 行（train_tracker 无 step + action_loss×3）→ 只出 3 点全来自 action_loss（50/100/150）；混合 step 行 + action_loss 行两者都会保留（注意！prefer_action 只影响 action_loss 行，旧 step 行仍解析——若训练日志同时有含 step 的 loss 行会混口径，实际 lerobot_train 日志不含 step 所以安全）
- **ScopeWidget 1 点渲染**：`len(data) < 2 → continue` 会让训练中 1 点曲线不画——改 `< 1`，1 点画圆点（drawEllipse 半径4），≥2 才画折线
- **🐛 图例被 1 点 continue 跳过（老倪："scope的蓝色线，没有名字"）**：原 paintEvent 把**图例绘制放在波形循环内**，1 点曲线画圆点后 `continue` → **连图例一起跳过** → 训练中的曲线（ACT 蓝色圆点）无名。修复：图例绘制**移到循环外单独 for 循环统一绘制**（所有曲线无论点数都有图例）；验证：真实数据 3 条（含 2 条 1 点）图例全绘制 + 图例总宽 < 窗口宽（`18 + horizontalAdvance(name) + 16` 横向累加，超宽会画到窗外——必要时换行）
- **🐛 图例色块全变同一颜色（老倪："你的图例，怎么都用黄色？都是一个颜色。线也不是一个颜色啊"）**：QPainter **pen/brush 状态会跨绘制阶段残留**——画 1 点圆点时 `setBrush(橙色)`，之后图例的 `drawRect` 是空心矩形（只 setPen 没 setBrush），**被残留的橙色 brush 填充** → 所有图例色块都变橙色（用户看到的"黄色"）。修复：图例色块显式 `p.setPen(QPen(color,2)) + p.setBrush(color)` 实心填充各自颜色，画完 `p.setBrush(Qt.NoBrush)` 清除。验证套路：**像素级采样**——`grab().toImage().pixelColor(色块中心x, 13)` 断言 hex 与期望一致（紫#a371f7/橙#d29922/蓝#58a6ff）。教训：QPainter 共享状态下，任何 `setBrush/setPen` 后要么显式清除、要么每次都完整设置；"全部一个颜色"类 UI bug 先怀疑 painter 状态残留（圆点/填充图元画过之后）

## 🐛 Scope \"还是1条曲线\" 最终根因（老倪：\"怎么scope还是一条曲线？应该是3条啊\"）
- 排查顺序（先看 reports/ 文件再动代码）：① `train_curve_act.json` **不存在** = ACT 本轮根本没训练过（Scope 只显示存在文件）② 训练中的 `train_curve_smolvla.json` 只有 **1 点**——`_load_data` 的 `len(cv) < 2` 直接 continue 跳过！③ 于是只剩 smolvla_lew 旧数据 1 条
- 修复：`_load_data` len 门槛 `< 2 → < 1`（训练中 1 点也显示）+ 指标行追加 `⚠️ 缺: ACT/SmolVLA/SmolVLA+LEW (训练后自动出现)`（present_policies 集合比对）
- 教训：**Scope 显示 N 条的前提是 N 个曲线文件都存在且有 ≥ 门槛点数**；用户报\"少了\"先 `ls reports/train_curve_*.json` 看文件数/点数/时间戳，别急着改代码——本案例真正缺的是 ACT 训练，代码只误杀了训练中的 1 点曲线
- **🐛 0 点曲线文件诊断**（用户\"为什么smolvla训练, act波形没了\"时发现 act/smolvla 文件 `curve: []` 但 mtime 是训练启动时刻）：**有内容但 curve 空的文件 = 训练子进程 0 步就失败**（on_train 走到最终落盘、但 stdout 无 loss 行）——不是\"没训过\"（没训过不会有文件），是\"训了但秒挂\"。区分法：文件存在+0点+ts=训练启动时间 = 启动即失败；文件不存在 = 本轮没轮到/没训。**隔离法（比猜快）**：`nice -n 10 .venv/bin/python -m lerobot.scripts.lerobot_train --config_path config_<policy>_metaworld.yaml 2>&1 | tail` 手动跑一遍——ACT 手动 100 步 26s 完全正常 = 当时是临时失败（数据源/并发抖动），让用户重跑即可，别为一次性故障改代码

## ⚠️ 其他坑
- 验证脚本用 venv python（有 torch 无 PyQt5）跑 GUI 会 ModuleNotFoundError；GUI 测试用系统 python3，torch 测试用 .venv/bin/python，分开跑
- tempfile 脚本内含中文时不要用 b''' 字节字面量（SyntaxError），用 str + .encode()
- execute_code 内 subprocess 会被系统 60s 追踪上限截断（模型加载 40s+ 场景）→ 用 terminal 直接跑
- **系统 stale 验证提示的误报**：execute_code 内 subprocess 超时会被系统记录为"last command 超时"，即使实际验证已通过——重跑验证用 terminal 单命令（tempfile 创建→跑→删），别用 execute_code 嵌套

## 🎥 推理效果对比（老倪：训练完继续推理，3 个视频 display 窗口对比）
- **tools/rollout_video.py**：metaworld V3 rollout 生成帧序列（`--policy act|smolvla|smolvla_lew --steps N --out`）
  - `load_policy`：读 `reports/train_curve_<policy>.json` 的 ckpt → last/000150/000300/pretrained_model；ACT 用 ACTPolicy，其余用 SmolVLALewPolicy（`from_pretrained(local_files_only=True)`）
  - 输出：`<out>/frame_%04d.png` + actions.npy + info.json（帧数/秒/fps/动作均值）
- **simulink_scope.py InferenceVideoDialog**：3 视频窗口横排（QLabel + QTimer 100ms 逐帧，**无 QtMultimedia 依赖**——WSLg 缺 libpulse，QMediaPlayer 起不来）+ ▶播放/⏸暂停/🔄重新生成(rollout)/💾导出PNG
- REFERENCE_APPS 加「🎥 推理效果对比」模板（7 节点：数据→3训练→3视频显示，三行布局）；on_node_activated 加 `params.get("video")` 分支 → on_infer_video → 对话框
- 帧同步：3 模型共用最小公共帧数 min_len 截断
- **接入训练流程**（老倪："是不是直接接到当前训练流程之后呢？"）：三模型模板 18→19 节点 / 22→25 连线——3 个训练节点各连一条线到「🎥 推理效果对比」节点（params.video="all"），拓扑序保证训练完才触发；布局第 4 行加推理节点与训练列垂直对齐；InferenceVideoDialog 构造时 `_load_frames` 无帧 → `QTimer.singleShot(300, self._run_rollouts)` 自动生成（不阻塞构造）；on_infer_video 检测三模型 rollout 帧缺失时提示自动生成

## 🐛 metaworld V3 API 踩坑（rollout_video.py 实测）
- 环境名是 **`push-v3`**（不是 push-v2/v1——"not a V3 environment"）；`metaworld.MT1("push-v3")` 的 train_envs 属性**不存在**（dir 只有 train_classes/train_tasks）
- 正确创建：`from metaworld.env_dict import ALL_V3_ENVIRONMENTS; env = ALL_V3_ENVIRONMENTS["push-v3"]()` → `env._freeze_rand_vec = False` → **`env.set_task(mt1.train_tasks[0])` 必须在 step 前**（否则 RuntimeError）→ `env.reset(seed=...)` 返回 **(obs, info) 元组**
- 帧获取：`env.render()` 返回 (H,W,3) uint8；obs 是 39D 状态 ndarray **无 "image" 键**（V3 改了）
- select_action 输出维度与 env.action_space 不符时：截断/补零（`act[:] = a[:act.size]`），推理异常 except 兜底零动作（视频仍展示环境）

## 🎥 录屏功能（老倪：训练→推理→部署全程录制成视频，可加速，总长<1分钟）
- 工具栏「🔴 录制 / ⏹ 停止」两按钮（btn_record / btn_stop_rec，红/橙配色，停止默认 disabled）
- `start_recording`：QTimer **1000ms（1fps 采集）**（2026-08-05 下午改：原 500ms/2fps grab 整窗大图会**占满事件循环** → 停止按钮点击排不上队 → 老倪报「按停止按钮，没反应」）→ `self.grab()` 整窗截图（**含画布+终端输出+模型结果**）→ `reports/screenrec_<ts>/frame_%04d.jpg`（**JPEG q85，勿用 PNG**——PNG 压缩大图慢卡 UI）
- **防堆积标志 `_rec_busy`**（关键）：`_rec_tick` 开头 `if self._rec_busy: return`，try 里置 True、finally 置 False——上一次 grab+save 未完成则跳过本次采集，**保证事件循环始终有空处理按钮点击**。实测：录制 10s 采 10 帧（≈1fps 不堆积）、停止返回 0.001s、录制中按钮全程可点
- `stop_recording`：停定时器 + 按钮复位 **立即返回** → **后台线程** `_ffmpeg_compose`（threading.Thread daemon）合成；完成经 `log_signal.emit` 回主线程日志（**线程内不能直接调 _log/弹窗**，用信号）
- **🐛 ffmpeg 加速陷阱**：`-framerate 1 -i ... -r 2` **不加速**（时长按输入帧数算，10 帧 1fps → 10s 视频）——要 2x 加速必须**输入帧率直接给 2**：`-framerate 2 -i frame_%04d.jpg -vf "pad=ceil(iw/2)*2:ceil(ih/2)*2" -c:v libx264 -pix_fmt yuv420p -r 2 screen_rec.mp4`（play_fps = 采集 fps × 2）。实测：录 10s → 视频 5.0s ✓
- **🐛 MP4 0 字节坑（libx264 偶数尺寸）**：grab() 窗口尺寸可能奇数（实测 1668x929，高 929 奇数）→ libx264 报 `Generic error in an external library` → **输出 0 字节 MP4**（ffprobe 为空、用户找不到视频）。修复：`-vf pad=ceil(iw/2)*2:ceil(ih/2)*2` 补齐偶数。**验证：ffprobe -show_entries stream=width,height,duration 确认输出非 0 且宽高偶数**
- **🎬 录制视觉反馈（老倪："点击录制按钮，没反应"）**：功能正常但无醒目反馈 → 用户以为没反应。start_recording 里按钮变「⏺ 录制中…」+ `_rec_blink` QTimer 500ms 呼吸闪烁（红/深红交替 setStyleSheet）；stop_recording 停 blink + 恢复「🔴 录制」+ 还原样式；**closeEvent 的定时器清理列表要同步加 `_rec_blink`**（否则录屏中关窗又 exit 134）。排查"按钮没反应"：先 `ps aux | grep "[s]tudio.py"` 查进程是否存活（可能已崩）→ offscreen `btn.click()` 实测（看 _rec_dir 是否创建/_rec_timer 是否 active）+ `ls reports/screenrec_*` 看用户是否其实在录（旧代码 PNG 卡死会录出数百帧但停止按钮点不动）
- **offscreen 测试坑：`time.sleep()` 不驱动 QTimer**——录制测试必须 `while time.time()<t_end: app.processEvents(); time.sleep(0.05)` 手动驱动事件循环，否则 sleep 3s 只采到 1 帧

## 📐 Scope 坐标轴（老倪："scope loss曲线，为什么没有横纵坐标"）
- 原 paintEvent 只画网格+曲线+图例，**没有坐标轴刻度** → 加 Simulink Scope 风格坐标轴：
- **x 轴（底部）**：5 等分 step 刻度（`max_n` = 各 series 最大点数，`step_hi = max_n-1`，`step_val = int(round(k*step_hi/4))`）+ 短刻度线 + 右下角 "step" 标签；`max_n < 2`（全是 1 点训练中）时只画标签不画刻度
- **y 轴（左侧）**：5 等分 loss 值刻度（`val = y_hi - k*(y_hi-y_lo)/4`，`f"{val:.2f}"`）+ 左侧短刻度线 + 左上角 "loss" 标签；颜色用主题 text2（灰），字号 Consolas 8
- 绘制位置：网格之后、曲线之前（y_lo/y_hi 变量在坐标轴处先算一次，曲线处再算，两处一致）
- **验证套路（像素级，防"坐标采样错位"坑）**：`grab().toImage()` 后——注意 **grab 返回图含窗口边框，尺寸 ≠ widget 尺寸**（实测 scope 640x480 但 grab 756x421）！采样区域必须按 `img.height()/width()` 实际尺寸算（底部 16px 亮像素 > 20、左侧 50px 亮像素 > 100 判定刻度文字存在），不能按 widget 尺寸硬编码 y 坐标
- 教训：用户要"坐标轴/刻度/标注"类功能时，自绘 widget 必须连刻度带标签一起画，光有网格线用户会认为"没有横纵坐标"

## 📐 Scope x 轴真实 step（老倪："只显示 1 2 4 step，而训练已经 35/150 了"）
- 症状：x 轴刻度显示 1/2/4 而不是 50/100/150——曲线数据是 `[[step, loss], ...]`，但 series 只存了 loss 数组，**step 被丢弃**，x 轴按索引 0/1/2 画
- 修复：series 值从 3 元组 `(ys, color, dashed)` 升级为 **4 元组 `(xs, ys, color, dashed)`**（xs=None 兼容旧格式）：
  - FlowScopeDialog._load_data：`xs = np.array([float(s) for s, _ in cv])`，`series[key] = (xs, ys, color, False)`；兜底单条同样带 xs
  - ScopeWidget 波形绘制：`x_lo, x_hi = (xs[0], xs[-1])`，每点 `x = (xi - x_lo)/(x_hi - x_lo) * w`（真实 step 归一化）
  - `_y_range()` 取 `v[1] if len(v)>=2 else v[0]`；图例/指标行同样解 4 元组
  - 验证：真实数据 ACT xs == [50, 100, 150]（不是 [0,1,2]）
- **y 轴 "loss" 标签与图例重叠（老倪："左上角的loss与模型的名字重合了"）**：原标签画 (4,14)，图例从 (10,8) 起 → 撞上。修复：y 轴标签移到左下角 `drawText(4, h-18, "loss")`（图例区留给图例）
- **"SmolVLA(训练中) 长时间只显示一个点"**：根因 log_freq=50——训练 35/150 还没到 50 步落盘点，Scope 只有旧数据 1 点。修复：3 个 metaworld config `log_freq: 50 → 10` + `_parse_loss_curve` 的 step 推断 `+50 → +10`（`step = (max(dedup, default=0) + 10) if dedup else 10`）——150 步训练 = 15 个点，波形密集，训练中不再"卡在 1 点"
- 教训：**自绘折线图的 x 轴必须是数据的真实自变量，不能用数组索引冒充**——用户训练进度 35/150 与图上 step 对不上立刻会被发现；多模型曲线各自的 step 范围不同（ACT 50-150 vs LEW 50-300）时各曲线用自己 xs 归一化，x 轴刻度取最大 step 范围


## 🛡 QThread 崩溃修复 #2（录屏定时器，exit 134 复发）
- 症状复现：用户在录屏中（_rec_timer 还在跑）关闭窗口 → 又崩 `QThread: Destroyed while thread is still running` exit 134
- 根因：closeEvent 只清理了采集轮询（_acq_timer/_acq_worker），**没清理后来新增的 _rec_timer**（QTimer 定时 grab 截图）
- 修复：closeEvent 追加 `_rec_timer.stop()` + 置 None
- **教训：每次新增 QTimer/QThread 成员，closeEvent 都要同步补清理**——崩溃修复 #1 只覆盖了当时的定时器，后续加录屏/轮询定时器忘了同步 → 复发。养成习惯：加定时器成员时顺手在 closeEvent 加 stop

## 🔍 Scope 波形缩放（老倪："scope的波形，大小要能够缩放，现在动不了，UI不好"）
- ScopeWidget 交互三件套（Simulink Scope 风格）：
  - `wheelEvent`：以鼠标位置为中心缩放 y 轴（up=1.25x 放大收窄范围，down=0.8x 缩小）——`frac = 1 - ev.pos().y()/h` 算鼠标处数据值做 center，`new_span = span/factor`
  - `mousePressEvent/MouseMoveEvent`：**中键拖拽平移**（老倪二次反馈："scope 无法用鼠标中键拖动, 改"）——中键按下时若 `_y_lo_manual is None` 先自动初始化手动范围（**未缩放也能拖**）+ `setCursor(Qt.ClosedHandCursor)`；`dy * span / h` 换算数据增量；释放恢复 Arrow 光标。左键按下也记 _drag_last（兼容），但用户明确定义中键为平移
  - `mouseDoubleClickEvent`：复位自动范围（_y_lo_manual=None）
- 状态：`_y_lo_manual/_y_hi_manual`（None=自动），`_y_range()` 有手动值时返回手动范围
- **拖拽方向语义（测试断言写反教训）**：鼠标向上拖（y 减小）→ 波形视觉上移 → 显示范围**下移**（看更低的值）→ `lo3 < lo2` 才正确！写测试断言时先想清楚方向
- **PyQt5 QWheelEvent 构造坑**：offscreen 测试需 9 参 `QWheelEvent(pos, globalPos, pixelDelta(QPoint), angleDelta(QPoint), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False, Qt.MouseEventNotSynthesized)`——pixelDelta/angleDelta 必须 QPoint 非 QPointF，buttons 在 modifiers 前

## 🛡 QThread 崩溃修复 #3（SimulinkModule 主类无 closeEvent，exit 134 三连复发）
- 症状：用户在录屏后关闭窗口（reports/screenrec_150545 有帧），又崩 `QThread: Destroyed while thread is still running` exit 134
- 根因：修复 #1/#2 都加在 **CICDPanel.closeEvent**（978 行）——但 **SimulinkModule 主类（QWidget）根本没有 closeEvent**！主窗口关闭 → SimulinkModule 析构时 `_worker`（CICDWorker QThread，3248 行 `self._worker = worker`）/ `_acq_worker` / `_rec_timer` 全部未清理 → 崩
- 修复：SimulinkModule 加 closeEvent——循环停 5 个定时器（_timer/_remote_timer/_acq_timer/_rec_timer/_tutorial_timer）+ 循环 `wait(3000)` 2 个 QThread（_worker/_acq_worker）+ 置 None
- **排查法**：崩溃复发先 `grep -n "def closeEvent"` 看**哪个类**有/没有 closeEvent——本案例崩的是主窗口路径（主类无 closeEvent），不是面板路径；录屏产物（screenrec_*/rollout_*）时间戳能反推用户崩溃前在做什么
- **patch 插入错位教训（高危）**：用 patch 往 `__init__` 末尾加方法时，若 old_string 锚定 __init__ 内最后一行（如 `self._worker = None`），新方法体会被插进 **__init__ 内部**（`_cicd_state`/`_build()` 等变成新方法的尾部代码）→ 构造执行路径错乱。修复：把 __init__ 尾部语句移回 closeEvent 之前。**教训：往类里加方法，old_string 锚点必须含「完整方法定义边界」；加完立刻 `compile()` + 构造一次验证**
- 录屏/训练中关闭窗口验证套路：start_recording() → processEvents 驱动 1s（不停止录屏）→ 直接 close() → 重新构造 SimulinkModule → ×3 无崩溃；用 shutil.rmtree 清 screenrec_* 孤儿目录

## 🛡 QThread 崩溃修复 #4（StudioMainWindow 主窗口 closeEvent，exit 134 四连复发）✅ 已修复
- 症状：用户报「录制按钮又没反应」——先查 `ps aux | grep "[s]tudio.py"` → **0 进程 = 控制台已崩**（exit 134），按钮当然没反应。排查\"按钮没反应\"第一步永远是查进程是否存活
- 根因：`StudioMainWindow(QMainWindow)`（6762 行）**没有 closeEvent**——`_orin_timer`(4967, 5s 轮询 Orin)/`_rerun_worker`(5207, _RerunStreamWorker QThread)/`_live_timer`/`_replay_timer`/`_stats_timer` 关闭时全部未清理 → 主窗口关闭即 `QThread: Destroyed while thread is still running`
- 修复：StudioMainWindow 加 closeEvent——循环停 5 个定时器（_timer/_orin_timer/_live_timer/_replay_timer/_stats_timer）+ `_rerun_worker.stop() + wait(3000)` + 兜底 `sim.close()` 触发 SimulinkModule.closeEvent 链
- 验证：主窗口构造 → `w.simulink.start_recording()` → processEvents 驱动 1.5s → `w.close()` → 无崩溃
- **教训（崩溃排查总纲）**：exit 134 四连复发（CICDPanel→录屏定时器→SimulinkModule 主类→StudioMainWindow 主窗口）后总结——**每个持 QTimer/QThread 的类都要有自己的 closeEvent**，且新增定时器/线程成员时必须同步补 closeEvent 清理。查法：`grep -n "def closeEvent" tools/gui/*.py` 列出**每个类**，对照成员表逐类核对

## 🛡 QThread 崩溃修复 #5（训练中关闭窗口：wait(3000) 不够 → 先 pkill 子进程，exit 134 五连复发）
- 症状：用户训练 ACT（150 步 ~15s+）**进行中**关闭窗口 → 又崩 `QThread: Destroyed while thread is still running` exit 134（train_curve_act.json 时间戳可反推：15:47 训练中崩溃）
- 根因：#3 修的 closeEvent 里 `_worker.wait(3000)` 只等 3s——**CICDWorker 是阻塞 QThread**（run() 里执行 on_train 的 subprocess.run，训练 150 步远超 3s），wait 超时后线程还在跑 → 析构必崩
- 修复：closeEvent 的 QThread 清理分支，wait 前**先 pkill 终止训练子进程**让 worker 快速结束：
  ```python
  import subprocess as _sp
  _sp.run(["pkill", "-f", "lerobot.scripts.lerobot_train"], capture_output=True, timeout=5)
  _sp.run(["pkill", "-f", "tools.cicd_pipeline"], capture_output=True, timeout=5)
  w.wait(10000)
  ```
- 教训：**阻塞型 QThread（内部跑长 subprocess）无法靠 wait(短超时) 优雅退出**——要么等完要么先杀子进程；用户\"训练中关窗\"是高发崩溃场景，验证必须覆盖（start_recording 或启动训练后立即 close）

## 🛡 QThread 崩溃修复 #6（CICDPanel.closeEvent 漏清 _worker，exit 134 六连复发）
- 症状：用户通过**数据闭环控制台面板**训练 ACT 后关闭窗口 → 又崩 `QThread: Destroyed while thread is still running` exit 134（train_curve_act.json 时间戳 15:56 反推）
- 根因：**CICDPanel.closeEvent（978 行）只清理了采集轮询（_acq_timer/_acq_worker）和录屏（_rec_timer），漏了它自己的 `_worker`**（947 行 `self._worker = worker` 创建的 CICDWorker）——修复 #1-#5 全在 SimulinkModule/StudioMainWindow，CICDPanel 的 _worker 从未被清理
- 修复：CICDPanel.closeEvent 追加与 SimulinkModule 同款的 _worker 清理（pkill lerobot_train/cicd_pipeline + wait 10000）
- **排查法更新（崩溃总纲终极版）**：exit 134 六连复发后确认——`grep -n "def closeEvent"` 列出**每个类**，且 closeEvent 里必须覆盖**该类自己创建的全部** QTimer/QThread 成员；同一个类里 `self._worker = CICDWorker(...)` 和 closeEvent 往往相距很远（本案例 947 vs 978 行），用 `grep -n "self\._worker = \|self\._acq_worker = "` 对照 closeEvent 逐一核对

## 📊 训练中不显示曲线（老倪反转决策：\"刚开始，不要显示任何曲线，会引起歧义。训练完了再显示\"）
- ⚠️ **本节推翻了前面「1 点曲线也显示+圆点+训练中标注」的设计**——用户明确要求训练刚开始不要显示任何曲线
- 实现（FlowScopeDialog._load_data）：`if len(cv) < 2: training.add(disp); continue`——1 点（训练中）**不进 series 不画**；完整曲线（≥2 点）才显示
- 指标行区分：`⏳ 训练中: SmolVLA`（training 集合）与 `⚠️ 缺: ACT`（present_policies 比对，排除 training 中模型）——用户能分清\"正在训\"和\"没训过\"
- 验证套路：真实数据（act 3点 + smolvla 1点 + lew 6点）→ 断言 series 只有 2 条（ACT+SmolVLA+LEW）、无含\"训练中\"的 key、metrics 含 \"⏳ 训练中\"
- 教训：**用户对\"训练中呈现\"的偏好可能反转**（先要实时波形→后来嫌歧义）——记录最终决策而非中间态；1 点圆点在 Scope 里容易歧义，用户宁可等训练完再看完整曲线

## 📊 Scope 默认清空（最终决策：\"默认不要显示线，你还没训练呢，不要显示线。scope先清空\"）
- ⚠️ 最终定案（在本节之上又进一步）：**Scope 打开就是空白，任何历史/默认曲线都不显示**——即使 reports/ 里有旧曲线文件也不画
- ⚠️⚠️ **2026-08-05 傍晚最终语义修正（51097377，用户\"smolvla训练为什么act波形没了\"）**：清空只针对**当前 policy 自己**的旧曲线，**必须保留其他模型已完成曲线**——三模型对比串行训练时，SmolVLA 训练启动不能把 ACT 训完的曲线删掉。实现：on_train 只 `os.remove(train_curve_{policy}.json)`；Scope `_load_data` **去掉 mtime 过滤**（保留所有已训练曲线）。\"scope先清空\"= 打开时无默认线（series 空 → `set_series({})` + 提示，去掉旧 `_train_curve` 兜底），**不是**训练启动清别人的曲线。
- 完整行为链（验证过）：训练启动→只删当前 policy 文件（其他模型曲线保留）→ Scope 打开显示已完成模型曲线 + ⏳ 训练中提示 → 当前模型训练完成（≥2 点）自动加入

## 📐 Scope 坐标轴单位/含义标注（老倪：\\\"纵坐标的单位，含义也写上\\\"）
- 老倪问 loss 纵坐标单位含义 → 回答：**MSE（均方误差，Mean Squared Error）= 模型预测动作与真值动作之间的平均平方误差**，越小学得越好
- 实现（ScopeWidget.paintEvent 坐标轴区）：
  - y 轴标签（左下角，替代原来光秃秃的 "loss"）：`drawText(4, h-18, "loss (MSE · 动作预测误差)")`——**单位+含义一起写**
  - x 轴标签（右下角）：`drawText(w-78, h-4, "step (训练步数)")`（原 "step" 太短且无含义；留 78px 给文字宽度）
  - x 轴刻度改用**真实 step 范围**（不再用 max_n 索引推断）：遍历 series 取各曲线 `xs[0]/xs[-1]` 的 min/max，5 等分 `step_val = round(x_min + k*(x_max-x_min)/4)`——多条曲线 step 范围不同（ACT 50-150 vs LEW 50-300）时统一按最大范围
- 验证套路：grab().toImage() 左下角区域（x 4~170, y h-20~h）亮像素 > 阈值判定标签文字渲染存在
- 教训：用户问"单位/含义"时直接写进图里（标签带括号说明），别只口头回答——自绘 widget 的轴标签是唯一说明渠道

## 🛡 QThread 崩溃修复 #7（InferenceVideoDialog 无 closeEvent，exit 134 七连复发）✅ 已修复
- 症状：用户 15:58 训练 ACT 后崩溃（train_curve_act.json 时间戳反推），`QThread: Destroyed while thread is still running` exit 134
- 根因：**InferenceVideoDialog（simulink_scope.py 867 行）没有 closeEvent**——它持有 `_timer`（100ms 视频播放）和 `_poll_timer`（500ms rollout 轮询 QTimer），用户打开推理对比对话框（rollout 生成中）关闭 → 定时器未停 → 析构崩
- 修复：类尾部加 closeEvent——循环停 `("_timer", "_poll_timer")` + super().closeEvent(ev)
- **崩溃排查总纲（七连复发最终版）**：`grep -n "def closeEvent" tools/gui/*.py` 列出**每个类**，核对每个持 QTimer/QThread 的类都有 closeEvent 且覆盖**该类自己创建的全部**定时器/线程成员。已覆盖清单：CICDPanel（#1 采集轮询 #2 录屏 #6 _worker）→ SimulinkModule 主类（#3）→ StudioMainWindow（#4 _orin_timer/_rerun_worker）→ 阻塞 worker pkill（#5）→ InferenceVideoDialog（#7）。**新增 QTimer/QThread 成员时同步补 closeEvent 是唯一根治手段**

## ▶ 运行反馈增强（老倪："点击运行，感觉没反应，没有反馈" → "运行，还是没反应"）
- 症状：用户加载模板后点 ▶ 运行，没有训练启动、没有提示，感觉"没反应"；加了自动展开后用户仍说"还是没反应"（可能画布为空/观察模板，或点击瞬间无任何视觉变化）
- **第一优先级修复（点击瞬间即时反馈）**：start_sim 开头无条件执行——`btn_run.setText("⏳ 运行中…") + setEnabled(False)` + log「▶ 运行指令已接收, 正在解析画布…」；空画布分支要**恢复按钮**（`setText("▶ 运行") + setEnabled(True)`）再提示。这样任何路径点击瞬间都有按钮变化，用户不会觉得"没反应"。**"运行/录制/保存"类按钮被点后先给状态反馈，再走分支逻辑**
- 根因：**start_sim 的逻辑是"有环节节点(采集/训练/验证/部署/推理)才真实执行，否则静默进仿真"**——但加载「🎛 总系统·三模型对比」这类**观察/子系统模板**（顶层只有 数据→子系统块→Scope，无环节节点）时，走仿真分支：只 log 一行「▶ 仿真开始」、节点不执行任何真实动作 → 用户看不到训练/推理 → 以为没反应
- 修复（start_sim 无环节分支）：
  1. 检测 `params.get("subsystem")` 的子系统块 → **自动 `_open_subsystem(sub_node)` 展开** → `QApplication.instance().processEvents()` → 重新 `_canvas_stage_nodes()` → 有环节则 `_start_canvas_flow(stages)` 直接启动内部真实流程（用户点运行就是要训练，不用先教他双击展开）
  2. 展开后仍无环节 → 明确日志 + `_show_bubble` 气泡提示「子系统内部无执行环节 — 加载「🔬 三模型对比」模板再运行」（不静默）
  3. 无子系统也无环节 → 同样气泡提示「画布无执行环节」
- 验证套路：加载「🎛 总系统·三模型对比」（3 节点）→ start_sim → 断言展开后 >3 节点 + `_flow_queue` 非空 + `_worker` 已创建
- 教训：**运行按钮必须有可见反馈链**——模板按"观察型（无环节）"和"执行型（有环节）"分两类；观察型点运行要么自动展开进入执行、要么气泡明说怎么才能跑起来，绝不能静默进仿真；顺带注意模板名（「🎛 总系统·三模型对比」≠「🎛 总系统」，加载用错名返回 False 且 nodes 不变，排查时先打印 REFERENCE_APPS 名字列表）

## 📈 训练中进度日志（老倪："上一个任务还在跑，请稍候 为什么这里卡住很长时间了"）
- **症状**：用户训练中又点运行/双击节点 → 日志只有「⏳ 上一个任务还在跑, 请稍候…」，用户以为卡死
- **排查**：`ps aux | grep "[l]erobot_train"` → 训练进程在跑且 **CPU 460% 满负荷 = 训练正常进行中，不是卡住**——真正问题是**训练中日志区没有任何输出**（_line_hook 只解析 loss 写文件，不打印），界面静止像死机
- **修复**（simulink_module.py on_train 的 _line_hook）：每解析到一个 loss 点就 emit 进度行：
  ```python
  total = int(steps) if steps else 300
  self.log_signal.emit(f"📈 {pname} 训练中: {step}/{total} 步 · loss {loss:.4f}")
  ```
  （log_freq 已改 5，所以每 5 步一行，100 步训练共 20 行进度）
- 4 处「⏳ 上一个任务还在跑, 请稍候…」拦截提示统一改为「…(训练中, 日志区可看到 📈 进度)」（_run_node_stage/_start_canvas_flow/_start_worker/_run_full_flow）
- **教训**：**"卡住/没反应"先查进程 CPU/存活，再查是否有进度输出**——长任务（训练/合成/下载）必须在后台 worker 里周期 emit 进度日志，否则界面静止 = 用户必然报"卡死"；拦截提示要引导用户看进度日志在哪

## ▶ 运行弹窗反馈（最终版：非模态 show + 3s 自动关，老倪第三次报"点击运行没反应没有反馈"）
- 按钮变色+日志仍不够（用户不看日志区）→ `_start_canvas_flow` 启动时弹醒目提示窗「🚀 正在执行 N 个环节: X → Y → Z」+「后台自动运行中 — 关闭本窗口可继续查看画布/日志区进度」+ 按钮「知道了, 开始运行」
- **🐛 exec_ 模态陷阱**：`QTimer.singleShot(0, mb.exec_)` 会**阻塞主线程**——训练中日志刷新/画布全停，且 offscreen 测试卡死（EXIT=124 超时，无用户点按钮）。**必须非模态**：`mb.show()` + `QTimer.singleShot(3000, mb.close)`（3s 自动关，不挡操作）
- 三层反馈链最终版：① 按钮变「⏳ 运行中…」禁用 ② 非模态弹窗列出执行环节 ③ 日志区流程行 + 训练中 📈 进度行
- 验证：offscreen 下**不要实际 exec_ 弹窗**——断言源码含 `mb.show()` + `QTimer.singleShot(3000, mb.close)` + 标题「运行已启动」即可；流程启动断言看 `_flow_queue` 非空 + `_worker` 已创建
- **测试脚本自身防崩教训**：offscreen 验证脚本里创建 2 个 SimulinkModule 实例（w 的 worker 还在跑时建 w2 或脚本退出）→ 脚本自身 exit 134 `QThread: Destroyed while thread is still running`——**脚本退出前必须 `pkill -f lerobot.scripts.lerobot_train` + `wkr.wait(5000)` 清理 worker**，否则是测试脚本在崩不是产品在崩

## 🛡 QThread 崩溃修复 #8（CICDPanel.closeEvent 漏清 _remote_worker，exit 134 八连复发）✅ 已修复
- 症状：用户 16:14 训练 ACT 中崩溃（train_curve_act.json 时间戳反推），`QThread: Destroyed while thread is still running` exit 134
- 根因：**CICDPanel.closeEvent 清了三件套（_acq_worker/_worker/_rec_timer），但漏了 `_remote_worker`**（1100-1104 行，`worker = CICDWorker(_work)` + `self._remote_worker = worker`——远程 Orin 状态轮询 CICDWorker）→ 用户开数据闭环面板（会触发远程状态查询）后关闭 → 轮询 worker 还在跑 → 析构崩
- 修复：CICDPanel.closeEvent 追加 `_remote_worker` 清理分支（`isRunning() → wait(3000)` + 置 None）
- **崩溃排查总纲（八连复发最终版）**：`grep -n "def closeEvent" tools/gui/*.py` 列出每个类；对每个类 `grep -n "self\._xxx = CICDWorker\|self\._xxx = worker\|QTimer("` 找出**该类自己创建的全部** QTimer/QThread 成员，逐一核对 closeEvent 覆盖。CICDPanel 里 worker 创建点（947/1103 行）和 closeEvent（978 行）相距很远且散落多个 `self._xxx = worker` 赋值——**同一个类里每个 `self._xxx = worker` 都要在 closeEvent 有对应清理**。已验证覆盖清单：CICDPanel（_acq_timer/_acq_worker/_worker/_remote_worker/_rec_timer/_rec_blink）→ SimulinkModule 主类（全定时器+_worker/_acq_worker）→ StudioMainWindow（_orin_timer/_rerun_worker 等）→ InferenceVideoDialog（_timer/_poll_timer）
- **验证套路（closeEvent 全量覆盖自检）**：正则 `re.search(r'class CICDPanel.*?def closeEvent.*?(?=\n    def |\Z)', src, re.S)` 抓 closeEvent 方法体 → 断言每个 worker 名都在方法体字符串里（比肉眼核对可靠）；再实际 构造→开面板→关闭 无崩溃
- **教训：崩溃修复 #1-#7 都是\"修一个漏一个\"**——每次都是用户崩溃后才在日志/时间戳反推补下一个 worker。根治手段 = 每新增一个 QTimer/QThread 成员立刻在 closeEvent 补清理 + 定期跑 closeEvent 覆盖自检正则

