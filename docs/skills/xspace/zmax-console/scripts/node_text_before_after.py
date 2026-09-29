#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同口径对照: 老规则(9pt + 按全名撑宽) vs 新规则(10pt + 短显示名 + 按短名撑宽)。

两边都走**各自的 autofit**(=界面加载时真实走的那步), 再按各自字体测"框里那行字"。
只读 flows/state_space_obs.json, 不写任何东西。
"""
import json
import math
import os
import sys

sys.path.insert(0, "/home/ubuntu/zmax_rel/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtGui import QGuiApplication, QFontMetrics, QFont  # noqa: E402

_app = QGuiApplication.instance() or QGuiApplication([])
import simulink_module as SM  # noqa: E402

DW, DH = 280, 110
PAD_L, PAD_R, LINES = 14, 56, 2


def old_autofit(node, max_w=380, fm=None):
    w = int(node.get("w") or DW)
    name = str(node.get("name") or "")
    need1 = fm.horizontalAdvance(name) + PAD_L + PAD_R
    if need1 <= w:
        return w
    if need1 <= max_w:
        return int(max(DW, need1))
    return int(max(DW, min(max_w, need1 // 2 + PAD_L + PAD_R + 24)))


def old_wrap(text, fm, avail, max_lines=LINES):
    avail = int(avail)
    if avail <= 20 or not text:
        return [text], False
    if fm.horizontalAdvance(text) <= avail:
        return [text], False
    parts = text.replace("·", " · ").replace("(", " ( ").replace(")", " ) ").split()
    lines, cur = [], ""
    for pt in (parts or [text]):
        trial = (cur + " " + pt).strip()
        if fm.horizontalAdvance(trial) <= avail or not cur:
            cur = trial
            continue
        lines.append(cur)
        cur = pt
        if len(lines) >= max_lines:
            break
    if cur:
        lines.append(cur)
    if len(lines) <= max_lines and all(fm.horizontalAdvance(x) <= avail for x in lines):
        return lines, False
    lines, cur = [], ""
    for ch in text:
        if fm.horizontalAdvance(cur + ch) <= avail or not cur:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
            if len(lines) >= max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    trunc = "".join(lines) != text
    return lines[:max_lines], trunc


def main():
    d = json.load(open("/home/ubuntu/zmax_rel/flows/state_space_obs.json", encoding="utf-8"))
    nodes = [n for n in d["nodes"] if n.get("type") != "row_bg"]
    fm_old = QFontMetrics(QFont("Noto Sans CJK SC", 9, QFont.Bold))
    fm_new = QFontMetrics(SM._node_font(SM.NODE_TITLE_PT, True))
    stat = {"old": {"two": 0, "trunc": 0, "px": []}, "new": {"two": 0, "trunc": 0, "px": []}}
    for n in nodes:
        # 老: 按全名撑宽 + 全名拆行
        w_o = old_autofit(n, fm=fm_old)
        avail_o = max(40, w_o - PAD_R)
        lines_o, tr_o = old_wrap(str(n.get("name")), fm_old, avail_o)
        stat["old"]["two"] += 1 if len(lines_o) > 1 else 0
        stat["old"]["trunc"] += 1 if tr_o else 0
        stat["old"]["px"].append(fm_old.horizontalAdvance(str(n.get("name"))))
        # 新: 按短名撑宽 + 短名拆行 (与界面 load_flow 后的真实状态一致)
        w_n = old_autofit(n, fm=fm_new)   # 同名同逻辑, 只换"撑宽依据的名字"
        disp = SM.node_display_name(n.get("name"), SM.NODE_LABEL_MAX_PX)
        need1 = fm_new.horizontalAdvance(disp) + PAD_L + PAD_R
        if need1 <= int(n.get("w") or DW):
            w_n = int(n.get("w") or DW)
        elif need1 <= 380:
            w_n = int(max(DW, need1))
        else:
            w_n = int(max(DW, min(380, need1 // 2 + PAD_L + PAD_R + 24)))
        avail_n = max(40, w_n - PAD_R)
        lines_n, tr_n = SM._wrap_title(disp, fm_new, avail_n)
        stat["new"]["two"] += 1 if len(lines_n) > 1 else 0
        stat["new"]["trunc"] += 1 if tr_n else 0
        stat["new"]["px"].append(fm_new.horizontalAdvance(disp))
    n = len(nodes)
    for k, label in (("old", "老(9pt+全名)"), ("new", "新(10pt+短名)")):
        s = stat[k]
        print(f"  {label}: 节点{n} · 两行 {s['two']} · 被省略(显示不全) {s['trunc']} · "
              f"标题宽 中位 {sorted(s['px'])[n // 2]}px 最大 {max(s['px'])}px")
    # 色带
    print("  ── 色带(方框)名字区 ──")
    others = d["nodes"]
    old_tr = new_tr = 0
    for b in [x for x in others if x.get("type") == "row_bg"]:
        bx = float(b.get("x", 0))
        nm = str(b.get("name", ""))
        if nm.startswith("🎨 "):
            nm = nm[2:]
        lines_o, tr_o = old_wrap(nm, fm_old, 80)          # 老代码: 全画布最小 x ⇒ 恒 80px
        old_tr += 1 if tr_o else 0
        by, bh = float(b.get("y", 0)), float(b.get("h", 244))
        _ys, _ye = by + 8, by + bh - 8
        cand = [float(x.get("x", 0)) for x in others if x.get("type") != "row_bg"
                and _ys <= float(x.get("y", 0)) + float(x.get("h", 110)) / 2.0 <= _ye]
        aw = int(max(80.0, (min(cand) if cand else bx + 240) - bx - 16))
        disp = SM.node_display_name(nm, None)
        lines_n, tr_n = SM._wrap_title(disp, fm_new, aw)
        new_tr += 1 if tr_n else 0
    print(f"  老: 被省略 {old_tr}/15 (名字区恒 80px)   新: 被省略 {new_tr}/15 (名字区按本带内部节点算)")


if __name__ == "__main__":
    main()
