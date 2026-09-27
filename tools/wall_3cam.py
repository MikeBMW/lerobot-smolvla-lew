#!/usr/bin/env python3
"""三相机拼图 —— 把现场 3 个相机(臂上 D405 / 笔记本 / MAXHUB) + 带框叠加版拼成一张图。

为什么要有这个:
  手机在外网打不开内网地址(10.x 是私有网段), 而公网通道一次只方便传**一张**图。
  把 3 个相机拼成一张 ⇒ 公网页/飞书/隧道任一条通道都只搬一张图, 就知道现场全貌。
  每格都打上 **帧率 + 帧龄 + 拍照时间**, 画面自身带状态(老倪口径: 实时数据必须标时间/帧龄)。

用法:
  python3 tools/wall_3cam.py                     # 出 3 相机拼图 → reports/web/wall_3cam.jpg
  python3 tools/wall_3cam.py --overlay           # 用带检测框的那路(ov_)当上排
  python3 tools/wall_3cam.py --out /tmp/x.jpg --cols 3
  python3 tools/wall_3cam.py --push-url <ECS端点>  # 顺便推到公网(端点由 web 侧提供)
"""
import argparse
import io
import json
import os
import time
import urllib.request

TYPE = "https://datadrive.world"          # 仅用于提示, 不主动访问
CAMS = [("arm", "臂上 D405 (Orin)"), ("local", "笔记本内置"), ("local2", "MAXHUB 顶视")]


def _get(url, timeout=8):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def _stats(port):
    try:
        return json.loads(_get("http://127.0.0.1:%d/stats" % port))
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--out", default="reports/web/wall_3cam.jpg")
    ap.add_argument("--cols", type=int, default=3, help="3=横向一排(默认, 无空格) 1=竖排(手机)")
    ap.add_argument("--cell-w", type=int, default=640)
    ap.add_argument("--overlay", action="store_true", help="用带框的 ov_ 那路")
    ap.add_argument("--quality", type=int, default=80)
    ap.add_argument("--push-url", default="", help="可选: POST 到公网端点(由 web 侧提供)")
    a = ap.parse_args()

    from PIL import Image, ImageDraw
    _RS = getattr(Image, "Resampling", Image)          # Pillow 10+ 把常量挪进 Resampling
    LANCZOS = getattr(_RS, "LANCZOS", 1)
    st = _stats(a.port)
    tiles = []
    for key, label in CAMS:
        name = ("ov_" + key) if a.overlay else key
        s = st.get(name, {}) or {}
        fps, age = s.get("fps"), s.get("age_s")
        try:
            raw = _get("http://127.0.0.1:%d/snapshot/%s.jpg" % (a.port, name))
            im = Image.open(io.BytesIO(raw)).convert("RGB")
        except Exception as e:                                             # noqa: BLE001
            im = Image.new("RGB", (a.cell_w, int(a.cell_w * 0.75)), (18, 22, 28))
            d0 = ImageDraw.Draw(im)
            d0.text((12, 12), "%s 取帧失败: %s" % (label, str(e)[:60]), fill=(255, 120, 120))
        w = a.cell_w
        im = im.resize((w, max(1, int(im.height * w / im.width))), LANCZOS)
        cap = "%s   %s   %s" % (
            label,
            ("%.1ffps" % fps) if fps else "fps -",
            ("帧龄 %.1fs" % age) if isinstance(age, (int, float)) else "帧龄 -",
        )
        tiles.append((im, cap, bool(fps and fps > 1 and (age if isinstance(age, (int, float)) else 9e9) < 3)))

    cols = max(1, min(a.cols, len(tiles)))
    rows = (len(tiles) + cols - 1) // cols
    cw = a.cell_w
    ch = max(t[0].height for t in tiles) + 30
    head, foot = 40, 26
    wall = Image.new("RGB", (cw * cols, head + ch * rows + foot), (11, 14, 18))
    dr = ImageDraw.Draw(wall)
    dr.text((12, 12), "Z-MAX \u00b7 \u73b0\u573a 3 \u76f8\u673a", fill=(230, 240, 250))
    for i, (im, cap, ok) in enumerate(tiles):
        cx, cy = i % cols, i // cols
        x, y = cx * cw, head + cy * ch
        wall.paste(im, (x, y + 30))
        dr.rectangle([x, y, x + cw - 1, y + 29], fill=(20, 26, 34))
        dr.text((x + 8, y + 8), cap, fill=(150, 240, 170) if ok else (255, 170, 90))
        dr.rectangle([x, y + 30, x + cw - 1, y + 30 + im.height], outline=(40, 48, 58))
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    dr.text((12, wall.height - 18), "\u62cd\u7167\u65f6\u95f4 %s  \u00b7  %dx%d" % (stamp, wall.width, wall.height),
            fill=(140, 155, 170))
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    wall.save(a.out, "JPEG", quality=a.quality)
    print("已生成 %s  %dx%d  %.1fKB" % (a.out, wall.width, wall.height, os.path.getsize(a.out) / 1024))
    for _, cap, ok in tiles:
        print("   %s %s" % ("OK " if ok else "!! ", cap))
    if a.push_url:
        data = open(a.out, "rb").read()
        req = urllib.request.Request(a.push_url, data=data, headers={"Content-Type": "image/jpeg"})
        with urllib.request.urlopen(req, timeout=15) as r:
            print("   推送 %s → HTTP %s" % (a.push_url, r.status))


if __name__ == "__main__":
    main()
