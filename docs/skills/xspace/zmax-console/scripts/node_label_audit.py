#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""节点标签体检 (只读): 把 26 个 flow / 1000+ 个节点的「画进框里的字」全量算一遍,
按老倪的规矩判: 字数 ≤10 · 一行放得下(≤300px) · 不得只剩层号(L2/L3/L4) · 不得过简。

用法:  cd /home/ubuntu/zmax_rel
       QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python <本脚本>
三个 "0" (超10字 / 超300px / 只剩层号) = 通过。
"""
import glob
import json
import os
import re
import sys

REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax_rel")
sys.path.insert(0, os.path.join(REPO, "tools", "gui"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtGui import QFontMetrics  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402


def main() -> int:
    app = QApplication.instance() or QApplication([])
    import simulink_module as SM  # noqa: E402

    fm = QFontMetrics(SM._node_font(SM.NODE_TITLE_PT, True))
    files = sorted(set(glob.glob(os.path.join(REPO, "flows", "*.json")))
                   | set(glob.glob(os.path.join(REPO, "src/lerobot/engineering/flows", "*.json"))))
    tot = over = wide = bare = thin = 0
    bad = []
    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        nodes = d.get("nodes") if isinstance(d, dict) else d
        if not isinstance(nodes, list):
            continue
        for n in nodes:
            if not isinstance(n, dict) or n.get("type") == "row_bg":
                continue
            nm = str(n.get("name", "")).strip()
            if not nm:
                continue
            tot += 1
            lab = SM.node_display_name(nm, SM.NODE_LABEL_MAX_PX)
            body = SM._split_icon(lab)[1]
            c, w = SM._label_cost(body), fm.horizontalAdvance(lab)
            o = SM._label_cost(SM._split_icon(nm)[1])
            why = None
            if c > SM.NODE_LABEL_MAX_CHARS:
                why = "超10字"
            elif w > SM.NODE_LABEL_MAX_PX:
                why = "超宽"
            elif re.fullmatch(r"L[1-5]", body.strip()):
                why = "只剩层号"
            elif o > SM.NODE_LABEL_MAX_CHARS and c < SM.NODE_LABEL_MIN_CHARS:
                why = "过简"
            if why:
                bad.append((why, os.path.basename(f), nm, lab, c, w))
    print(f"扫 {tot} 个节点标签 @ {REPO}")
    for why, f, nm, lab, c, w in bad[:40]:
        print(f"  [{why}] {f} {nm[:40]} → {lab[:28]} ({c}字 {w}px)")
    over = sum(1 for b in bad if b[0] == "超10字")
    wide = sum(1 for b in bad if b[0] == "超宽")
    bare = sum(1 for b in bad if b[0] == "只剩层号")
    thin = sum(1 for b in bad if b[0] == "过简")
    print(f"超10字 {over} | 超300px {wide} | 只剩层号 {bare} | 过简 {thin}")
    ok = (over == 0 and wide == 0 and bare == 0 and thin == 0)
    print("=== 结论:", "全部通过 ✅" if ok else "有问题 ❌", "===")
    sys.stdout.flush()
    os._exit(0 if ok else 1)


if __name__ == "__main__":
    raise SystemExit(main())
