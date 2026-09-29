# -*- coding: utf-8 -*-
"""帧来源 —— 与叠加/推流**同一真源**(别各读一处)

口径: 分割必须吃**未加工的原始帧**(不是叠加帧), 否则掩膜会把自己画上去的框当物体。

⚠️ 踩过的坑: `scene_overlay.fetch_frame(cam, port, path)` 里 `path` 是**本地文件路径**,
   传 "snapshot/local.jpg" 会被当磁盘路径读 → 静默拿 None。要取 HTTP 端点就得自己发请求,
   所以这里直连 `http://host:port/<端点>` 并**把来源串带回**(取证要能追是哪一台哪一路)。
"""
from __future__ import annotations

import os

import numpy as np

SNAPSHOT_PORT = int(os.environ.get("ZMAX_SNAPSHOT_PORT", "8791"))
SNAPSHOT_HOST = os.environ.get("ZMAX_SNAPSHOT_HOST", "127.0.0.1")


def http_get(path: str, host: str = SNAPSHOT_HOST, port: int = SNAPSHOT_PORT,
             timeout: float = 10.0) -> bytes | None:
    """从推流服务取一路端点的原始字节 (path 形如 'snapshot/local.jpg')"""
    import urllib.error
    import urllib.request
    url = "http://%s:%d/%s" % (host, port, path.lstrip("/"))
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read() if r.status == 200 else None
    except Exception:                                                       # noqa: BLE001
        return None


def grab_frame(cam: str = "local", port: int = SNAPSHOT_PORT, path: str = "") -> tuple[np.ndarray | None, str]:
    """抓**原始**帧 → (BGR ndarray, 说明)。说明串永远带来源(取证要能追)"""
    import cv2
    for p in ([path] if path else ["snapshot/%s.jpg" % cam, "%s.jpg" % cam]):
        blob = http_get(p, port=port)
        if not blob:
            continue
        a = cv2.imdecode(np.frombuffer(blob, np.uint8), cv2.IMREAD_COLOR)
        if a is not None and a.size:
            return a, "http://%s:%d/%s (%dB, %dx%d)" % (SNAPSHOT_HOST, port, p, len(blob), a.shape[1], a.shape[0])
    return None, "推流服务 %s:%d 取不到 %s 的原始帧(试过 snapshot/%s.jpg / %s.jpg)" % (
        SNAPSHOT_HOST, port, cam, cam, cam)


def read_image(path: str) -> np.ndarray:
    """读本地图片 (存档帧取证用)"""
    import cv2
    a = cv2.imread(path, cv2.IMREAD_COLOR)
    if a is None:
        raise FileNotFoundError("读不到图: %s" % path)
    return a
