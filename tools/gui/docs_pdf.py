#!/usr/bin/env python3
"""帮助文档 → PDF 导出 (2026-08-12 老倪: 帮助文档要有 PDF 导出功能)
reportlab 自动分页 + 文泉驿微米黑 TTF (TrueType 轮廓 — Noto CJK 是 CFF, reportlab 不支持)
用法: .venv/bin/python docs_pdf.py <input.md> <output.pdf> -> exit 0/1
"""
import os, re

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, Preformatted)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

_WQY = "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"
_FONT = "WQY"


def _ensure_font():
    """注册文泉驿微米黑 (TrueType, reportlab 可用)"""
    try:
        pdfmetrics.getFont(_FONT)
    except Exception:
        try:
            pdfmetrics.registerFont(TTFont(_FONT, _WQY, subfontIndex=0))
        except Exception:
            pass
    return _FONT


def _esc(t):
    """markdown 符号 → HTML 安全文本 (粗体/行内代码/链接降级为纯文本, 去 emoji)"""
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"`(.+?)`", r"\1", t)
    t = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", t)
    t = re.sub(r"!\[(.+?)\]\(.+?\)", r"\1", t)
    # 🐛 2026-08-12: emoji 在 WQY 无字形 → 渲染空字符/方块 → 剥离
    t = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200d]", "", t)
    return t


def md_to_pdf(md_path, pdf_path):
    """markdown 文件 → PDF (轻量解析: 标题/列表/段落/代码块/表格, reportlab 自动分页)"""
    try:
        if not os.path.exists(_WQY):
            return False, f"缺中文字体: {_WQY} (apt install fonts-wqy-microhei)"
        _ensure_font()
        with open(md_path, encoding="utf-8") as f:
            lines = f.read().splitlines()

        styles = getSampleStyleSheet()
        base = styles["BodyText"].clone("Base", fontName=_FONT, fontSize=9.5,
                                        leading=14, spaceAfter=6, textColor=colors.HexColor("#1f2328"))
        h1 = styles["Heading1"].clone("H1", fontName=_FONT, fontSize=16,
                                      leading=20, spaceBefore=10, spaceAfter=6, textColor=colors.HexColor("#0d1117"))
        h2 = styles["Heading2"].clone("H2", fontName=_FONT, fontSize=13,
                                      leading=17, spaceBefore=8, spaceAfter=4, textColor=colors.HexColor("#0d1117"))
        h3 = styles["Heading3"].clone("H3", fontName=_FONT, fontSize=11,
                                      leading=15, spaceBefore=6, spaceAfter=3, textColor=colors.HexColor("#0d1117"))
        code = styles["Code"].clone("Code", fontName="Courier", fontSize=7.5, leading=10,
                                    backColor=colors.HexColor("#f6f8fa"), borderPadding=4)
        li = styles["BodyText"].clone("Li", fontName=_FONT, fontSize=9.5, leading=14,
                                      spaceAfter=3, leftIndent=12, bulletIndent=4)

        story = []
        in_code, code_buf, rows = False, [], []
        for raw in lines:
            line = raw.rstrip()
            if line.strip().startswith("```"):
                if in_code:
                    story.append(Preformatted("\n".join(code_buf), code))
                    code_buf, in_code = [], False
                else:
                    in_code = True
                continue
            if in_code:
                code_buf.append(line)
                continue
            if line.strip().startswith("|") and line.strip().endswith("|"):
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                    continue
                rows.append(cells)
                continue
            if rows and not line.strip().startswith("|"):
                story.append(_table(rows))
                rows = []
            m = re.match(r"^(#{1,3})\s+(.*)", line)
            if m:
                story.append(Paragraph(_esc(m.group(2)), {1: h1, 2: h2, 3: h3}[len(m.group(1))]))
                continue
            m = re.match(r"^[-*]\s+(.*)", line)
            if m:
                story.append(Paragraph(_esc(m.group(1)), li, bulletText="•"))
                continue
            if re.match(r"^\s*---+\s*$", line):
                story.append(Spacer(1, 4))
                continue
            if line.strip():
                story.append(Paragraph(_esc(line), base))
        if rows:
            story.append(_table(rows))
        if code_buf:
            story.append(Preformatted("\n".join(code_buf), code))

        os.makedirs(os.path.dirname(pdf_path) or ".", exist_ok=True)
        doc = SimpleDocTemplate(pdf_path, pagesize=A4,
                                leftMargin=18 * mm, rightMargin=18 * mm,
                                topMargin=15 * mm, bottomMargin=15 * mm,
                                title=os.path.basename(md_path))
        doc.build(story)
        return True, pdf_path
    except Exception as e:
        return False, str(e)


def _table(rows):
    t = Table([[Paragraph(_esc(c), ParagraphStyle("c", fontName=_FONT, fontSize=8, leading=11)) for c in r] for r in rows])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f5")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d0d7de")),
        ("FONTNAME", (0, 0), (-1, -1), _FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("用法: python3 docs_pdf.py <input.md> <output.pdf>")
        sys.exit(1)
    ok, msg = md_to_pdf(sys.argv[1], sys.argv[2])
    print("✅" if ok else "❌", msg)
    sys.exit(0 if ok else 1)
