# 画布数学化: 数据字典 Model Tree + 状态空间评估 (2026-08-12 老倪)

画布从"流程图工具"升级为"控制系统数学化工具": 右侧数据字典(参考 MATLAB Workspace)
+ 节点参数标定 + 状态空间分析 + 稳定性评估 + 工程图输出。

## 右侧数据字典面板 (tools/gui/model_tree.py)

`ModelTreeDock(QDockWidget)` — 下拉菜单 4 视图:
- 📚 数据字典: 树 = 系统参数(dt/节点数) + 按行分组节点 + 参数叶子(名=值)
- ⚙️ 参数标定: 同树, 双击参数叶子 → QInputDialog → 写回 node params + `module._refresh_node(node)`
- 🧮 数学分析: 主链路 → G(s)=N(s)/D(s) → 状态空间 (A,B,C,D 可控标准型) → 极点/零点/稳定性
- 🎛 状态空间设计: 节点→控制角色映射(感知链=C/左脑=K/右脑=转移/状态机=硬约束) +
  谱半径 + 李雅普诺夫(P>0 且 AᵀP+PA<0) + 可控/可观测 + 复平面图(QPainter 手绘 PoleZeroPlot)

集成: simulink_module._build 里 `ModelTreeDock(self)` + addDockWidget(Right);
load_flow_file 结尾 `model_tree.refresh()`。角色映射按节点名关键词(左脑/右脑/接触判定/➤等)。

## 状态空间评估 (tools/eval_state_space.py)

`BRAIN_CKPT=<dir> .venv/bin/python tools/eval_state_space.py [seeds]` → reports/eval_state_space.json
九指标:
1. L2增益: 左脑静态映射 Lipschitz 实测(obs±δ → ||Δa||/||δ|| max/mean)
2. BIBO: 随机有界 obs → 动作/next_obs 范数有界
3. 自回归谱半径 ρ: 右脑 next_obs 多步预测误差增长率(<1 收敛)
4. 状态机覆盖: 6阶段可达 + 成功率(真实环境 rollout, 含 render 保持轨迹一致)
5. 李雅普诺夫势能: 各阶段 V(接近 ||hand-peg||²/转移 ||peg-hole||²) 首尾下降率
6. 谱范数 Lipschitz: 权重 σ_max 乘积上界
7. (占位)潜空间频谱
8. 接触分离度: 未接触 vs 接触 contact 均值差 + 震荡区(0.3~0.7)占比
9. 动作平滑度: 动作差分 ||Δa|| 均值/峰值 + 超调(>0.5)占比

三分析模块(用户点名): spectral_norm_analysis(逐层 σ_max + Π乘积) /
gru_gate_analysis(门控谱半径收缩) / force_limit_analysis(饱和 [-0.6,0.6] → ζ=1/(1+超调))。

## 工程图 (tools/plot_state_space.py, matplotlib Agg)

- 图1 GRU极点图: 潜状态特征值 Z 平面(单位圆内=收敛)
- 图2 误差衰减曲线: 状态机 e(t)=||hand-peg|| 多增益对比(0.5/1.0/2.0/3.0 → 临界阻尼)
- 图3 潜空间流形轨迹: 预测链 PCA(eigh 前 2 主成分) + contact 着色
输出 reports/eval_*.png → 复制 C 盘 + cmd start 打开。

## 坑 (2026-08-12 实测)

- **matplotlib 中文乱码**: matplotlib 字体缓存无 WenQuanYi(有 Noto CJK)。
  修复: `font_manager.addfont("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc")` +
  `rcParams["font.sans-serif"] = ["WenQuanYi Micro Hei", "Noto Sans CJK SC", "DejaVu Sans"]`。
  .venv 有 matplotlib 3.11(无头 Agg); GUI 系统 python3 无 matplotlib — 图表脚本必须走 .venv。
- **画布节点 id 加载后被重映射**: load_flow_file 把 json id(如 ans1)换成随机 nxxx。
  验证/查找节点**按 params 键找**(`next(n for n in m.nodes if n.params.get("spectral_norm"))`),
  别按 json id 找 — 按 id 会 None。
- **右脑 RightBrainWM 实际是 MLP 无 GRU**: 结构 = enc(Linear 43→256, 256→256) +
  pred_next(256→39) + contact_head(256→1)。设计文档/汇报里说 GRU 是概念表述;
  评估/画图求"潜状态转移矩阵"用 enc 方阵(256×256)特征值, 别找 weight_hh_l0。
- 模型成功率的 seed 敏感: 同一 checkpoint 每次评估成功率波动大(25%→0%),
  报告成功率用多 seed(≥4)取均值, 单 seed 会误导。
