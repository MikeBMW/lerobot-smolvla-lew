#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l5_promote_l2.py — L5 训练产物 → 在役权重切换 (老倪 2026-09-28 L5 定义第 5 条)

老倪原话: 「训完把在役权重软链 yolo_peg_live.pt 指向新 best.pt(**换软链, 不要覆盖文件**),
这样重启自动加载那条链就自然用上新模型。」

本工具只做一件事, 但做全证据:
  · `--check-only` : 校验"新 best.pt"真能加载 + 真跑一次真帧推理 → 打印切换/回滚命令 (不改任何东西)
  · `--yes`        : `ln -sfn` **原子替换软链** (绝不覆盖被指向的文件), 记旧指向 + 回滚命令 + 复验
铁律:
  ① 绝不用 cp/覆盖原文件 —— 只动软链 (一条命令就能回滚);
  ② 切换前后各跑一次真帧推理 (检出框数) 作为"换没换成功、行为变没变"的硬证据;
  ③ ⚠️ 若新模型在真帧上检出 0 框而旧模型有检出 → 明确警告"这是回退风险", 需 --force 才切。

用法:
  ./gui-venv311/bin/python tools/l5_promote_l2.py --best <best.pt> --check-only
  ./gui-venv311/bin/python tools/l5_promote_l2.py --best <best.pt> --yes
  ./gui-venv311/bin/python tools/l5_promote_l2.py --restore      # 用登记的旧指向回滚
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(ROOT, "models", "yolo_peg_live.pt")
PROMOTE_LOG = os.path.join(os.path.expanduser("~"), "zmax_data", "l5_loop", "promote_l2.json")
PY = os.path.join(ROOT, "gui-venv311", "bin", "python")


def _probe(weights: str, log=None) -> dict:
    """真加载 + 真帧推理 (一张真机帧) → 类别/框数; 拿不到帧就只报加载结果 (如实)"""
    r = {"weights": weights, "exists": os.path.isfile(weights), "resolve": None}
    try:
        r["resolve"] = os.path.realpath(weights)
        r["size_mb"] = round(os.path.getsize(weights) / 1e6, 2)
    except Exception as e:                                                       # noqa: BLE001
        r["size_mb"] = None
        r["err"] = str(e)
    if not r["exists"]:
        r["ok"] = False
        r["reason"] = "文件不存在"
        return r
    code = (
        "import json,sys;sys.path.insert(0,'%s');"
        "from ultralytics import YOLO;import auto_annotate as AA;import numpy as np,cv2,tempfile,os;"
        "m=YOLO(%r);print(json.dumps({'classes':list(m.names.values()),'nc':len(m.names)}));"
        "raw=AA.grab('arm');open('/tmp/_l5probe.jpg','wb').write(raw);"
        "res=m.predict('/tmp/_l5probe.jpg',conf=0.25,verbose=False);"
        "print('BOXES',len(res[0].boxes))" % (os.path.join(ROOT, "tools"), weights)
    )
    try:
        p = subprocess.run([PY, "-c", code], capture_output=True, text=True, timeout=300)
        out = (p.stdout or "") + (p.stderr or "")
        for ln in out.splitlines():
            if ln.startswith("{"):
                try:
                    d = json.loads(ln)
                    r["classes"], r["nc"] = d.get("classes"), d.get("nc")
                except Exception:                                               # noqa: BLE001
                    pass
            if ln.startswith("BOXES"):
                r["n_boxes_live_frame"] = int(ln.split()[-1])
        r["ok"] = r.get("classes") is not None
        if not r["ok"]:
            r["reason"] = out.strip().splitlines()[-1][:200] if out.strip() else "加载无输出"
    except Exception as e:                                                       # noqa: BLE001
        r["ok"] = False
        r["reason"] = "%s: %s" % (type(e).__name__, str(e)[:160])
    return r


