#!/usr/bin/env python3
"""确定性方向判定: 机械臂 sawyer 是红色, 找红色像素 vs 真值 hand 投影位置"""
import os, sys, numpy as np
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")
ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, ROOT)
import metaworld

mt = metaworld.MT1("peg-insert-side-v3")
env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
env._freeze_rand_vec = False
env.set_task(mt.train_tasks[0])
env.reset(seed=0)
env._freeze_rand_vec = True
img = env.render()
H, W = img.shape[:2]

# 真值 hand 3D
hand3d = env.data.site_xpos[env.model.site("endEffector").id]
print(f"真值 hand 3D: {np.round(hand3d,3)}")

# 标准投影
cam_id = env.model.cam("corner2").id
cam_pos = env.model.cam_pos[cam_id]
cam_mat = np.asarray(env.model.cam_mat0[cam_id]).reshape(3, 3).T
fovy = env.model.cam_fovy[cam_id]
f = (H/2)/np.tan(np.radians(fovy)/2)
pc = cam_mat @ (hand3d - cam_pos)
d = -pc[2]
px = W/2 + pc[0]*f/d
py = H/2 - pc[1]*f/d
print(f"标准投影 (px,py)=({px:.1f},{py:.1f})")

# 4 个候选位置的像素颜色 (img 是 RGB)
cand = {
    "(px,py) 标准":      (int(px), int(py)),
    "(px,H-py) 上下翻":  (int(px), int(H-1-py)),
    "(W-px,py) 左右翻":  (int(W-1-px), int(py)),
    "(W-px,H-py) 180翻": (int(W-1-px), int(H-1-py)),
}
print("=== 候选位置像素颜色 (RGB) ===")
for name, (x, y) in cand.items():
    x = max(0, min(W-1, x)); y = max(0, min(H-1, y))
    print(f"  {name}: {img[y,x].tolist()}")

# 全图红色像素 (机械臂 sawyer 暗红: R 明显 > G 且 > B) 的质心
r, g, b = img[:,:,0].astype(int), img[:,:,1].astype(int), img[:,:,2].astype(int)
red_mask = (r > 100) & (r > g*1.5) & (r > b*1.5)
ys, xs = np.nonzero(red_mask)
if len(xs):
    print(f"红色像素质心 = ({xs.mean():.1f}, {ys.mean():.1f})  像素数={len(xs)}")
else:
    print("未找到红色像素 (机械臂颜色假设需调整)")
env.close()
