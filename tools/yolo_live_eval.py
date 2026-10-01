#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎯 真机实时帧上的 YOLO 检出评测 (同口径 before/after)

老倪 2026-09-18: 「基于当前的数据和实时图像, 更新训练 YOLO 模型, 直到能看到摄像头前面的光模块」

用途: 把"能不能在**真机实时帧**上看到光模块"变成一个**可量化的数** (不含糊其辞):
  · 采 N 张**新鲜** cam_rs.png (Docker tap 只读落盘, 与 L2 同源) → 冻结成评测集 (不参与训练)
  · 对每个候选权重: 跑真推理 → 统计 检出帧数/总帧数 · peg 置信度 (mean/max) · 框尺寸中位
  · 逐帧写出可视化图 (画框) 供人工目检; 结果落 JSON

用法:
  gui-venv311/bin/python tools/yolo_live_eval.py --frames 40 --out reports/yolo_live_eval_before.json
  gui-venv311/bin/python tools/yolo_live_eval.py --weights a.pt b.pt --imgsz 640 --conf 0.25 \
      --frames-dir /tmp/live_eval_0718 --vis-dir reports/yolo_live_vis_after
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import time

REPO = "/home/ubuntu/zmax"
SHARED = os.environ.get("ZMAX_SS_REMOTE_DIR", "/home/ubuntu/zmax_ss_remote")
DEFAULT_FRESH = os.path.join(SHARED, "cam_rs.png")


def _fp(p: str, s: int = 16) -> bytes:
    """内容指纹(缩放灰度横向梯度二值化) —— 按**内容**判同, 不靠 mtime/size。"""
    import numpy as np
    from PIL import Image
    g = np.asarray(Image.open(p).convert("L").resize((s + 1, s)), dtype=np.float32)
    return (g[:, 1:] > g[:, :-1]).tobytes()


