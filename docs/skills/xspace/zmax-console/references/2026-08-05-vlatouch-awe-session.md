# 2026-08-05 晚场: 训练开关 + VLA-Touch + AWE 管道 (commit d815fafb / 640a5467)

## ☑ 训练开关 node (train_gate)
需求: checkbox 打勾=训练 / 不打=不训练, 放最前边控全链路。
- NODE_TYPES 加 `"train_gate": {"cn": "训练开关", "color": "#3fb950"}`
- SimNodeItem.paint 加 train_gate 分支: 画勾选框(打勾绿#3fb950/关红#f85149) + "训练: 开/关"
- on_node_activated 加 1.6 分支 → `_toggle_train_gate(node)` (双击切换, 日志+_sync)
- `_train_gate_state()`: 无开关节点→放行 True; 多开关任一关→拦截 (保守语义: 关闭总开关必须真挡住)
- on_train `_work()` 开头查 gate: 关则 `return True, "训练已跳过 (开关关闭)"` (不报失败)
- LIBRARY 系统组条目 + CICD 主控台模板首节点 (数据源→Switch→gate→训练, 连线 (3,0)(0,4))

⚠️ **新增节点类型必须同步 ALL 硬编码映射** (漏一处就崩):
① NODE_TYPES ② add_node 的 icon dict (`{"train_gate": "☑"}` — 漏了 KeyError!) ③ simulink_ci.py 的 NODE_TYPES set (验证器拒绝未知类型) ④ 模板/LIBRARY 条目。改完 grep `\[ntype\]` / icon dict 全量检查。

## 🖐 VLA-Touch 管道 (4060 精简)
官方 github.com/jxbi1010/VLA-Touch (RA-L 2026, master 分支): 双层触觉反馈 —
- Planning 层: Octopi 触觉语言模型 → VLM 任务规划 (硬件重, 4060 不做)
- Manipulation 层 (核心): base VLA π(a|s,I) 生成动作块 → Interpolant π_I(â|s,a,m) 用触觉精炼
  输入 = DINOv2 视觉嵌入 + GelSight marker 触觉信号 m + VLA 动作 a
  参考文件: VLA/residual_controller/{bridge_controller.py, bridge/bridge_model.py, tactile/marker/marker_tracker.py, visual_encoder.py}

4060 精简 (论文卖点: without fine-tuning the base VLA → 只训轻量控制器):
- DINOv2-small (22M) 冻结视觉 · Marker 触觉跟踪 (7x9 网格→低维力, CV 轻量) · DiT-B base VLA 冻结 · StochasticInterpolants 控制器 (velocity_loss, 唯一训练模块)
- 训练脚本 tools/train_vla_touch.py: on_train policy="vla_touch" → cfg_path=None 跳过 config 生成, _run_cmd 独立分支
- REFERENCE_APPS "🖐 VLA-Touch 触觉对比" 8节点9连线: 数据→DINOv2/Marker/DiT-B→ActionHead→Interpolant→训练→Scope

## 🧿 AWE 管道 (它石 AWE 3.5/OmniVTA 架构)
三大核心哲学 (用户架构参考: "场景原生"路线, 光模块插拔垂直场景):
1. **Born as One 原生架构**: 视觉(SigLIP) + 状态 + 动作(+触觉/力觉模拟) 原生拼接进潜空间, 非后期"乐高式"拼接
2. **世界模型驱动**: zFlow H-JEPA 三层潜空间 z₁空间(128D)/z₂物体(128D)/z₃语义(64D) + GRU 预测器预测未来潜状态 (轻量, Orin Nano 可部署)
3. **隐空间动作**: 潜空间推演 → Action Head 解码
4. 交叉注意力分层注入 (门控 1.0/0.1/0.01), 推理时门控归零可剥离 (零额外开销)
- 训练脚本 tools/train_awe_zflow.py, policy="awe_zflow"
- ⚠️ 坑: nn.Linear 不能在 forward() 里创建 (每步新建模块 + device 错乱) → dec_proj 等投影层常驻 __init__

## 训练脚本通用约定 (train_vla_touch.py / train_awe_zflow.py 共享)
- **checkpoint 结构**: `<ckpt>/<step>/pretrained_model/` (compare_models.find_ckpt glob "*/pretrained_model" 兼容, 别的结构找不到)
- **输出行**: `action_loss:xxx` (GUI `_parse_loss_curve(prefer_action=True)` 解析 → Scope 曲线实时可见)
- **视觉编码器回退**: DINOv2/SigLIP 不可用(无网/显存)自动回退 state-only: vis_dim=0, 条件补零, 网络结构固定 (训练/评估一致安全)
- **触觉/力觉模拟**: 状态差分 d[:,:3]*10 + 力范数*5, 训练与 eval 同管道; 维度 = min(state_dim,3)+1 → 测试数据 state_dim 必须匹配 tactile_dim (不匹配 mat1/mat2 崩)
- **模型前向测试 DEVICE 一致性**: CPU 建模 → 评估也要 cm.DEVICE='cpu', 否则 cuda/cpu 混合报错
- **冒烟**: `HF_HUB_OFFLINE=1` 强制 state-only 快速验证 (跳过 DINOv2/SigLIP 下载卡住)
- 训练后清理冒烟产物: `outputs/train/<prefix>_<ts>/` + `reports/train_curve_<policy>.json`

## 界面可见性教训 (老倪两次反馈 "没有VLA-Touch管道啊")
- 参考应用条是 QScrollArea 横向滚动, 12+ 模板时新模板排末尾 → 用户看不到 (滚动条里被忽略)
- 规律: 新增管道/模板 → **第二行工具栏加显眼按钮** (btn_xxx = mk_btn + open_xxx 方法, 加载模板+日志引导), 同 ACT-Meta 引导/总系统处理 (open_vlatouch / open_awe 样板)
- offscreen 验证: 断言按钮存在 + open_xxx() 后节点/连线数正确

## 对话框深色 QSS (黑字看不清修复)
- TrainConfigDialog/BlockParamsDialog 原本按浅色写 (head color:#1f2328) → 深色主题下黑字黑底看不清
- 修: 共享 `_DLG_DARK_QSS` (QDialog 深底 #0d1117, QLineEdit/QSpinBox/QComboBox/QPushButton 白字 #e6edf3), 两对话框 setStyleSheet 应用
- 原则: simulink_module 内对话框一律深色主题 QSS, 别用浅色硬编码色

## 验证方法
- 双环境: 系统 python3 (PyQt5) 跑 GUI offscreen 断言; .venv (torch) 跑模型前向/eval — 分开跑
- 仓库内保留验证脚本: tools/gui/verify_20260805_gate_vla_awe.py (模板结构/gate 状态机/QSS/训练脚本导入)

## SmolVLA+LEW loss 反复原因 (老倪问过)
不是坏了, 扩散+世界模型固有特性: ①扩散每步随机采样噪声步 t (t 大 loss 天然大) ②LEW 第二路 loss 叠加 (lew_loss_weight 0.1) ③batch=1 梯度噪声大 ④LEW 独立从头训+VLM 冻结初期不稳。判断用 Scope 归一化 (前3点均值=1) 看下降斜率, 别比绝对值 (loss 口径: ACT 动作空间 MSE 大 vs SmolVLA 系扩散噪声 MSE 小)。

## 🔬 五模型对比模板 (commit 5354e70e, 31节点44连线)
"把 ACT SmolVLA smolvla+lew VLA-Touch AWE 5个模型放到一起纵向对比" — 技术选型终极画布。
- 结构: ♻共用3 (metaworld数据/对比评估Scope/推理效果对比) + ACT 7 + SmolVLA 4 + SmolVLA+LEW 5 + VLA-Touch 6 + AWE 6
- 节点索引: 0=数据, 1-7 ACT, 8-11 SmolVLA, 12-16 LEW, 17-22 VLA-Touch, 23-28 AWE, 29=Scope, 30=推理
- 连线: 5 训练 → Scope (29) / 推理 (30) 各 5 条; 各分支内部连线照抄三模型对比/VLA-Touch/AWE 模板
- **同构同列布局**: 每行一个模型, 同构模块同列垂直对齐 (视觉编码列 ResNet18/SmolVLM2/DINOv2/SigLIP 同 x, ActionHead列 5个同 x, 训练列 5个同 x)
- **列对齐验证技巧**: 加载后按节点名收集 x 坐标, `len(set(xs))==1` 断言同列 (视觉编码/训练列/Scope 列)
- 工具栏 btn_compare5 → open_compare5() (同 open_compare3 样板, 确认弹窗+加载+日志讲解 5 模型)

## ⚠️ AWE 视触觉编码纠正 (老倪纠正: "AWE 的视觉编码, 不应该是视触觉编码么?")
AWE 是**场景原生**架构 (视觉·触觉·力觉·动作场景级深度融合) → 编码节点必须叫「🖐 SigLIP **视触觉**编码」, 不是"视觉编码":
- 训练脚本 HJEPAEncoder forward 已是三路融合 (proj_vis + proj_state + proj_tactile 同层相加), 只需节点名/desc/docstring 对齐
- 连线标签: 数据→编码 "图像+力觉", 编码→潜空间 "视触觉特征" (别只写 "视觉特征")
- 改节点名必须 5 处同步: 五模型对比模板 + AWE 单模板 + 两处 layout + LIBRARY 子模块 (grep "SigLIP" 全量检查)
- metaworld **无真触觉数据** → 触觉/力觉为状态差分模拟, 节点 desc 明确标注 "⚠️ metaworld 无真触觉, 当前为状态差分模拟, 真机换 H06 力传感器" (防误读)

## 📖 node_logic 右键源码补全 (commit 42eb3835)
新模型节点必须注册 node_logic.py, 否则右键「查看/编辑节点逻辑」显示"无独立逻辑" (老倪反馈 "很多节点右键都没有源代码")。
- 本轮补 12 个: smolvlm2/dit_b/lew/dinov2/marker/interpolant/siglip/hjepa/zflow/cross_attn/train_gate/video_display
- 每个: ✏️可修改区 (参数可调, 如 DiT-B hidden/layers/freeze, H-JEPA 三层维度) + 官方源码位置注释 + 🔒框架动作 (结构节点 `return (True, "配置")`)
- 匹配坑: match_node 最长关键字匹配 — 「视频显示」「视频」会匹配 🎥 视频显示节点; 「DiT-B」「DiT」共用 dit_b 无冲突
- node_logic 框架动作要调 module 方法时 (如 train_gate) → SimulinkModule 补兼容入口 `_toggle_train_gate_ctx(name, enabled)`
- 验证: 五模型对比 31 节点零未匹配 + 12 关键节点映射 + get_node_source 含 "可修改区" + 执行不崩 + NodeLogicDialog 打开显示源码 + 旧 ACT 节点回归 (match_node 最长匹配防回归)

## 🔀 真 CrossAttention 教训 (老倪当场抓出: "为什么叫交叉注意力呢？也不是啊", commit 0cf25ed0)
假实现: 三层潜状态拼接成单 token K/V + `gates.sum()` 乘整个输出 → Q/K/V 各 1 token,
注意力退化恒等 (1×1 attention 权重恒为 1), 门控是整体标量非分层。
✅ 真实现 (CrossAttnInject):
- 每层潜状态独立投影 K/V (ModuleList, 层间不共享权重)
- Q=解码隐层, 逐层 MultiheadAttention (真交互)
- 每层输出乘各自门控 (1.0/0.1/0.01) 再残差融合
- forward 传 z_triple 元组 (torch.split 按 latent_dims 拆回), 别拼接
验证 (offscreen 13/13): 门控全0=纯残差 / z₁变化→输出变 (真注入) / 门控隔离 z₂ /
反向传播无 None grad。
⚠️ 通用铁律 (老倪架构严谨性): 名字叫 cross-attention 就必须 Q/K/V 来自不同源且多 token
交互; 门控是"分层"就必须每层独立权重独立作用, 禁止拼接后单标量。写代码前先自问
"这个实现配得上这个名字吗"。

### ✏️ 改名: 🔀 未来决策交叉注意力 (commit 059a365a, 老倪: "加个前缀表达用未来预测决策的意思")
节点名从「🔀 交叉注意力注入」→「🔀 未来决策交叉注意力」, 表达语义链:
zFlow 世界引擎"预言未来"(生成未来潜状态) → 未来决策交叉注意力"让动作决策看见预言"(K/V 注入)。
- 世界模型命名语义 (老倪问过"为什么叫世界模型"): 世界模型 = 能预测"世界接下来会怎样"的
  环境动态模型 (输入当前状态+动作 → 输出预测未来状态), 不是字面"世界的模型"; zFlow GRU
  做潜状态级未来预测, 与 LEW(帧级)/Interpolant(动作级) 同列对比预测粒度。
- 改节点名只动显示名: 保留"交叉注意力"关键字 → match_node 最长匹配仍命中 cross_attn,
  右键源码/node_logic 注册不受影响; 同步模板/布局/LIBRARY/tooltip/日志/注释 (~14 处,
  grep 旧名全量检查, 别漏 desc 里的 CrossConditionalBlock — 那是 LEW 的, 不用改)。
- 概念关系 (老倪追问"交叉注意力和世界引擎什么关系"): 二者是"生成预测"与"使用预测"的
  流水线 — 世界引擎产出未来预测, 交叉注意力是唯一把它送进动作决策的通道; 没有注入,
  预测就是算完即丢的废值。门控 1.0/0.1/0.01 = 各层未来预测对动作的影响权重 (训练注入,
  推理归零可剥离 = 它石"训练/推理可切换")。类比: 军师(世界引擎)推演战局 → 传令兵
  (交叉注意力)送情报 → 将军(动作头)决策。

## 🎨 row_bg 背景行节点 (老倪补充: "5个背景实际上是5个特殊的背景类型node, 可编辑", commit 3737c91d)
五模型对比 5 行背景 = 5 个真节点 (row_bg 类型), 不是画布装饰:
- NODE_TYPES 加 `"row_bg": {"cn": "背景行", "color": "#3a3f4b"}` + add_node icon "▤"
- SimNodeItem.paint 顶部 row_bg 分支: 整行半透明色带 (bg 色 alpha 40) + 左侧 24px 粗体
  白字模型名 + "▤ 背景行 · 右键改名/改色" 小标; **必须 return 提前退出** (不走普通节点绘制)
- SimNodeItem.h 改读 `node.get("h", DH)` (背景行高 214, 普通节点 50)
- 编辑: 右键「⚙️ 节点参数」/双击 → BlockParamsDialog; name 改大字, bg 参数自动变颜色下拉
  (QComboBox 12 预设色带 label, `_apply` 取 `currentData()`; 键名 bg/bg_color/color 触发)
- 定位: `_draw_model_rows(row_names)` 动态 add_node 5 个 (🎨 ACT..AWE, y=base_y+r*230-20,
  w=整行跨度 x0=60), `it.setZValue(1)` **低于普通节点 z=10** → 点空白命中背景行,
  点节点命中节点 (不挡交互); clear() 先 `_clear_model_rows()` 删 row_bg 再 scene.clear()
- open_compare5() 加载后调 `_draw_model_rows(["ACT","SmolVLA","SmolVLA+LEW","VLA-Touch","AWE"])`
- 顺带修: 右键菜单 QSS 原浅色白底黑字 → 深色 (#161b22 底 #e6edf3 字), 与对话框一致
- 验证 (offscreen 20/20): 5 节点生成/行 y 递增 230/5 色各异/paint 不崩/改名改色生效/
  clear 清理/双击路由 BlockParamsDialog/三模型对比无 row_bg 回归

### 🐛 row_bg 黑色块 bug 修复 (commit ea918c94, 老倪: "中间一大块黑色背景是怎么回事")
两个根因, 缺一都会黑:
1. **item 尺寸不同步 (核心)**: add_node 创建 SimNodeItem 时 w=150/h=50, 之后改 node["w"]/["h"]
   但 **item.w/item.h 没同步** → boundingRect 仍 150×50, paint 却画 2000×214 → 渲染成深色小块。
   修: `_draw_model_rows` 里改 node 尺寸后必须 `it.w = int(w); it.h = row_h - 16` (item 是渲染实体,
   node dict 只是数据)。⚠️ 通用教训: 给 QGraphicsItem 改尺寸要改 item 自身, 只改 node 字典没用。
2. **alpha 太低**: 单层 alpha=40 在深色画布 (#0a0a0f) 上≈纯黑。修: 双层绘制 — 深底
   QColor(13,17,23,120) + 色相层 alpha 90 (颜色清晰可见), 边框 alpha 200。
验证 (offscreen 10/10): item.w==node.w 且 item.h==node.h 且 zValue==1 / 整行渲染中心像素
非纯黑 (rgb 和 > 40) / clear 清理 / 三模型对比无 row_bg。

### 🐛 row_bg 大字叠字修复 (commits fa38c188/86d85fce, 老倪: "上面带颜色标出的三模型对比 + 下面白色字体的三模型对比, 重复好多")
症状: 画布上模型名文字与节点文字叠在一起, 像"重复"。
根因: row_bg 大字 (24px bold, 含 🎨 前缀, "SmolVLA+LEW" 宽达 180px) 绘制区
(x0+14 起, 宽 w-28) 与每行第一列节点 (x≥120) 文字水平重叠。
修复 (三层保险):
1. **大字区让开节点列**: row_bg 起点 `x0 = base_x - 140` (非 -60/-130); 大字绘制框
   QRectF(8, 0, 126, h) → 绝对右界 = x0+8+126 = -6 < 节点 x=120, 零重叠
2. **去 emoji + 缩小字体**: `if name.startswith("🎨 "): name = name[2:]`, 15px bold
3. **长名拆两行**: `"+" in name` → split 成两行 (SmolVLA+LEW → SmolVLA / LEW),
   每行 QRectF 高 24, y = h/2-24 与 h/2+2
⚠️ 布局偏移 off-by-one 教训: `base_x=120` 时 `x0=base_x-130=-10` (不是 -130!),
大字绝对右界 = -10+8+126 = 124 > 120 仍重叠 4px → 验证脚本必须用**实际 base_x 值**
计算 (120-140=-20, 右界 114 < 120 ✓), 别写死偏移量。
验证 (offscreen 13/15): QFontMetricsF 逐名量宽 (15px bold 拆行后每行 ≤126px) +
大字绝对右界 < 节点 x / 加载后 row_bg x==-20 / 渲染不崩 / 三模型+CICD 回归。
通用教训: 画布上"文字重复/叠字"类反馈, 先渲染出节点坐标看同一区域有无多个
绘制项 (row_bg 大字 vs 普通节点标题), 用 QFontMetricsF 量化文字宽度再定布局。

## 🐛 NODE_RUN_ACTIONS 关键字误匹配陷阱 (commit 6acd11ca, 老倪: "训练到第3个就停了/检查是否正常运行")
症状: 五模型对比 ▶运行 训练到第 3 个 (SmolVLA+LEW) 后队列停止, VLA-Touch/AWE 不启动,
无训练进程, GPU 空闲, 日志反复 "⏳ 上一个任务还在跑"。

根因: `_canvas_stage_nodes()` 用**子串匹配** NODE_RUN_ACTIONS 关键字 (采集/训练/验证/集成/
部署/推理/对比评估/Scope), 观察/控制类节点名撞关键字被误当执行环节:
- `🎥 推理效果对比` 含 "推理" → 误匹配 on_infer → 混进执行队列 (排最后) → 它执行时
  可能阻塞/报错, 队列卡在它后面, VLA-Touch/AWE 永远轮不到
- `☑ 训练开关` 含 "训练" → 误匹配 on_train → CICD 主控台 ▶运行 首个环节是开关
  (打乱流程语义)

修复: `_canvas_stage_nodes` 循环里显式排除观察/控制类节点:
```python
if "Scope" in n.get("name", ""): continue          # 原已有
if n.get("params", {}).get("video"): continue      # 🎥 视频显示 (含"推理"会误匹配)
if n.get("type") == "train_gate": continue         # ☑ 训练开关 (含"训练"会误匹配)
```

通用铁律: **新增节点类型/名称时 grep NODE_RUN_ACTIONS 关键字, 观察类节点 (video/Scope/
开关) 必须显式排除, 否则混进执行队列阻塞流程**。验证: 断言 `_canvas_stage_nodes()` 返回
恰为预期 stage 集合 (五模型=5 训练节点, 无视频无开关; CICD 主控台首个=ACT 训练)。

顺带修: `_speed` 排序字典补新 policy (`{"act":0,"smolvla":1,"smolvla_lew":2,
"vla_touch":3,"awe_zflow":4}`, 未知排 9) — 原只有 3 模型, 新模型排最后虽不致命但顺序
不直观。验证 (offscreen 9/9 + 回归): 五模型恰 5 stage / 无推理效果对比 / 无训练开关 /
排序 act→awe_zflow / CICD 无开关首环节 ACT / 三模型仍 3 policy。

诊断套路 (队列疑似卡住): ① `pgrep -f train_*` 查训练进程 ② nvidia-smi 查 GPU
(无训练进程但 GPU 忙 = 另有进程) ③ `reports/train_curve_*.json` 步数看完成到哪个模型
④ offscreen 调 `_canvas_stage_nodes()` 看队列里混了什么。
