#!/usr/bin/env python3
"""朝向诊断: env.render() 原始方向 vs rot180 vs 真值投影"""
import os, sys, numpy as np
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")
ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, ROOT)

import metaworld
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "yolo_state_aligner",
    os.path.join(ROOT, "src/lerobot/policies/yolo_3d/yolo_state_aligner.py"))
_ysa = importlib.util.module_from_spec(_spec)
sys.modules["yolo_state_aligner"] = _ysa
_spec.loader.exec_module(_ysa)
YoloStateAligner = _ysa.YoloStateAligner

mt = metaworld.MT1("peg-insert-side-v3")
env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
env._freeze_rand_vec = False
env.set_task(mt.train_tasks[0])
env.reset(seed=0)
env._freeze_rand_vec = True
img = env.render()
H, W = img.shape[:2]

# 真值 3D 位置
sites = {
    "hand": env.data.site_xpos[env.model.site("endEffector").id],
    "peg": env.data.site_xpos[env.model.site("pegGrasp").id],
    "hole": env.data.site_xpos[env.model.site("hole").id],
}

# 标准 mujoco 相机投影 (与 gen_yolo_data project_3d_to_2d 的 px,py 部分一致, 不做 rot180)
cam_id = env.model.cam("corner2").id
cam_pos = env.model.cam_pos[cam_id]
cam_mat = np.asarray(env.model.cam_mat0[cam_id]).reshape(3, 3).T
fovy = env.model.cam_fovy[cam_id]
f = (H / 2) / np.tan(np.radians(fovy) / 2)

def proj_std(xyz):
    pc = cam_mat @ (np.asarray(xyz, float) - cam_pos)
    d = -pc[2]
    if d <= 0:
        return None
    px = W / 2 + pc[0] * f / d
    py = H / 2 - pc[1] * f / d
    return px, py

print("=== 真值 3D ===")
for k, v in sites.items():
    print(f"  {k}: {np.round(v,3)}")

print("=== 标准投影 (px,py) 落在哪个方向帧 ===")
for k, v in sites.items():
    p = proj_std(v)
    if p is None:
        continue
    px, py = p
    # 该点在 img 原始 和 img_rot180 上的对应位置
    print(f"  {k}: std(px,py)=({px:.1f},{py:.1f})")

# YOLO 检测 (detect_3d 内部 rot180)
aligner = YoloStateAligner(
    os.path.join(ROOT, "runs/detect/outputs/yolo_peg/peg_v1/weights/best.pt"), env)
det3d = aligner.detect_3d(img)
print("=== YOLO detect_3d 结果 (反投影 3D) ===")
for k, v in det3d.items():
    print(f"  {k}: {np.round(v,3)}  真值: {np.round(sites[k],3)}")

# 关键实验: 直接 YOLO predict 分别喂 img原始 和 rot180, 看 hand box 中心
import cv2
for name, arr in [("img原始", img), ("img_rot180", np.rot90(img, k=2))]:
    bgr = cv2.cvtColor((arr*255).astype(np.uint8) if arr.dtype != np.uint8 else arr, cv2.COLOR_RGB2BGR)
    res = aligner.model.predict(bgr, conf=0.4, verbose=False)[0]
    for b in res.boxes:
        cls = res.names[int(b.cls)]
        if cls == "hand":
            x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
            print(f"  [{name}] hand box 中心 = ({(x1+x2)/2:.1f}, {(y1+y2)/2:.1f})  conf={float(b.conf):.3f}")

env.close()
