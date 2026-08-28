# 七模型 PDF 报告修复实录 (2026-08-07)

老倪连续反馈 5+ 轮 PDF 问题, 每轮都是"某个图/某行文字乱码或重叠"。根因分四层, 全修完才稳定:

## 层级 1: matplotlib 图片中文乱码 — 每个绘图脚本独立配字体
报告图片不是 generate_report.py 画的, 是**独立脚本预生成 PNG 再嵌入**:

| 脚本 | 图片 | 症状 |
|---|---|---|
| `tools/gen_report_figs.py` | model_arch.png / pipeline.png / training_flow.png | 系统全貌图全中文乱码 |
| `tools/gen_theory_figs.py` | reports/figs/theory/theory_{act,smolvla,lew,vla_touch,awe}.png | 10.1-10.5 理论图乱码 |

两脚本都只有 `import matplotlib; matplotlib.use("Agg")`, **零字体配置** → 默认 DejaVu Sans 无中文 glyph → 方块。
修复(两脚本各自加, 与 generate_report._cfg_cjk 同款):
```python
from matplotlib import font_manager
for _cand in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
              "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"):
    if os.path.exists(_cand):
        try: font_manager.fontManager.addfont(_cand)
        except Exception: pass
matplotlib.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "Noto Serif CJK SC", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False
```
验证: 重跑脚本后 PNG mtime 变新 + `findfont("Noto Sans CJK SC", fallback_to_default=False)` 返回 Noto 路径 + 画中文图 warnings 无 "Glyph"。

**节奏教训**: 老倪逐章报乱码 (系统全貌 → 10.1 → 10.2 → 10.3 → 10.4 → 10.5) = 他看的是**飞书里旧版 PDF**。修完立即重发飞书 + 标版本号 (v3/v4/v5), 并说明"你看的是旧版, 新版已发"。

## 层级 2: reportlab Table 长文本不换行 → 窄列溢出重叠
症状 (老倪原话): "生成方式 回归式 (deterministic regression) 扩散式 (denoisistic regression)..." 多列文本挤成一团; "训练策略 backbone 冻结 (pretrained) SmolVLM2..." 同; "第9章 优势劣势 这些字体很多都重合了"。

根因: reportlab `Table` 对**普通 str cell 不换行**, 窄列 (20mm) + 长文本 (30-40 字) 横向溢出压到相邻列。与 emoji/下标重叠 (已有 _clean 修复) 是**两个独立根因**。

修复 — TBL 全 cell 走 Paragraph + CJK 换行:
```python
from reportlab.lib.styles import ParagraphStyle
_cell_st = ParagraphStyle("tblcell", fontName=FONT, fontSize=fs,
                          leading=max(fs * 1.3, 9), wordWrap="CJK")
_hdr_st = ParagraphStyle("tblhdr", fontName=FBOLD, fontSize=fs,
                         leading=max(fs * 1.3, 9), wordWrap="CJK")
tbl_rows = []
for ri, row in enumerate(rows):
    st = _hdr_st if (header and ri == 0) else _cell_st
    tbl_rows.append([Paragraph(c, st) if isinstance(c, str) else c for c in row])
t = Table(tbl_rows, colWidths=widths, repeatRows=1 if header else 0)
# ⚠️ 删掉 TableStyle 的 ("FONT", ...) 命令 — Paragraph 自带 fontName, 命令对它无效
```
改完全部表受益 (7 模型后第 6/7/9 章都是宽表)。

## 层级 3: 模型数同步 (五→七)
- `generate_report.MODELS` 加 2 条目 (每模型 **strengths/weaknesses 成对**, 老倪铁律)
- 第 6 章架构区别表头硬编码 5 列 → 8 列 (widths 20mm×8)
- 第 7 章能力矩阵 caps dict 每个能力加 expert_mlp/expert_policy 评分
- gen_report_figs.py 的 MODELS 也要加 (图是独立数据源!) — 7 卡片 figsize 11×17.5, 字号 17/12.5/9.5 (旧 13/9.5/6.6 被批"文字很小不协调")
- 图比例变后 PDF 嵌入尺寸同步: `Image(_fig_arch, width=150*mm, height=238*mm)` (保持 11:17.5, 175×200 会变形)
- **Python 字符串换行坑**: patch 时写 `\n` (单反斜杠), 写成 `\\n` 会显示字面反斜杠+n

## 层级 4: 分数/文案要有依据
- 8.1 评分公式明细: 8 维公式逐条 + 权重 + 维度得分明细表 (读者可复算) — 老倪"对比分数要有公式对应"
- 7.1 能力评分依据: 6 能力逐条打分规则 — 老倪"7/10 5/10 这些啥意思"
- 封面步数动态化: 从 curves 读 `max(非 expert_mlp 曲线末步)` — 老倪"你是50步训练么?" (照抄旧模板写死 50 步被抓)

## 验证方法 (可复用)
```python
import fitz, re
doc = fitz.open(pdf); txt = "".join(p.get_text() for p in doc)
# 1. 乱码: 0 个 U+FFFD/???
assert txt.count("\ufffd") + txt.count("???") == 0
# 2. 文本断言宽松匹配 (标题双空格提取变单空格!):
def has(frag): return re.search(r"\s*".join(re.escape(c) for c in frag), txt) is not None
# 3. 视觉重叠量化: words 带 bbox, 两两交集面积 >30% 较小面积 = 重叠对, 断言 0
words = page.get_text("words")  # (x0,y0,x1,y1,word,...)
# 4. 图内文字不在 PDF 文本层 — 别用文本断言查图内容 (如"七模型架构对比"在 PNG 里)
```
环境: `.venv/bin/python` (有 matplotlib/reportlab/fitz); 系统 python3 有 PyQt5 无 matplotlib — 验证 GUI 用系统 python3, 验证报告用 .venv, 别混。
