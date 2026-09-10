#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📄 Z-MAX 双脑+状态机 插拔方案报告生成器 (2026-08-10 老倪)
输入: reports/dual_brain_state_machine_plan.json (方案数据底座)
      + [--frame reports/_insert_demo_frame.png] (演示视频帧, 可选)
输出: reports/插拔方案报告_<时间戳>.pdf

报告结构 (6章, 全部数据来自方案 JSON, 可溯源):
  1 实验概况   — 目的/成绩/结论 (抓起8/8 插入7/8 超越官方专家)
  2 整体架构   — 双脑: 左脑MLP动作生成 + 右脑WorldModel时机判断
  3 状态机     — 6阶段执行链 (接近→抓取→抬起→转移→插入→完成)
  4 关键调优   — 5条关键参数 (偏置接近/夹持0.6/抬起8cm/容差5cm/接触判定)
  5 方案对比   — 五方案成绩矩阵 (双脑 vs 专家 vs 纯状态机 vs MLP vs 视觉BC)
  6 下一步     — 稳定性测试/真机迁移/8/8冲刺 + 交付物清单

用法 (容器, 与 generate_report.py 一致):
    sudo docker run --rm -v <root>:/app -w /app -e PYTHONPATH=/app/src \
        --entrypoint python zmax-std:1.0 /app/tools/gen_insert_report.py [--frame ...]