- 训练产物 root 600 权限 → 评估脚本读不到 → 先 chmod 644(记忆铁律)。
- LeftBrainMLP(train_full_pipeline 版)无 obs_dim 属性 → 从首个 in_features 推断。

## GUI 集成 (simulink_module.py)

- 工具栏 `mk_btn("🔍 Z 分析", ..., self.on_z_analysis, "#d29922")` → 一键全面评估
  (右侧面板切状态空间视图 + 跑 eval + 飞书预告)。
- 画布节点: 📊 模型评估(状态空间, params.eval_state_space) / 🧮 谱归一化(spectral_norm) /
  🧮 GRU门控(gru_gate) / 🧮 力幅值限幅(force_limit) / 📄 稳定性评估PDF(eval_report_pdf) —
  双击分发 → on_eval_state_space / on_z_analysis / on_eval_report_pdf。
- 飞书文本报告: `_feishu_send_text_async(text)` 后台线程发 text 消息(独立于文件发送)。
- 训练/推理完成自动发飞书报告(_done 回调 stage=="train" + left_right)。

## 稳定性评估 PDF 报告 (2026-08-14 老倪: 每图详释 + 汇总报告 → PDF 节点 → 飞书)

`tools/gen_report_state_space.py`(.venv 跑, reportlab) → `reports/状态空间稳定性评估报告_<ts>.pdf`。

**八章节结构** (每图=原理+公式+数据+图+解读, 老倪要求"每个图要有详细的解释,是个报告"):
1. 摘要与结论(verdict 驱动: 稳定/部分稳定, 附解释)
2. 状态空间建模 — X=[X_obs(43D), X_latent, X_sm(6阶段)] 三层 + 连续转移方程
   (左脑 a=f_MLP(obs) / 右脑 [next_obs,c]=f_WM(obs,a) / 环境 obs'=Env) + 离散转移(contact+阈值)
3. 图1 GRU 极点图 — 公式 ρ(W)=max|λ_i| + 单位圆判据 + 数据 + 解读
4. 图2 误差衰减 — 二阶系统 Mẍ+Bẋ+Kx=0, ζ=B/(2√MK) + 多增益对比 + 临界阻尼解读
5. 图3 流形轨迹 — PCA 投影 P=X_c·W_2 公式 + 解读
6. 九指标表 — 每行: 指标/公式/数据/判定(全来自 eval_state_space.json)
7. 三模块 — 谱归一化 Πσ_max / GRU门控 ρ(W_hz) / 力幅值限幅 ζ(饱和=非线性阻尼)
8. 结论与调优建议 — 一句话总结(李雅普诺夫+谱归一化+GRU门控+力幅值限幅) + 未达标项针对性建议

**技术点**:
- 字体: reportlab TTFont 注册 `/usr/share/fonts/truetype/wqy/wqy-microhei.ttc`(TrueType; Noto ttc 不支持 — 见 SKILL.md 主文 PDF 中文坑); 全 TBL 用 Paragraph(带 <b>/&lt; 转义); 中文括号/希腊字母(ρ/ζ/λ)直接 unicode 可显示
- 图嵌入: `Image(path, width=140mm, height=w*0.95)` — 图缺失跳过不报错(print ⚠ 缺图)
- **f-string 里不能有反斜杠/嵌套引号**: GRU 门控数据行曾 `chr(961)`+转义引号 SyntaxError → 先算 `_gstr = ", ".join(f"{k}:ρ={v.get('rho',0):.4f}" ...)` 再 f-string 引用
- **验证 PDF 内容: fitz 只在 .venv**(系统 python3 无 fitz) → 验证脚本里用 subprocess 调 `.venv/bin/python -c "import fitz..."` 断言页数/图数/中文标题; 别在主验证脚本 import fitz(会 ModuleNotFoundError FAIL)
- 画布节点 📄 稳定性评估 PDF(id=dbpdf, 交付行 x=1150, 连线 dbev→dbpdf 评估完成→出报告) + on_node_activated 分支 1.78 → `on_eval_report_pdf`(worker 跑生成器 → glob 最新 PDF → `_feishu_send_file_work(pdf,"pdf",标题)` 发飞书)
- **on_eval_state_space worker 成功尾部自动串 PDF**: subprocess 跑 gen_report_state_space.py → glob 最新 → 发飞书文件 → 摘要字符串带 PDF 文件名(老倪"在飞书等报告" — 评估完成即收到 PDF)
- 用户验收反馈("分析报告没有图啊"→"啊 有图"): 先查 PDF 内嵌图(用 .venv fitz 数 get_images + 像素非白占比)再回 — 图在只是用户没看到; 用户确认前别改代码
