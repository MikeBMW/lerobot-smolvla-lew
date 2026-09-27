#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_aoi_autograb_branch.py — 单测「工控机没照片 → 自动取景」这条分支(不碰真产线)。

现场实录(2026-09-27): 10082 空闲时 `GET /picture?kind=origin` 返 404「尚无照片: 先 POST
/capture_detect 或 GET /picture?grab=1」⇒ 老倪看到的那一格"没有图像"。
这里把"网络"换成假的(第一次 404, 带 grab 的那次给一张真图), 验证 __aoi_worker__ 会自己补拍。

判据: ① 假 404 被识别成"没照片" ② 自动取景真的发出了带 grab=1 的请求
      ③ 拍到的图进了帧槽(判据图 + 整板缩图两路) ④ note 上打了 auto_grab=True
"""
import io
import json
import sys
import threading
import time
import urllib.error

import cv2
import numpy as np

sys.path.insert(0, "/home/ubuntu/zmax_rel/tools")
import cam_live_stream as C                                                      # noqa: E402

CALLS = []
STOP_AT = time.time() + 2.2


class FakeResp(io.BytesIO):
    def __init__(self, data, status=200):
        super().__init__(data)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def make_png():
    img = np.zeros((300, 400, 3), np.uint8)
    img[:] = (40, 90, 160)
    cv2.rectangle(img, (60, 60), (340, 240), (230, 230, 230), -1)
    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes()


PNG = make_png()


def fake_urlopen(req, timeout=None):
    url = req.full_url if hasattr(req, "full_url") else str(req)
    CALLS.append(url)
    if time.time() > STOP_AT:
        C._STOP.set()
    if "grab=1" in url:
        return FakeResp(PNG, 200)                       # 现拍成功 → 直接给图片字节
    raise urllib.error.HTTPError(
        url, 404, "Not Found", {},
        io.BytesIO(json.dumps({"code": 404,
                               "msg": "尚无照片: 先 POST /capture_detect 或 GET /picture?grab=1"}
                              ).encode()))


_orig = C.urllib.request.urlopen
C.urllib.request.urlopen = fake_urlopen
C._AOI_AUTO[10082] = True
C._AOI_AUTO_AT[10082] = 0.0
C._STOP.clear()
try:
    th = threading.Thread(target=C._aoi_worker,
                          args=(10082, "aoi_ut", 4.0, "origin", True, False, "aoi_ut_raw"),
                          daemon=True)
    th.start()
    th.join(timeout=6.0)
finally:
    C._STOP.set()
    C.urllib.request.urlopen = _orig

note = C._AOI_INFO.get(10082, {})
jpg, _seq, _ts, _src, _kb = C._get("aoi_ut")
rawjpg, _s2, _t2, _s3, _k2 = C._get("aoi_ut_raw")
grab_calls = [u for u in CALLS if "grab=1" in u]
c1 = len(grab_calls) >= 1
c2 = bool(note.get("auto_grab"))
c3 = bool(jpg) and bool(rawjpg)
c4 = len(CALLS) >= 2

print("假请求序列:")
for u in CALLS[:6]:
    print("   ", u)
print("判据:")
print("   ① 先请示了不带 grab 的图(会 404):", any("grab=1" not in u for u in CALLS))
print("   ② 自动取景发出了带 grab=1 的现拍:", c1, grab_calls[:1])
print("   ③ 拍到的图进了两路帧槽: 判据图 %d B / 整板缩图 %d B" % (len(jpg), len(rawjpg)))
print("   ④ note 标记 auto_grab:", c2, "| ok=http", note.get("http"), "shape", note.get("shape"))
ok = (c1 and c2 and c3 and c4)
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
