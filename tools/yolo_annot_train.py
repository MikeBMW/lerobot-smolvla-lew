#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""yolo_annot_train.py — 用**标定工程师标好的真机图片**训练/微调 YOLO 检测模型

老倪 2026-09-17: 「yolo 模型可以通过保存的图片进行模型训练」

流程 (先体检再训练, 拒绝脏数据):
  1. 读 data/yolo_annot/dataset/data.yaml → 校验 (图片/标注配对, 类别范围, 坐标范围) —— 有错直接退出 2
  2. 选基座权重: `--base auto` 优先找**现有仿真权重**做域适应微调 (仿真权重在真机 0 检出, 微调是正路);
     找不到就用 --model (默认 yolov8n.pt)
  3. ultralytics 训练 (device 自动: cuda 可用就用 GPU)
  4. 训练后**真推理验证**: 在 val 图上跑 N 张, 打印检出数/置信度 → 证明模型真能识别标定的目标

用法:
  gui-venv311/bin/python tools/yolo_annot_train.py --epochs 100 --imgsz 640 --name annot_v1
  gui-venv311/bin/python tools/yolo_annot_train.py --no-base          # 从 COCO 预训练重头训
  gui-venv311/bin/python tools/yolo_annot_train.py --base outputs/yolo_peg/xxx/weights/best.pt
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import yolo_annot_dataset as yad                                          # noqa: E402

# 候选基座权重: 仿真 peg 检测权重 (域适应起点) —— 真机帧上当前 0 检出, 微调后应显著改善
_BASE_CANDS = [
    "outputs/yolo_peg_full/*/weights/best.pt",
    "outputs/yolo_peg/*/weights/best.pt",
    "outputs/yolo_annot*/**/weights/best.pt",
    "models/yolo*/*.pt", "models/yolo*.pt",
    "runs/detect/**/weights/best.pt",
]


def find_base(repo="."):
    cands = []
    for pat in _BASE_CANDS:
        cands += glob.glob(os.path.join(repo, pat), recursive=True)
    cands = [c for c in cands if os.path.isfile(c)]
    if not cands:
        return None
    return max(cands, key=os.path.getmtime)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(yad.ROOT_DEFAULT, "dataset"))
    ap.add_argument("--root", default=yad.ROOT_DEFAULT, help="标定数据根 (体检用)")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--model", default="yolov8n.pt")
    ap.add_argument("--base", default="auto", help="auto=自动找现有权重微调 / none / 具体 .pt 路径")
    ap.add_argument("--device", default="", help="留空=自动 (有 CUDA 用 0, 否则 cpu)")
    ap.add_argument("--name", default="annot_" + time.strftime("%m%d_%H%M"))
    ap.add_argument("--project", default="outputs/yolo_annot")
    ap.add_argument("--verify", type=int, default=8, help="训练后在 N 张 val 图上真推理验证")
    ap.add_argument("--force", action="store_true", help="体检有错也继续 (不推荐)")
    a = ap.parse_args()

    # ── 1. 体检 ──
    print("=" * 78)
    r = yad.check_dataset(a.root, strict=True)
    print(f"[体检] 图片 {r['n_images']} · 标注 {r['n_labels']} · 框 {r['n_boxes']} · "
          f"背景样本 {r['n_empty_label']} · 类别分布 {r['per_class']}")
    for e in r["errors"][:10]:
        print("   ❌", e)
    for w in r["warnings"][:5]:
        print("   ⚠️", w)
    if r["errors"] and not a.force:
        print("❌ 体检不通过 → 先修数据 (或 --force 强行继续)")
        return 2
    yml = os.path.join(a.data, "data.yaml")
    if not os.path.isfile(yml):
        print(f"❌ 缺 {yml} → 先跑: python3 tools/yolo_annot_dataset.py --build --check")
        return 2
    ytxt = open(yml, encoding="utf-8").read()
    names = yad.load_classes(a.root)
    print(f"[数据集] {yml}")
    for ln in ytxt.strip().splitlines():
        print("   " + ln)
    if r["n_images"] < 10:
        print(f"⚠️ 只有 {r['n_images']} 张 → 能跑通管线, 但精度别指望 (建议首轮 ≥100 张覆盖多位置/光照)")

    # ── 2. 基座权重 ──
    import torch
    from ultralytics import YOLO
    dev = a.device or ("0" if torch.cuda.is_available() else "cpu")
    if a.base == "auto":
        b = find_base(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        base = b or a.model
        print(f"[基座] auto → {base}" + ("  (现有权重 → 域适应微调)" if b else "  (没找到现有权重 → COCO 预训练)"))
    elif a.base.lower() in ("none", "no", "false"):
        base = a.model
        print(f"[基座] {base} (重头训)")
    else:
        base = a.base
        print(f"[基座] 指定 {base}")
    print(f"[设备] {dev} · torch {torch.__version__} · cuda={torch.cuda.is_available()}")
    print(f"[参数] epochs={a.epochs} imgsz={a.imgsz} batch={a.batch} 类别={names} nc={len(names)}")
    print("=" * 78, flush=True)

    # ── 3. 训练 ──
    t0 = time.time()
    model = YOLO(base)
    model.train(data=yml, epochs=a.epochs, imgsz=a.imgsz, batch=a.batch, device=dev,
                project=a.project, name=a.name, workers=2, verbose=True,
                exist_ok=True, plots=True)
    dt = time.time() - t0

    # ── 4. 找 best.pt + 真推理验证 ──
    best = None
    for pat in (os.path.join(a.project, a.name, "weights", "best.pt"),
                os.path.join("runs", "detect", a.project, a.name, "weights", "best.pt"),
                os.path.join("runs", "detect", "outputs", a.project, a.name, "weights", "best.pt")):
        if os.path.isfile(pat):
            best = pat
            break
    if best is None:
        c = glob.glob(os.path.join("runs", "**", a.name, "weights", "best.pt"), recursive=True)
        best = c[0] if c else None
    print("=" * 78)
    print(f"⏱ 训练完成: {dt/60:.1f} 分钟 ({a.epochs} 轮) · 权重 {best}")
    if best:
        m = YOLO(best)
        imgs = sorted(glob.glob(os.path.join(a.data, "images", "val", "*")))
        imgs = imgs[:max(1, a.verify)]
        ndet, confs, lines = 0, [], []
        for p in imgs:
            res = m.predict(p, conf=0.25, verbose=False)[0]
            n = len(res.boxes)
            c = [float(x) for x in (res.boxes.conf if res.boxes is not None else [])]
            ndet += n
            confs += c
            lines.append(f"   {os.path.basename(p)}: {n} 框" +
                         (f" · conf {min(c):.2f}~{max(c):.2f}" if c else " (无检出)"))
        print(f"[真推理验证] val 抽样 {len(imgs)} 张 → 共检出 {ndet} 框 · "
              f"平均 conf {sum(confs)/len(confs):.3f}" if confs else
              f"[真推理验证] val 抽样 {len(imgs)} 张 → 0 框 (数据太少/未收敛?)")
        for l in lines:
            print(l)
        print("   权重路径(给 Orin 部署): " + best)
    print("✅ 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
