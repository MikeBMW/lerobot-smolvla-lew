#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""image_health_probe.py — 相机/图像链路像素级取证 (跑一次就知道"图到底黑不黑")

用法:
    python3 image_health_probe.py <文件或URL> [更多文件/URL ...]
例:
    python3 image_health_probe.py /tmp/now.png
    python3 image_health_probe.py "http://192.168.23.23:10082/picture?grab=1" /tmp/ref_bright.png
    python3 image_health_probe.py --pair a.png b.png      # 额外给出两图差分(证明是实时采集)

输出: 大小/md5/格式/尺寸/mean/std/min/max/低灰阶桶/中心与四角统计 + 判定(全黑|偏暗|正常)
判定口径: max<=12 且 mean<8 → 全黑(只在拍但进光≈0); mean<25 → 偏暗; 否则正常。
依赖: numpy + Pillow (GUI venv 里都有: <repo>/gui-venv311/bin/python 亦可)。
"""
import hashlib
import io
import sys
import urllib.request

import numpy as np
from PIL import Image


def _png_header(b):
    if b[:8] != b"\x89PNG\r\n\x1a\n":
        return "非 PNG"
    import struct
    w, h = struct.unpack(">II", b[16:24])
    return "PNG %dx%d bitdepth=%d colortype=%d" % (w, h, b[24], b[25])


def grab(src):
    """URL 或本地路径 → (bytes, 描述)"""
    if src.startswith("http://") or src.startswith("https://"):
        with urllib.request.urlopen(src, timeout=60) as r:
            return r.read(), src
    with open(src, "rb") as f:
        return f.read(), src


def analyze(raw, tag):
    print("=" * 74)
    print("%s  %d bytes  md5=%s" % (tag, len(raw), hashlib.md5(raw).hexdigest()))
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
        a = np.asarray(im).astype(np.float32)
        f = a
        mean, std, mn, mx = float(f.mean()), float(f.std()), float(f.min()), float(f.max())
        if mx <= 12 and mean < 8:
            v = "⚠️ 全黑: 设备在拍但进光≈0 — 查光源/镜头盖/遮挡/曝光"
        elif mean < 25:
            v = "⚠️ 偏暗: 进光不足"
        else:
            v = "✅ 正常"
        print("  头部: %s | PIL %s %s %s" % (_png_header(raw), im.format, im.mode, im.size))
        print("  全图 mean=%.3f std=%.3f min=%.0f max=%.0f  最低桶占比=%.5f" %
              (mean, std, mn, mx, float((a < 32).mean())))
        print("  8 桶直方图: %s" % np.histogram(a, bins=8, range=(0, 255))[0].tolist())
        h, w = a.shape[:2]
        cy, cx = h // 2, w // 2
        for nm, sl in (("中心200x200", (slice(max(0, cy - 100), cy + 100), slice(max(0, cx - 100), cx + 100))),
                       ("左上100x100", (slice(0, 100), slice(0, 100))),
                       ("右下100x100", (slice(-100, None), slice(-100, None)))):
            c = f[sl]
            print("  %-12s mean=%7.3f std=%6.3f max=%.0f" % (nm, c.mean(), c.std(), c.max()))
        print("  ⇒ 判定: %s" % v)
        return a
    except Exception as e:                                                  # noqa: BLE001
        print("  解析失败: %s: %s" % (type(e).__name__, e))
        return None


def main():
    args = [a for a in sys.argv[1:]]
    pair = "--pair" in args
    args = [a for a in args if a != "--pair"]
    if not args:
        print(__doc__)
        return 2
    arrays = []
    for s in args:
        try:
            raw, tag = grab(s)
        except Exception as e:                                              # noqa: BLE001
            print("!! 取图失败 %s: %s" % (s, e))
            continue
        arrays.append(analyze(raw, tag))
    if pair and len(arrays) == 2 and all(a is not None for a in arrays):
        d = arrays[1] - arrays[0]
        print("=" * 74)
        print("两帧差分: mean=%.4f std=%.4f 非零像素占比=%.4f max|d|=%.0f" %
              (d.mean(), d.std(), float((d != 0).mean()), float(np.abs(d).max())))
        print("  非零像素 >0 ⇒ 传感器在实时重新曝光(不是静态占位图 / 不是同一张缓存)")
        print("  非零像素 =0 ⇒ 两次拿到同一张(可能读的是缓存图; 用 ?grab=1 现场重拍验证)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
