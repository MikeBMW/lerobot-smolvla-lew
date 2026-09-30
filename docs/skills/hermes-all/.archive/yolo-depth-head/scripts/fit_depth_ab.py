#!/usr/bin/env python3
"""拟合 mujoco depth buffer (透视归一化 [0,1]) → 米制深度 的 A,B 常数。

公式: depth = A - B/z  →  z(米) = B / (A - depth)
方法: 渲染 depth_array + mj_ray 测已知物体真值深度 → 最小二乘拟合 A/B。
用法: DISPLAY=:0 MUJOCO_GL=egl gui-venv311/bin/python fit_depth_ab.py
  各 seed 打印的 A/B 应一致 (稳定); 不一致则需每集动态校准。
"""
import sys, os, numpy as np
sys.path.insert(0, "/home/ubuntu/lerobot-smolvla-lew")
sys.path.insert(0, "/home/ubuntu/lerobot-smolvla-lew/tools")
os.environ.setdefault("MUJOCO_GL", "egl"); os.environ.setdefault("MUJOCO_EGL_DEVICE", "0")

import metaworld, mujoco
mt = metaworld.MT1("peg-insert-side-v3")


def fit_AB(seed):
    env = mt.train_classes["peg-insert-side-v3"](render_mode="depth_array", camera_name="corner2")
    env._freeze_rand_vec = False; env.set_task(mt.train_tasks[0]); env.reset(seed=seed); env._freeze_rand_vec = True
    depth = np.asarray(env.render())
    model, data = env.model, env.data
    cam_id = model.camera("corner2").id
    cam_pos = model.cam_pos[cam_id].copy()
    cam_mat = np.asarray(model.cam_mat0[cam_id]).reshape(3, 3).T
    fovy = model.cam_fovy[cam_id]
    H = W = 480; f = (H / 2) / np.tan(np.radians(fovy) / 2)
    zs, ds = [], []
    for site in ["pegGrasp", "hole", "endEffector"]:
        xyz = data.site_xpos[model.site(site).id]
        pc = cam_mat @ (xyz - cam_pos); d_axis = -pc[2]
        px = int(np.clip(round(W / 2 + pc[0] * f / d_axis), 0, W - 1))
        py = int(np.clip(round(H / 2 - pc[1] * f / d_axis), 0, H - 1))
        dv = float(depth[py, px])
        ndc_x = (px - W / 2) / f; ndc_y = (py - H / 2) / f
        pcc = np.array([ndc_x, -ndc_y, -1.0])
        dir_w = (cam_mat.T @ pcc); dir_w = dir_w / np.linalg.norm(dir_w)
        geomid = np.zeros(1, dtype=np.int32)
        dist = mujoco.mj_ray(model, data, cam_pos.astype(np.float64), dir_w.astype(np.float64), None, 1, -1, geomid)
        if dist is not None and dist > 0:
            zs.append(dist); ds.append(dv)
    env.close()
    zs = np.array(zs); ds = np.array(ds)
    X = np.stack([np.ones_like(zs), -1 / zs], axis=1)
    A, B = np.linalg.lstsq(X, ds, rcond=None)[0]
    return A, B, zs, ds


if __name__ == "__main__":
    for seed in [0, 1, 2, 5, 10]:
        A, B, zs, ds = fit_AB(seed)
        z_pred = B / (A - ds)
        err = np.abs(z_pred - zs) * 100
        print(f"seed{seed}: A={A:.4f} B={B:.4f}  反推误差 max={err.max():.1f}cm mean={err.mean():.1f}cm  深度范围 [{zs.min():.2f},{zs.max():.2f}]m")
