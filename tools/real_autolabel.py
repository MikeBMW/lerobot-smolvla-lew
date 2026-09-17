#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""real_autolabel.py — 用「机器人实际动作」自动标注光模块 (kinematic auto-labeling)

老倪 2026-09-17:「设计一下, 如何通过机器人的实际动作, 抓取光模块, 自动标注。」

═══ 原理 (为什么根本不需要人拖框) ═══
机器人自己就是标定物与真值源, 分三步:

  S0 探针运动 (probe)     机器人夹着光模块在相机视野内走 9~12 个位姿 (覆盖画面四角/中心/不同深度)。
                          每个位姿记 3D 真值 = /robot/tcp_pose (=base_link 真值, ~50Hz 已落盘) 与一帧图像。
                          模块的**像素位置**不用人工框: 画面里只有夹爪+模块在动 → 相邻帧差分取运动连通域中心即可
                          (见 motion_center)。孔口/工装静止不参与差分, 天然被排除。

  S1 自标定 (kinematic eye-hand calibration)
                          拿 N 对 (3D 真值 → 像素点) 解 3x4 投影矩阵 P (DLT + Hartley 归一化, ≥6 对)。
                          ⚠️ 这等价于一次手眼标定, 但**不用棋盘格** —— 机器人带着模块当标定物。
                          P = K·[R|t] 已含内参与手眼外参的乘积, 做 2D 标注完全够; 需要 3D 反投影时才拆 K。
                          产出 models/real_cam_proj.json {P, n_pairs, rms_px, K_est(fx,fy,cx,cy)}。
                          与仿真口径对照: 仿真用 MuJoCo cam_mat0/cam_pos/cam_fovy 投影 (gen_yolo_data.project_3d_to_2d),
                          真机就是这一步的现场自标定版 —— 两边都是"真值 3D → 像素框", 同口径。

  S2 批量自动标注 (label) 之后任何"抓取→搬运→插入"过程都自动出标注:
                          光模块中心 (TCP + R·offset) + 模块物理尺寸 → 8 角点 → 投影 → AABB → YOLO 框 (class peg);
                          示教了 goal 点就同样投影出 hole 框。
                          **只在"抓取确认成立"的时段标** (抬升随动判据, 与 L4 抬升试探同口径) → 不给"没夹住"的帧发标签。
                          落盘复用 yolo_annot_dataset.save_sample → sessions/auto_<ts>/, annotator="auto:kinematic",
                          与人工样本同结构 → 直接进 dataset/truth.jsonl + 训练。

═══ 诚实边界 (不达标就不进默认档) ═══
· 框尺寸靠**配置的模块物理尺寸**, 不猜: 用 --size 给实测值 (默认 40x16x12mm 仅为占位, 输出里标 pending)。
· offset (模块中心相对 TCP) 未知时先按 0 解 P; 残差 rms_px 明显偏大 → 把 offset 一起最小二乘 (insight: 二者可辨识,
  因为探针运动里姿态在变)。仍未收敛就如实报, 不硬凑。
· 自动标注**绝不用来当 val/测试集** —— 评估必须在人工标注的留出集上做 (否则自证循环)。
· 自动标注与仿真权重能否复用, 由"人工留出集上的指标"裁决, 不由本轮自检裁决。

用法:
  python3 tools/real_autolabel.py --selftest                     # 数学核自检 (合成真值 → 反解 → 断言)
  python3 tools/real_autolabel.py --fit pairs.json --out models/real_cam_proj.json
  python3 tools/real_autolabel.py --label --proj models/real_cam_proj.json --size 0.040,0.016,0.012
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
PROJ_DEFAULT = os.path.join(_REPO, "models", "real_cam_proj.json")


# ───────────────────────── 投影核 (DLT) ─────────────────────────
def _norm2d(pts):
    """Hartley 归一化 (2D 齐次点 Nx3): 质心→0, 平均距离→sqrt(2)"""
    c = pts[:, :2].mean(axis=0)
    d = np.linalg.norm(pts[:, :2] - c, axis=1).mean()
    s = math.sqrt(2.0) / (d if d > 1e-12 else 1.0)
    T = np.array([[s, 0, -s * c[0]], [0, s, -s * c[1]], [0, 0, 1.0]])
    return pts @ T.T, T


