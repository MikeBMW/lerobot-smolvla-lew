#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
laptop_guide_lines.py — 在**笔记本摄像头(local 路)** 画面上画"辅助水平线", 用来标出横梁围成的内部空间层次。
老倪 2026-09-30: 「定位桌子上面、横梁内部的空间位置, 给我画几条辅助水平线, 叠加到笔记本摄像头的画面上」

口径:
  · 线位置 = 像素取证(Hough/亮度台阶) 定的 y; 模型(VL)只给语义"这条线是哪根梁的哪个面"
  · 落地通道 = data/scene/overlay_spec.json → cameras.local.boxes, 元素 {"origin":"guide","xyxy":[0,y-1,640,y+2],"no_label":true}
    (渲染器 2D 分支 cv2.rectangle 线宽 2; 细盒即水平线; no_label 保证不出现"白底黑字"标签芯片)
  · 因为 2D 分支有退化判定 (x2-x1<2 or y2-y1<2 跳过) ⇒ 盒高取 3px
用法:
  gui-venv311/bin/python tools/laptop_guide_lines.py --lines "264:空间顶(横梁下沿),466:台面" --deploy
"""
import argparse, json, os, re, shutil, sys, time
import urllib.request
import cv2
import numpy as np

BASE = "http://127.0.0.1:8791"
Q = "?k=zmax-live"
SPEC = "/home/ubuntu/zmax_rel/data/scene/overlay_spec.json"
GUIDE_BGR = (255, 255, 0)          # 亮青, 与 ORIGIN_STYLE["guide"] 一致


def get(url, binary=True, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "zmax-guide/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = r.read()
    return d if binary else d.decode()


def frame(name="local"):
    return cv2.imdecode(np.frombuffer(get("%s/snapshot/%s.jpg%s" % (BASE, name, Q)), np.uint8), cv2.IMREAD_COLOR)


def parse_lines(s):
    out = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^\s*(\d+)\s*[:：]\s*(.*)$", part)
        if not m:
            raise SystemExit("✗ 行格式应为 y:说明, 收到 %r" % part)
        out.append((int(m.group(1)), m.group(2).strip()))
    return out


def deploy(lines, W, H):
    spec = json.load(open(SPEC, encoding="utf-8"))
    bak = "/home/ubuntu/zmax_data/overlay_spec.bak_guide_%s.json" % time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(SPEC, bak)
    cams = spec.setdefault("cameras", {})
    loc = cams.setdefault("local", {})
    old = [b for b in loc.get("boxes", []) if b.get("origin") == "guide"]
    loc["boxes"] = [b for b in loc.get("boxes", []) if b.get("origin") != "guide"]
    for y, why in lines:
        loc["boxes"].append({"origin": "guide", "label": "辅助水平线 y=%d %s" % (y, why),
                             "xyxy": [0.0, float(y - 1), float(W), float(y + 2)], "no_label": True})
    dec = spec.setdefault("deleted", {}).setdefault("local", [])
    for b in old:
        x1, y1, x2, y2 = b["xyxy"]
        key = "%s|y=%d" % (b.get("origin"), int((y1 + y2) / 2))
        if key not in dec:
            dec.append(key)
    loc["by_origin"] = {}
    for b in loc["boxes"]:
        loc["by_origin"][b.get("origin")] = loc["by_origin"].get(b.get("origin"), 0) + 1
    spec["ts"] = time.time()
    spec["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    src = spec.setdefault("sources", {}).setdefault("guide", {})
    src.update({"by": "tools/laptop_guide_lines.py", "cam": "local",
                "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "n": len(lines), "ys": [y for y, _ in lines],
                "note": "辅助水平线: 标出横梁围成的内部空间层次; 位置由像素取证定, 语义由 L5/子代理给"})
    json.dump(spec, open(SPEC, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("   ✓ 已写入规格: local.boxes 中 guide 元素 %d 个 (旧 %d 个进 deleted)" % (len(lines), len(old)))
    print("   ✓ 备份 %s" % bak)
    return True


def verify(lines, W, H, sleep=2.2):
    time.sleep(sleep)
    a = frame("local")
    b = frame("overlay_local")
    if a is None or b is None:
        print("   ✗ 取帧失败, 无法核验"); return
    print("   ── 端到端核验(叠加帧 vs 原始帧, 只看 guide 色系) ──")
    ok = 0
    for y, why in lines:
        band = slice(max(0, y - 3), min(H, y + 4))
        ma = ((np.abs(a[band].astype(int) - np.array(GUIDE_BGR)).sum(2)) < 170).sum()
        mb = ((np.abs(b[band].astype(int) - np.array(GUIDE_BGR)).sum(2)) < 170).sum()
        # 服务可能缩放: 按比例映射 y
        hit = mb - ma
        print("      y=%-4d %-22s 叠加帧青 px %5d / 原始 %5d ⇒ 增量 %+5d %s" % (
            y, why, mb, ma, hit, "✓" if hit > 0.5 * W else "✗(线没画上或颜色不符)"))
        ok += 1 if hit > 0.5 * W else 0
    print("   小结: %d/%d 条线在实时叠加帧中可见" % (ok, len(lines)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", default="", help='逗号分隔 "y:说明", 例 "264:空间顶(横梁下沿),466:台面"')
    ap.add_argument("--deploy", action="store_true", help="写入 overlay_spec.json 使其叠加到工位总览/叠加页")
    ap.add_argument("--clear", action="store_true", help="清掉已有的 guide 线")
    ap.add_argument("--out", default="/home/ubuntu/zmax_data/feishu_send/laptop_guide_lines.jpg")
    ap.add_argument("--no-colorcheck", action="store_true")
    a = ap.parse_args()

    img = frame("local")
    if img is None:
        raise SystemExit("✗ 取不到 local 帧 (服务在跑吗? /snapshot/local.jpg)")
    H, W = img.shape[:2]
    print("   帧 %dx%d" % (W, H))

    if a.clear:
        deploy([], W, H); print("   ✓ 已清空 guide 线"); return
    if not a.lines:
        raise SystemExit("✗ 需要 --lines 或 --clear")
    lines = parse_lines(a.lines)
    print("   将画 %d 条水平线: %s" % (len(lines), lines))

    # ① 离线渲染(给老倪看的那张)
    vis = img.copy()
    for i, (y, why) in enumerate(lines):
        cv2.line(vis, (0, y), (W - 1, y), GUIDE_BGR, 2, cv2.LINE_AA)
        cv2.putText(vis, "L%d y=%d" % (i + 1, y), (5, max(11, y - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, GUIDE_BGR, 1, cv2.LINE_AA)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    cv2.imwrite(a.out, vis, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    print("   ✓ 渲染图 %s" % a.out)

    # ② 落地 + 核验
    if a.deploy:
        deploy(lines, W, H)
        if not a.no_colorcheck:
            verify(lines, W, H)
    print("FILE " + a.out)


if __name__ == "__main__":
    main()
