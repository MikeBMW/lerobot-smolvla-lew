#!/usr/bin/env python3
"""探针3: 分解 3D 误差来源 — 真值深度代入公式 vs 深度模型 (2026-09-07)
若 真值深度+公式 ≈ 0 误差 → 误差全在深度模型输出 (scale/语义)
若 真值深度也偏 → 公式或 2D 中心有系统偏差
跑法: cd repo && gui-venv311/bin/python tools/probe_r1_yolo_err3.py
"""
import os, sys
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")
import numpy as np

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

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

def main():
    import cv2
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("yolo_state_aligner",
        os.path.join(REPO, "src", "lerobot", "policies", "yolo_3d", "yolo_state_aligner.py"))
    _m = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_m)
    seed = 104
    env = make_env(seed)
    w = os.path.join(REPO, "runs", "detect", "outputs", "yolo_peg", "peg_v1", "weights", "best.pt")
    dw = os.path.join(REPO, "outputs", "yolo_peg_depth", "peg_depth_v1-2", "weights", "best.pt")
    al = _m.YoloStateAligner(w, env, depth_weights=dw)
    cam_id = env.model.camera("corner2").id
    cam_pos = env.model.cam_pos[cam_id].copy()
    cam_mat = np.asarray(env.model.cam_mat0[cam_id]).reshape(3, 3).T
    fovy = env.model.cam_fovy[cam_id]
    H = W = 480
    f = (H / 2) / np.tan(np.radians(fovy) / 2)
    forward = cam_mat.T @ np.array([0.0, 0.0, -1.0]); forward /= np.linalg.norm(forward)
    o = np.asarray(env._get_obs(), dtype=np.float64).ravel()
    peg_true = o[4:7].copy()
    img = env.render()
    img_rot = np.rot90(img, k=2)
    img_bgr = cv2.cvtColor(img_rot, cv2.COLOR_RGB2BGR)
    res = al.model.predict(img_bgr, conf=0.4, verbose=False)[0]
    _d = al.depth_model.predict(img_bgr, verbose=False)[0].depth.data
    depth_map = np.asarray(_d.detach().cpu().numpy()).squeeze()
    print(f"peg 真值: {np.round(peg_true,3)}")
    d_true_axial = float(np.dot(peg_true - cam_pos, forward))   # 沿光轴真值深度
    d_true_euc = float(np.linalg.norm(peg_true - cam_pos))
    print(f"cam_pos={np.round(cam_pos,3)} f={f:.1f}")
    print(f"真值深度: 沿光轴={d_true_axial:.3f} 欧氏={d_true_euc:.3f}")
    for b in res.boxes:
        cls = res.names[int(b.cls)]
        x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
        u, v = (x1 + x2) / 2, (y1 + y2) / 2
        uo, vo = W - u, H - v
        ndc_x, ndc_y = (uo - W / 2) / f, (vo - H / 2) / f
        pc_vec = np.array([ndc_x, -ndc_y, -1.0])
        dir_w = cam_mat.T @ pc_vec
        dir_w = dir_w / np.linalg.norm(dir_w)
        cos_t = float(np.dot(dir_w, forward))
        # A: 用真值沿光轴深度 → 3D (验证公式+2D中心自洽性)
        p_true_depth = cam_pos + (d_true_axial / cos_t) * dir_w
        # 只对 peg 类详细
        tag = ""
        if cls in ("peg", "光模块"):
            tgt = peg_true
            xi1, yi1 = int(np.clip(x1,0,W-1)), int(np.clip(y1,0,H-1))
            xi2, yi2 = int(np.clip(x2,0,W-1)), int(np.clip(y2,0,H-1))
            vals = np.sort(depth_map[yi1:yi2, xi1:xi2].ravel())
            vals = vals[np.isfinite(vals)]
            dm_med = float(np.median(vals)) if vals.size else float("nan")
            err_true = np.linalg.norm(p_true_depth - tgt) * 1000
            tag = (f"  | 真值深度代入误差={err_true:.0f}mm (公式自洽性)"
                   f"\n    深度模型 med={dm_med:.3f} (scale0.978→{dm_med*0.978:.3f}) vs 真轴向 {d_true_axial:.3f}"
                   f" → 模型深度偏差 {(dm_med*0.978 - d_true_axial)*1000:+.0f}mm"
                   f"\n    模型3D误差(原detect_3d): "
                   f"{np.linalg.norm((cam_pos + ((dm_med*0.978)/cos_t)*dir_w) - tgt)*1000:.0f}mm")
            # 深度模型原始比例: 若模型输出×k=真值, k=?
            if np.isfinite(dm_med) and dm_med > 0.1:
                tag += f"\n    隐含真scale(轴向)= {d_true_axial/dm_med:.4f}"
        print(f"  [{cls}] 2D中心原帧=({uo:.1f},{vo:.1f}) dir=({dir_w[0]:+.3f},{dir_w[1]:+.3f},{dir_w[2]:+.3f}) cos={cos_t:.3f}{tag}")

if __name__ == "__main__":
    main()