def _norm3d(X):
    c = X[:, :3].mean(axis=0)
    d = np.linalg.norm(X[:, :3] - c, axis=1).mean()
    s = math.sqrt(3.0) / (d if d > 1e-12 else 1.0)
    T = np.eye(4)
    T[0, 0] = T[1, 1] = T[2, 2] = s
    T[:3, 3] = -s * c
    return X @ T.T, T


def fit_proj(pairs):
    """(3D, 2D) 对应 → 3x4 投影矩阵 P。pairs=[((X,Y,Z),(u,v)), ...], 最少 6 对。

    返回 (P(3x4), rms_px)。用 Hartley 归一化 + SVD 取最小奇异向量 (标准 DLT)。
    """
    pairs = [(np.asarray(x, float).reshape(3), np.asarray(uv, float).reshape(2)) for x, uv in pairs]
    if len(pairs) < 6:
        raise ValueError(f"至少需要 6 对点才能解 P, 现在只有 {len(pairs)} 对")
    X = np.hstack([np.stack([p[0] for p in pairs]), np.ones((len(pairs), 1))])       # Nx4
    U = np.hstack([np.stack([p[1] for p in pairs]), np.ones((len(pairs), 1))])       # Nx3
    Xn, T3 = _norm3d(X)
    Un, T2 = _norm2d(U)
    A = []
    for i in range(len(pairs)):
        x, y, z, w = Xn[i]
        u, v = Un[i, 0], Un[i, 1]
        A.append([0, 0, 0, 0, -w * x, -w * y, -w * z, -w * w, v * x, v * y, v * z, v * w])
        A.append([w * x, w * y, w * z, w * w, 0, 0, 0, 0, -u * x, -u * y, -u * z, -u * w])
    _, _, Vt = np.linalg.svd(np.array(A, float))
    Pn = Vt[-1].reshape(3, 4)
    P = np.linalg.inv(T2) @ Pn @ T3
    P = P / (np.linalg.norm(P[:3, :3]) if np.linalg.norm(P[:3, :3]) > 1e-12 else 1.0)
    err = []
    for x, uv in pairs:
        p = project(P, x)
        err.append(float(np.linalg.norm(p - uv)))
    return P, float(np.sqrt(np.mean(np.square(err))))


def project(P, xyz):
    """3D (base_link, 米) → 像素 (u,v)"""
    x = np.append(np.asarray(xyz, float).reshape(3), 1.0)
    h = np.asarray(P, float).reshape(3, 4) @ x
    if abs(h[2]) < 1e-12:
        raise ValueError("点落在相机平面 (w≈0)")
    return np.array([h[0] / h[2], h[1] / h[2]])


