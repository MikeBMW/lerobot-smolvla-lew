#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""clear_overlay_round.py — 清「轮次层」，**永不清 meas(实测 3D 几何)**。

老倪 2026-09-29: 「清理历史，进入实时检测」; 但我上一次手写的清空脚本把 meas 也清了 ⇒ 3D 边界框
消失、被追问。这条把它固化成工具: 只清 trace/plan/l5corners/vlm/det/sim 这些"轮次/推导"层,
meas(= 按真机标定+手眼量出来的 3D 长方体) 与操作者的删除清单**一律保留**。

🔴 2026-09-30 修正: 判定改成**黑名单**(只清 CLEAR 里列出的), 不再用白名单 KEEP。
   原因: 白名单会把**没枚举过的新 origin** 静默清掉 —— SAM3 的 `seg` 层就这么没的
   (老倪追问"昨天本地下载了 SAM3 模型, 怎么没有")。新增能力(seg/guide/...)从此默认免疫。

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
    ap.add_argument("--spec", default=SPEC, help="对哪份规格操作(默认在役那份; 演练可指副本)")
    ap.add_argument("--dry-run", action="store_true", help="只打印将清/将留, 不落盘")
    a = ap.parse_args()
    sp = json.load(open(a.spec, encoding="utf-8"))
    for cam, obj in (sp.get("cameras") or {}).items():
        boxes = obj.get("boxes") or []
        if a.report:
            print("  %s: %s" % (cam, dict(Counter(str(b.get("origin")) for b in boxes))))
            continue
        arch = os.path.join(ROOT, "reports", "session_archive", "clear_%s" % time.strftime("%Y%m%d_%H%M%S"))
        os.makedirs(arch, exist_ok=True)
        dst = os.path.join(arch, "overlay_spec_before_clear.json")
        shutil.copy2(a.spec, dst)
        # 🔴 2026-09-30 改白名单为**黑名单**语义(fail-safe):
        #   旧写法 `origin in KEEP` 是白名单 ⇒ 任何**没被枚举过的新 origin**(如 SAM3 的 seg、
        #   辅助线 guide)会被静默清掉 —— 老倪"昨天下了 SAM3 怎么没有"就是这么来的:
        #   KEEP=("meas",) 里没有 seg, 清轮次时把分割层一起杀了(9-29 那次)。
        #   现在只有**明确列进 CLEAR** 的才清, 新图层默认保留 ⇒ 加新能力不会再被清理误伤。
        kept = [b for b in boxes if str(b.get("origin")) not in CLEAR]
        gone = [b for b in boxes if str(b.get("origin")) in CLEAR]
        obj["boxes"] = kept
        obj["by_origin"] = dict(Counter(str(b.get("origin")) for b in kept))
        print("  %s: 保留 %d 个 · 清 %s" % (cam, len(kept),
              dict(Counter(str(b.get("origin")) for b in gone)) or "无"))
        print("     归档: %s" % os.path.relpath(os.path.join(arch, "overlay_spec_before_clear.json"), ROOT))
    if not a.report:
        if a.dry_run:
            print("      (--dry-run: 未落盘)")
        else:
            json.dump(sp, open(a.spec, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print("     已落盘: %s" % os.path.relpath(a.spec, ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
