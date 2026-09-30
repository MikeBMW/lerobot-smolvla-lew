#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mono23d_experiment.py — 「YOLO 2D框 → 3D」可行性与算法设计实验 (纯合成, 无机器人)

问题: 机器人有位姿真值, 光模块没有任何位姿信息。能不能**只用 YOLO 的 2D 框** + 生产/示教时自动
      攒下来的 (框, TCP, 姿态) 数据, 把 3D 反出来 —— 不量尺寸、不量偏移、不做手眼标定?

物理关系 (唯一的先验): 模块刚性夹持 → 中心 = TCP + R(q)·off (off 常数, 未知)
观测: 框中心 (u,v) 与框宽高 (w,h)        ← YOLO 就给这些
未知: 投影矩阵 P(11) + 附着偏移 off(3)

本脚本比较 4 种组合, 回答"到底靠什么才可辨识":
  A 只用框中心       · 位姿多样性小   (≈ 之前 13 点探针, 工作域 10cm / 单轴 ±16°)
  B 只用框中心       · 位姿多样性大   (生产级: 25cm 域 / 两轴 ±25°)
  C 框中心+框宽高    · 位姿多样性小
  D 框中心+框宽高    · 位姿多样性大   ← 提案方案
  (+ 残差学习: 用 (u,v,w,h) 岭回归修正系统偏差, 训练/留出分开)