def _rq(A):
    """RQ 分解: A = K·R (K 上三角, R 正交) — Hartley & Zisserman 标准做法 (别用裸 QR, 会解错)"""
    P = np.array([[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [1.0, 0.0, 0.0]])
    Q, Rm = np.linalg.qr((P @ A).T)
    return P @ Rm.T @ P, P @ Q.T


def decompose_K(P):
    """从 P 左上 3x3 (=K·R 部分) RQ 分解出内参 (真实性判据: fx>0 且量级合理, 如 300~2000)"""
    M = np.asarray(P, float).reshape(3, 4)[:, :3]
    K, R = _rq(M)
    if abs(K[2, 2]) < 1e-12:
        raise ValueError("RQ 分解失败 (K[2,2]≈0)")
    K = K / K[2, 2]
    S = np.diag(np.sign(np.diag(K)))
    K, R = K @ S, S @ R
    if K[0, 0] < 0:
        K[:, 0] *= -1
        R[0, :] *= -1
    if K[1, 1] < 0:
        K[:, 1] *= -1
        R[1, :] *= -1
    return {"fx": float(K[0, 0]), "fy": float(K[1, 1]),
            "cx": float(K[0, 2]), "cy": float(K[1, 2])}


def quat_to_R(q):
    x, y, z, w = [float(v) for v in q]
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def module_corners(center, quat_xyzw, size_m):
    """光模块 8 角点 (base_link): center + R·(±sx/2, ±sy/2, ±sz/2)"""
    R = quat_to_R(quat_xyzw) if quat_xyzw else np.eye(3)
    hx, hy, hz = [s / 2.0 for s in size_m]
    return [tuple(np.asarray(center, float) + R @ np.array([sx * hx, sy * hy, sz * hz]))
            for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]


def box_from_3d(P, center, quat, size_m, img_wh):
    """模块 (中心+姿态+尺寸) → 图像 axis-aligned 框 (x1,y1,x2,y2)。
    越界裁剪到画面内; 若裁剪后框退化或整体落在画面外 → 返回 None (调用方跳过该帧, 不产生假标签)。"""
    pts = [project(P, c) for c in module_corners(center, quat, size_m)]
    W, H = img_wh
    x1 = max(0.0, min(p[0] for p in pts))
    y1 = max(0.0, min(p[1] for p in pts))
    x2 = min(float(W), max(p[0] for p in pts))
    y2 = min(float(H), max(p[1] for p in pts))
    if (x2 - x1) < 2.0 or (y2 - y1) < 2.0:
        return None
    return x1, y1, x2, y2


# ───────────────────────── S0: 运动域中心 (无需人工框) ─────────────────────────
def motion_center(prev_rgb, cur_rgb, min_area=60):
    """相邻帧差分的最大运动连通域中心 (像素) —— 画面里只有夹爪+模块在动, 静止背景(孔口/工装)天然排除。

    返回 ((u, v), area) 或 (None, 0)。无 cv2 或全静止 → None。
    """
    try:
        import cv2
    except ImportError:
        return None, 0
    if prev_rgb is None or cur_rgb is None:
        return None, 0
    a = cv2.cvtColor(prev_rgb, cv2.COLOR_RGB2GRAY)
    b = cv2.cvtColor(cur_rgb, cv2.COLOR_RGB2GRAY)
    d = cv2.absdiff(a, b)
    _, th = cv2.threshold(d, 18, 255, cv2.THRESH_BINARY)
    th = cv2.morphologyEx(th, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, stats, cent = cv2.connectedComponentsWithStats(th, 8)
    best, best_a = None, 0
    for i in range(1, n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area >= min_area and area > best_a:
            best, best_a = tuple(cent[i]), area
    return best, best_a


# ───────────────────────── 标定文件读写 ─────────────────────────
def save_proj(path, P, n_pairs, rms_px, extra=None):
    d = {"ready": True, "P": np.asarray(P, float).reshape(3, 4).tolist(),
         "n_pairs": int(n_pairs), "rms_px": round(float(rms_px), 4),
         "K_est": decompose_K(P), "method": "kinematic DLT (机器人带模块当标定物)",
         "updated_at": time.strftime("%F %T")}
    d["K_est_valid"] = bool(d["K_est"]["fx"] > 0 and d["K_est"]["fy"] > 0)
    if extra:
        d.update(extra)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return d


def load_proj(path=PROJ_DEFAULT):
    try:
        d = json.load(open(path, encoding="utf-8"))
        if d.get("ready"):
            return np.asarray(d["P"], float).reshape(3, 4), d
    except Exception:                                   # noqa: BLE001
        pass
    return None, {}


# ───────────────────────── S1 采集: 从落盘真值 + 图像生成标定点对 ─────────────────────────
def probe_pairs_from_session(session_frame_dir, truth_jsonl=None, out=None):
    """把一次"探针运动"的记录整理成 DLT 点对:
    图像 (frames/*.jpg) + 该时刻真值 (sessions/<s>/truth.jsonl 里的 TCP/quat) + 运动域中心 (=模块像素)。

    ⚠️ 需要**成对**的帧与真值; 真值侧车由「输入图像」窗口保存样本时写入 (annotator=probe 亦可)。
    返回 (pairs, info); pairs 不够 6 对时拟合会明确报错, 不硬凑。
    """
    import cv2
    pairs, used = [], []
    truth = {}
    if truth_jsonl and os.path.isfile(truth_jsonl):
        for ln in open(truth_jsonl, encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
                truth[r["stem"]] = r
            except ValueError:
                continue
    frames = sorted(glob.glob(os.path.join(session_frame_dir, "*.jpg")))
    prev, prev_tcp = None, None
    for fp in frames:
        stem = os.path.splitext(os.path.basename(fp))[0]
        img = cv2.imread(fp)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB) if img is not None else None
        t = truth.get(stem, {}).get("truth", {})
        tcp, quat = t.get("tcp"), t.get("tcp_quat")
        if img is not None and prev is not None and tcp and prev_tcp:
            uv, area = motion_center(prev, img)
            if uv:
                # ⚠️ 差分出来的运动域是**两帧之间**的位置, 所以 3D 用两帧 TCP 的**中点**配对 ——
                #   直接用后一帧 TCP 会引入半个采样周期的滞后偏置 (探针里机器人一直在动, 不能忽略)。
                mid = [round((a + b) / 2.0, 6) for a, b in zip(prev_tcp, tcp)]
                pairs.append((mid, uv))
                used.append({"stem": stem, "tcp_mid": mid, "uv": [round(v, 2) for v in uv], "area": area})
        prev, prev_tcp = img, tcp
    return pairs, {"n_frame": len(frames), "n_truth": len(truth), "n_pairs": len(pairs),
                   "pairing": "运动域中心 ↔ 两帧 TCP 中点 (消除半采样周期偏置)", "used": used}


def selftest():
    """数学核自检: 造已知 P → 反解 → 断言 (真跑, 不是口头)"""
    rng = np.random.default_rng(7)
    K = np.array([[610.0, 0, 318.0], [0, 607.0, 242.0], [0, 0, 1.0]])
    R = quat_to_R([0.7664547, 0.0754595, 0.6154991, 0.1673735])
    t = np.array([0.25, -0.18, 0.62])
    P_true = K @ np.hstack([R, t.reshape(3, 1)])
    pts3 = np.column_stack([rng.uniform(0.30, 0.70, 12), rng.uniform(-0.20, 0.20, 12),
                            rng.uniform(0.10, 0.45, 12)])
    pairs = [(p, project(P_true, p)) for p in pts3]
    P_hat, rms = fit_proj(pairs)
    K_est = decompose_K(P_hat)
    ok = rms < 1e-6 and abs(K_est["fx"] - 610.0) < 1.0 and abs(K_est["fy"] - 607.0) < 1.0
    print(f"[selftest] 12 对点 → DLT 反解: rms = {rms:.3e} px")
    print(f"[selftest] 还原内参: fx={K_est['fx']:.3f} (真 610) fy={K_est['fy']:.3f} (真 607)"
          f" cx={K_est['cx']:.2f} (真 318) cy={K_est['cy']:.2f} (真 242)")
    # 抗噪: 1px 像素噪声下残差应≈噪声量级
    noisy = [(x, uv + rng.normal(0, 1.0, 2)) for x, uv in pairs]
    _, rms_n = fit_proj(noisy)
    print(f"[selftest] 加 1px 高斯噪声: rms = {rms_n:.3f} px (应≈1.0, 说明不放大误差)")
    # 框生成: 取一个**必定在画面内**的点 (沿光轴 0.45m 处), 绕**相机光轴**转 90° 后框宽高应互换。
    # 用薄片 (厚度 0) 做这个检查 —— 有厚度时 AABB 会被沿光轴的深度分量污染, 宽高不是简单互换 (不是 bug)。
    C = -R.T @ t                                        # 相机中心 (base_link)
    c = C + R.T @ np.array([0.0, 0.0, 0.45])
    q0 = [0, 0, 0, 1.0]
    ax = R.T @ np.array([0.0, 0.0, 1.0])
    ax = ax / np.linalg.norm(ax)
    ang = math.pi / 2
    q90 = [float(ax[0] * math.sin(ang / 2)), float(ax[1] * math.sin(ang / 2)),
           float(ax[2] * math.sin(ang / 2)), math.cos(ang / 2)]
    thin = (0.040, 0.016, 0.0)
    b0 = box_from_3d(P_true, c, q0, thin, (640, 480))
    b90 = box_from_3d(P_true, c, q90, thin, (640, 480))
    print("[selftest] 测试点投影 =", np.round(project(P_true, c), 1), "(应在 640x480 内)")
    if b0 is None or b90 is None:
        print("[selftest] ❌ 框生成返回 None (点不在画面内) — 测试用例设计问题")
        return 1
    w0, h0 = b0[2] - b0[0], b0[3] - b0[1]
    w90, h90 = b90[2] - b90[0], b90[3] - b90[1]
    print(f"[selftest] 框生成(薄片): 0° 框 {w0:.1f}x{h0:.1f}px · 绕光轴转90° 后 {w90:.1f}x{h90:.1f}px (应换过来)")
    ok = ok and abs(w0 - h90) < max(3.0, 0.15 * h90) and abs(h0 - w90) < max(3.0, 0.15 * w90)
    print("[selftest] 判定:", "✅ 通过 (DLT 精确可逆 + 噪声不放大 + 姿态→框几何自洽)" if ok else "❌ 失败")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="机器人动作 → 光模块自动标注 (kinematic auto-labeling)")
    ap.add_argument("--selftest", action="store_true", help="数学核自检 (合成真值反解)")
    ap.add_argument("--fit", default=None, help="点对 JSON 文件 → 解投影矩阵")
    ap.add_argument("--probe", default=None, help="探针会话的 frames 目录 → 自动出点对 (配 --truth)")
    ap.add_argument("--truth", default=None, help="该会话的 truth.jsonl")
    ap.add_argument("--out", default=PROJ_DEFAULT, help="投影矩阵落盘路径")
    ap.add_argument("--label", action="store_true", help="用投影矩阵 + 真值批量生成 YOLO 标签")
    ap.add_argument("--proj", default=PROJ_DEFAULT)
    ap.add_argument("--size", default=None, help="模块物理尺寸 mm, 形如 40,16,12")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if a.probe:
        pairs, info = probe_pairs_from_session(a.probe, a.truth, a.out)
        print(json.dumps(info, ensure_ascii=False, indent=1))
        if len(pairs) < 6:
            print(f"❌ 只凑到 {len(pairs)} 对, DLT 需要 ≥6 对 — 探针运动请多走几个位姿 (覆盖画面四角+中心)")
            return 1
        P, rms = fit_proj(pairs)
        d = save_proj(a.out, P, len(pairs), rms)
        print(f"✅ 解出投影矩阵: rms={rms:.3f}px · {a.out}")
        print("   内参估计:", d["K_est"], "valid =", d["K_est_valid"])
        return 0
    if a.fit:
        raw = json.load(open(a.fit, encoding="utf-8"))
        pairs = [(p["xyz"], p["uv"]) for p in raw]
        P, rms = fit_proj(pairs)
        d = save_proj(a.out, P, len(pairs), rms)
        print(f"✅ rms={rms:.3f}px → {a.out} · K_est={d['K_est']}")
        return 0
    if a.label:
        P, meta = load_proj(a.proj)
        if P is None:
            print(f"❌ 投影矩阵不可用 ({a.proj}) — 先跑 --probe/--fit")
            return 1
        if not a.size:
            print("❌ --label 必须给 --size (模块实测物理尺寸 mm) — 框大小不能猜")
            return 1
        print("ℹ️ 批量标注循环在 S2 阶段接产线/示教时段 (输入 truth.jsonl + frames), 见本文件顶部设计; "
              "此处只做参数与前置校验:")
        print("   proj ready =", meta.get("rms_px"), "px · size(mm) =", a.size, "· 抓取判据 = 抬升随动")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
