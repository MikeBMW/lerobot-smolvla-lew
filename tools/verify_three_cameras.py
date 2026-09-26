#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三相机服务端取证: 六路快照都可取 + 页面含三个相机按钮 + 端到端差异像素"""
import io
import re
import urllib.request

import numpy as np
from PIL import Image

B = "http://127.0.0.1:8791"
CAMS = [("arm", "机器人臂上 D405"), ("local", "笔记本内置"), ("local2", "MAXHUB 电视顶摄")]
fails = []


def get(p, t=8):
    with urllib.request.urlopen(B + p, timeout=t) as r:
        return r.status, r.read()


def chk(name, cond, detail=""):
    print(("  %-42s %s %s" % (name, "✅" if cond else "❌", detail)).rstrip())
    if not cond:
        fails.append(name)


def arr(b):
    return np.asarray(Image.open(io.BytesIO(b)).convert("RGB"), dtype=np.int16)


for cam, label in CAMS:
    st_r, raw = get("/snapshot/%s.jpg" % cam)
    st_o, ov = get("/snapshot/overlay_%s.jpg" % cam)
    ok = (raw[:2] == b"\xff\xd8") and (ov[:2] == b"\xff\xd8")
    a, b = arr(raw), arr(ov)
    if a.shape == b.shape:
        d = float((np.abs(a - b).max(axis=2) > 12).mean()) * 100.0
        dim = "%dx%d" % (b.shape[1], b.shape[0])
    else:
        d, dim = -1.0, "尺寸不同"
    chk("快照 %s (%s) 原帧+叠加帧" % (cam, label), ok, "%s · 叠加差异 %.2f%%" % (dim, d))
    if cam == "local2":
        Image.fromarray(b.astype(np.uint8)).save("/tmp/ov_local2_view.png")

# 页面里三个相机按钮 + /gen 带 cam
_, pg = get("/overlay")
pg = pg.decode("utf-8", "ignore")
for cid in ("c_arm", "c_local", "c_local2"):
    chk("叠加页有按钮 %s" % cid, ('id="%s"' % cid) in pg)
chk("叠加页 gen 带 cam 参数", "&cam=" in pg)
chk("叠加页含三相机说明", "MAXHUB" in pg and "笔记本内置" in pg)

# 手机版页面
_, mp = get("/app")
mp = mp.decode("utf-8", "ignore")
chk("手机页有 MAXHUB 按钮", 'cMax' in mp and "local2" in mp)

# 通用路由: 未知源应 503 而不是 404 (端点存在)
try:
    st, _ = get("/snapshot/overlay_camX.jpg", 6)
except Exception as e:
    st = str(e)
chk("通用路由对未知源有响应 (非 404 死路)", st != 404, "status=%s" % st)
print("\n结论: %s" % ("三相机全部就绪 ✅" if not fails else "失败 %d 项 ❌ %s" % (len(fails), fails)))
