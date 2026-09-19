"""board_frame_module.py — 模块在"板坐标系"里的位置 (不需要高精度手眼)"""
import glob, os, sys
import cv2
import numpy as np
sys.path.insert(0, "/home/ubuntu/lerobot-smolvla-lew/tools")
import handeye_solve_ls as HS
from ultralytics import YOLO

REPO = "/home/ubuntu/lerobot-smolvla-lew"

def run(img_path, conf=0.25):
    im = cv2.imread(img_path)
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    pts, grid = HS.detect(g)
    if pts is None:
        return {"ok": False, "why": "板未检出"}
    Km, _ = HS._K()
    obj = HS.obj_points(grid, HS.SPACING_MM / 1000.0)
    R, t = HS._board_pose(pts, obj, Km)
    n = R @ np.array([0.0, 0.0, 1.0])
    m = YOLO(os.path.join(REPO, "models", "yolo_peg_live.pt"))
    r = m.predict(im, conf=conf, verbose=False)[0]
    if len(r.boxes) == 0:
        return {"ok": False, "why": "模块未检出", "板点": len(pts)}
    b = r.boxes[0]
    u, v = [float(x) for x in b.xyxy[0].tolist()][:2], [float(x) for x in b.xyxy[0].tolist()][2:]
    cx, cy = (u[0] + v[0]) / 2.0, (u[1] + v[1]) / 2.0
    K = Km
    ray = np.array([(cx - K[0, 2]) / K[0, 0], (cy - K[1, 2]) / K[1, 1], 1.0])
    lam = float(np.dot(n, t)) / float(np.dot(n, ray))
    p_cam = ray * lam
    p_board = R.T @ (p_cam - t)
    return {"ok": True, "板点": len(pts), "板距_m": round(float(np.linalg.norm(t)), 4),
            "模块在板坐标 (x,y,mm)": [round(float(p_board[0]) * 1000, 1), round(float(p_board[1]) * 1000, 1)],
            "离板面mm": round(float(p_board[2]) * 1000, 1), "框": [round(cx, 1), round(cy, 1)],
            "conf": round(float(b.conf[0]), 3)}

if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/zmax_ss_remote/cam_rs.png")
    print(p, "→", run(p))
