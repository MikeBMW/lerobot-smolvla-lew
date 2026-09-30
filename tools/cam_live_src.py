#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cam_live_src.py — 现场实时流取帧 (8791 cam_live_stream) 的**共用**取帧口。

为什么单独抽出来 (2026-09-28 老倪: 「硬件工具箱 · 摄像头实时画面, 也不是现场摄像头」):
  那个面板原来只认 ① 远端 ECS 快照 datadrive.world/api/snapshot/latest ② Docker tap 落的
  cam_rs.png/cam_local.png —— **都不是本机直连的现场相机画面**。真实现场画面在 8791:
    arm    = 臂上 D405 (Orin, rs_fast_node → 8791 中转)
    local  = 笔记本内置相机
    local2 = MAXHUB 顶视 (现场工位俯视)

口径: 帧龄**取相机自己的出帧时间** (/stats.age_s), 不拿 HTTP 往返时间冒充 (老倪: 实时数据须标帧龄)。
"""
import json
import os
import time
import urllib.request

DEFAULT_BASE = os.environ.get("ZMAX_STREAM", "http://127.0.0.1:8791")

LABELS = {
    "arm": "手臂相机 · 随臂 D405 (Orin, 硬连接)",
    "local": "笔记本相机 (本机 USB)",
    "local2": "MAXHUB 电视机摄像头 (本机 USB)",
    "depth": "手臂相机深度图 (D405)",
}


def label(name: str) -> str:
    return LABELS.get(name, "现场实时流 · %s" % name)


def fetch(name: str, base: "str | None" = None, timeout: float = 3.0):
    """取一帧现场画面 → (bytes, 帧龄s) ; 失败/无帧返回 (None, None)。

    帧龄 = /stats 里该路相机的 age_s (相机出帧时刻到现在); 拿不到就给 None,
    **绝不用 0 或 HTTP 耗时冒充**新鲜度。
    """
    base = (base or DEFAULT_BASE).rstrip("/")
    try:
        with urllib.request.urlopen("%s/snapshot/%s.jpg?_=%d" % (base, name, int(time.time())),
                                    timeout=timeout) as r:
            if r.status != 200:
                return None, None
            b = r.read()
    except Exception:                                                       # noqa: BLE001
        return None, None
    if not b:
        return None, None
    age = None
    try:
        with urllib.request.urlopen("%s/stats" % base, timeout=2) as r:
            st = json.loads(r.read().decode("utf-8", "ignore"))
        entry = (st.get("frames") or st).get(name) or {}
        a = entry.get("age_s")
        age = float(a) if a is not None else None
    except Exception:                                                       # noqa: BLE001
        age = None
    return b, age


def age_txt(age) -> str:
    """帧龄文案: 负龄(时钟回拨)/缺失一律如实写'—', 不当 0 用。"""
    if age is None:
        return "帧龄 —"
    if float(age) < -1.0:
        return "帧龄 负龄(拒用)"
    return "帧龄 %.1fs" % float(age)


if __name__ == "__main__":
    import sys
    for nm in (sys.argv[1:] or ["arm", "local", "local2"]):
        b, a = fetch(nm)
        print("%-7s %s %s" % (nm, ("%d 字节" % len(b)) if b else "取帧失败", age_txt(a)))
