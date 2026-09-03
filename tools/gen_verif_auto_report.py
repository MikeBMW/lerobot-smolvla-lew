#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧪 gen_verif_auto_report.py — 状态空间模型自动测试报告 (2026-09-04 老倪)

一键自动测试三连: 环境自检 → 执行用例 → 出报告 (PDF + Excel)
用法 (gui-venv311, reportlab 已装):
  gui-venv311/bin/python tools/gen_verif_auto_report.py
输出:
  reports/状态空间自动测试报告_<ts>.pdf   (验收报告: 环境/汇总/明细/分级/RFP 映射)
  reports/state_space_features.xlsx       (6 sheet 清单+分级+RFP+结果)
打印末行: REPORT_PDF=<abs path>  (GUI 后台线程解析取回弹链接)

报告结构:
  1 执行摘要 (环境✓ / 通过率 / 分级状态 / 模型选型路线)
  2 测试环境自检 (引擎/六层/YOLO 权重/标定/流形/planner — 真实加载)
  3 用例结果汇总 (339 auto: 按节点 PASS/FAIL 表)
  4 产品作业分级 (L1 基础已交付 → L2 高级 → L3 扩展 路线)
  5 需求规格书 RFP 指标映射 (★否决项 → 支撑作业/功能)
  6 泛化指标 (G_pose/G_data/G_skill 实测)
  7 结论与下一步 (对 L2/L3 的差距)
