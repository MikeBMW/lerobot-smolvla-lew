#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aoi_gold_region_label.py — 金手指「区域」数据集自动打标 (给 YOLO 目标检测模块用)

思路: 模板法几何(/region 同一份算法, 本地 tools/gf_aoi/gf_crop.py)已经在原始图上**精确**给出金手指区域,
      直接把它当**真值框**去标注 → 人不用画框, 也不会标歪; 低可信样本(score/金覆盖不达标)单独挑出来人工复核。

产出 (标准 YOLO 检测数据集):
    <out>/images/{train,val}/*.png        原图(拷贝或软链)
    <out>/labels/{train,val}/*.txt        `0 cx cy w h` (归一化, 类别0=gold_finger_region)
    <out>/data.yaml                       ultralytics 训练配置
    <out>/manifest.jsonl                  每张: 源文件/score/金覆盖/角度/框, 便于筛低可信与复现

用法:
    python3 tools/aoi_gold_region_label.py --src <图片目录> --out data/gf_region_ds
    python3 tools/aoi_gold_region_label.py --fetch 60 --out data/gf_region_ds   # 从 10082 现场抓(会真拍照!)
"""
import argparse
import glob
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "gf_aoi"))
import cv2                                    # noqa: E402
from gf_crop import GoldFingerCropper         # noqa: E402

TEMPLATE = os.path.join(HERE, "gf_aoi", "templates", "gf_strip_template.png")
CLASS_NAMES = ["gold_finger_region"]


def label_one(cropper, img_path, out, split, min_score=0.90, min_cover=0.45, copy=True):
    im = cv2.imread(img_path)
    if im is None:
        return None
    crop, info = cropper.crop(im)
    if info.get("method") != "template":
        return {"file": os.path.basename(img_path), "ok": False, "reason": "非模板法(兜底) → 不标"}
    q = info.get("quality") or {}
    sc, cov = info.get("score"), q.get("gold_cover")
    if (sc is not None and sc < min_score) or (cov is not None and cov < min_cover):
        return {"file": os.path.basename(img_path), "ok": False,
                "reason": f"低可信 score={sc} cover={cov} → 人工复核", "score": sc, "cover": cov}
    s = info["strip"]
    cx, cy, w, h = s["cx"], s["cy"], s["w"], s["h"]
    H, W = im.shape[:2]
    # YOLO 用轴对齐框(旋转框版另说): 由定向框的四边形外接矩形给出
    import numpy as np
    R = cv2.getRotationMatrix2D((0, 0), s.get("angle", 0.0), 1.0)
    pts = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    xs = [cx + R[0, 0] * dx + R[0, 1] * dy for dx, dy in pts]
    ys = [cy + R[1, 0] * dx + R[1, 1] * dy for dx, dy in pts]
    bx, by = min(xs), min(ys)
    bw, bh = max(xs) - bx, max(ys) - by
    bx = max(0.0, bx); by = max(0.0, by)
    bw = min(bw, W - bx); bh = min(bh, H - by)
    line = "0 %.6f %.6f %.6f %.6f\n" % ((bx + bw / 2) / W, (by + bh / 2) / H, bw / W, bh / H)
    base = os.path.splitext(os.path.basename(img_path))[0]
    os.makedirs(os.path.join(out, "images", split), exist_ok=True)
    os.makedirs(os.path.join(out, "labels", split), exist_ok=True)
    with open(os.path.join(out, "labels", split, base + ".txt"), "w") as f:
        f.write(line)
    dst = os.path.join(out, "images", split, os.path.basename(img_path))
    if not os.path.exists(dst):
        (shutil.copy2 if copy else os.symlink)(img_path, dst)
    return {"file": os.path.basename(img_path), "ok": True, "split": split, "score": sc,
            "cover": cov, "angle": s.get("angle"), "bbox_xywh": [round(v, 1) for v in (bx, by, bw, bh)],
            "norm": line.strip(), "quality": q}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", help="图片目录 (Finger_Image_*.png)")
    ap.add_argument("--fetch", type=int, default=0, help="从 10082 现场抓 N 张(会真拍照, 需现场许可)")
    ap.add_argument("--out", default="data/gf_region_ds")
    ap.add_argument("--val-ratio", type=float, default=0.25)
    ap.add_argument("--min-score", type=float, default=0.90)
    ap.add_argument("--min-cover", type=float, default=0.45)
    a = ap.parse_args()

    imgs = []
    if a.fetch:
        import urllib.request
        os.makedirs("/tmp/gf_fetch", exist_ok=True)
        for i in range(a.fetch):
            with urllib.request.urlopen("http://192.168.23.23:10082/picture", timeout=30) as r:
                p = f"/tmp/gf_fetch/fetch_{i:04d}.png"
                open(p, "wb").write(r.read())
            imgs.append(p)
    else:
        assert a.src, "给 --src 目录或 --fetch N"
        imgs = sorted(glob.glob(os.path.join(a.src, "*.png")) + glob.glob(os.path.join(a.src, "*.jpg")))
    assert imgs, "没找到图片"

    cr = GoldFingerCropper(TEMPLATE, canonical_w=1600, canonical_h=220, margin_x=0.03, margin_y=0.04,
                           preserve_aspect=True)
    os.makedirs(a.out, exist_ok=True)
    man = open(os.path.join(a.out, "manifest.jsonl"), "w", encoding="utf-8")
    ok = skipped = 0
    n_val = max(1, int(round(len(imgs) * a.val_ratio))) if len(imgs) > 3 else 0
    for idx, p in enumerate(imgs):
        split = "val" if idx % max(1, int(1 / max(a.val_ratio, 0.01))) == 0 and n_val else "train"
        r = label_one(cr, p, a.out, split, a.min_score, a.min_cover)
        if r is None:
            continue
        man.write(json.dumps(r, ensure_ascii=False) + "\n")
        if r.get("ok"):
            ok += 1
            print(f"  ✅ {r['file']} → {r['split']}  score={r['score']} cover={r['cover']} "
                  f"角度={r['angle']}° 框={r['bbox_xywh']}")
        else:
            skipped += 1
            print(f"  ⚠️ {r['file']} 跳过: {r['reason']}")
    man.close()
    import yaml
    cfg = {"path": os.path.abspath(a.out), "train": "images/train", "val": "images/val",
           "names": {i: n for i, n in enumerate(CLASS_NAMES)}}
    with open(os.path.join(a.out, "data.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True)
    print(f"\n完成: 标好 {ok} 张 / 跳过 {skipped} 张 → {a.out}")
    print(f"  data.yaml: {json.dumps(cfg, ensure_ascii=False)}")
    print(f"  训练: yolo detect train data={os.path.join(a.out,'data.yaml')} model=yolo11n.pt epochs=100 imgsz=960")
    return 0


if __name__ == "__main__":
    sys.exit(main())
