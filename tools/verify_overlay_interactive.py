#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""叠加交互链回归自检 (删除选定框 → 提示词让 L5 重标 → 像素/计数核验)。

老倪 2026-09-28: 「你要在手臂相机上画出 3D 的物体边界框；再增加一个用户交互功能:
用户可以选择每个叠加的 3D 边界框, 可以删除错的边界框; 然后视觉语言大模型再次标注,
期间我可以通过提示词跟你互动, 指导你标注的方向」。

本脚本只走**页面按钮用的同一条端点**(/boxes · /boxes/delete · /boxes/restore · /gen?hint=),
不直接改文件; 跑完把删除清单清空, 现场恢复原状。

用法:
  python tools/verify_overlay_interactive.py                 # 全链(含真调 L5, 10~140s)
  python tools/verify_overlay_interactive.py --no-vlm        # 只验删除/恢复(秒级)
  python tools/verify_overlay_interactive.py --hint "只标光模块和它的插槽"
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request

API = "http://127.0.0.1:8791"
HINT_DEFAULT = "只标光模块和它的插槽；不要标托盘整体、不要标线缆和标定板"


def get(path: str, timeout: int = 20) -> dict:
    with urllib.request.urlopen(API + path, timeout=timeout) as r:
        return json.loads(r.read().decode())


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", default="arm")
    ap.add_argument("--hint", default=HINT_DEFAULT)
    ap.add_argument("--no-vlm", action="store_true", help="跳过真调大模型(只验删除/恢复)")
    a = ap.parse_args()
    cam = a.cam

    bx = get("/boxes?cam=%s" % cam)
    if not bx.get("ok"):
        print("✗ /boxes 不可用: %s" % bx.get("msg"))
        return 1
    kinds = {}
    for b in bx["boxes"]:
        kinds[b["kind"]] = kinds.get(b["kind"], 0) + 1
    print("① /boxes: 框 %d 个 (%s) · 3D=%s 2D=%s · 已删=%s"
          % (len(bx["boxes"]), kinds, bx.get("n_3d"), bx.get("n_2d"), bx.get("deleted")))
    three = next((b for b in bx["boxes"] if b["kind"] == "3d" and b.get("corners")), None)
    print("   首个 3D 线框: %s · 角点 %d 个 · 深度 %smm · 像素框 %s"
          % (three["id"] if three else "无", len([c for c in (three or {}).get("corners") or [] if c]),
             (three or {}).get("z_mm"), [int(v) for v in (three or {}).get("xyxy", [])]))
    if not three:
        print("✗ 没有 3D 线框可测（仿真元素生成了吗 / 目标在视锥外?）")
        return 1

    # ② 删除 → 服务自报计数
    tgt = three["id"]
    r = post("/boxes/delete", {"cam": cam, "ids": [tgt]})
    time.sleep(1.4)
    after = get("/boxes?cam=%s" % cam)
    gone = all(b["id"] != tgt for b in after["boxes"])
    print("② 删除 %s → %s" % (tgt, str(r.get("msg"))[:60]))
    print("   删后: 框 %d · 3D=%s (删前 %s) · 该框已不在清单: %s · 已删清单 %s"
          % (len(after["boxes"]), after.get("n_3d"), bx.get("n_3d"), gone, after.get("deleted")))

    # ③ 恢复
    r2 = post("/boxes/restore", {"cam": cam, "ids": [tgt]})
    time.sleep(1.4)
    back = get("/boxes?cam=%s" % cam)
    print("③ 恢复 → %s · 该框回到画面: %s"
          % (str(r2.get("msg"))[:40], any(b["id"] == tgt for b in back["boxes"])))

    # ④ 带提示词重新标注
    if not a.no_vlm:
        print("④ 触发 L5 带提示词重新标注（提示词:「%s」）…" % a.hint[:36])
        post_gen = get("/gen?kind=vlm&cam=%s&hint=%s" % (cam, urllib.parse.quote(a.hint)))
        print("   端点回: %s" % post_gen.get("msg"))
        t0 = time.time()
        last = None
        while time.time() - t0 < 300:
            time.sleep(5)
            g = get("/scene.json").get("_gen") or {}
            if not g.get("busy"):
                last = g.get("last")
                break
        spec = get("/scene.json")
        sm = (spec.get("sources") or {}).get("vlm") or {}
        vl = [b for b in (((spec.get("cameras") or {}).get(cam) or {}).get("boxes") or [])
              if b.get("origin") == "vlm"]
        print("   %.0fs · %s" % (time.time() - t0, last))
        print("   规格记录: hint=「%s」 negatives=%s model=%s"
              % ((sm.get("hint") or "")[:50], sm.get("negatives"), sm.get("model")))
        print("   新一轮 vlm 框 %d 个: %s" % (len(vl), ", ".join(b.get("label", "?") for b in vl)))
    else:
        print("④ (--no-vlm 跳过)")

    # ⑤ 恢复现场: 清空删除清单
    r3 = post("/boxes/restore", {"cam": cam, "ids": []})
    time.sleep(1.0)
    print("⑤ 清空删除清单 → %s · 最终已删=%s"
          % (str(r3.get("msg"))[:30], get("/boxes?cam=%s" % cam).get("deleted")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
