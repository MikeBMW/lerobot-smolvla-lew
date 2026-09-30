# PDF 报告: 七模型扩展 + 图片中文乱码全修 + 表格换行 (2026-08-07)

承接 2026-08-05-pdf-report.md。本次五模型→七模型（+MLP蒸馏 expert_mlp +官方专家 expert_policy），
老倪连续 4+ 次报图片乱码，根因都是同一类：**matplotlib 字体配置只加在了一个脚本里**。

## 1. ⚠️ 铁律: 每个 matplotlib 绘图脚本都要单独配 Noto CJK

`generate_report.py` 有 `_cfg_cjk()`，但**兄弟脚本没有**：
- `tools/gen_report_figs.py` → reports/figs/{pipeline,model_arch,training_flow}.png（系统全貌图乱码）
- `tools/gen_theory_figs.py` → reports/figs/theory/theory_{act,smolvla,lew,vla_touch,awe}.png（10.1-10.5 全乱码）

`_cfg_cjk()` 不是全局生效的——**每个生成 PNG 的脚本入口都要贴一份**：
```python
from matplotlib import font_manager
for _cand in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",):
    if os.path.exists(_cand):
        font_manager.fontManager.addfont(_cand)
matplotlib.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "Noto Serif CJK SC", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False
```
修完必须**重新跑生成脚本**（旧 PNG 不会自动更新），再重生成 PDF 重发飞书。
验证：`findfont("Noto Sans CJK SC")` + offscreen 画中文图捕获 `Glyph ... missing` 警告 = 0。

## 2. reportlab Table 单元格不换行 → 窄列文本溢出重叠

普通 str cell 在 reportlab Table 里**不换行**，列宽 20mm + 长文本（category/freeze 英文括号串）
→ 横向溢出到相邻列，视觉上"字体重复/重叠"（老倪报过 生成方式行、训练策略行）。

修复（TBL 统一处理，全报告所有表受益）：
```python
from reportlab.lib.styles import ParagraphStyle
_cell_st = ParagraphStyle("tblcell", fontName=FONT, fontSize=fs,
                          leading=max(fs*1.3, 9), wordWrap="CJK")
_hdr_st  = ParagraphStyle("tblhdr",  fontName=FBOLD, fontSize=fs, ...)
tbl_rows = [[Paragraph(c, _hdr_st if (header and ri==0) else _cell_st)
             if isinstance(c, str) else c for c in row] for ri, row in enumerate(rows)]
```
- 表头也走 Paragraph（FONT TableStyle 命令对 Paragraph cell 无效，用 ParagraphStyle 的 fontName 控制加粗）。
- CJK wordWrap 会把英文长词拆行 → fitz 提取文本时片段被换行拆开，**验证断言要用宽松匹配**：
  `re.search(r"\s*".join(re.escape(c) for c in frag), txt)`。

## 3. 模型数增长 → 硬编码列表要同步（KeyError/缺列）

MODELS 从 5 → 7 后，以下**硬编码 5 模型**的地方全炸过：
- 第 7 章能力矩阵 `caps`：每个能力 dict 只有 5 键 → `vals[p]` KeyError。
- 第 6 章架构区别表头 + TBL widths 列数（5 列 → 7 列，20mm×8）。
- `score_model` 的 `mem` 档位 dict（补 expert_mlp/expert_policy: 0.5）+ 数据需求 dict 加 `"无": 9.5`。
- MODELS 新条目必须**字段齐全**（含 strengths/weaknesses 成对——第 9 章表用）。
- 封面标题/副标题别写死"五模型"。

## 4. 评分公式要写进报告（老倪: 对比分数要有公式对应）

8.1 节：每维度一行公式 + 权重 + 维度得分明细表（模型×8维×综合，读者可复算）：
- 收敛性 = min(10, 3+归一化下降率%/12) · 吞吐 = min(10, 4+1.8·log₁₀(step_s+1))
- 显存 = max(3, 10−1.2×档位) · 世界模型 8.5/4.5 · 触觉 9.0/4.0 · 边缘 9.0/5.5
- 数据 无9.5/低9/中7.5/高5.5/很高4 · 视频 6.5+(有帧+1.5)
- 权重从 `next(iter(score_map.values()))["weights"]` 取（score_model 返回里带，模块级无 W）。

## 5. rollout_have 探测（build_pdf 视频证据分）

build_pdf 里 rollout_have 探测默认找 `rollout_{policy}/`，expert_mlp/expert_policy 的帧在
`rollout_mlp/` `rollout_expert_full/`（与 InferenceVideoDialog._dir_map 同款映射），
不映射 → 视频证据分少 +1.5。7 模型全映射后 rollout 证据 7 个齐。

## 6. 7 视频对比 + 报告 + 飞书（纯 CPU，不碰训练）

gen_7model_report.sh 模式（ffmpeg + reportlab，零 GPU）：
1. 7 模型各从 rollout 帧合成 mp4：`ffmpeg -framerate 20 -pattern_type glob -i "$d/frame_*.png" -vf scale=320:240`（帧命名 frame_0000.png 0 基，固定宽度字典序 OK）。
2. 7 宫格 xstack：`xstack=inputs=7:layout=0_0|320_0|640_0|0_240|320_240|640_240|320_480`（3列×3行末行居中）。
3. build_pdf（.venv python）→ 发飞书（file_type=stream 视频 / pdf 报告，CHAT=FEISHU_REPORT_CHAT_ID）。
4. 全程 CPU；开始/结束 `pgrep -f lerobot_train` 确认训练未受影响。

## 7. 验证方法

- fitz 提取文本断言章节关键词 + 无乱码（U+FFFD/??? 计数 0）+ 无跨模型粘连
  （`re.findall(r"deterministic regression\)\s*扩散式", txt)` 为空）。
- 图内文字（PNG 嵌入）**不在 PDF 文本层**——断言"七模型架构对比"会误失败，改断言文本层标题。
- pdftotext 未安装 → 用 `.venv/bin/python -c "import fitz"`（.venv 有 PyQt5 之外还有 fitz/matplotlib/reportlab）。
- 两个环境分工：.venv（matplotlib/reportlab/fitz）跑报告；系统 python3（PyQt5）跑 GUI offscreen 验证。