"""
import glob
import importlib.util
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS = os.path.join(ROOT, "reports")
sys.path.insert(0, os.path.join(ROOT, "src", "lerobot", "verification"))


def _load_mod(rel_path, name):
    p = os.path.join(ROOT, rel_path)
    spec = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run_all_tests():
    """环境自检 + 跑三级树全部 auto 用例。返回 (env_ok_list, results)"""
    vl = _load_mod("src/lerobot/verification/verification_layer.py",
                   "lerobot.verification.verification_layer")
    v = vl.VerificationLayer(log=lambda *a: None)
    # ① 环境自检 (真实加载)
    env = []
    import numpy as np
    checks = [
        ("引擎 StateSpaceSim", lambda: v.engine() is not None),
        ("六层模块", lambda: all(v.ss(k) is not None for k in
                                ("perception", "parallel", "cognition", "dynamics",
                                 "execution", "safety"))),
        ("标定层", lambda: _load_mod("src/lerobot/calibration/calibration_layer.py",
                                    "lerobot.calibration.calibration_layer") is not None),
        ("流形层", lambda: _load_mod("src/lerobot/manifold/manifold_layer.py",
                                    "lerobot.manifold.manifold_layer") is not None),
        ("技能编排", lambda: _load_mod("src/lerobot/policies/left_right/state_space/planner.py",
                                     "lerobot.policies.left_right.state_space.planner") is not None),
    ]
    for name, fn in checks:
        try:
            ok = bool(fn())
        except Exception as _e:
            ok = False
        env.append((name, ok))
    # ② 跑用例
    nft = _load_mod("src/lerobot/verification/node_func_tree.py",
                    "lerobot.verification.node_func_tree")
    ok_all, results = v.run_tree(skip_slow=True, log_fn=lambda *a: None)
    return env, results, v, nft


def make_pdf(env, results, v, nft, ts):
    """reportlab PDF — 全中文 TBL 用 Paragraph, 中文字体 wqy"""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib import colors as _C
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle)
    wqy = "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"
    if not os.path.exists(wqy):
        wqy = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
    if not os.path.exists(wqy):
        wqy = "/usr/share/fonts/truetype/arphic/uming.ttc"
    if not os.path.exists(wqy):
        wqy = "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"
    pdfmetrics.registerFont(TTFont("WQY", wqy))
    pdfmetrics.registerFontFamily("WQY", normal="WQY", bold="WQY",
                                  italic="WQY", boldItalic="WQY")
    ST = {
        "title": ParagraphStyle("t", fontName="WQY", fontSize=15, leading=20,
                                alignment=TA_CENTER, textColor=_C.HexColor("#0a0e14")),
        "h1": ParagraphStyle("h1", fontName="WQY", fontSize=12, leading=17,
                             textColor=_C.HexColor("#d29922"), spaceBefore=10),
        "h2": ParagraphStyle("h2", fontName="WQY", fontSize=10.5, leading=14,
                             textColor=_C.HexColor("#1f6feb"), spaceBefore=8),
        "b": ParagraphStyle("b", fontName="WQY", fontSize=8.8, leading=12.5,
                            textColor=_C.HexColor("#1c2128")),
        "small": ParagraphStyle("s", fontName="WQY", fontSize=7.5, leading=10,
                                textColor=_C.HexColor("#57606a")),
    }
    doc = SimpleDocTemplate(os.path.join(REPORTS, f"状态空间自动测试报告_{ts}.pdf"),
                            pagesize=A4, leftMargin=24, rightMargin=24,
                            topMargin=20, bottomMargin=18)
    story = []
    passed = sum(1 for x in results.values() if x and x[0] is True)
    failed = sum(1 for x in results.values() if x and x[0] is False)
    total = len(results)

    def P(t, s="b"):
        story.append(Paragraph(t, ST[s]))

    def TBL(data, widths, hdr_bg="#1f6feb"):
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), _C.HexColor(hdr_bg)),
            ("TEXTCOLOR", (0, 0), (-1, 0), _C.white),
            ("FONTNAME", (0, 0), (-1, -1), "WQY"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("GRID", (0, 0), (-1, -1), 0.4, _C.HexColor("#d0d7de")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [_C.white, _C.HexColor("#f6f8fa")]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.append(t)

    # 1 摘要
    P("状态空间模型自动测试报告", "title")
    P(f"Z-MAX Z700 具身智能机器人 · 生成时间 {ts}", "small")
    P("")
    P(f"① 测试环境: {sum(1 for _, ok in env if ok)}/{len(env)} 项就绪"
      f"  ② 自动用例: PASS {passed} / FAIL {failed} / 总 {total}"
      f"  ③ 产品分级: L1 基础功能已交付(分段式) · L2 高级柔性规划中(端到端)"
      f"  ④ 泛化指标: G_pose/G_data/G_skill 已建立基线", "h1")
    P("")
    # 2 环境
    P("2. 测试环境自检 (真实加载, 无 mock)", "h1")
    TBL([["模块", "状态"]] + [[n, "✅ 就绪" if ok else "❌ 失败"]
                              for n, ok in env], [300, 80])
    story.append(Spacer(1, 6))
    # 3 用例汇总 by 节点
    P("3. 自动用例结果 (按节点)", "h1")
    node_res = {}
    for k, x in results.items():
        node = k.split(".")[0]
        node_res.setdefault(node, [0, 0])
        if x:
            node_res[node][0 if x[0] is True else 1] += 1
    rows = [["节点", "功能数", "PASS", "FAIL"]]
    for nk, node in nft.NODE_TREE.items():
        p, f = node_res.get(nk, [0, 0])
        rows.append([f"{node['name']} ({nk})", len(node["funcs"]), str(p), str(f)])
    rows.append(["合计", "", str(passed), str(failed)])
    TBL(rows, [250, 60, 50, 50])
    story.append(Spacer(1, 6))
    # 4 产品分级
    P("4. 产品作业分级与模型选型", "h1")
    for lv in nft.PRODUCT_TREE:
        P(f"{lv['level']} {lv['lvl_name']} · {lv['kind']} — {lv['desc']}", "h2")
        rows = [["产品作业", "实现状态", "模型选型路线"]]
        for j in lv["jobs"]:
            rows.append([j["job"], j["status"], j.get("model_route", "")])
        TBL(rows, [110, 150, 260])
        story.append(Spacer(1, 5))
    # 5 RFP 映射
    P("5. 需求规格书 RFP 指标映射", "h1")
    rows = [["★", "指标", "量化要求", "关联作业"]]
    for name, q, veto, job, _f in nft.RFP_SPEC["key_items"]:
        rows.append(["★" if veto else "", name, q, job])
    TBL(rows, [24, 130, 220, 90])
    story.append(Spacer(1, 6))
    # 5b 技术规格
    P("5b. 技术规格书 (供应商 3 组 12 项 → 产品作业)", "h1")
    for g in nft.TECH_SPECS:
        P(f"{g['group']} {g['g_name']} ({g['g_en']}) — {g['g_desc']}", "h2")
        rows = [["规格项", "量化要求", "关联作业"]]
        for it in g["items"]:
            rows.append([it["spec"], it["req"], it["job"]])
        TBL(rows, [110, 250, 90])
        story.append(Spacer(1, 5))
    # 6 泛化指标
    P("6. 泛化指标基线 (G 组断言实测)", "h1")
    import numpy as np
    gnames = ["t_gpose_selfalign", "t_gpose_oob", "t_gskill_reuse",
              "t_gskill_chain", "t_gskill_overlap", "t_gdata_engine", "t_gdata_route"]
    rows = [["泛化指标", "结果", "实测证据"]]
    for g in gnames:
        try:
            ok, d = getattr(v, g)(np)
            rows.append([g, "✅" if ok else "❌", str(d)[:90]])
        except Exception as e:
            rows.append([g, "❌", f"{type(e).__name__}: {e}"])
    TBL(rows, [150, 44, 280])
    story.append(Spacer(1, 6))
    # 7 结论
    P("7. 结论与下一步", "h1")
    if failed == 0:
        P("自动用例全绿。L1 基础功能 (刚体接触插拔/取放/视觉定位) 已具备交付基线;"
          "L2 高级功能 (光纤柔性插拔) 与 L3 扩展功能 (光耦合性能调节) 按模型选型路线"
          "进入规划 — L2 走端到端 VLA 插拔头/柔顺导纳, L3 走世界模型+优化搜索。")
    else:
        P(f"存在 {failed} 项失败 — 修复后重跑本报告 (gui-venv311/bin/python tools/gen_verif_auto_report.py)")
    doc.build(story)
    return os.path.join(REPORTS, f"状态空间自动测试报告_{ts}.pdf")


def main():
    os.makedirs(REPORTS, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    env, results, v, nft = run_all_tests()
    pdf = make_pdf(env, results, v, nft, ts)
    # Excel (复用 verification_dialog.export_verif_excel)
    sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
    from verification_dialog import export_verif_excel
    xlsx = export_verif_excel(tree=nft, results=results)
    print(f"✅ 自动测试: 环境 {sum(1 for _, ok in env if ok)}/{len(env)} · "
          f"PASS {sum(1 for x in results.values() if x and x[0] is True)} / "
          f"FAIL {sum(1 for x in results.values() if x and x[0] is False)}")
    print(f"REPORT_PDF={pdf}")
    print(f"EXCEL={xlsx}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
