#!/usr/bin/env python3
"""探针5: 2D检测中心 + 已知台面 z 平面反投影 → peg xy 定位精度 (全程含遮挡) (2026-09-07)
对比: 深度反投影(单目尺度漂移 30mm) vs 平面反投影(2D 中心已证 1px 准)
跑法: cd repo && gui-venv311/bin/python tools/probe_r1_yolo_plane.py
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
    return env, mt

def main():
    import cv2
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("yolo_state_aligner",
        os.path.join(REPO, "src", "lerobot", "policies", "yolo_3d", "yolo_state_aligner.py"))
    _m = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_m)
    from metaworld.policies.sawyer_peg_insertion_side_v3_policy import SawyerPegInsertionSideV3Policy
    errs_plane = []
    errs_depth = []
    n_det = 0
    for seed in [100, 104, 105]:
        env, mt = make_env(seed)
        expert = SawyerPegInsertionSideV3Policy()
        w = os.path.join(REPO, "runs", "detect", "outputs", "yolo_peg", "peg_v1", "weights", "best.pt")
        dw = os.path.join(REPO, "outputs", "yolo_peg_depth", "peg_depth_v1-2", "weights", "best.pt")
        al = _m.YoloStateAligner(w, env, depth_weights=dw)
        cam_id = env.model.camera("corner2").id
        cam_pos = env.model.cam_pos[cam_id].copy()
        cam_mat = np.asarray(env.model.cam_mat0[cam_id]).reshape(3, 3).T
        fovy = env.model.cam_fovy[cam_id]
        H = W = 480
        f = (H / 2) / np.tan(np.radians(fovy) / 2)
        term = trunc = False
        for step in range(0, 160, 2):
            for _ in range(2):
                obs_v = np.asarray(env._get_obs(), dtype=np.float64).ravel()
                act = expert.get_action(obs_v)
                o, r, term, trunc, _ = env.step(act)
                if term or trunc:
                    break
            if term or trunc:
                break
            obs_v = np.asarray(env._get_obs(), dtype=np.float64).ravel()
            peg_true = obs_v[4:7].copy()
            plane_z = float(obs_v[4])          # 现场采样 peg 中心 z (工位标定语义)
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
                continue
            n_det += 1
            x1, y1, x2, y2 = [float(v) for v in peg_box.xyxy[0]]
            u, v = (x1 + x2) / 2, (y1 + y2) / 2
            uo, vo = W - u, H - v
            ndc_x, ndc_y = (uo - W / 2) / f, (vo - H / 2) / f
            pc_vec = np.array([ndc_x, -ndc_y, -1.0])
            dir_w = cam_mat.T @ pc_vec
            dir_w = dir_w / np.linalg.norm(dir_w)
            # 平面反投影: 射线与 z=plane_z 求交
            t_pl = (plane_z - cam_pos[2]) / dir_w[2] if abs(dir_w[2]) > 1e-6 else None
            if t_pl and t_pl > 0:
                p_plane = cam_pos + t_pl * dir_w
                err_xy = np.linalg.norm(p_plane[:2] - peg_true[:2]) * 1000
                errs_plane.append(err_xy)
            # 深度反投影 (0.9616)
            xi1, yi1 = int(np.clip(x1,0,W-1)), int(np.clip(y1,0,H-1))
            xi2, yi2 = int(np.clip(x2,0,W-1)), int(np.clip(y2,0,H-1))
            vals = np.sort(depth_map[yi1:yi2, xi1:xi2].ravel())
            vals = vals[np.isfinite(vals)]
            if vals.size:
                dm = float(np.median(vals)) * 0.9616
                forward = cam_mat.T @ np.array([0.0, 0.0, -1.0])
                forward /= np.linalg.norm(forward)
                cos_t = float(np.dot(dir_w, forward))
                p_dep = cam_pos + (dm / cos_t) * dir_w
                errs_depth.append(np.linalg.norm(p_dep - peg_true) * 1000)
    e_pl = np.asarray(errs_plane)
    e_dp = np.asarray(errs_depth)
    print(f"检出帧 {n_det}")
    print(f"平面反投影 xy 误差: 均值 {e_pl.mean():.0f}mm 中位 {np.median(e_pl):.0f}mm p90 {np.percentile(e_pl,90):.0f}mm")
    print(f"深度反投影 3D 误差: 均值 {e_dp.mean():.0f}mm 中位 {np.median(e_dp):.0f}mm p90 {np.percentile(e_dp,90):.0f}mm")

if __name__ == "__main__":
    main()
