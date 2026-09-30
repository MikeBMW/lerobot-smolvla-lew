#!/usr/bin/env python3
"""YOLO peg-insert 检测训练 — 感知前端 (2026-08-07 老倪: 开启 YOLO 训练)
数据: data/yolo_peg (真值投影自动标注, 3类: hand/光模块/hole)
用法: python train_yolo.py [--data data/yolo_peg] [--epochs 25] [--device cpu] [--model yolov8n.pt]
2026-08-23: 加 --device/--model 参数, CPU 可训 (无 GPU 环境), 默认 yolov8n
"""
import os, sys, argparse

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/yolo_peg")
    ap.add_argument("--epochs", type=int, default=25)
    ap.add_argument("--imgsz", type=int, default=480)
    ap.add_argument("--name", default="peg_v1")
    ap.add_argument("--model", default="yolov8n.pt")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--batch", type=int, default=8)
    args = ap.parse_args()

    from ultralytics import YOLO
    model = YOLO(args.model)
    model.train(data=os.path.join(args.data, "data.yaml"),
                epochs=args.epochs, imgsz=args.imgsz,
                batch=args.batch, device=args.device,
                project="outputs/yolo_peg", name=args.name,
                workers=2, verbose=False)
    print(f"✅ YOLO 训练完成: outputs/yolo_peg/{args.name}")

if __name__ == "__main__":
    main()
