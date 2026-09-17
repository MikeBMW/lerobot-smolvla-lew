# -*- coding: utf-8 -*-
"""sim→real 域随机化 (DR) 同口径对照训练。

两臂完全同超参 / 同基座 (生产权重 peg_v1 域适应微调) / 同 seed, 只差数据:
  臂 A' (ctrl_sim)  : 原仿真集 1800 张           → 控变量: "只重训一轮"能带多少
  臂 B  (dr_mix)    : 原仿真 1800 + DR 8100 张   → 目标: 真机能检出

用法: python train_arms.py [--epochs 25] [--batch 16] [--device 0] [--arm ctrl_sim|dr_mix|both]
"""
import argparse, os, sys
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")
ROOT = "/home/ubuntu/lerobot-smolvla-lew"
BASE = f"{ROOT}/runs/detect/outputs/yolo_peg/peg_v1/weights/best.pt"   # 生产基座 (hand/peg/hole)
ARMS = {
    "ctrl_sim": f"{ROOT}/data/yolo_peg/data.yaml",
    "dr_mix": f"{ROOT}/data/yolo_peg_drmix/data.yaml",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=25)
    ap.add_argument("--imgsz", type=int, default=480)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--device", default="0")
    ap.add_argument("--arm", default="both")
    ap.add_argument("--base", default=BASE)
    args = ap.parse_args()

    from ultralytics import YOLO
    arms = list(ARMS) if args.arm == "both" else [args.arm]
    for arm in arms:
        print(f"\n{'='*70}\n臂 {arm}: 基座={os.path.basename(args.base)} 数据={ARMS[arm]} "
              f"epochs={args.epochs} imgsz={args.imgsz} batch={args.batch} device={args.device}\n{'='*70}", flush=True)
        model = YOLO(args.base)
        model.train(data=ARMS[arm], epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
                    device=args.device, project="outputs/yolo_peg", name=arm,
                    seed=0, workers=4, verbose=True, exist_ok=True)
        w = f"{ROOT}/runs/detect/outputs/yolo_peg/{arm}/weights/best.pt"
        print(f"✅ 臂 {arm} 完成 → {w}", flush=True)


if __name__ == "__main__":
    main()
