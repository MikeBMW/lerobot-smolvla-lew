#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单帧快照取证: 原帧 vs 叠加帧的差异像素占比 (证明真的画上了, 而不是只有日志)"""
import io
import urllib.request

import numpy as np
from PIL import Image

B = "http://127.0.0.1:8791"


def get(p):
    with urllib.request.urlopen(B + p, timeout=5) as r:
        return r.read()


for src in ("local", "arm"):
    try:
        a = np.asarray(Image.open(io.BytesIO(get("/snapshot/%s.jpg" % src))).convert("RGB"), dtype=np.int16)
        b = np.asarray(Image.open(io.BytesIO(get("/snapshot/overlay_%s.jpg" % src))).convert("RGB"), dtype=np.int16)
        if a.shape != b.shape:
            print("%-6s 尺寸不同: 原%s 叠%s" % (src, a.shape, b.shape))
            continue
        d = np.abs(a - b).max(axis=2)
        diff = float((d > 12).mean()) * 100.0
        print("%-6s %dx%d · 差异像素 %.2f%% · 叠加帧均值 %.1f · 原帧均值 %.1f"
              % (src, b.shape[1], b.shape[0], diff, b.mean(), a.mean()))
        Image.fromarray(b.astype(np.uint8)).save("/tmp/ov_%s_view.png" % src)
        print("       落图: /tmp/ov_%s_view.png" % src)
    except Exception as e:
        print("%-6s 失败: %s" % (src, e))
