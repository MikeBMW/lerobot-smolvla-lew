#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aoi_surface_exposure_sweep.py — 现场扫表面相机(10083)曝光/增益, 用**图像实测**选值。

为什么这么做: 该相机 SDK 只有 SetFloatValue, **没有 GetFloatValue** ⇒ "设成功"的回执不等于"画面真变好"
  ⇒ 唯一可信的判据是**同一场景下抓一帧量出来**的统计量。
验收口径(老倪现场口径 + 技能里的历史口径):
  · 饱和(>=250)占比 目标 **≤5%**(金手指那侧的验收线; 表面同口径参考)
  · mean 目标 **60~200**(太暗看不清纹理 / 太亮丢细节)
  · 不做任何假设: 每个候选值都真抓一帧、真量; 全部打表, 由人拍板。
只读/低影响: 用 `GET /picture?kind=origin&grab=1`(**不落盘**), 每档间隔 1.2s。

用法:
  ./gui-venv311/bin/python tools/aoi_surface_exposure_sweep.py --host 192.168.23.23 \
      --cands 80000,40000,20000,12000,8000 --gain 0  [--apply-best]
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request

import cv2
import numpy as np


def _get(url: str, timeout: float = 20.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read()


def _post(url: str, timeout: float = 20.0):
    req = urllib.request.Request(url, data=b"", method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def measure(host: str, port: int = 10083):
    """抓一帧(不落盘)并量: 均值/σ/饱和占比/暗部占比/Tenengrad。"""
    # ⚠️ 实测(2026-09-30): 该机 `origin&grab=1` **偶发失败**(6 连打 2 次 500「抓帧失败」≈33%)
    #    ⇒ 单次探测不可信, 必须重试; 不重试就会把"随机一次失败"当成"曝光改坏了"。
    st, raw, last = 0, b"", ""
    for _t in range(6):
        try:
            st, raw = _get("http://%s:%d/picture?kind=origin&grab=1" % (host, port), timeout=40)
        except Exception as e:                                                       # noqa: BLE001
            st, raw = 0, b""
            last = str(e)[:60]
        if st == 200 and len(raw) > 5000:
            break
        last = "HTTP %s / %dB %s" % (st, len(raw), raw[:60].decode("utf-8", "replace"))
        time.sleep(2.0)
    if st != 200 or len(raw) < 5000:
        return None, "重试 6 次仍未出图: " + last
    im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if im is None:
        return None, "解码失败"
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    band = g
    try:      # 按 /crop_info 的 band_y 取"模块所在带" —— 验收口径是带内饱和≤5%, 整幅会被白底稀释
        _st, _raw = _get("http://%s:%d/crop_info" % (host, port), timeout=8)
        _b = json.loads(_raw).get("band_y")
        if _b and len(_b) == 2 and 0 < _b[0] < _b[1] <= g.shape[0]:
            band = g[int(_b[0]):int(_b[1]), :]
    except Exception:
        pass
    return {"band": band.mean() * 0 + band.shape[0], "w": im.shape[1], "h": im.shape[0],
            "band_mean": round(float(band.mean()), 1), "band_sat_pct": round(100.0 * float((band >= 250).mean()), 2),
            "mean": round(float(g.mean()), 1),
            "std": round(float(g.std()), 1),
            "sat_pct": round(100.0 * float((g >= 250).mean()), 2),
            "dark_pct": round(100.0 * float((g <= 20).mean()), 2),
            "tenengrad": round(float(cv2.Laplacian(g, cv2.CV_64F).var()), 0),
            "kb": round(len(raw) / 1024.0, 1)}, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="192.168.23.23")
    ap.add_argument("--port", type=int, default=10083)
    ap.add_argument("--cands", default="80000,40000,20000,12000,8000", help="曝光候选(微秒), 逗号分隔")
    ap.add_argument("--gain", type=float, default=None, help="固定增益(不给则不动增益)")
    ap.add_argument("--apply-best", action="store_true", help="按判据选最优并落盘(否则只打表)")
    a = ap.parse_args()
    base = "http://%s:%d" % (a.host, a.port)

    st, raw = _get(base + "/exposure")
    now = json.loads(raw)
    print("══ 起点: /exposure → %s" % json.dumps(now, ensure_ascii=False)[:200])
    if now.get("us") is None:
        print("   ✗ 该端口还没有 /exposure(v13 未上线?)"); return 2

    rows = []
    for us in [float(x) for x in a.cands.split(",") if x.strip()]:
        q = "%s/exposure?us=%g" % (base, us)
        if a.gain is not None:
            q += "&gain=%g" % a.gain
        try:
            st, raw = _post(q)
            r = json.loads(raw)
        except Exception as e:                                                       # noqa: BLE001
            print("   ✗ us=%-7g 设置失败: %s" % (us, str(e)[:60])); continue
        time.sleep(1.2)                      # 让相机真按新参数出图
        m, err = measure(a.host, a.port)
        if m is None:
            print("   ✗ us=%-7g ok=%s 但抓帧失败: %s" % (us, r.get("ok"), err)); continue
        rows.append((us, r.get("ok"), r.get("reopened"), m))
        print("   us=%-7g ok=%-5s → 带内(模块) mean %6.1f 饱和 %5.2f%% | 整幅 mean %6.1f 饱和 %5.2f%% 暗部 %5.2f%% | 清晰 %8.0f"
              % (us, r.get("ok"), m["band_mean"], m["band_sat_pct"], m["mean"], m["sat_pct"], m["dark_pct"], m["tenengrad"]))

    if not rows:
        print("   ✗ 没拿到任何有效档"); return 3
    # 选值: 先满足 饱和<=5% 且 60<=mean<=200, 再在合格里取 mean 最接近 130(中间) 的
    good = [(us, m) for us, ok, rp, m in rows if m["band_sat_pct"] <= 5.0 and 60.0 <= m["band_mean"] <= 200.0]
    pick = min(good, key=lambda t: abs(t[1]["band_mean"] - 130.0)) if good else (min(rows, key=lambda t: (t[3]["band_sat_pct"], -t[3]["band_mean"]))[0], None)
    print("\n   合格档(带内饱和<=5%% 且 60<=带内mean<=200): %s"
          % (", ".join("us=%g(带内 mean %.1f/饱和 %.2f%%)" % (u, m["band_mean"], m["band_sat_pct"]) for u, m in good) or "无"))
    print("   ★ 建议: us=%g%s" % (pick[0] if isinstance(pick, tuple) else pick, "" if good else " (无合格档, 取饱和最低者)"))
    if a.apply_best:
        st, raw = _post("%s/exposure?us=%g" % (base, pick[0] if isinstance(pick, tuple) else pick))
        print("   已应用: %s" % json.dumps(json.loads(raw), ensure_ascii=False)[:200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
