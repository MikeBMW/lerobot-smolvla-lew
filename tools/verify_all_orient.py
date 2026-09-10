#!/usr/bin/env python3
"""验证各视频帧方向: YOLO 只认 bottom-up(训练方向=img rot180).
- 直接喂检出 hand → 视频是 bottom-up(反, 需180°摆正)
- rot180喂才检出 hand → 视频是 top-down(正, 无需旋转)
"""
import os, sys, cv2, numpy as np
ROOT = "/home/ubuntu/lerobot-smolvla-lew"
from ultralytics import YOLO
model = YOLO(os.path.join(ROOT, "runs/detect/outputs/yolo_peg/peg_v1/weights/best.pt"))

vids = [
    "reports/insert_success_demo.mp4",
    "reports/mlp_insert_success.mp4",
    "reports/mlp_best.mp4",
    "reports/yolo_perception_op.mp4",
]
for v in vids:
    p = os.path.join(ROOT, v)
    if not os.path.exists(p):
        print(f"{v}: 不存在"); continue
    cap = cv2.VideoCapture(p)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    # 抽中间 3 帧各喂一次, 统计检出
    cnt_direct = cnt_rot = 0
    for frac in (0.3, 0.5, 0.7):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(total*frac))
        ok, fr = cap.read()
        if not ok: continue
        r1 = model.predict(fr, conf=0.4, verbose=False)[0]
        r2 = model.predict(cv2.rotate(fr, cv2.ROTATE_180), conf=0.4, verbose=False)[0]
        n1 = len(r1.boxes); n2 = len(r2.boxes)
        cnt_direct += n1; cnt_rot += n2
    cap.release()
    verdict = "bottom-up(反,需180°)" if cnt_direct > cnt_rot else "top-down(正,无需旋转)"
    print(f"{os.path.basename(v)}: 总帧{total} 直接喂检出={cnt_direct}类 rot180喂检出={cnt_rot}类 → {verdict}")
