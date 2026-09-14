# 2026-08-05 VLA-Touch / AWE / 五模型对比 / row_bg 背景行 会话

(commit d815fafb → ea918c94) 老倪需求: 参考 VLA-Touch 项目 + 它石 AWE 架构,
新增管道纵向对比不同模型 (技术选型)。核心教训 = 机制必须真 (老倪逐条质疑)。

## 1. 新模型管道接入模式 (VLA-Touch / AWE 共用套路)

- 独立训练脚本 `tools/train_<policy>.py` (不依赖 lerobot_train):
  - 输出 `action_loss:xxx` 行 → GUI `_parse_loss_curve(prefer_action=True)` 直接吃
  - checkpoint 结构必须 `<ckpt>/<step>/pretrained_model/` (compare_models.find_ckpt 的 glob `*/pretrained_model` 兼容)
  - 曲线落盘 `reports/train_curve_<policy>.json` (Scope/对比评估数据源)
- on_train 分支: policy 判 4 路 (act/smolvla/smolvla_lew/其他), 新增 vla_touch + awe_zflow
  → `cfg_path=None` 跳过 config 生成 (tmp_cfg 判 None), 独立 `_run_cmd` 分支
- 训练脚本通用坑:
  - 视觉编码器 (DINOv2/SigLIP) 不可用自动回退 state-only: `vis_dim=0` 时模型结构固定,
    forward 里 vis_feat=None 补零 `torch.zeros(b, vis_dim)` — 结构与训练一致, 评估/无网安全
  - 触觉模拟 = 状态差分 `d[:, :3]*10 + 力范数*5`; 维度 = min(state_dim,3)+1,
    **测试数据 state_dim 必须匹配 tactile_dim** (2D state → tac 3D 会撞模型 4D 输入)
  - 模型前向测试 DEVICE 必须一致: CPU 建模型 → `cm.DEVICE='cpu'`, 否则 mat1 cuda/cpu 冲突
  - `HF_HUB_OFFLINE=1` 强制回退 state-only, 冒烟测试不卡下载

## 2. 老倪架构严谨性纠正 (最重要)

### 假 CrossAttention → 真 CrossAttention (train_awe_zflow.py CrossAttnInject)
- 假实现: 三层潜状态**拼接成单 token** K/V + `gates.sum()` 乘整个输出 →
  1×1 attention 权重恒为 1, 退化成恒等, 门控是整体标量不是分层
- 真实现: `proj_kv = nn.ModuleList` 每层独立投影 K/V token (层间不共享) →
  Q=解码隐层 → 逐层 MultiheadAttention → 每层输出乘各自门控 → 残差融合;
  forward 传 z_triple 元组 (`torch.split(z_future, latent_dims, dim=-1)` 拆回三层)
- 验证方法 (offscreen 6 项): 门控全 0 = 纯残差 / z₁ vs z₂ 注入结果不同 /
  单层 z 变化影响输出 / 门控隔离 (只开 z₁ 时 z₂ 变化不影响) / 反向无 None grad
- **教训: 注释写"分层 K/V 注入"代码就得真是分层 K/V 注入**, 老倪会看实现。

### AWE 视觉编码 → 视触觉编码 (老倪: "AWE的视觉编码不应该是视触觉编码么")
- 场景原生架构 = 视觉·触觉·力觉·动作 场景级深度融合, 不是纯视觉
- SigLIP 节点名/desc/连线全改: `🖐 SigLIP 视触觉编码`, 连线标签 `图像+力觉`/`视触觉特征`
- 实现 HJEPAEncoder 本来就是三路融合 (proj_vis+proj_state+proj_tactile 同层相加),
  改 docstring/注释对齐语义即可 — **命名必须先对齐架构语义再写代码**

### metaworld 无真触觉 (老倪: "metaworld数据有触觉数据么")
- metaworld 只有 state/action/image, **无触觉/力觉通道**
- 触觉/力觉 = 状态差分模拟 (占位), desc 必须标注 `⚠️ metaworld 无真触觉,
  力觉为状态差分模拟, 真机换 H06`; 节点 desc 五模型模板/AWE 单模板/LIBRARY 三处都要标
  (漏一处老倪就会看到不一致)

## 3. 五模型对比模板 (31 节点 44 连线)

- ACT 7 + SmolVLA 4 + SmolVLA+LEW 5 + VLA-Touch 6 + AWE 6 + ♻数据/Scope/推理
- 同构模块同列垂直对齐: 视觉编码列 / 动作生成列 / 世界模型列 / ActionHead列 / 训练列
- 验证列对齐: `by_name` 分组取 x 坐标, `len(set(xs)) == 1`
- 5 训练节点 policy 透传 (act/smolvla/smolvla_lew/vla_touch/awe_zflow), 全部 → Scope
- 工具按钮 `btn_compare5` → `open_compare5()`

## 4. row_bg 背景行节点 (黑色块 bug 复盘)

需求演进: 画布装饰 → 老倪补充"是5个特殊的背景类型node, 可编辑/改名/改色" → 真节点

- 新类型 `row_bg` (NODE_TYPES + add_node icon 字典 + SimNodeItem.paint 专用分支)
- **黑色块根因 (关键 bug)**: `add_node` 创建 SimNodeItem 时 `self.w=150/h=DH=50` 固定;
  之后改 node 字典 `n["w"]/n["h"]` 但**不同步 item.w/item.h** → boundingRect 仍 150×50,
  paint 却画 2000×214 → 渲染成深色小块。修复: 插入后 `it.w=int(w); it.h=row_h-16`
- 深色画布 (#0a0a0f) 上 alpha=40 ≈ 黑 → 双层: 深色底 (13,17,23,120) + 色相层 (color,90)
- z=1 低于节点 z=10 不挡点击 (点空白命中背景行, 点节点命中节点)
- 编辑: BlockParamsDialog 的 bg 参数 → QComboBox 12 预设色 (itemData 存 hex),
  `_apply` 里 `isinstance(w, QComboBox)` 取 `currentData()`; name 行内编辑
- 清理: `_clear_model_rows` 遍历 nodes 删 row_bg (真节点随 nodes 持有)

## 5. node_logic 注册 (右键源码)

- 新增模型节点**必须注册 node_logic.py**, 否则右键显示"无独立逻辑" (老倪: "很多节点右键都没源代码")
- `_reg(key, matches, doc, fn)`, match_node 最长关键字匹配
- 每个逻辑: ✏️可修改区 (参数可调) + 官方源码位置注释 + 🔒框架动作 (结构节点返回 (True, 配置))
- 训练开关需 `_toggle_train_gate_ctx(name, enabled)` 框架动作 (simulink_module 补方法)
- 五模型对比 31 节点验证: 零未匹配 + 12 关键映射断言 + get_node_source 可取 + 执行不崩
- 模型实现改了, node_logic 注释必须同步 (老倪贴源码核对)

## 6. UI 展示教训 (本会话第二次踩)

参考应用条是横向滚动条, 新模板排末尾 → 老倪"没有VLA-Touch管道啊" →
**新管道必须加显眼工具栏按钮** (btn_vlatouch/btn_awe/btn_compare5, 同 ACT-Meta/总系统处理)。
Rule: 任何新模板 = 工具栏入口 + 参考应用条目双份。

## 7. 验证环境拆分

GUI 部分 (PyQt5) 用系统 python3 offscreen; 模型前向 (torch) 用 .venv/bin/python。
一个验证脚本里 subprocess 调 .venv 跑模型, 主脚本系统 python 跑 GUI。
