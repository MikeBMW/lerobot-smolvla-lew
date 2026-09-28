#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""clear_overlay_round.py — 清「轮次层」，**永不清 meas(实测 3D 几何)**。

老倪 2026-09-29: 「清理历史，进入实时检测」; 但我上一次手写的清空脚本把 meas 也清了 ⇒ 3D 边界框
消失、被追问。这条把它固化成工具: 只清 trace/plan/l5corners/vlm/det/sim 这些"轮次/推导"层,
meas(= 按真机标定+手眼量出来的 3D 长方体) 与操作者的删除清单**一律保留**。

用法:
  ./gui-venv311/bin/python tools/clear_overlay_round.py            # 清轮次层(先归档)
  ./gui-venv311/bin/python tools/clear_overlay_round.py --report   # 只看各层计数
"""
from __future__ import annotations
import argparse, json, os, shutil, time
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, "data", "scene", "overlay_spec.json")
KEEP = ("meas",)                       # 🔒 实测几何: 永不清
CLEAR = ("vlm", "det", "sim", "plan", "trace", "l5corners")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="只打印各层计数")
    ap.add_argument("--keep-deleted", action="store_true", default=True)
    a = ap.parse_args()
    sp = json.load(open(SPEC, encoding="utf-8"))
    for cam, obj in (sp.get("cameras") or {}).items():
        boxes = obj.get("boxes") or []
        if a.report:
            print("  %s: %s" % (cam, dict(Counter(str(b.get("origin")) for b in boxes))))
            continue
        arch = os.path.join(ROOT, "reports", "session_archive", "clear_%s" % time.strftime("%Y%m%d_%H%M%S"))
        os.makedirs(arch, exist_ok=True)
        shutil.copy2(SPEC, os.path.join(arch, "overlay_spec_before_clear.json"))
        kept = [b for b in boxes if str(b.get("origin")) in KEEP]
        gone = [b for b in boxes if str(b.get("origin")) in CLEAR]
        obj["boxes"] = kept
        obj["by_origin"] = dict(Counter(str(b.get("origin")) for b in kept))
        print("  %s: 保留 %s×%d · 清 %s" % (cam, "/".join(KEEP), len(kept),
              dict(Counter(str(b.get("origin")) for b in gone)) or "无"))
        print("     归档: %s" % os.path.relpath(os.path.join(arch, "overlay_spec_before_clear.json"), ROOT))
    if not a.report:
        json.dump(sp, open(SPEC, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
