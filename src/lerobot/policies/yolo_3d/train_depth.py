#!/usr/bin/env python3
"""YOLO 深度估计训练 — peg-insert 场景 (2026-08-23 老倪: YOLO 加 depth head)
数据: data/yolo_peg_depth (RGB+depth 对齐, depth_scale=256)
模型: yolo26n-depth (YOLO backbone + DPT-style depth head, Depth Anything 风格)
用法: python train_depth.py [--epochs 50] [--batch 8] [--imgsz 480] [--device cpu] [--name peg_depth_v1]
"""
import os, sys, argparse

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
sys.path.insert(0, ROOT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/yolo_peg_depth")
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--imgsz", type=int, default=480)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--name", default="peg_depth_v1")
    ap.add_argument("--model", default="yolo26n-depth.yaml")
    args = ap.parse_args()

    from ultralytics import YOLO
    model = YOLO(args.model)  # 从零训练 (无 depth 预训练权重)
    model.train(
        data=os.path.join(ROOT, args.data, "data.yaml"),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=os.path.join(ROOT, "outputs", "yolo_peg_depth"),
        name=args.name,
        workers=2,
        verbose=True,
    )
    print(f"✅ 深度训练完成: outputs/yolo_peg_depth/{args.name}")


if __name__ == "__main__":
    main()