def main() -> int:
    ap = argparse.ArgumentParser(description="L5 → 在役 L2 权重换软链 (不覆盖文件)")
    ap.add_argument("--best", default="", help="新 best.pt 路径")
    ap.add_argument("--check-only", action="store_true", help="只校验 + 打印命令")
    ap.add_argument("--yes", action="store_true", help="真换软链")
    ap.add_argument("--force", action="store_true", help="新模型 0 框时也切 (回退风险自负)")
    ap.add_argument("--restore", action="store_true", help="用上次登记的旧指向回滚")
    a = ap.parse_args()
    st = {}
    if os.path.isfile(PROMOTE_LOG):
        try:
            st = json.load(open(PROMOTE_LOG, encoding="utf-8"))
        except Exception:                                                       # noqa: BLE001
            st = {}
    cur = {"link": os.path.relpath(LIVE, ROOT), "is_symlink": os.path.islink(LIVE),
           "points_to": os.path.realpath(LIVE) if os.path.exists(LIVE) else None}
    print("🔗 在役软链: %s · is_symlink=%s → %s" % (cur["link"], cur["is_symlink"], cur["points_to"]))
    if a.restore:
        old = (st.get("last_best") or {}).get("prev_points_to")
        if not old or not os.path.isfile(old):
            print("❌ 没有可回滚的旧指向登记 (%s)" % PROMOTE_LOG)
            return 2
        os.symlink(old, LIVE + ".new")
        os.replace(LIVE + ".new", LIVE)
        r = _probe(LIVE)
        st["restore"] = {"ts": time.strftime("%F %T"), "to": old, "probe": r}
        json.dump(st, open(PROMOTE_LOG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("✅ 已回滚 → %s · 复验 %s (检出 %s 框)" % (old, r.get("ok"), r.get("n_boxes_live_frame")))
        return 0
    if not a.best:
        print("❌ 需要 --best <best.pt> (或 --restore)")
        return 2
    best = a.best if os.path.isabs(a.best) else os.path.join(ROOT, a.best)
    new = _probe(best)
    old = _probe(LIVE) if os.path.exists(LIVE) else {"ok": False, "reason": "在役不存在"}
    print("🧪 新模型: ok=%s · 类别 %s · 真帧检出 %s" % (new.get("ok"), new.get("classes"),
                                                    new.get("n_boxes_live_frame")))
    print("🧪 在役  : ok=%s · 类别 %s · 真帧检出 %s" % (old.get("ok"), old.get("classes"),
                                                    old.get("n_boxes_live_frame")))
    n_new, n_old = new.get("n_boxes_live_frame"), old.get("n_boxes_live_frame")
    warn = (n_new == 0 and (n_old or 0) > 0)
    if warn:
        print("⚠️ 新模型真帧 0 框而在役有 %s 框 → 这是**回退风险** (自动切换到它会丢在役检测)" % n_old)
    cmd = "ln -sfn %s %s" % (new.get("resolve") or best, os.path.relpath(LIVE, ROOT))
    if a.check_only or not a.yes:
        print("（只校验）切换命令: %s" % cmd)
        print("  ⚠️ 实切: 加 --yes%s" % ("" if not warn else " --force (当前有回退风险)"))
        return 0 if new.get("ok") else 1
    if warn and not a.force:
        print("⛔ 拒绝切换: 新模型 0 框而在役有检出 (回退风险)。确要切加 --force")
        return 3
    prev = os.path.realpath(LIVE) if os.path.exists(LIVE) else None
    os.symlink(new.get("resolve") or best, LIVE + ".new")   # 原子换: 先建临时链再 replace
    os.replace(LIVE + ".new", LIVE)
    after = _probe(LIVE)
    st["last_best"] = {"ts": time.strftime("%F %T"), "best": best, "prev_points_to": prev,
                       "after_points_to": os.path.realpath(LIVE), "probe_new": new, "probe_old": old,
                       "probe_after": after}
    json.dump(st, open(PROMOTE_LOG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("✅ 已换软链 (未覆盖任何文件): yolo_peg_live.pt → %s" % st["last_best"]["after_points_to"])
    print("   复验: 加载 ok=%s · 类别 %s · 真帧检出 %s" % (after.get("ok"), after.get("classes"),
                                                        after.get("n_boxes_live_frame")))
    print("   ↩️ 回滚: python tools/l5_promote_l2.py --restore   (旧指向 %s)" % prev)
    print("   重启自动加载验证: ./gui-venv311/bin/python tools/model_autoload.py --only L2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
