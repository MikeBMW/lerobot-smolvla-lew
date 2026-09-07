#!/usr/bin/env python3
"""探针2: 深度分位扫描 — 多帧 × 不同深度分位 → peg 3D 误差 (2026-09-07)
验证假设: 框内中位数深度被背景污染(peg 细柱只占框 ~16%) → 深度偏大 → 3D 点外移
跑法: cd repo && gui-venv311/bin/python tools/probe_r1_yolo_err2.py
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
    seed = 104
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
    forward = cam_mat.T @ np.array([0.0, 0.0, -1.0]); forward /= np.linalg.norm(forward)

    QUANTILES = [0.05, 0.1, 0.15, 0.2, 0.3, 0.5]
    errs = {q: [] for q in QUANTILES}
    det_hit = 0
    o = None
    term = trunc = False
    for step in range(0, 140, 5):
        # 专家动作推进 (产生不同遮挡阶段)
        if step > 0:
            for _ in range(5):
                obs_v = np.asarray(env._get_obs(), dtype=np.float64).ravel()
                act = expert.get_action(obs_v)
                o, r, term, trunc, _ = env.step(act)
                if term or trunc:
                    break
        if term or trunc:
            break
        obs_v = np.asarray(env._get_obs(), dtype=np.float64).ravel()
        peg_true = obs_v[4:7].copy()
        img = env.render()
        img_rot = np.rot90(img, k=2)
        img_bgr = cv2.cvtColor(img_rot, cv2.COLOR_RGB2BGR)
        res = al.model.predict(img_bgr, conf=0.4, verbose=False)[0]
        _d = al.depth_model.predict(img_bgr, verbose=False)[0].depth.data
        depth_map = np.asarray(_d.detach().cpu().numpy()).squeeze()
        hand_z = obs_v[0:3][2]
        peg_box = None
        for b in res.boxes:
            if res.names[int(b.cls)] in ("peg", "光模块"):
                peg_box = b
                break
        if peg_box is None:
            continue
        det_hit += 1
        x1, y1, x2, y2 = [float(v) for v in peg_box.xyxy[0]]
        xi1, yi1 = int(np.clip(x1,0,W-1)), int(np.clip(y1,0,H-1))
        xi2, yi2 = int(np.clip(x2,0,W-1)), int(np.clip(y2,0,H-1))
        u, v = (x1+x2)/2, (y1+y2)/2
        uo, vo = W-u, H-v
        ndc_x, ndc_y = (uo-W/2)/f, (vo-H/2)/f
        pc_v = np.array([ndc_x, -ndc_y, -1.0])
        dir_w = cam_mat.T @ pc_v
        dir_w = dir_w / np.linalg.norm(dir_w)
        cos_t = float(np.dot(dir_w, forward))
        vals = np.sort(depth_map[yi1:yi2, xi1:xi2].ravel())
        vals = vals[np.isfinite(vals)]
        if vals.size == 0:
            continue
        for q in QUANTILES:
            _idx = min(vals.size - 1, int(q * (vals.size - 1)))
            dq = float(vals[_idx]) * 0.978
            t = dq / cos_t
            p3 = cam_pos + t * dir_w
            errs[q].append(float(np.linalg.norm(p3 - peg_true)))
        # 供日志
        dm_med = float(np.median(depth_map[yi1:yi2, xi1:xi2])) * 0.978
    print(f"帧数(检出 peg): {det_hit}, 夹爪末 z={hand_z:.3f}")
    print(f"{'分位':>6} {'平均误差mm':>10} {'中位':>8} {'p90':>8}")
    for q in QUANTILES:
        e = np.asarray(errs[q]) * 1000
        print(f"{q*100:>5.0f}% {e.mean():>10.0f} {np.median(e):>8.0f} {np.percentile(e,90):>8.0f}")
    # 末帧也输出真 peg 3D vs 2D
    print(f"末帧 peg 真值: {np.round(peg_true,3)}")

if __name__ == "__main__":
    main()
