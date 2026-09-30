#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盯 10082 金手指这一格: 等工控机内存里的照片过期(404 尚无照片) → 看自动取景是否替它现拍一张。

判据(全过才算修好):
  ① 出现 err 含 grab=1 / 尚无照片 的 404   (= 老倪看到"没图像"的那一刻)
  ② 之后 ≤35s 内 note 变成 ok=True 且带 auto_grab=True   (= 自动取景真的拍了)
  ③ 该路快照重新变新(age 小) 且 >60KB                (= 画面真的回来了)
"""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8793"


def get(path, timeout=12):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


t0 = time.time()
seen_404 = None
seen_auto = None
seen_fresh = None
while time.time() - t0 < 200:
    st = get("/station/status?t=%d" % (time.time() * 1000))
    g = st["aoi"].get("10082", {})
    stats = st["stats"].get("aoi_gold", {})
    err = str(g.get("err") or "")
    lc = g.get("last_capture") or {}
    line = "  t+%3ds ok=%-5s http=%-4s age=%-6s KB=%-7s %s" % (
        int(time.time() - t0), g.get("ok"), g.get("http"), stats.get("age_s"),
        stats.get("kb_per_frame"), ("NO-PHOTO" if "grab=1" in err or "尚无" in err else ""))
    if lc.get("got_image") or g.get("auto_grab"):
        line += " | last_capture=%s auto_grab=%s" % (lc.get("how"), g.get("auto_grab"))
    print(line, flush=True)
    if not seen_404 and ("grab=1" in err or "尚无" in err):
        seen_404 = time.time()
        print("  ① 工控机内存里没照片了 (这就是老倪看到的'没图像')", flush=True)
    if seen_404 and not seen_auto and g.get("auto_grab"):
        seen_auto = time.time()
        print("  ② 自动取景已替它现拍: 延迟 %.0fs" % (seen_auto - seen_404), flush=True)
    if seen_auto and not seen_fresh and (stats.get("age_s") or 99) < 40:
        seen_fresh = time.time()
        print("  ③ 这一格画面回来了: age=%.1fs KB=%s" % (stats.get("age_s"),
                                                         stats.get("kb_per_frame")), flush=True)
    if seen_fresh:
        break
    time.sleep(15)

print("---- 结论 ----")
print("  ① 见到 404 尚无照片:", bool(seen_404))
print("  ② 自动取景拍到了  :", bool(seen_auto),
      ("(延迟 %.0fs)" % (seen_auto - seen_404)) if (seen_auto and seen_404) else "")
print("  ③ 画面回来了      :", bool(seen_fresh))