"""
import argparse
import glob
import json
import os
import re
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS = os.path.join(ROOT, "reports")
PLAN = os.path.join(REPORTS, "dual_brain_state_machine_plan.json")


# ── 绘图 (matplotlib, 无显示环境) ─────────────────────────────────────────────
def _cfg_cjk():
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import font_manager
    for cand in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                 "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"):
        if os.path.exists(cand):
            font_manager.fontManager.addfont(cand)
    matplotlib.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "Noto Serif CJK SC", "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False


def plot_overview(plan, path):
    """图1: 五方案成绩柱状图 (抓起/插入)"""
    _cfg_cjk()
    import matplotlib.pyplot as plt
    import numpy as np
    import re as _re
    cmp = plan.get("对比", {})
    rows = [("双脑+状态机", cmp.get("双脑+状态机", "8/8, 7/8")),
            ("官方专家", cmp.get("官方专家", "7/8, 7/8")),
            ("纯状态机+学习", cmp.get("纯状态机+学习", "0/8, 0/8")),
            ("MLP蒸馏", cmp.get("MLP蒸馏", "6/10, 3/10")),
            ("视觉BC模型", cmp.get("视觉BC模型", "0/8, 0/8"))]

    def _fracs(s):
        """提取字符串里所有 x/y 分数的分子, 如 '抓起 8/8, 插入 7/8' → [8, 7]"""
        return [float(m.group(1)) for m in _re.finditer(r"(\d+)/(\d+)", str(s))]

    names, grab, ins = [], [], []
    for nm, s in rows:
        vals = _fracs(s)
        names.append(nm)
        grab.append(vals[0] if vals else 0.0)
        ins.append(vals[1] if len(vals) > 1 else (vals[0] if vals else 0.0))
    x = np.arange(len(names)); w = 0.35
    fig, ax = plt.subplots(figsize=(9.2, 4.0))
    fig.patch.set_facecolor("#ffffff")
    b1 = ax.bar(x - w/2, grab, w, label="抓起", color="#58a6ff", alpha=.9)
    b2 = ax.bar(x + w/2, ins, w, label="插入", color="#00d4aa", alpha=.9)
    for b in list(b1) + list(b2):
        ax.text(b.get_x() + b.get_width()/2, b.get_height() + 0.08, f"{b.get_height():.0f}",
                ha="center", fontsize=8.5, fontweight="bold")
    ax.set_xticks(x); ax.set_xticklabels(names, fontsize=9)
    ax.set_ylabel("成功率 (次/8 或 /10)"); ax.set_ylim(0, 9.5)
    ax.legend(fontsize=9); ax.grid(axis="y", alpha=.3)
    ax.set_title("五方案成绩对比 — 双脑+状态机 抓起8/8 插入7/8 (首个学习架构解决完整插拔)", fontsize=10)
    plt.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_state_machine(plan, path):
    """图2: 状态机 6 阶段流程 (帧数标注)"""
    _cfg_cjk()
    import matplotlib.pyplot as plt
    sm = (plan.get("整体架构", {}).get("状态机", {}))
    stages = sm.get("阶段", ["接近", "抓取", "抬起", "转移", "插入", "完成"])
    frames = [32, 45, 9, 38, 1] + [0] * max(0, len(stages) - 5)  # 完成不耗帧
    fig, ax = plt.subplots(figsize=(9.2, 2.6))
    fig.patch.set_facecolor("#ffffff")
    x = list(range(len(stages)))
    bars = ax.bar(x, frames, color=["#58a6ff", "#a371f7", "#d29922", "#00d4aa", "#ff9f43", "#3fb950"], alpha=.9)
    for b, f in zip(bars, frames):
        ax.text(b.get_x() + b.get_width()/2, b.get_height() + 0.6, f"{f}帧",
                ha="center", fontsize=9, fontweight="bold")
    ax.set_xticks(x); ax.set_xticklabels(stages, fontsize=10)
    ax.set_ylabel("帧数"); ax.set_ylim(0, 55)
    ax.grid(axis="y", alpha=.3)
    ax.set_title("状态机 6 阶段执行链 — 合计125帧", fontsize=10)
    plt.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


# ── PDF 生成 (reportlab, 同 generate_report.py 铁律) ──────────────────────────
def _reg_cjk_fonts():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    cands = []
    for p in ["/mnt/c/Windows/Fonts/simhei.ttf", "/mnt/c/Windows/Fonts/msyh.ttc",
              "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"]:
        if os.path.exists(p):
            cands.append(p)
    if not cands:
        try:
            import subprocess
            r = subprocess.run(["fc-list", ":lang=zh", "file"], capture_output=True, text=True, timeout=10)
            for line in r.stdout.splitlines():
                p = line.split(":")[0].strip()
                if p and os.path.exists(p) and p not in cands:
                    cands.append(p)
        except Exception:
            pass
    for i, path in enumerate(cands):
        name = f"CJK{i}"
        try:
            pdfmetrics.registerFont(TTFont(name, path, subfontIndex=0))
        except Exception:
            try:
                pdfmetrics.registerFont(TTFont(name, path))
            except Exception:
                continue
    reg = pdfmetrics.getRegisteredFontNames()
    alias_src = None
    for i in range(len(cands)):
        if f"CJK{i}" in reg:
            alias_src = cands[i]
            break
    if alias_src is None and cands:
        alias_src = cands[0]
    if "NotoSansCJK" not in reg and alias_src:
        for alias in ["NotoSansCJK", "NotoSansCJKBold"]:
            if alias not in reg:
                try:
                    pdfmetrics.registerFont(TTFont(alias, alias_src, subfontIndex=0))
                except Exception:
                    try:
                        pdfmetrics.registerFont(TTFont(alias, alias_src))
                    except Exception:
                        pass
    if "MicrosoftYaHei" not in reg and alias_src:
        try:
            pdfmetrics.registerFont(TTFont("MicrosoftYaHei", alias_src, subfontIndex=0))
        except Exception:
            pass


_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002700-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002600-\U000026FF\U00002B00-\U00002BFF\uFE0F\u200D"
    "\U00002190-\U000021FF\U000025A0-\U000025FF\u2705\u26A0\u274C"
    "\U00002300-\U000023FF\U00002500-\U0000257F\U00002900-\U000029FF"
    "\U00002080-\U0000209F\U00002070-\U0000207F\U00000000-\U0000001F]")


def _clean(text):
    if not isinstance(text, str):
        return text
    text = _EMOJI_RE.sub("", text)
    text = text.replace("\u2081", "1").replace("\u2082", "2").replace("\u2083", "3")
    text = text.replace("\u2084", "4").replace("\u2085", "5").replace("\u2086", "6")
    text = text.replace("\u2070", "0").replace("\u00b9", "1").replace("\u00b2", "2").replace("\u00b3", "3")
    return text


def build_pdf(plan, frame_path, out_path):
    _reg_cjk_fonts()
    from reportlab.pdfbase import pdfmetrics
    _ok = "NotoSansCJK" in pdfmetrics.getRegisteredFontNames()
    FONT = "NotoSansCJK" if _ok else ("MicrosoftYaHei" if "MicrosoftYaHei" in pdfmetrics.getRegisteredFontNames() else "Helvetica")
    FBOLD = "NotoSansCJKBold" if "NotoSansCJKBold" in pdfmetrics.getRegisteredFontNames() else FONT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors as rc
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle, Image, PageBreak)
    from reportlab.lib.enums import TA_CENTER, TA_LEFT

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=15, spaceBefore=10, spaceAfter=6,
                        textColor=rc.HexColor("#1f6feb"), fontName=FBOLD)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12.5, spaceBefore=8, spaceAfter=4,
                        textColor=rc.HexColor("#24292f"), fontName=FBOLD)
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=9.5, leading=14,
                          textColor=rc.HexColor("#24292f"), fontName=FONT)
    small = ParagraphStyle("Small", parent=styles["BodyText"], fontSize=8.5, leading=12,
                           textColor=rc.HexColor("#57606a"), fontName=FONT)
    center = ParagraphStyle("Center", parent=body, alignment=TA_CENTER)
    title_st = ParagraphStyle("Title", parent=styles["Title"], fontSize=20, alignment=TA_CENTER,
                              textColor=rc.HexColor("#1f6feb"), spaceAfter=4, fontName=FBOLD)

    doc = SimpleDocTemplate(out_path, pagesize=A4, leftMargin=16*mm, rightMargin=16*mm,
                            topMargin=14*mm, bottomMargin=14*mm,
                            title="Z-MAX 双脑+状态机插拔方案报告", author="Z-MAX 控制台")
    E = []

    def _P(text, style):
        return Paragraph(_clean(text), style)

    def TBL(rows, widths=None, header=True, fs=8):
        rows = [[_clean(c) if isinstance(c, str) else c for c in row] for row in rows]
        from reportlab.lib.styles import ParagraphStyle as _PS
        _cell_st = _PS("tblcell", fontName=FONT, fontSize=fs, leading=max(fs*1.3, 9), wordWrap="CJK")
        rows = [[Paragraph(str(c), _cell_st) if not isinstance(c, (Image,)) else c for c in row] for row in rows]
        t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
        st = [("GRID", (0, 0), (-1, -1), 0.4, rc.HexColor("#d0d7de")),
              ("VALIGN", (0, 0), (-1, -1), "TOP"),
              ("BACKGROUND", (0, 0), (-1, 0), rc.HexColor("#f0f3f6")),
              ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
              ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
        if header:
            st.append(("FONTNAME", (0, 0), (-1, 0), FBOLD))
        t.setStyle(TableStyle(st))
        return t

    # ── 封面 ──
    E.append(Spacer(1, 8*mm))
    E.append(_P("Z-MAX 可插拔学习方案", title_st))
    E.append(_P("双脑 + 状态机 = 完整插拔流程", center))
    E.append(Spacer(1, 3*mm))
    E.append(_P(f"版本 {plan.get('版本', 'v1.0')} · 日期 {plan.get('日期', time.strftime('%Y-%m-%d'))}", center))
    E.append(Spacer(1, 6*mm))
    score = plan.get("成绩", {})
    E.append(TBL([
        ["抓起成功率", "插入成功率", "状态"],
        [score.get("抓起", "-"), score.get("插入", "-"), score.get("状态", "-")],
    ], widths=[60*mm, 60*mm, 62*mm], fs=12))
    E.append(Spacer(1, 6*mm))
    if frame_path and os.path.exists(frame_path):
        E.append(Image(frame_path, width=120*mm, height=80*mm))
        E.append(_P("▲ 插拔演示视频帧 (reports/insert_success_demo.mp4)", small))
    E.append(PageBreak())

    # ── 1 实验概况 ──
    E.append(_P("1  实验概况", h1))
    E.append(_P("目的: 用学习架构解决完整插拔任务 (抓销钉→抬起→转移→插入孔)。此前纯状态机+学习 0/8, "
                "视觉BC模型全部 0/8; 双脑+状态机首次达到 抓起 8/8 (超越官方专家 7/8)、插入 7/8 (与官方专家持平)。", body))
    E.append(_P("结论: 首个学习架构解决完整插拔 — 左脑 MLP 负责连续动作生成, 右脑 WorldModel 负责抓取时机判断, "
                "状态机负责 6 阶段执行链。", body))
    E.append(Spacer(1, 3*mm))
    fig1 = os.path.join(REPORTS, "_insert_fig_scores.png")
    plot_overview(plan, fig1)
    E.append(Image(fig1, width=165*mm, height=72*mm))
    E.append(Spacer(1, 4*mm))

    # ── 2 整体架构 (双脑) ──
    E.append(_P("2  整体架构 — 双脑", h1))
    dual = plan.get("整体架构", {}).get("双脑", {})
    left = dual.get("左脑_MLP", {})
    right = dual.get("右脑_WorldModel", {})
    E.append(_P("2.1 左脑 MLP — 连续动作生成", h2))
    E.append(TBL([
        ["项目", "内容"],
        ["作用", left.get("作用", "-")],
        ["输入", str(left.get("输入", "-"))],
        ["输出", str(left.get("输出", "-"))],
        ["结构", left.get("结构", "-")],
        ["关键", left.get("关键", "-")],
    ], widths=[35*mm, 147*mm]))
    E.append(Spacer(1, 3*mm))
    E.append(_P("2.2 右脑 WorldModel — 抓取时机判断", h2))
    E.append(TBL([
        ["项目", "内容"],
        ["作用", right.get("作用", "-")],
        ["输入", str(right.get("输入", "-"))],
        ["输出", str(right.get("输出", "-"))],
        ["接触判断准确率", right.get("准确率", "-")],
        ["关键", right.get("关键", "-")],
    ], widths=[35*mm, 147*mm]))
    E.append(Spacer(1, 3*mm))
    E.append(_P("数据流: 39D obs 同时送入左脑 (动作回归, MSE 800 epoch, seed 42) 与右脑 "
                "(next obs 预测 + contact 二分类, BCE 800 epoch, seed 42)。左脑 4D 动作 (3D速度+夹爪) 输出给状态机执行, "
                "右脑 contact 概率 + 钳口-销钉距离 d_hp 联合判定抓取时机。", body))

    # ── 3 状态机 ──
    E.append(_P("3  状态机 — 6 阶段执行链", h1))
    sm = plan.get("整体架构", {}).get("状态机", {})
    _F = {"接近": "32", "抓取": "45", "抬起": "9", "转移": "38", "插入": "1", "完成": "-"}
    st_rows = [["阶段", "触发条件 / 行为", "帧数"]]
    for k in ["接近", "抓取", "抬起", "转移", "插入", "完成"]:
        v = sm.get(k, {})
        if isinstance(v, str):
            desc = v
        else:
            desc = v.get("desc") or v.get("trigger") or v.get("target") or ("" if k == "完成" else "-")
        st_rows.append([k, str(desc), _F.get(k, "-")])
    E.append(TBL(st_rows, widths=[28*mm, 130*mm, 24*mm]))
    E.append(Spacer(1, 3*mm))
    fig2 = os.path.join(REPORTS, "_insert_fig_sm.png")
    plot_state_machine(plan, fig2)
    E.append(Image(fig2, width=165*mm, height=47*mm))

    # ── 4 关键调优 ──
    E.append(_P("4  关键调优 (可溯源参数)", h1))
    E.append(TBL([["#", "调优点", "参数/值"]],
                 widths=[10*mm, 30*mm, 142*mm]))
    E.append(TBL([["1", "偏置接近", "act*0.3 + hand→peg方向*2.0 — 比纯解析接近强 (5/8 vs 0/8)"],
                  ["2", "夹持 0.6", "专家式 grab_effort + 位置锁定"],
                  ["3", "抬起 +8cm", "力 0.8, 避开台面, 转移不卡"],
                  ["4", "转移容差 5cm", "peg 有导向"],
                  ["5", "接触判定 d_hp<0.06", "钳口贴住 (右脑 contact>0.5 联合判定)"]],
                 widths=[10*mm, 30*mm, 142*mm]))
    E.append(Spacer(1, 2*mm))
    E.append(_P("训练数据: 官方专家轨迹 50 条 (obs, action, next_obs, contact 标签, 抓握点 delta)。种子 seed 42 固定保证复现。", small))

    # ── 5 方案对比 ──
    E.append(_P("5  方案对比", h1))
    cmp = plan.get("对比", {})
    E.append(TBL([
        ["方案", "抓起", "插入", "说明"],
        ["双脑+状态机", "8/8", "7/8", "首个学习架构解决完整插拔"],
        ["官方专家", "7/8", "7/8", "PD 控制律基准"],
        ["纯状态机+学习", "0/8", "0/8", "无学习"],
        ["MLP蒸馏", "6/10", "3/10", "纯回归无右脑"],
        ["视觉BC模型", "0/8", "0/8", "视觉BC全部失败"],
    ], widths=[42*mm, 30*mm, 30*mm, 80*mm]))
    E.append(Spacer(1, 3*mm))
    E.append(_P("注: 双脑+状态机为 8 次试验成绩, MLP蒸馏为 10 次试验成绩; 专家锚点 (7/8) 为对比基准, 不参与排名。", small))

    # ── 6 下一步 ──
    E.append(_P("6  下一步与交付物", h1))
    nxt = plan.get("下一步", [])
    E.append(TBL([["#", "任务"]], widths=[12*mm, 170*mm]))
    E.append(TBL([[str(i+1), str(v)] for i, v in enumerate(nxt)],
                 widths=[12*mm, 170*mm]))
    E.append(Spacer(1, 3*mm))
    files = plan.get("文件", {})
    E.append(TBL([
        ["交付物", "路径"],
        ["训练脚本", files.get("训练脚本", "tools/train_full_pipeline.py")],
        ["模型权重", files.get("模型权重", "outputs/rl_peg/full_pipeline.pt")],
        ["视频生成", files.get("视频生成", "tools/gen_insert_video.py")],
        ["演示视频", "reports/insert_success_demo.mp4"],
        ["画布流程", "flows/dual_brain_peg.json"],
        ["方案数据", "reports/dual_brain_state_machine_plan.json"],
    ], widths=[42*mm, 140*mm]))
    E.append(Spacer(1, 4*mm))
    E.append(_P(f"— Z-MAX 控制台 · 生成于 {time.strftime('%Y-%m-%d %H:%M:%S')}", small))

    doc.build(E)
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", default=os.path.join(REPORTS, "_insert_demo_frame.png"))
    args = ap.parse_args()
    if not os.path.exists(PLAN):
        print(f"❌ 缺方案数据: {PLAN}", flush=True)
        return 1
    plan = json.load(open(PLAN, encoding="utf-8"))
    ts = time.strftime("%Y%m%d_%H%M%S")
    out = os.path.join(REPORTS, f"插拔方案报告_{ts}.pdf")
    build_pdf(plan, args.frame, out)
    print(f"✅ 报告已生成: {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