def frame_diversity(frames: list) -> dict:
    """帧多样性: 两两平均绝对差(灰度级)分布 —— 用来判"这批帧是不是等于同一张图"。
    2026-09-30 教训: 16 帧 mean 86.5→86.2 / 亮部 8.63→8.64 / 清晰 406→406 ⇒ 实为同一张静态图,
    两边都 0/16 的对照**没有统计意义**。判据: 中位两两差 < 1.0 灰度级 ⇒ 判为无效评测集。"""
    import itertools
    import numpy as np
    from PIL import Image
    arrs = [np.asarray(Image.open(p).convert("L"), dtype=np.int16) for p in frames]
    ds = [float(np.abs(a - b).mean()) for a, b in itertools.combinations(arrs, 2)]
    ds.sort()
    return {"n_pairs": len(ds), "min": round(ds[0], 3) if ds else None,
            "median": round(ds[len(ds) // 2], 3) if ds else None,
            "max": round(ds[-1], 3) if ds else None,
            "enough": bool(ds and ds[len(ds) // 2] >= 1.0)}


def capture_frames(n: int, out_dir: str, src: str, interval: float = 0.5,
                   min_gap: float = 1.0, max_wait_s: float = 0.0) -> list:
    """采 n 张**内容互不相同**的新鲜帧(落 out_dir, 永久目录, 不复用 /tmp)。

    2026-09-30 踩坑: 原来按 (mtime,size) 去重 + interval 0.12s ⇒ 源头(Orin tap)以固定/微变 mtime
    重写**同一张**图时, 会采到 16 张"看着不同、其实逐像素相同"的帧 ⇒ 对照评测无统计意义; 且默认
    落 /tmp ⇒ 事后不可复现。⇒ 现在: ①按**内容指纹**去重 ②两次采帧至少间隔 min_gap 秒
    ③新帧落盘时打印与上一帧的差异, 让人一眼看出是不是同一张。
    """
    os.makedirs(out_dir, exist_ok=True)
    got, fps = [], set()
    last_t = 0.0
    t0 = time.time()
    budget = max_wait_s if max_wait_s > 0 else max(60.0, n * (min_gap + interval) * 2.5)
    while len(got) < n and time.time() - t0 < budget:
        if time.time() - last_t < min_gap:
            time.sleep(0.05)
            continue
        try:
            os.stat(src)
        except OSError:
            time.sleep(interval)
            continue
        p = os.path.join(out_dir, f"live_{len(got):03d}.png")
        shutil.copyfile(src, p)
        f = _fp(p)
        if f in fps:                                  # 内容与已采帧相同 ⇒ 丢弃(不算一帧)
            os.remove(p)
            time.sleep(interval)
            continue
        if got:
            import numpy as np
            from PIL import Image
            a = np.asarray(Image.open(got[-1]).convert("L"), dtype=np.int16)
            b = np.asarray(Image.open(p).convert("L"), dtype=np.int16)
            print(f"   采到 live_{len(got):03d} · 与上一帧差异 {float(np.abs(a - b).mean()):.2f} 灰度级", flush=True)
        fps.add(f)
        got.append(p)
        last_t = time.time()
    return got


def eval_weights(weights: str, frames: list, imgsz: int, conf: float, vis_dir: str | None,
                 device: str = "") -> dict:
    import numpy as np
    from PIL import Image, ImageDraw
    from ultralytics import YOLO
    m = YOLO(weights)
    m.predict(np.zeros((imgsz, imgsz, 3), dtype=np.uint8), imgsz=imgsz, verbose=False,
              device=device or None)
    names = m.names if isinstance(m.names, dict) else {i: n for i, n in enumerate(m.names)}
    peg_idx = [i for i, n in names.items() if str(n).lower() == "peg"]
    rows, n_hit = [], 0
    confs = []
    if vis_dir:
        os.makedirs(vis_dir, exist_ok=True)
    for p in frames:
        r = m.predict(p, imgsz=imgsz, conf=conf, verbose=False, device=device or None)[0]
        dets = []
        for b in r.boxes:
            ci = int(b.cls[0])
            dets.append({"cls": names.get(ci, str(ci)), "conf": round(float(b.conf[0]), 3),
                         "xyxy": [round(float(v), 1) for v in b.xyxy[0].tolist()]})
        peg = [d for d in dets if d["cls"].lower() == "peg"]
        if peg:
            n_hit += 1
            confs.append(max(d["conf"] for d in peg))
        rows.append({"frame": os.path.basename(p), "n": len(dets), "peg": len(peg), "dets": dets})
        if vis_dir:
            im = Image.open(p).convert("RGB")
            dr = ImageDraw.Draw(im)
            for d in dets:
                x1, y1, x2, y2 = d["xyxy"]
                col = (0, 255, 128) if d["cls"].lower() == "peg" else (255, 200, 0)
                dr.rectangle([x1, y1, x2, y2], outline=col, width=3)
                dr.text((x1 + 3, max(0, y1 - 14)), f"{d['cls']} {d['conf']:.2f}", fill=col)
            im.save(os.path.join(vis_dir, os.path.basename(p)))
    return {"weights": weights, "imgsz": imgsz, "conf": conf, "n_frames": len(frames),
            "frames_with_peg": n_hit, "peg_rate": round(n_hit / max(1, len(frames)), 3),
            "peg_conf_mean": round(sum(confs) / len(confs), 3) if confs else None,
            "peg_conf_max": round(max(confs), 3) if confs else None,
            "classes": names, "peg_class_idx": peg_idx, "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", nargs="*", default=[
        "runs/detect/outputs/yolo_peg/peg_v1/weights/best.pt",
        "runs/detect/outputs/yolo_peg/dr_mix/weights/best.pt",
        "runs/detect/outputs/yolo_annot/annot_0918_0711/weights/best.pt",
        "runs/detect/outputs/yolo_annot/annot_0918_0718/weights/best.pt",
    ])
    ap.add_argument("--frames", type=int, default=40)
    ap.add_argument("--min-gap", type=float, default=1.0,
                    help="两次采帧最小间隔秒(保证帧间真的变了; 2026-09-30 加)")
    ap.add_argument("--max-wait", type=float, default=0.0, help="采帧总预算秒(0=自动)")
    ap.add_argument("--frames-dir", default="")
    ap.add_argument("--src", default=DEFAULT_FRESH)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--device", default="")
    ap.add_argument("--vis-dir", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    os.chdir(REPO)
    # 2026-09-30: 默认落**永久**目录(原来 /tmp ⇒ 评测集事后不可复现, 无法复查那次 0/16)
    fdir = a.frames_dir or os.path.join(
        os.environ.get("ZMAX_DATA", "/home/ubuntu/zmax_data"), "eval_frames",
        "live_" + time.strftime("%m%d_%H%M%S"))
    frames = sorted(glob.glob(os.path.join(fdir, "live_*.png")))
    if not frames:
        print(f"采帧: {a.frames} 张 → {fdir} (源 {a.src})")
        frames = capture_frames(a.frames, fdir, a.src, min_gap=a.min_gap, max_wait_s=a.max_wait)
    print(f"评测集: {len(frames)} 帧 (目录 {fdir})")
    if not frames:
        print("❌ 没采到帧 (真机帧文件不可用?)")
        return 2
    div = frame_diversity(frames)
    print(f"帧多样性: 两两差 min {div['min']} / 中位 {div['median']} / max {div['max']} 灰度级"
          f" ⇒ {'合格 ✓' if div['enough'] else '❌ 不足(这批帧约等于同一张图, 对照评测无效)'}")
    res = {"frames_dir": fdir, "frames": len(frames), "ts": time.strftime("%F %T"),
           "diversity": div, "results": []}
    for w in a.weights:
        if not os.path.isfile(w):
            print(f"  跳过 (不存在): {w}")
            continue
        vd = os.path.join(a.vis_dir, os.path.basename(os.path.dirname(os.path.dirname(w)))) if a.vis_dir else None
        r = eval_weights(w, frames, a.imgsz, a.conf, vd, a.device)
        res["results"].append(r)
        print(f"  {os.path.basename(os.path.dirname(os.path.dirname(w))):22} "
              f"检出peg {r['frames_with_peg']}/{r['n_frames']} 帧 (rate {r['peg_rate']}) · "
              f"conf mean {r['peg_conf_mean']} max {r['peg_conf_max']} · 类别 {list(r['classes'].values())}")
    if a.out:
        json.dump(res, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"→ {a.out}")
    if not div["enough"]:
        print("❌ 判为**无效评测**: 帧多样性不足 ⇒ 不得把本次结果写成'持平/提升/回退'。"
              "请拉开采帧间隔(--min-gap)或改用录制数据。")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