指标: ① 解出的 off 误差(mm)  ② 留出位姿上的 3D 位置误差(mm)  ③ 留出位姿上的像素误差(px)
"""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import real_autolabel as RAL                                                   # noqa: E402
import real_probe_dryrun_selftest as RS                                        # noqa: E402

SIZE = (0.040, 0.016, 0.012)
OFF_TRUE = np.array([0.0, -0.090, 0.0])          # 模块中心相对 TCP (工具系, 米)
K = np.array([[610.0, 0, 318.0], [0.0, 607.0, 242.0], [0.0, 0.0, 1.0]])


def P_from_KRT(K, R, t):
    return K @ np.hstack([R, np.asarray(t, float).reshape(3, 1)])


def pose_set(n, spread, tilt_deg, seed, kind):
    """生成机器人位姿 (tcp, quat)。kind=small: 单轴小范围 (旧探针); kind=big: 两轴大范围 (生产级)"""
    rng = np.random.default_rng(seed)
    P_true, axes, _C = RS.make_camera((0.00, -0.45, 0.60), (0.30, 0.05, 0.10))
    u, v, w = axes[:, 0], axes[:, 1], axes[:, 2]
    base = np.asarray((0.30, 0.05, 0.10), float)
    out = []
    for i in range(n):
        a, b = rng.uniform(-1, 1, 2)
        if kind == "small":
            p = base + a * 0.03 * u + b * 0.03 * v          # 10cm 域, 无深度变化 + 单轴倾斜
            R = np.stack([u, v, w], axis=1) @ RS.axis_angle_R([0, 1, 0], math.radians(tilt_deg * a))
        else:
            c = rng.uniform(-1, 1)
            p = base + a * 0.125 * u + b * 0.125 * v + c * 0.125 * w   # 25cm 域含深度
            # 两轴姿态变化 (像人示教/生产时那样翻手腕)
            R = (np.stack([u, v, w], axis=1)
                 @ RS.axis_angle_R([0, 1, 0], math.radians(tilt_deg * a))
                 @ RS.axis_angle_R([1, 0, 0], math.radians(tilt_deg * b)))
        out.append((p, R))
    return out, (P_true, axes)


def observe(P_true, tcp, R_tool, size, off, noise_px=0.5, rng=None):
    """模拟 YOLO 框: 中心 + 宽高 (由真值 3D 框投影得到) + 亚像素噪声"""
    rng = rng or np.random.default_rng(0)
    center = np.asarray(tcp, float) + R_tool @ off
    quat = RS.rot_to_quat(R_tool)
    box = RAL.box_from_3d(P_true, center, quat, size, (640, 480))
    if box is None:
        return None
    x1, y1, x2, y2 = box
    uv = np.array([(x1 + x2) / 2, (y1 + y2) / 2]) + rng.normal(0, noise_px, 2)
    wh = np.array([x2 - x1, y2 - y1]) + rng.normal(0, noise_px, 2)
    return uv, wh


def residuals(params, poses, obs, size, use_size, lam=1.0):
    """params = [P(12 自由, 末尾归一) , off(3)] → 残差向量"""
    Pm = np.asarray(params[:12], float).reshape(3, 4)
    Pm = Pm / (np.linalg.norm(Pm) or 1.0)
    off = np.asarray(params[12:], float)
    r = []
    for (tcp, R), (uv, wh) in zip(poses, obs):
        center = np.asarray(tcp, float) + R @ off
        quat = RS.rot_to_quat(R)
        box = RAL.box_from_3d(Pm, center, quat, size, (640, 480))
        if box is None:
            r.extend([30.0, 30.0] + ([30.0 * lam, 30.0 * lam] if use_size else []))
            continue
        x1, y1, x2, y2 = box
        pu, pv = (x1 + x2) / 2, (y1 + y2) / 2
        r.extend([pu - uv[0], pv - uv[1]])
        if use_size:
            r.extend([lam * ((x2 - x1) - wh[0]), lam * ((y2 - y1) - wh[1])])
    return np.asarray(r, float)


def solve(poses, obs, size, use_size, iters=120, h=1e-4, lam_lm=1e-3):
    """LM 优化 (P, off) —— 手写数值雅可比, 参数 15 个, 观测几十上百条"""
    rng = np.random.default_rng(7)
    Pm0 = (rng.normal(0, 0.05, (3, 4)) + np.array([[600., 0, 320, 250.], [0, 600., 240, 200.], [0, 0, 1, 0.7]]))
    x = np.concatenate([Pm0.reshape(-1), np.zeros(3)])
    f = residuals(x, poses, obs, size, use_size)
    cost = float(f @ f)
    lam = lam_lm
    for _ in range(iters):
        J = np.zeros((f.size, x.size))
        for k in range(x.size):
            d = np.zeros(x.size); d[k] = h
            J[:, k] = (residuals(x + d, poses, obs, size, use_size)
                       - residuals(x - d, poses, obs, size, use_size)) / (2 * h)
        A = J.T @ J + lam * np.eye(x.size)
        try:
            step = np.linalg.solve(A, -J.T @ f)
        except np.linalg.LinAlgError:
            break
        x2 = x + step
        f2 = residuals(x2, poses, obs, size, use_size)
        c2 = float(f2 @ f2)
        if c2 < cost:
            x, f, cost, lam = x2, f2, c2, max(lam * 0.7, 1e-9)
        else:
            lam *= 3.0
        if lam > 1e7:
            break
    P_hat = x[:12].reshape(3, 4); P_hat = P_hat / (np.linalg.norm(P_hat) or 1.0)
    return P_hat, x[12:], float(np.sqrt(np.mean(f ** 2)))


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1]); x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def evaluate(P_hat, off_hat, P_true, holdout, size):
    """留出位姿 (没参与拟合): ① 3D 中心误差(mm) —— 注意: 3D 位置误差 ≡ 偏移误差 (P 只管投影)
       ② 投回图像的像素误差(px) ③ 框 IoU —— **决策相关的是 IoU** (自动标注直接用框)"""
    e3d, epx, ious = [], [], []
    for tcp, R in holdout:
        c_true = np.asarray(tcp, float) + R @ OFF_TRUE
        c_hat = np.asarray(tcp, float) + R @ np.asarray(off_hat, float)
        e3d.append(float(np.linalg.norm(c_hat - c_true)) * 1000)
        epx.append(float(np.linalg.norm(RAL.project(P_hat, c_hat) - RAL.project(P_true, c_true))))
        q = RS.rot_to_quat(R)
        b_t = RAL.box_from_3d(P_true, c_true, q, size, (640, 480))
        b_h = RAL.box_from_3d(P_hat, c_hat, q, size, (640, 480))
        if b_t and b_h:
            ious.append(iou(b_t, b_h))
    return (float(np.mean(e3d)), float(np.max(e3d)), float(np.mean(epx)),
            (float(np.median(ious)) if ious else None), len(ious))


def main():
    P_true, axes = pose_set(1, 0, 0, 0, "small")[1]
    rng = np.random.default_rng(2026)
    size = SIZE
    results = {}
    for kind, n, spread, tilt, tag in (("small", 24, 0.03, 16.0, "位姿小 (旧探针级)"),
                                       ("big", 90, 0.125, 25.0, "位姿大 (生产/示教级)")):
        poses_all, _ = pose_set(n + 12, spread, tilt, 11 if kind == "small" else 12, kind)
        train, holdout = poses_all[:n], poses_all[n:]
        obs = [observe(P_true, tcp, R, size, OFF_TRUE, 0.5, rng) for tcp, R in train]
        keep = [i for i, o in enumerate(obs) if o is not None]
        train = [train[i] for i in keep]
        obs = [obs[i] for i in keep]
        for use_size in (False, True):
            P_hat, off_hat, rms = solve(train, obs, size, use_size)
            m3, x3, mpx, miou, niou = evaluate(P_hat, off_hat, P_true, holdout, size)
            off_err = float(np.linalg.norm(off_hat - OFF_TRUE)) * 1000
            degenerate = rms > 20.0          # 残差卡在兜底值 = 解跑飞 (中心法就是这种)
            key = f"{tag} · {'框4边(中心+宽高)' if use_size else '只用框中心'}"
            results[key] = {"train_n": len(train), "rms_px": round(rms, 3), "degenerate": bool(degenerate),
                            "off_err_mm": round(off_err, 2),
                            "off_hat_mm": [round(float(v) * 1000, 1) for v in off_hat],
                            "holdout_3d_mm_mean": round(m3, 2), "holdout_3d_mm_max": round(x3, 2),
                            "holdout_px_mean": round(mpx, 3),
                            "holdout_iou_median": (round(miou, 3) if miou is not None else None)}
    # 在线收敛: 位姿大 + 框4边, 逐段增加帧数 (模拟生产/示教过程中越攒越多的数据)
    print("\n═══ 在线收敛 (位姿生产级 · 框4边): 攒多少帧 → 偏移解到多少 ═══")
    poses_all, _ = pose_set(240, 0.125, 25.0, 12, "big")
    rng3 = np.random.default_rng(99)
    conv = {}
    for n in (5, 10, 20, 40, 80, 160):
        tr = poses_all[:n]
        ob = [observe(P_true, tcp, R, size, OFF_TRUE, 0.5, rng3) for tcp, R in tr]
        kp = [i for i, o in enumerate(ob) if o is not None]
        tr = [tr[i] for i in kp]; ob = [ob[i] for i in kp]
        P_hat, off_hat, rms = solve(tr, ob, size, True)
        off_err = float(np.linalg.norm(off_hat - OFF_TRUE)) * 1000
        _, _, mpx, miou, _ = evaluate(P_hat, off_hat, P_true, poses_all[200:240], size)
        conv[n] = {"off_err_mm": round(off_err, 2), "rms_px": round(rms, 3),
                   "holdout_px": round(mpx, 3), "holdout_iou": (round(miou, 3) if miou is not None else None)}
        print(f"  {n:>4} 帧: off 误差 {off_err:7.2f}mm · 拟合 {rms:5.2f}px · "
              f"留出像素 {mpx:5.2f}px · 留出框 IoU {miou}")
    results["_convergence"] = conv

    rng2 = np.random.default_rng(5)
    print("\n═══ 「YOLO 2D框 → 3D」可辨识性实验 (合成, 真值偏移 = (0, -90, 0) mm) ═══")
    print(f"{'配置':<36}{'训练帧':>6}{'拟合rms':>9}{'off误差':>10}{'留出3D':>10}{'留出像素':>9}{'留出框IoU':>11}")
    for k, v in results.items():
        if "degenerate" not in v:
            continue
        flag = " (退化/跑飞)" if v["degenerate"] else ""
        print(f"{k:<36}{v['train_n']:>6}{v['rms_px']:>9.2f}{v['off_err_mm']:>8.1f}mm"
              f"{v['holdout_3d_mm_mean']:>8.1f}mm{v['holdout_px_mean']:>8.2f}px"
              f"{str(v['holdout_iou_median']):>11}{flag}")
    out = os.path.join("/home/ubuntu/zmax_data", f"mono23d_experiment_{__import__('time').strftime('%Y%m%d_%H%M%S')}.json")
    json.dump({"off_true_mm": [round(float(v) * 1000, 1) for v in OFF_TRUE], "size_mm": [s * 1000 for s in size],
               "noise_px": 0.5, "results": results}, open(out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n报告: {out}")


if __name__ == "__main__":
    raise SystemExit(main())
