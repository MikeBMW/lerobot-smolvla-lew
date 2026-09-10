#!/usr/bin/env python3
"""验证 insert_success_demo.mp4 方向: 抽第一帧 YOLO detect hand 中心 vs 标准投影"""
import os, sys, numpy as np, cv2, importlib.util
ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, ROOT)

import metaworld
_spec = importlib.util.spec_from_file_location(
    "yolo_state_aligner",
    os.path.join(ROOT, "src/lerobot/policies/yolo_3d/yolo_state_aligner.py"))
_ysa = importlib.util.module_from_spec(_spec); sys.modules["yolo_state_aligner"] = _ysa
_spec.loader.exec_module(_ysa)
YoloStateAligner = _ysa.YoloStateAligner

# 1. 真值标准投影 (seed 无关, 只取相机参数)
mt = metaworld.MT1("peg-insert-side-v3")
env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
env._freeze_rand_vec = False; env.set_task(mt.train_tasks[0]); env.reset(seed=0)
cam_id = env.model.cam("corner2").id
cam_pos = env.model.cam_pos[cam_id]
cam_mat = np.asarray(env.model.cam_mat0[cam_id]).reshape(3, 3).T
fovy = env.model.cam_fovy[cam_id]
H = W = 480
f = (H/2)/np.tan(np.radians(fovy)/2)
def proj_std(xyz):
    pc = cam_mat @ (np.asarray(xyz,float)-cam_pos); d=-pc[2]
    return (W/2+pc[0]*f/d, H/2-pc[1]*f/d) if d>0 else None
hand_truth = env.data.site_xpos[env.model.site("endEffector").id]
px, py = proj_std(hand_truth)
print(f"真值 hand 标准投影: ({px:.1f}, {py:.1f})")
env.close()

# 2. 读视频多帧检测 hand
vid = os.path.join(ROOT, "reports/insert_success_demo.mp4")
from ultralytics import YOLO
model = YOLO(os.path.join(ROOT, "runs/detect/outputs/yolo_peg/peg_v1/weights/best.pt"))
cap = cv2.VideoCapture(vid)
total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
print(f"视频总帧数={total}")
for idx in range(0, total, max(1, total//6)):
    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
    ok, frame = cap.read()
    if not ok:
        continue
    # 视频帧是 img 原始方向(正确); YOLO 只认 rot180(训练方向) → 先 rot180 再喂
    f_rot = cv2.rotate(frame, cv2.ROTATE_180)
    res = model.predict(f_rot, conf=0.4, verbose=False)[0]
    boxes = {res.names[int(b.cls)]: ((b.xyxy[0][0]+b.xyxy[0][2])/2, (b.xyxy[0][1]+b.xyxy[0][3])/2) for b in res.boxes}
    h = boxes.get("hand")
    hs = f"hand(rot180系)=({h[0]:.1f},{h[1]:.1f})" if h else "hand未检出"
    print(f"  帧{idx}: 检出{len(boxes)}类 {list(boxes.keys())} {hs}")
cap.release()
print("判据: 视频帧 rot180 后应检出 hand (中心≈242,261) → 证明视频帧=img原始方向=正确人眼方向")
print("      hand 真值在 img原始方向的位置=(237.6,219.2) [标准投影], 在 rot180 系=(242.4,260.8)")
