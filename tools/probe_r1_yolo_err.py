#!/usr/bin/env python3
"""探针: 钉死 R1 视觉 peg 51mm 偏差来源 — 2D框偏 / 深度偏 / 反投影公式偏 (2026-09-07 静静)
跑法: cd repo && gui-venv311/bin/python tools/probe_r1_yolo_err.py
"""
import os, sys
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")
import numpy as np

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(REPO, "tools", "gui"))

def make_env(seed):
    import metaworld
    mt = metaworld.MT1("peg-insert-side-v3")
    env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
    env.set_task(mt.train_tasks[0])
    env._freeze_rand_vec = False
    np.random.seed(seed * 7919 + 13)
    env.reset(seed=seed)
    env._freeze_rand_vec = True
    return env

def forward_project(env, p3d):
    """世界 3D → 原始帧像素 (cam_mat0 正向投影, 与反投影互逆)"""
    import numpy as np
    cam_id = env.model.camera("corner2").id
    cam_pos = env.model.cam_pos[cam_id].copy()
    cam_mat = np.asarray(env.model.cam_mat0[cam_id]).reshape(3, 3).T
    fovy = env.model.cam_fovy[cam_id]
    H = W = env.render().shape[0] if False else 480
    f = (H / 2) / np.tan(np.radians(fovy) / 2)
    # 相机坐标: 世界→相机 = R^T (p - cam_pos); R = cam_mat (世界基向量为列?) 用反投影逆推
    rel = p3d - cam_pos
    pc = cam_mat @ rel          # cam_mat.T 的逆? cam_mat0 是相机在世界系的方向余弦阵(列=相机轴)
    if pc[2] >= 0:
        return None             # 在相机后方
    ndc_x, ndc_y = pc[0] / -pc[2], pc[1] / -pc[2]
    u = W / 2 + ndc_x * f
    v = H / 2 + ndc_y * f       # 反投影里 ndc_y = (v-H/2)/f 且 dir=forward+ndc_x*right-ndc_y*up → y 向上
    return u, v

def main():
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("yolo_state_aligner",
        os.path.join(REPO, "src", "lerobot", "policies", "yolo_3d", "yolo_state_aligner.py"))
    _m = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_m)
    YoloStateAligner = _m.YoloStateAligner
    seed = 104
    env = make_env(seed)
    m, d = env.model, env.data
    site_ph = m.site("pegHead").id
    site_peg = None
    # pegGrasp/peg 本体: obs[4:7]
    o = np.asarray(env._get_obs(), dtype=np.float64).ravel()
    peg_true = o[4:7].copy()
    hole_true = d.site_xpos[m.site("hole").id].copy()
    hand_true = o[0:3].copy()
    print(f"seed{seed} 真值: hand={np.round(hand_true,3)} peg={np.round(peg_true,3)} hole={np.round(hole_true,3)}")

    w = os.path.join(REPO, "runs", "detect", "outputs", "yolo_peg", "peg_v1", "weights", "best.pt")
    dw = os.path.join(REPO, "outputs", "yolo_peg_depth", "peg_depth_v1-2", "weights", "best.pt")
    al = YoloStateAligner(w, env, depth_weights=dw)
    img = env.render()
    det3d = al.detect_3d(img)
    print("YOLO 3D:", {k: np.round(v, 3).tolist() for k, v in det3d.items()})
    for name, t in [("hand", hand_true), ("光模块", peg_true), ("hole", hole_true)]:
        p2 = forward_project(env, t)
        print(f"  真值投影 {name}: {np.round(p2,1) if p2 else None}")
    # 2D 检测框
    res = al._last_res
    cam_id = env.model.camera("corner2").id
    cam_pos = env.model.cam_pos[cam_id].copy()
    cam_mat = np.asarray(env.model.cam_mat0[cam_id]).reshape(3, 3).T
    fovy = env.model.cam_fovy[cam_id]
    H2, W2 = img.shape[:2]
    f = (H2 / 2) / np.tan(np.radians(fovy) / 2)
    forward = cam_mat.T @ np.array([0.0, 0.0, -1.0]); forward /= np.linalg.norm(forward)
    print(f"图 {W2}x{H2}, f={f:.1f}, cam_pos={np.round(cam_pos,3)}, fovy={fovy}")
    depth_map = None
    if al.depth_model is not None:
        import cv2
        img_rot = np.rot90(img, k=2)
        img_bgr = cv2.cvtColor(img_rot, cv2.COLOR_RGB2BGR)
        _d = al.depth_model.predict(img_bgr, verbose=False)[0].depth.data
        depth_map = np.asarray(_d.detach().cpu().numpy()).squeeze()
        print("depth_map shape:", depth_map.shape, "range:", depth_map.min(), depth_map.max())
    for b in res.boxes:
        cls = res.names[int(b.cls)]
        x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
        u, v = (x1 + x2) / 2, (y1 + y2) / 2
        # rot90 → 原帧
        uo, vo = W2 - u, H2 - v
        dm = None
        if depth_map is not None:
            xi1, yi1 = int(np.clip(x1,0,W2-1)), int(np.clip(y1,0,H2-1))
            xi2, yi2 = int(np.clip(x2,0,W2-1)), int(np.clip(y2,0,H2-1))
            dm = float(np.median(depth_map[yi1:yi2, xi1:xi2]))
            sc = al._hand_scale if cls == "hand" else al._depth_scale
            dm *= sc
        print(f"  [{cls}] 2D框(rot90)=({x1:.0f},{y1:.0f},{x2:.0f},{y2:.0f}) 中心原帧=({uo:.1f},{vo:.1f}) "
              f"depth_med={dm if dm else 'None'}")
        # 真值投影到原帧后, 与 2D 中心对比
        tname = {"hand":"hand","光模块":"光模块","peg":"光模块","hole":"hole"}.get(cls, cls)
        if cls in ("hand","peg","hole"):
            tt = {"hand":hand_true,"peg":peg_true,"hole":hole_true}[cls]
            p2 = forward_project(env, tt)
            if p2:
                print(f"    真值[{cls}]投影=({p2[0]:.1f},{p2[1]:.1f}) → 中心偏差 "
                      f"({p2[0]-uo:+.1f},{p2[1]-vo:+.1f})px")

if __name__ == "__main__":
    main()
