# 2026-08-05 尾场: 5 视频对比节点 + 📄 PDF 技术选型报告节点 (commit b856a031)

需求 (老倪): 五模型对比管道「🎥 推理效果对比」之后接 5 个视频对比节点 (每模型一个),
最后接 📄 PDF 生成节点 — 报告要"科学、认真、有道理": 概况/分系统功能/接口/参数对比/
架构区别/功能分析/性价比/优劣势, 结论必须有数据支撑。

## 🎥 5 个视频对比节点
模板五模型对比升级 31→37 节点, 61 连线:
- 5 个 `("system", "🎥 视频对比 · <模型>", {"video": True, "video_policy": "act"|"smolvla"|...})`
  节点索引 31-35 (ACT/SmolVLA/SmolVLA+LEW/VLA-Touch/AWE)
- 连线: 5 训练节点 → 各自视频节点 ("rollout" 标签) + 推理效果对比(30) → 5 视频节点
- 布局新增两行: 视频对比行 (列1-5) + PDF 报告行 (列7)

### InferenceVideoDialog 参数化 (simulink_scope.py)
- 原 POLICIES 硬编码 3 模型 → 加 `POLICIES_5` (含 vla_touch/awe_zflow), 构造签名
  `__init__(self, module, policies=None, parent=None)` — `self.POLICIES = list(policies or self.POLICIES)`
- 窗口宽高/标题/提示文案全部随 `len(self.POLICIES)` 动态 (`min(1280, 240+n*220)`)
- 旧调用 `InferenceVideoDialog(self)` 不传 policies → 默认 3 模型, 向后兼容

### on_infer_video(policy=None) 自动探测 (simulink_module.py)
```python
if policy:   # 单模型视频节点 → 只放该模型
    policies = [(policy, self._policy_display(policy), self._policy_color(policy))]
else:        # 自动探测: 画布有 VLA-Touch/AWE 训练节点 → 5 模型, 否则 3 模型
    names = " ".join(n.get("name","") for n in self.nodes)
    policies = (InferenceVideoDialog.POLICIES_5 if ("VLA-Touch" in names or "AWE" in names)
                else InferenceVideoDialog.POLICIES)
```
- on_node_activated 视频分支: `self.on_infer_video(policy=params.get("video_policy"))`
- 静态助手 `_policy_display` / `_policy_color` (act/smolvla/smolvla_lew/vla_touch/awe_zflow 5 套)

## 📄 PDF 技术选型报告节点 (pdf_report 类型)
- NODE_TYPES 加 `"pdf_report": {"cn": "PDF报告", "color": "#1f6feb"}` + add_node icon "📄"
- NODE_RUN_ACTIONS 加 `("PDF", "on_pdf_report")` → ▶运行 尾段自动生成报告 (队列 5训练+PDF=6 stage)
- node_logic 注册 `pdf_report` (match "PDF"), 框架动作调 `module.on_pdf_report()`
- LIBRARY 系统组加 "📄 PDF 技术选型报告" 条目
- on_pdf_report(): 画布 flow 存 `reports/_flow_snapshot.json` → subprocess
  `.venv/bin/python tools/generate_report.py --flow ...` → glob 找最新
  `五模型对比技术选型报告_*.pdf` → 日志返回文件名

## 🧩 报告引擎 tools/generate_report.py (核心交付, 专业工程师视角)
11 章: ①实验概况 ②系统全貌(Simulink拓扑) ③分系统功能分析 ④接口说明 ⑤参数对比
⑥架构区别 ⑦功能分析(能力矩阵) ⑧性价比分析 ⑨优势劣势总结(数据支撑) ⑨.1推理视频对比 → 结论

数据底座 (科学性的关键):
- `MODELS` OrderedDict 5 模型注册表: name/arch/category/world_model/params_m/hidden/layers/
  freeze/data_need/train_cost/gpu_mem/edge/strengths/weaknesses/dep — 报告所有表格数据来自这里
- `SUBSYSTEMS` 6 子系统 × 5 模型实现映射; `MODULE_IO` 模块输入输出表
- `load_curves()` 缺数据容错 (curve=None → 表格显示 "无曲线数据", 不崩)
- **Scope 归一化** `scope_normalize(curve)`: 前3点均值=1 看下降斜率 — loss 口径不同
  (ACT 动作MSE 大 vs SmolVLA 系扩散噪声MSE 小), 绝对值不可横比
- `curve_stats`: first/last/drop_pct/jitter_pct (数据支撑的收敛/波动指标)
- `score_model` 加权选型矩阵 (Z-MAX 场景权重): 收敛20% 世界模型15% 触觉20% 部署15%
  吞吐10% 显存10% 数据5% 视频5% → total 0-10; 无数据维度给中性 5
- `conclusion(score_map, curves)`: 按综合分排名 + 归一化下降率排序 → 数据支撑的选型结论
- 图: `plot_curves` 左原始/右Scope归一化双图; `plot_scores` 评分柱状图;
  `make_montage` 各模型 rollout 首帧横向拼图 (PIL)

### ⚠️ 中文渲染两坑 (必踩, 否则中文方块)
1. **reportlab**: 默认 Helvetica 无中文 → 必须先注册 Noto CJK:
   ```python
   pdfmetrics.registerFont(TTFont("NotoSansCJK", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", subfontIndex=0))
   ```
   ⚠️ .ttc 集合字体必须带 `subfontIndex=0`; 且**所有 ParagraphStyle 的 fontName
   和 TableStyle 的 ("FONT", ...) 都要用注册名**, 漏一个就那片变方块。
2. **matplotlib**: `font_manager.fontManager.addfont(ttc路径)` + 
   `rcParams["font.sans-serif"] = ["Noto Sans CJK SC", ...]` + `axes.unicode_minus=False`
   (fc-list 可查系统 CJK 字体; WSL 下 /usr/share/fonts/opentype/noto/ 必有)

### 验证套路 (PDF 类任务)
- 生成冒烟: `.venv/bin/python tools/generate_report.py --out /tmp/x.pdf`
- 内容验证: `.venv/bin/python -c "import fitz; doc=fitz.open(...); full=''.join(p.get_text() for p in doc);
  [k in full for k in 章节关键词]"` — 中文提取 OK 说明 reportlab 字体注册成功
  (zlib 手动解流提取不到 reportlab 的 CID 编码文本, 用 PyMuPDF)
- 模板结构 offscreen: 37 节点/5 视频/PDF 类型/连线≥61/PDF 入边 7 (Scope+推理+5视频)/
  ▶运行队列 6 stage 无视频混入

## 🐜 gitignore 铁律 (老倪: 大文件不提交)
reports/ 下 rollout 帧/视频/报告 PDF 全是被 git 跟踪的大文件 (历史已提交 194MB)。
新增规则防继续膨胀:
```
reports/rollout_*/
reports/rollout_*.mp4
reports/_*.png
reports/_*.json
reports/五模型对比技术选型报告_*.pdf
```
规律: 训练/推理产物 (rollout 帧, mp4, 报告 PDF) 一律不进库; 曲线 json 可留作数据支撑。
