#!/usr/bin/env python3
"""探针4: 多布局深度 scale 标定 (2026-09-07) — 初始悬停帧(无遮挡)隐含真 scale
跑法: cd repo && gui-venv311/bin/python tools/probe_r1_yolo_calib.py
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
    w = os.path.join(REPO, "runs", "detect", "outputs", "yolo_peg", "peg_v1", "weights", "best.pt")
    dw = os.path.join(REPO, "outputs", "yolo_peg_depth", "peg_depth_v1-2", "weights", "best.pt")
    scales = []
    errs_old = []
    errs_new = []
    for seed in [100, 101, 102, 103, 104, 105, 106, 107, 108, 109]:
        env = make_env(seed)
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
        peg_box = None
        for b in res.boxes:
            if res.names[int(b.cls)] in ("peg", "光模块"):
                peg_box = b
                break
        if peg_box is None:
            print(f"seed{seed}: peg 未检出, 跳过")
            continue
        x1, y1, x2, y2 = [float(v) for v in peg_box.xyxy[0]]
        xi1, yi1 = int(np.clip(x1,0,W-1)), int(np.clip(y1,0,H-1))
        xi2, yi2 = int(np.clip(x2,0,W-1)), int(np.clip(y2,0,H-1))
        vals = np.sort(depth_map[yi1:yi2, xi1:xi2].ravel())
        vals = vals[np.isfinite(vals)]
        if vals.size == 0:
            print(f"seed{seed}: 深度空, 跳过")
            continue
        dm = float(np.median(vals))
        d_true = float(np.dot(peg_true - cam_pos, forward))
        s = d_true / dm
        scales.append(s)
        # 误差对比 (旧 scale 0.978 vs 隐含标定)
        u, v = (x1+x2)/2, (y1+y2)/2
        uo, vo = W-u, H-v
        ndc_x, ndc_y = (uo-W/2)/f, (vo-H/2)/f
        pc_vec = np.array([ndc_x, -ndc_y, -1.0])
        dir_w = cam_mat.T @ pc_vec; dir_w = dir_w/np.linalg.norm(dir_w)
        cos_t = float(np.dot(dir_w, forward))
        p_old = cam_pos + ((dm*0.978)/cos_t)*dir_w
        p_new = cam_pos + ((dm*s)/cos_t)*dir_w
        errs_old.append(np.linalg.norm(p_old - peg_true)*1000)
        errs_new.append(np.linalg.norm(p_new - peg_true)*1000)
        print(f"seed{seed}: 隐含scale={s:.4f} · 旧0.978误差={errs_old[-1]:.0f}mm → 标定后={errs_new[-1]:.0f}mm")
    if scales:
        sc = float(np.mean(scales))
        print(f"\n🏁 平均隐含 scale = {sc:.4f} (n={len(scales)})")
        print(f"   旧 0.978 平均误差 {np.mean(errs_old):.0f}mm → 标定 {sc:.4f} 后 {np.mean(errs_new):.0f}mm")
        print(f"   建议 DEPTH_SCALE={sc:.4f}")

if __name__ == "__main__":
    main()
