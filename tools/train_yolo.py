#!/usr/bin/env python3
"""YOLO peg-insert 检测训练 — 感知前端 (2026-08-07 老倪: 开启 YOLO 训练)
数据: data/yolo_peg (450张, 3类: hand/peg/hole) 或 data/yolo_peg_full (更大)
用法: python tools/train_yolo.py [--data data/yolo_peg] [--epochs 50]
"""
import os, sys, argparse

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/yolo_peg")
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--imgsz", type=int, default=480)
    ap.add_argument("--name", default="run1")
    args = ap.parse_args()

    from ultralytics import YOLO
    model = YOLO("yolov8s.pt")
    model.train(data=os.path.join(args.data, "data.yaml"),
                epochs=args.epochs, imgsz=args.imgsz,
                batch=8, device=0,
                project="outputs/yolo_peg", name=args.name,
                workers=2, verbose=False)
    print(f"✅ YOLO 训练完成: outputs/yolo_peg/{args.name}")

if __name__ == "__main__":
    main()
