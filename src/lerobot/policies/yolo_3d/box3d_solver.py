#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""box3d_solver.py — 单目「YOLO 2D 框 → 3D」自监督解算器 (无人工测量 / 无深度 / 无手眼标定)

老倪 2026-09-18: 「就用当前 YOLO 目标检测的结果做 2D→3D 转换。你来设计算法或模型。」
              「仿真模式下的 2D→3D 也不能作弊, 要用感知给过来的结果。」

═══ 算法 (一条先验 + 一个自监督拟合) ═══
唯一先验: 模块被夹爪**刚性夹持** ⇒ 模块中心 = TCP + R(q)·off, off 是常数 (未知)。
观测: 每帧 YOLO 框的**四个边** (x1,y1,x2,y2) —— 等价于 (中心, 宽, 高)。
      ⚠️ 宽高是**必须的**: 单目里"框有多大"就是唯一的深度线索; 只用框中心 → 欠定 (实测直接跑飞)。
未知: 投影矩阵 P (11 自由度) + 附着偏移 off (3 自由度)。
自监督目标: 让「用 P 投影 (TCP + R·off) 得到的框」同时对上观测框的中心和宽高。
            **不需要任何人工测量**: P 与 off 一起从数据里解出来 (机器人给了位姿真值, 相机给了框)。

═══ 为什么它能收敛 (实测, 见 tools/mono23d_experiment.py) ═══
  · 只用框中心            → 欠定, 解跑飞 (拟合残差卡在兜底值, 留出框 IoU 无意义)
  · 框4边 + 位姿小范围    → off 误差 39.9mm, 留出框 IoU 0.924
  · 框4边 + 位姿生产级    → off 误差  4.5mm, 留出框 IoU 0.971
  · 在线收敛 (生产级): 10 帧→IoU 0.945 · 20 帧→0.974 · 80 帧→0.987 · 160 帧→0.988
  ⇒ 姿态多样性和"用框的宽高"是两把钥匙; 数据越攒越准 (装配线正常干活就在攒)。

═══ 两种输出 ═══
  predict_held(box, tcp, quat)  机器人夹着模块时用 (最准, 实测 ~4mm): 直接由 TCP⊕off 得 3D
  predict_mono(box)             机器人**没**夹模块时用 (比如模块躺在台面上): 由框的**像素尺寸**
                                反推深度 → 视线求交 → 3D。精度取决于框尺寸测量, 会明显低于前者。
两种都只用"感知给过来的框", 不读仿真/环境真值 (不投机取巧)。
"""
from __future__ import annotations

import json
import math
import os
import time

import numpy as np

__all__ = ["Box3DSolver", "quat_to_R", "project"]

STATE_DEFAULT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))), "models", "box3d_state.json")


# ───────────────────────── 基础几何 (自带, 不依赖别的模块) ─────────────────────────
def quat_to_R(q):
    x, y, z, w = [float(v) for v in q]
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def project(P, xyz):
    x = np.append(np.asarray(xyz, float).reshape(3), 1.0)
    h = np.asarray(P, float).reshape(3, 4) @ x
    if abs(h[2]) < 1e-12:
        raise ValueError("点在相机平面上")
    return np.array([h[0] / h[2], h[1] / h[2]])


def _corners_R(center, R, size_m):
    """3D 边界框的 8 个角点 (base 系): center ± R·(±hx, ±hy, ±hz)。
    **这就是\"3D 边界框\"的完整表示**: 中心 + 姿态 R + 尺寸 size。"""
    c = np.asarray(center, float).reshape(3)
    R = np.asarray(R, float).reshape(3, 3)
    hx, hy, hz = [s / 2.0 for s in size_m]
    return [c + R @ np.array([sx * hx, sy * hy, sz * hz])
            for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]


def _aabb_R(P, center, R, size_m, wh):
    """把姿态为 R 的 3D 框投影回 2D → 外接 AABB (检测器看到的就是这个)"""
    pts = [project(P, c) for c in _corners_R(center, R, size_m)]
    W, H = wh
    x1 = max(0.0, min(p[0] for p in pts)); y1 = max(0.0, min(p[1] for p in pts))
    x2 = min(float(W), max(p[0] for p in pts)); y2 = min(float(H), max(p[1] for p in pts))
    if (x2 - x1) < 2.0 or (y2 - y1) < 2.0:
        return None
    return np.array([x1, y1, x2, y2])


def _box_corners(center, quat, size_m):
    return _corners_R(center, quat_to_R(quat) if quat else np.eye(3), size_m)


def _aabb(P, center, quat, size_m, wh):
    return _aabb_R(P, center, quat_to_R(quat) if quat else np.eye(3), size_m, wh)


def iou_2d(a, b):
    if a is None or b is None:
        return None
    x1, y1 = max(a[0], b[0]), max(a[1], b[1]); x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return float(inter / ua) if ua > 0 else 0.0


def _R_euler(angles):
    """(roll, pitch, yaw) 弧度 → 旋转矩阵 Rz·Ry·Rx (工具系 → 模块框系的小转角)"""
    a, b, c = [float(v) for v in angles]
    Rz = np.array([[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]])
    Ry = np.array([[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]])
    Rx = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
    return Rz @ Ry @ Rx


def _R_rotvec(v):
    """Rodrigues: 旋转向量 (弧度·轴) → 旋转矩阵 (手眼外参的旋转部分参数化)"""
    v = np.asarray(v, float).reshape(3)
    th = float(np.linalg.norm(v))
    if th < 1e-12:
        return np.eye(3)
    k = v / th
    Kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(th) * Kx + (1 - math.cos(th)) * (Kx @ Kx)


def _log_R(R):
    """旋转矩阵 → 旋转向量 (Rodrigues 反变换); 近 180° 时退化取对角法"""
    R = np.asarray(R, float).reshape(3, 3)
    c = max(-1.0, min(1.0, (float(np.trace(R)) - 1.0) / 2.0))
    th = math.acos(c)
    if th < 1e-9:
        return np.zeros(3)
    if abs(math.pi - th) < 1e-4:                        # 近 180°: 用对称部分取轴
        A = (R + np.eye(3)) / 2.0
        d = np.clip(np.diag(A), 0.0, None)
        i = int(np.argmax(d))
        k = A[:, i] / max(math.sqrt(d[i]), 1e-12)
        return (k / (np.linalg.norm(k) or 1.0)) * th
    v = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]]) / (2.0 * math.sin(th))
    return v * th


def _camera_center(P):
    C = np.linalg.svd(np.asarray(P, float).reshape(3, 4))[2][-1]
    return None if abs(C[3]) < 1e-12 else (C / C[3])[:3]


class Box3DSolver:
    """自监督解算器: 攒 (框, TCP, 四元数) → 解 (P, off) → 3D""".strip(" .")

    def __init__(self, size_mm=(40.0, 16.0, 12.0), img_wh=(640, 480), off0=None, max_n=600,
                 fix_off=None, K=None):
        # K: 相机内参 3x3 (真机可由 /realsense/color/camera_info 直接读 = 出厂标定值)。
        #    给了 K → 拟合只解 **手眼外参 (rvec3+t3)** 而不是 11 自由度投影矩阵 P:
        #    尺度被米制锚定 (不再与尺寸/偏移退化), 参数更少更稳。
        self.K = None if K is None else np.asarray(K, float).reshape(3, 3)
        self.size = tuple(float(s) / 1000.0 if float(s) > 1.0 else float(s) for s in size_mm)
        self.size_nominal = self.size            # 标称尺寸 (自标定前的先验)
        self.size_src = "标称"                    # 标称 | 自标定
        self.Rrel = np.eye(3)                     # 工具系→模块框系的固定转角 (夹持歪斜, 自监督可估)
        self.rrel_src = "默认=工具系轴向 (未估)"
        self.wh = tuple(img_wh)
        self.max_n = int(max_n)
        self.VALID_IOU_HELD = 0.45                 # 夹持假设自检门: 反投影框 vs 检测框的 IoU 下限
        self.obs = []                       # [{"box":[x1,y1,x2,y2], "tcp":[...], "quat":[...], "ts":..., "meta":{}}]
        self.P = None
        self.off = np.zeros(3) if off0 is None else np.asarray(off0, float)
        # fix_off: 已知"工具系→模块参考点"的零位 (机器人 TCP 示教过) → 只解 P, 少 3 个未知量
        self.fix_off = None if fix_off is None else np.asarray(fix_off, float)
        self.fitted = False
        self._size_a = None                       # 自标定的"尺寸×距离"常数 (单目测距用)
        self._look_dir = np.zeros(3)              # 相机看向目标的平均方向 (定视线正负用)
        self.last_span_px = None                  # 最近一次观测框的像素跨度 (σ 折算用)
        self.T_cam_from_base = None               # 手眼外参 (K 已知模式解出来的: base→cam 的 R,t)
        self.rms_px = None
        self.holdout_px = None
        self.fit_hist = []

    # ── 攒数据 (带质量门, 不达标直接拒收并说明原因) ──
    def add(self, box_px, tcp, quat, meta=None, img_wh=None):
        wh = tuple(img_wh or self.wh)
        x1, y1, x2, y2 = [float(v) for v in box_px]
        if tcp is None or quat is None:
            return {"ok": False, "why": "无机器人位姿真值 (TCP/四元数)"}
        if not np.isfinite([x1, y1, x2, y2]).all():
            return {"ok": False, "why": "框含非有限值"}
        w, h = x2 - x1, y2 - y1
        if w < 8 or h < 8:
            return {"ok": False, "why": f"框太小 ({w:.0f}x{h:.0f}px) → 没有尺度信息, 不收"}
        if x1 < 1 or y1 < 1 or x2 > wh[0] - 1 or y2 > wh[1] - 1:
            return {"ok": False, "why": "框贴边/出画 (被裁掉的框会带偏标定)"}
        if not (0.05 <= w / max(h, 1e-6) <= 20.0):
            return {"ok": False, "why": f"框长宽比异常 ({w/max(h,1e-6):.1f})"}
        self.obs.append({"box": [x1, y1, x2, y2], "tcp": [float(v) for v in tcp],
                         "quat": [float(v) for v in quat], "ts": time.time(), "meta": meta or {}})
        if len(self.obs) > self.max_n:
            self.obs = self.obs[-self.max_n:]
        return {"ok": True, "n": len(self.obs)}

    # ── 位姿多样性体检 (可辨识性的前提, 不合格就拒绝拟合) ──
    def diversity(self):
        if len(self.obs) < 3:
            return {"ok": False, "why": f"只有 {len(self.obs)} 帧"}
        X = np.stack([np.asarray(o["tcp"], float) for o in self.obs])
        span = (X.max(0) - X.min(0)).tolist()
        sv = np.linalg.svd(X - X.mean(0), compute_uv=False)
        planarity = float(sv[2] / sv[0]) if sv[0] > 1e-12 else 0.0
        # 姿态散布: 各帧工具轴相对首帧的夹角最大值
        R0 = quat_to_R(self.obs[0]["quat"])
        angs = []
        for o in self.obs:
            R = quat_to_R(o["quat"])
            c = max(-1.0, min(1.0, (np.trace(R0.T @ R) - 1.0) / 2.0))
            angs.append(math.degrees(math.acos(c)))
        tilt = float(max(angs)) if angs else 0.0
        ok = len(self.obs) >= 10 and planarity >= 0.15 and tilt >= 10.0
        why = ("位姿合格 (非共面 + 姿态散布够)" if ok else
               f"位姿不足: 帧 {len(self.obs)} (需≥10) · 平面性 {planarity:.3f} (需≥0.15, 要有深度变化) · "
               f"姿态散布 {tilt:.0f}° (需≥10°, 否则 offset 与 P 分不开)")
        return {"ok": ok, "why": why, "n": len(self.obs), "span_m": [round(float(s), 4) for s in span],
                "planarity": round(planarity, 4), "tilt_deg": round(tilt, 1)}

    # ── 残差: 中心(2) + 宽高(2) ──
    def _resid(self, x, obs, use_size=True, spec=None):
        """残差: 每个观测 中心(2) + 宽高(2)。

        参数排布由 spec 指定 (两种模式):
          · 投影矩阵模式 (默认): P(12) —— 但**会归一化** (P 只定义到尺度, 尺度由 FK 米制锚定)
          · **内参已知模式** (`spec['K_i']`): 只解 手眼 (rvec 3 + t 3) → P = K·[R|t] (米制, 不归一化)
        另有可选: off(3) · R_rel 欧拉角(3) · 尺寸缩放(1)。
        —— 联合估 R_rel 是必要的: 夹持歪斜不建模时, off 会被"吸收"掉 (实测偏 77mm), 3D 框整体偏。
        """
        spec = spec or {}
        if spec.get("K_i") is not None:
            i = int(spec["K_i"])
            Rm = _R_rotvec(x[i:i + 3])
            Pm = np.asarray(self.K, float) @ np.hstack([Rm, np.asarray(x[i + 3:i + 6], float).reshape(3, 1)])
        else:
            i = int(spec.get("P_i", 0))
            Pm = np.asarray(x[i:i + 12], float).reshape(3, 4)
            Pm = Pm / (np.linalg.norm(Pm) or 1.0)
        off = (np.asarray(self.fix_off, float) if self.fix_off is not None
               else np.asarray(x[spec["off_i"]:spec["off_i"] + 3], float))
        i_rrel = spec.get("rrel_i")
        Rrel = _R_euler(x[i_rrel:i_rrel + 3]) if i_rrel is not None else np.asarray(self.Rrel, float)
        i_scale = spec.get("scale_i")
        size = (tuple(np.asarray(self.size_nominal, float) * float(x[i_scale])) if i_scale is not None
                else self.size)
        r = []
        for o in obs:
            R = quat_to_R(o["quat"])
            c = np.asarray(o["tcp"], float) + R @ off
            b = _aabb_R(Pm, c, R @ Rrel, size, self.wh)
            if b is None:                                   # 模型框出画 = 明确惩罚 (别让它跑到画面外"拟合")
                r.extend([40.0, 40.0] + ([40.0, 40.0] if use_size else []))
                continue
            ob = o["box"]
            r.extend([(b[0] + b[2]) / 2 - (ob[0] + ob[2]) / 2,
                      (b[1] + b[3]) / 2 - (ob[1] + ob[3]) / 2])
            if use_size:
                r.extend([(b[2] - b[0]) - (ob[2] - ob[0]), (b[3] - b[1]) - (ob[3] - ob[1])])
        return np.asarray(r, float)

    # ── 拟合 (LM, 数值雅可比; 15 个参数) ──
    def fit(self, iters=150, holdout_frac=0.2, seed=7, use_rrel=False, use_scale=False,
            rrel_range_deg=40.0, scale_range=(0.5, 2.0)):
        """LM 拟合。未知量 = P(11) [+ off(3)] [+ R_rel(3)] [+ 尺寸缩放(1)]。

        use_rrel=True: **联合**估计夹持歪斜 (只在姿态散布够时才有意义) —— 不估它, off 会被歪斜
                       吸收掉 (实测中心偏 77mm), 3D 边界框的 8 角点方向也不对。
        use_scale=True: 联合估计尺寸缩放 (不假设 40×16×12) —— 与 off 沿视线有弱耦合, 靠姿态多样性分开。
        """
        div = self.diversity()
        if not div["ok"]:
            self.fitted = False
            return {"ok": False, "why": div["why"], "diversity": div}
        rng = np.random.default_rng(seed)
        idx = rng.permutation(len(self.obs))
        n_h = max(3, int(len(self.obs) * holdout_frac))
        ho = [self.obs[i] for i in idx[:n_h]]
        tr = [self.obs[i] for i in idx[n_h:]] or self.obs
        _P0 = (np.array([[600., 0, self.wh[0] / 2, 250.], [0, 600., self.wh[1] / 2, 200.],
                         [0., 0, 1, 0.7]])).reshape(-1)
        spec = {}
        if self.K is not None:
            # ── 内参已知 (真机 camera_info): 先做一次无内参投影拟合当**初值**, 再按 P = s·K[R|t] 分解,
            #    最终只解 手眼 (rvec 3 + t 3) —— 尺度被米制锚定, 不再与尺寸/偏移退化 ──
            xp = (_P0.copy() if self.fix_off is not None else np.concatenate([_P0, np.zeros(3)]))
            sp0 = {"P_i": 0, "off_i": 12, "rrel_i": None, "scale_i": None}
            xp, _ = self._lm(xp, lambda z: self._resid(z, tr, spec=sp0), iters=80)
            Pm = np.asarray(xp[:12], float).reshape(3, 4)
            try:
                M = np.linalg.solve(np.asarray(self.K, float), Pm)          # ≈ s·[R|t]
            except np.linalg.LinAlgError:
                M = np.linalg.pinv(np.asarray(self.K, float)) @ Pm
            s = float(np.linalg.norm(M[:, 0])) or 1.0
            U, _sv, Vt = np.linalg.svd(M[:, :3] / s)
            R0 = U @ Vt
            if np.linalg.det(R0) < 0:
                R0 = U @ np.diag([1.0, 1.0, -1.0]) @ Vt
            x = np.concatenate([_log_R(R0), M[:, 3] / s])
            spec = {"K_i": 0, "off_i": 6}
            if self.fix_off is None:
                x = np.concatenate([x, xp[12:15]])
        else:
            x = (_P0.copy() if self.fix_off is not None else np.concatenate([_P0, np.zeros(3)]))
            spec = {"P_i": 0, "off_i": 12}
        if use_rrel:
            spec["rrel_i"] = int(x.size); x = np.concatenate([x, np.zeros(3)])
        if use_scale:
            spec["scale_i"] = int(x.size); x = np.concatenate([x, np.ones(1)])
        if use_rrel and div.get("tilt_deg", 0.0) < 8.0:
            # 姿态散布不够 → R_rel 不可辨识 → 退回不估 (否则它会吸收 off, 中心整体偏)
            _i = spec.pop("rrel_i")
            x = np.delete(x, slice(_i, _i + 3))
            if "scale_i" in spec:
                spec["scale_i"] = _i
        r = self._resid(x, tr, spec=spec); cost = float(r @ r); lam = 1e-3
        h = 1e-4
        hist = []
        for _ in range(int(iters)):
            J = np.zeros((r.size, x.size))
            for k in range(x.size):
                d = np.zeros(x.size); d[k] = h
                J[:, k] = (self._resid(x + d, tr, spec=spec) - self._resid(x - d, tr, spec=spec)) / (2 * h)
            try:
                step = np.linalg.solve(J.T @ J + lam * np.eye(x.size), -J.T @ r)
            except np.linalg.LinAlgError:
                break
            x2 = x + step
            if use_scale:
                x2[spec["scale_i"]] = float(np.clip(x2[spec["scale_i"]], scale_range[0], scale_range[1]))
            if use_rrel:
                dm = math.radians(float(rrel_range_deg))
                x2[spec["rrel_i"]:spec["rrel_i"] + 3] = np.clip(x2[spec["rrel_i"]:spec["rrel_i"] + 3], -dm, dm)
            r2 = self._resid(x2, tr, spec=spec); c2 = float(r2 @ r2)
            if c2 < cost:
                x, r, cost, lam = x2, r2, c2, max(lam * 0.7, 1e-9)
            else:
                lam *= 3.0
            hist.append(round(cost, 6))
            if lam > 1e7:
                break
        if spec.get("K_i") is not None:
            _i = int(spec["K_i"])
            Rm = _R_rotvec(x[_i:_i + 3])
            tv = np.asarray(x[_i + 3:_i + 6], float)
            P = np.asarray(self.K, float) @ np.hstack([Rm, tv.reshape(3, 1)])
            self.T_cam_from_base = {"R": np.round(Rm, 6).tolist(), "t": [round(float(v), 6) for v in tv],
                                   "src": "内参K已知 → 只解手眼 (R,t), 米制锚定"}
        else:
            P = x[:12].reshape(3, 4); P = P / (np.linalg.norm(P) or 1.0)
            self.T_cam_from_base = None
        self.P = P
        self.off = (np.asarray(self.fix_off, float) if self.fix_off is not None
                    else np.asarray(x[spec["off_i"]:spec["off_i"] + 3], float))
        if use_rrel and "rrel_i" in spec:
            self.Rrel = _R_euler(x[spec["rrel_i"]:spec["rrel_i"] + 3])
            self.rrel_src = "自标定(联合拟合)"
        if use_scale and "scale_i" in spec:
            k = float(x[spec["scale_i"]])
            self.size = tuple(float(s * k) for s in self.size_nominal)
            self.size_src = "自标定(联合拟合)"
        self.fitted = True
        self.rms_px = float(np.sqrt(np.mean(self._resid(x, tr, spec=spec) ** 2)))
        self.holdout_px = float(np.sqrt(np.mean(self._resid(x, ho, spec=spec) ** 2)))
        self.fit_hist = hist[-5:]
        # ── 自标定"尺寸×距离"常数 (供 predict_mono 用): span_px·dist ≈ a (物理上 a≈f·L) ──
        C = _camera_center(self.P)
        if C is not None:
            a_vals, dirs = [], []
            for o in tr:
                c = np.asarray(o["tcp"], float) + quat_to_R(o["quat"]) @ self.off
                dd = float(np.linalg.norm(C - c))
                span = math.hypot(o["box"][2] - o["box"][0], o["box"][3] - o["box"][1])
                if dd > 1e-6 and span > 4:
                    a_vals.append(span * dd)
                    dirs.append((c - C) / dd)
            if a_vals:
                self._size_a = float(np.median(a_vals))
                self._look_dir = np.mean(np.stack(dirs), axis=0)
                self._size_a_spread = float(np.std(a_vals) / max(1e-9, np.mean(a_vals)))
        return {"ok": True, "n_fit": len(tr), "n_holdout": len(ho), "rms_px": round(self.rms_px, 3),
                "K_known": bool(self.K is not None), "T_cam_from_base": self.T_cam_from_base,
                "holdout_rms_px": round(self.holdout_px, 3),
                "off_mm": [round(float(v) * 1000, 1) for v in self.off],
                "rrel_deg": (None if "rrel_i" not in spec else
                             [round(math.degrees(float(v)), 2) for v in x[spec["rrel_i"]:spec["rrel_i"] + 3]]),
                "size_mm": [round(s * 1000, 2) for s in self.size], "size_src": self.size_src,
                "size_a": (round(self._size_a, 2) if self._size_a else None),
                "size_a_spread": (round(getattr(self, "_size_a_spread", 0.0), 4)
                                  if getattr(self, "_size_a", None) else None),
                "diversity": div, "degenerate": bool(self.rms_px > 20.0)}

    # ── 出 3D ──
    def predict_held(self, tcp, quat):
        """机器人夹着时: 3D 中心 = TCP + R(q)·off (最准)"""
        if self.off is None:
            return None
        return (np.asarray(tcp, float) + quat_to_R(quat) @ self.off).tolist()

    def predict_mono(self, box_px):
        """机器人**没**夹着时: 只用框的像素尺寸反推距离 → 视线求交 → 3D (不需要机器人位姿)。

        距离靠**自标定的尺寸-距离关系**: 训练帧里每帧都有"框的像素跨度 span_px"和"模块到相机的
        真实距离 dist" (由 P 的相机中心 + TCP⊕off 算出) → 最小二乘解一个比例常数 a = span_px·dist
        (物理上 a ≈ f·L, f 焦距, L 模块尺寸)。用的时候 dist = a / span_px。
        不依赖 K、不依赖深度传感器; 精度取决于框尺寸的稳定性 (会明显低于 predict_held)。
        """
        r = self.predict_mono_sigma(box_px)
        return None if r is None else r["X"]

    def predict_box_model(self, box_px, quat, *, d_lo=0.10, d_hi=1.60, iters=28, sigma_px=0.5):
        """**已知姿态**时反解投影模型 (无偏) —— 单目从"框 + 姿态"定距离的正确做法。

        为什么必须有这个 (2026-09-18 实测): 只用"框跨度×距离=常数"的标量模型, 会因"哪个面朝相机"
        随姿态变化而带上 ~15% 的系统性偏差 (实测 0.70m 处估成 0.806m)。而模块的姿态我们是知道的
        (夹持时 = 机器人 FK; 固定工装件 = 一次示教) → 直接数值反解: 沿视线找一个距离 d, 使
        "把该姿态的模块放在 d 处投影出来的 AABB 跨度" 等于观测框跨度 (二分求根, 单调可解)。

        返回 {X, dist_m, sigma_m, span_model, span_obs, resid_px} 或 None
        """
        if self.P is None or quat is None:
            return None
        x1, y1, x2, y2 = [float(v) for v in box_px]
        P = np.asarray(self.P, float).reshape(3, 4)
        C = _camera_center(P)
        if C is None:
            return None
        u, v = (x1 + x2) / 2, (y1 + y2) / 2
        M = np.vstack([P[0] - u * P[2], P[1] - v * P[2]])[:, :3]
        d = np.linalg.svd(M)[2][-1]
        d = d / (np.linalg.norm(d) or 1.0)
        if float(np.dot(d, np.asarray(self._look_dir, float))) < 0:
            d = -d
        span_obs = math.hypot(x2 - x1, y2 - y1)

        def span_model(dist):
            b = _aabb(P, (C + dist * d).tolist(), quat, self.size, self.wh)
            if b is None:
                return None
            return math.hypot(b[2] - b[0], b[3] - b[1])

        lo, hi = float(d_lo), float(d_hi)
        s_lo, s_hi = span_model(lo), span_model(hi)
        if s_lo is None or s_hi is None or not (s_lo > span_obs > s_hi):
            return None                                     # 框太大/太小, 超出这个距离区间
        for _ in range(int(iters)):                          # 二分: span 随距离单调递减
            mid = 0.5 * (lo + hi)
            sm = span_model(mid)
            if sm is None:
                return None
            if sm > span_obs:
                lo = mid
            else:
                hi = mid
        dist = 0.5 * (lo + hi)
        # σ 由灵敏度给出: σ_dist = σ_span / |d span/d dist| (数值差分)
        h = max(1e-4, dist * 0.01)
        s1, s2 = span_model(dist + h), span_model(max(1e-3, dist - h))
        if s1 is None or s2 is None or abs(s1 - s2) < 1e-9:
            return None
        slope = abs(s1 - s2) / (2 * h)
        sigma = float(sigma_px) / max(1e-9, slope)
        return {"X": (C + dist * d).tolist(), "dist_m": round(float(dist), 4),
                "sigma_m": round(float(sigma), 5), "span_px": round(float(span_obs), 2),
                "span_model": round(float(span_model(dist) or 0.0), 2),
                "resid_px": round(abs(float(span_model(dist) or 0.0) - span_obs), 3),
                "method": "box+姿态 反解投影模型 (无偏)"}

    def predict_mono_sigma(self, box_px, sigma_span_px=0.5, quat=None):
        """同 predict_mono, 但**带不确定度** —— 闭环控制必须知道"这次测得有多准"。

        误差传播 (关键):
            dist = a / span      ⇒  σ_dist = dist²·σ_span / a = (dist/span)·σ_span
        即 **绝对深度误差 ∝ 距离²**: 0.7m 处 30px 框 → σ≈23mm; 0.2m 处 105px 框 → σ≈2mm。
        这就是"越靠近越准"的定量版本, 也是闭环能收敛的依据 (近处测量自然被加权更多)。
        """
        if quat is not None:
            m = self.predict_box_model(box_px, quat, sigma_px=sigma_span_px)
            if m is not None:
                return m
        if self.P is None or getattr(self, "_size_a", None) is None:
            return None
        x1, y1, x2, y2 = [float(v) for v in box_px]
        P = np.asarray(self.P, float).reshape(3, 4)
        C = _camera_center(P)
        if C is None:
            return None
        u, v = (x1 + x2) / 2, (y1 + y2) / 2
        M = np.vstack([P[0] - u * P[2], P[1] - v * P[2]])[:, :3]
        d = np.linalg.svd(M)[2][-1]
        d = d / (np.linalg.norm(d) or 1.0)
        if float(np.dot(d, np.asarray(self._look_dir, float))) < 0:
            d = -d
        span_px = max(6.0, math.hypot(x2 - x1, y2 - y1))
        dist = float(self._size_a) / span_px
        sigma = (dist / span_px) * float(sigma_span_px)
        X = C + dist * d
        return {"X": X.tolist(), "dist_m": round(float(dist), 4),
                "sigma_m": round(float(sigma * 2.0), 5), "span_px": round(float(span_px), 2),
                "method": "标量尺寸模型 (无姿态 → 有 10~20% 系统偏差, σ×2)"}

    @staticmethod
    def fuse(measurements):
        """多帧/多距离的测量融合: 按 1/σ² 加权 (近处小 σ → 权重大), 返回 (X_fused, sigma_fused)。

        这一步是闭环的"记忆": 同一目标从 0.7m 和 0.2m 各测一次, 融合后误差比单次都小。
        """
        ms = [m for m in measurements if m and m.get("X") and m.get("sigma_m")]
        if not ms:
            return None, None
        W = np.array([1.0 / max(1e-9, float(m["sigma_m"])) ** 2 for m in ms])
        Xs = np.stack([np.asarray(m["X"], float) for m in ms])
        Xf = (Xs * W[:, None]).sum(0) / W.sum()
        sig = float(1.0 / math.sqrt(float(W.sum())))    # 各轴同 σ 的简化 (视线近似同方差)
        return Xf.tolist(), round(sig, 5)

    def project_box(self, center, quat):
        if self.P is None:
            return None
        b = _aabb(self.P, center, quat, self.size, self.wh)
        return None if b is None else [round(float(v), 1) for v in b]

    def projected_box_for(self, box_px=None, tcp=None, quat=None, size_mm=None):
        """把"TCP⊕off + 当前尺寸/姿态"这个 3D 框**反投影**回 2D 框 —— 现场自检/前提自证用。
        (与要检测的那个框比对: IoU 高 = 中心=TCP+R·off / 尺寸 / 姿态 这套假设与相机模型自洽)"""
        if self.P is None or self.off is None or tcp is None or quat is None:
            return None
        size = self._size_m(size_mm)
        c = np.asarray(tcp, float) + quat_to_R(quat) @ np.asarray(self.off, float)
        b = _aabb_R(np.asarray(self.P, float).reshape(3, 4), c, self.R_box(quat), size, self.wh)
        return None if b is None else [round(float(v), 1) for v in b]

    # ══════════════ 2D 框 → **3D 边界框** (完整表示: 中心 + 姿态 + 尺寸 + 8 角点) ══════════════
    def _size_m(self, size_mm=None):
        if size_mm is None:
            return self.size
        return tuple(float(s) / 1000.0 if float(s) > 1.0 else float(s) for s in size_mm)

    def R_box(self, quat):
        """模块框姿态 = 工具姿态 R(q) · R_rel  (R_rel = 夹持歪斜, 默认单位阵)"""
        return quat_to_R(quat) @ np.asarray(self.Rrel, float).reshape(3, 3)

    def held_selfcheck(self, box_px, tcp, quat, size_mm=None):
        """**夹持假设自检**: 用 FK(TCP⊕off) 反投影出的框 vs 检测框。

        这是\"到底是不是同一块被夹着的模块\"唯一不用额外传感器的判据 —— 随动对上了 = 夹持成立,
        对不上 = 目标不在手上 (或 off/P 错)。IoU ≥ VALID_IOU_HELD 才算成立。
        """
        if self.P is None or self.off is None:
            return {"ok": False, "why": "相机 P 未标定 → 无法做夹持自检", "iou": None}
        size = self._size_m(size_mm)
        c = np.asarray(tcp, float) + quat_to_R(quat) @ np.asarray(self.off, float)
        b = _aabb_R(np.asarray(self.P, float).reshape(3, 4), c, self.R_box(quat), size, self.wh)
        iou = iou_2d(b, box_px)
        ok = bool(iou is not None and iou >= float(self.VALID_IOU_HELD))
        return {"ok": ok, "iou": (None if iou is None else round(iou, 3)),
                "box_model": (None if b is None else [round(float(v), 1) for v in b]),
                "why": ("夹持假设成立 (反投影框对上检测框)" if ok else
                        f"夹持假设不成立: IoU {iou if iou is None else round(iou,3)} < {self.VALID_IOU_HELD}")}

    def _sigma_center_m(self, resid_px, center):
        """像素残差 → 中心米误差: 局部比例 = dist / span (针孔近似)。未标定 → None (不编)。"""
        if self.P is None or resid_px is None:
            return None
        C = _camera_center(np.asarray(self.P, float).reshape(3, 4))
        if C is None:
            return None
        dist = float(np.linalg.norm(np.asarray(center, float) - C))
        span = self.last_span_px or 1.0
        return max(1e-6, float(resid_px) * dist / max(1.0, span))

    def predict_box3d(self, box_px, tcp=None, quat=None, *, held=None, size_mm=None,
                      sigma_px=0.5, sigma_rep_mm=0.5):
        """**2D 检测框 → 3D 边界框** (本场景唯一的正解路径, 按可用信息分档)。

        分支 (gaps 里逐条写清\"这一档靠什么成立\"):
          A `held`      夹持态 + 已标定  : 中心 = TCP + R(q)·off (FK 锚定) · 姿态 = R(q)·R_rel
                                         · 反投影框 vs 检测框 IoU 自检 · σ = 夹持重复性 + 残差折算
          B `mono_pose` 非夹持 + 已标定  : 框跨度 + 姿态 反解投影模型 定距离 → 视线求交 (无偏, σ∝距离²)
          C `mono_scalar` 非夹持 + 无姿态: 标量尺寸模型 (有 10~20% 系统偏差, σ×2)
          D `fk_only`   未标定 + 有位姿  : 只给 FK 锚定框 (off 未标定 / 尺寸标称 / 无自检) — **诚实降级**
          E `no_3d`     未标定 + 无位姿  : 拒绝出 3D (只回 2D 框 + 缺什么)

        返回: {ok, mode, center, R, size_mm, corners8, box2d_obs, box2d_reproj, iou, resid_px,
               sigma_mm{center,repeat}, dist_m, held_selfcheck, gaps[], method, ...}
        """
        box = [float(v) for v in box_px]
        size = self._size_m(size_mm)
        self.last_span_px = math.hypot(box[2] - box[0], box[3] - box[1])
        out = {"ok": False, "mode": "no_3d", "center": None, "R": None,
               "size_mm": [round(s * 1000, 3) for s in size], "size_src": self.size_src,
               "rrel_src": self.rrel_src, "corners8": None,
               "box2d_obs": [round(v, 1) for v in box], "box2d_reproj": None, "iou": None,
               "resid_px": None, "sigma_mm": None, "dist_m": None, "held_selfcheck": None,
               "gaps": [], "method": "", "fitted": bool(self.fitted), "n_obs": len(self.obs),
               "span_px": round(self.last_span_px, 1)}
        if self.size_src != "自标定":
            out["gaps"].append(f"尺寸用的是标称值 {[round(s*1000,1) for s in size]}mm (未自标定)")
        if self.rrel_src.startswith("默认"):
            out["gaps"].append("模块相对工具的固定转角 R_rel 未估 (按工具系轴向算 8 角点)")

        # ── A/B/C 全都要已标定的相机模型 P ──
        if self.P is not None and self.off is not None:
            if tcp is not None and quat is not None:
                sc = self.held_selfcheck(box, tcp, quat, size_mm=size)
                out["held_selfcheck"] = sc
                R_b = self.R_box(quat)
                c = np.asarray(tcp, float) + quat_to_R(quat) @ np.asarray(self.off, float)
                b_proj = _aabb_R(np.asarray(self.P, float).reshape(3, 4), c, R_b, size, self.wh)
                out["box2d_reproj"] = (None if b_proj is None else [round(float(v), 1) for v in b_proj])
                iou = iou_2d(b_proj, box)
                take_held = True if held is True else (held is None and sc.get("ok"))
                if take_held:
                    out.update({"ok": True, "mode": "held", "center": [round(float(v), 6) for v in c],
                                "R": np.round(R_b, 6).tolist(),
                                "corners8": [[round(float(v), 6) for v in p] for p in _corners_R(c, R_b, size)],
                                "iou": (None if iou is None else round(float(iou), 3)),
                                "resid_px": (None if b_proj is None else
                                             round(float(max(abs(b_proj[0]-box[0]), abs(b_proj[1]-box[1]),
                                                             abs(b_proj[2]-box[2]), abs(b_proj[3]-box[3]))), 2))})
                    sig_res = self._sigma_center_m(out["resid_px"], c)
                    sig_rep = 0.0 if self.fix_off is not None else float(sigma_rep_mm) / 1000.0
                    out["sigma_mm"] = {"center": (None if sig_res is None else round(float(sig_res) * 1000, 2)),
                                       "repeat": round(sig_rep * 1000, 2),
                                       "total": (None if sig_res is None else
                                                 round(float(math.hypot(sig_res, sig_rep)) * 1000, 2))}
                    _d = self._cam_dist(c)
                    out["dist_m"] = (None if _d is None else round(float(_d), 4))
                    out["method"] = ("夹持态 FK 锚定: 中心=TCP+R(q)·off · 姿态=R(q)·R_rel · "
                                     "尺寸" + ("自标定" if self.size_src == "自标定" else "标称") +
                                     " · 反投影框自检" + (f" IoU {out['iou']}" if out["iou"] is not None else ""))
                    if out["iou"] is not None and out["iou"] < float(self.VALID_IOU_HELD):
                        out["gaps"].append(f"反投影框与检测框 IoU {out['iou']} 偏低 → 中心/尺寸/姿态之一有偏")
                    if self.fix_off is not None:
                        out["gaps"].append("工具零点已示教 (off 固定) → 中心由 FK 直接给, 误差只剩夹持重复性")
                    else:
                        out["gaps"].append(f"夹持偏移 off 为自监督估计 {[round(float(v)*1000,1) for v in self.off]}mm "
                                           f"(拟合留出 {None if self.holdout_px is None else round(self.holdout_px,2)}px)")
                    return out
            # ── B/C: 非夹持态 → 单目定距离 ──
            m = None
            if quat is not None:
                m = self.predict_box_model(box, quat, sigma_px=sigma_px)
                if m is not None:
                    R_b = self.R_box(quat)
                    iou = iou_2d(_aabb_R(np.asarray(self.P, float).reshape(3, 4),
                                         m["X"], R_b, size, self.wh), box)
                    iou_io = iou
                    out.update({"ok": True, "mode": "mono_pose", "center": [round(float(v), 6) for v in m["X"]],
                                "R": np.round(R_b, 6).tolist(),
                                "corners8": [[round(float(v), 6) for v in p]
                                             for p in _corners_R(m["X"], R_b, size)],
                                "iou": (None if iou is None else round(float(iou), 3)),
                                "dist_m": m["dist_m"], "resid_px": m["resid_px"],
                                "sigma_mm": {"center": round(float(m["sigma_m"] * 1000), 2), "repeat": 0.0,
                                             "total": round(float(m["sigma_m"] * 1000), 2)},
                                "method": "非夹持态: 框跨度 + 姿态 反解投影模型定距离 → 视线求交 (无偏)"})
                    out["gaps"].append("非夹持单目测距: σ ∝ 距离² (越近越准), 远距离必须靠多帧融合")
                    return out
            m = self.predict_mono_sigma(box, sigma_span_px=sigma_px)
            if m is not None:
                out.update({"ok": True, "mode": "mono_scalar", "center": [round(float(v), 6) for v in m["X"]],
                            "R": np.round(self.Rrel, 6).tolist(),
                            "corners8": [[round(float(v), 6) for v in p]
                                         for p in _corners_R(m["X"], self.Rrel, size)],
                            "dist_m": m["dist_m"], "sigma_mm": {"center": round(float(m["sigma_m"] * 1000), 2),
                                                               "repeat": 0.0,
                                                               "total": round(float(m["sigma_m"] * 1000), 2)},
                            "method": "非夹持 + 无姿态: 标量尺寸模型反推距离 (有 10~20% 系统偏差)"})
                out["gaps"].append("没有姿态 → 标量模型系统偏差 10~20%, σ 已 ×2")
                return out
            out["gaps"].append("相机 P 已标定但本次框解不出距离 (框太大/太小, 超出 0.10~1.60m 可解区间)")
            return out

        # ── D: 未标定 + 有机器人位姿 → FK 锚定框 (诚实降级, 不算 3D 自检) ──
        if tcp is not None and quat is not None and held is not False:
            R_b = self.R_box(quat)
            off = np.zeros(3) if self.off is None else np.asarray(self.off, float)
            c = np.asarray(tcp, float) + quat_to_R(quat) @ off
            out.update({"ok": True, "mode": "fk_only", "center": [round(float(v), 6) for v in c],
                        "R": np.round(R_b, 6).tolist(),
                        "corners8": [[round(float(v), 6) for v in p] for p in _corners_R(c, R_b, size)],
                        "sigma_mm": None,
                        "method": ("未标定降级 (内参已知 · 手眼待标): 中心=TCP+R(q)·off (off 未知按 0) · 姿态=R(q) · 尺寸=标称" if self.K is not None else "未标定降级: 中心=TCP+R(q)·off (off 未知按 0) · 姿态=R(q) · 尺寸=标称")})
            out["gaps"] += [
                ("相机内参 K 已知 (真机 camera_info), 但**手眼外参未标定** → 无 2D 反投影自检, "
                 "也没有\"越近越准\"的 σ" if self.K is not None else
                 "相机 P 未标定 (无内参) → 无 2D 反投影自检, 也没有\"越近越准\"的 σ"),
                "夹持偏移 off 未标定 → 中心就用 TCP 近似 (真实偏移可能几 cm, 本档不可用于插拔)"]
            return out

        # ── E: 什么都没有 ──
        if not self.fitted:
            out["gaps"].append("相机模型未标定 (需攒 ≥10 帧不同位姿的『框+TCP位姿』自监督拟合): "
                               + ("已有内参 K → 只解手眼 (R,t) 6 自由度" if self.K is not None
                                  else "无内参 → 解 11 自由度投影 P"))
        if tcp is None or quat is None:
            out["gaps"].append("拿不到机器人位姿 (TCP/四元数)")
        out["gaps"].append("本帧拒绝产出 3D (宁缺勿假)")
        return out

    def _cam_dist(self, center):
        if self.P is None:
            return None
        C = _camera_center(np.asarray(self.P, float).reshape(3, 4))
        if C is None:
            return None
        return float(np.linalg.norm(np.asarray(center, float) - C))

    # ── 自监督: 尺寸 / 夹持转角 (都只在\"有提升\"时采用) ──
    def _lm(self, x0, resid_fn, iters=120, h=1e-4):
        x = np.asarray(x0, float).copy()
        r = resid_fn(x); cost = float(r @ r); lam = 1e-3
        for _ in range(int(iters)):
            J = np.zeros((r.size, x.size))
            for k in range(x.size):
                d = np.zeros(x.size); d[k] = h
                J[:, k] = (resid_fn(x + d) - resid_fn(x - d)) / (2 * h)
            try:
                step = np.linalg.solve(J.T @ J + lam * np.eye(x.size), -J.T @ r)
            except np.linalg.LinAlgError:
                break
            x2 = x + step; r2 = resid_fn(x2); c2 = float(r2 @ r2)
            if c2 < cost:
                x, r, cost, lam = x2, r2, c2, max(lam * 0.7, 1e-9)
            else:
                lam *= 3.0
            if lam > 1e7:
                break
        return x, cost

    def _size_resid(self, scale, obs):
        sz = tuple(np.asarray(self.size_nominal, float) * np.asarray(scale, float))
        r = []
        for o in obs:
            c = np.asarray(o["tcp"], float) + quat_to_R(o["quat"]) @ np.asarray(self.off, float)
            b = _aabb_R(np.asarray(self.P, float).reshape(3, 4), c, self.R_box(o["quat"]), sz, self.wh)
            if b is None:
                r.extend([30.0, 30.0, 30.0, 30.0]); continue
            ob = o["box"]
            r.extend([(b[0] + b[2]) / 2 - (ob[0] + ob[2]) / 2, (b[1] + b[3]) / 2 - (ob[1] + ob[3]) / 2,
                      (b[2] - b[0]) - (ob[2] - ob[0]), (b[3] - b[1]) - (ob[3] - ob[1])])
        return np.asarray(r, float)

    def _rrel_resid(self, angles, obs):
        a, b, c = [float(v) for v in angles]
        Rz = np.array([[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]])
        Ry = np.array([[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]])
        Rx = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
        R_rel = Rz @ Ry @ Rx
        r = []
        for o in obs:
            R_b = quat_to_R(o["quat"]) @ R_rel
            cc = np.asarray(o["tcp"], float) + quat_to_R(o["quat"]) @ np.asarray(self.off, float)
            bb = _aabb_R(np.asarray(self.P, float).reshape(3, 4), cc, R_b, self.size, self.wh)
            if bb is None:
                r.extend([30.0, 30.0, 30.0, 30.0]); continue
            ob = o["box"]
            r.extend([(bb[0] + bb[2]) / 2 - (ob[0] + ob[2]) / 2, (bb[1] + bb[3]) / 2 - (ob[1] + ob[3]) / 2,
                      (bb[2] - bb[0]) - (ob[2] - ob[0]), (bb[3] - bb[1]) - (ob[3] - ob[1])])
        return np.asarray(r, float)

    def calibrate_size(self, *, fit_axes=False, holdout_frac=0.2, seed=7, min_frames=12,
                       min_gain=0.03):
        """**自监督尺寸标定**: 夹持帧里 中心=TCP+R·off 已知 → 用框反解尺寸 (不再假设 40×16×12)。

        门 (有提升才采用): 帧数 ≥ min_frames · 已拟合 P/off · 留出残差相对标称**下降 ≥ min_gain**。
        """
        if self.P is None or self.off is None:
            return {"ok": False, "why": "相机 P / off 未标定 → 先拟合 (框+位姿)"}
        if len(self.obs) < int(min_frames):
            return {"ok": False, "why": f"帧数 {len(self.obs)} < {min_frames}"}
        rng = np.random.default_rng(seed)
        idx = rng.permutation(len(self.obs))
        n_h = max(3, int(len(self.obs) * holdout_frac))
        ho = [self.obs[i] for i in idx[:n_h]]; tr = [self.obs[i] for i in idx[n_h:]] or self.obs
        x0 = np.ones(3) if fit_axes else np.ones(1)
        base = float(np.sqrt(np.mean(self._size_resid(x0, ho) ** 2)))
        x, _ = self._lm(x0, lambda s: self._size_resid(s, tr))
        x = np.clip(x, 0.4, 2.5)
        new = float(np.sqrt(np.mean(self._size_resid(x, ho) ** 2)))
        gain = (base - new) / max(1e-9, base)
        if gain < float(min_gain):
            return {"ok": False, "why": f"留出残差没提升 (标称 {base:.2f}px → 自标定 {new:.2f}px, "
                                        f"增益 {gain*100:.1f}% < {min_gain*100:.0f}%) → 保留标称尺寸",
                    "holdout_before_px": round(base, 3), "holdout_after_px": round(new, 3)}
        scale = np.concatenate([x, np.ones(3 - x.size)]) if x.size < 3 else x
        self.size = tuple(float(s * k) for s, k in zip(self.size_nominal, scale))
        self.size_src = "自标定"
        return {"ok": True, "size_mm": [round(s * 1000, 2) for s in self.size],
                "scale": [round(float(v), 4) for v in scale],
                "holdout_before_px": round(base, 3), "holdout_after_px": round(new, 3),
                "gain_pct": round(gain * 100, 1), "n": len(self.obs)}

    def calibrate_rrel(self, *, holdout_frac=0.2, seed=11, min_frames=30, min_tilt_deg=20.0,
                       min_gain=0.05, range_deg=25.0):
        """自监督估 **模块相对工具的固定转角** R_rel (夹持歪斜) —— 只影响 8 角点朝向与框宽窄。

        门: 帧数 ≥ min_frames · 姿态散布 ≥ min_tilt_deg · 留出残差下降 ≥ min_gain (否则保持单位阵)。
        """
        if self.P is None or self.off is None:
            return {"ok": False, "why": "相机 P / off 未标定"}
        div = self.diversity()
        if div.get("tilt_deg", 0.0) < float(min_tilt_deg):
            return {"ok": False, "why": f"姿态散布 {div.get('tilt_deg')}° < {min_tilt_deg}° → R_rel 不可辨识"}
        if len(self.obs) < int(min_frames):
            return {"ok": False, "why": f"帧数 {len(self.obs)} < {min_frames}"}
        rng = np.random.default_rng(seed)
        idx = rng.permutation(len(self.obs))
        n_h = max(3, int(len(self.obs) * holdout_frac))
        ho = [self.obs[i] for i in idx[:n_h]]; tr = [self.obs[i] for i in idx[n_h:]] or self.obs
        base = float(np.sqrt(np.mean(self._rrel_resid([0, 0, 0], ho) ** 2)))
        x, _ = self._lm(np.zeros(3), lambda a: self._rrel_resid(a, tr))
        dmax = math.radians(float(range_deg))
        x = np.clip(x, -dmax, dmax)
        new = float(np.sqrt(np.mean(self._rrel_resid(x, ho) ** 2)))
        gain = (base - new) / max(1e-9, base)
        if gain < float(min_gain):
            return {"ok": False, "why": f"留出残差没提升 ({base:.2f}px → {new:.2f}px, 增益 {gain*100:.1f}%) "
                                        f"→ 保持 R_rel=I", "holdout_before_px": round(base, 3),
                    "holdout_after_px": round(new, 3)}
        a, b, c = [float(v) for v in x]
        Rz = np.array([[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]])
        Ry = np.array([[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]])
        Rx = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
        self.Rrel = Rz @ Ry @ Rx
        self.rrel_src = f"自标定 (roll/pitch/yaw = {math.degrees(a):.1f}°/{math.degrees(b):.1f}°/{math.degrees(c):.1f}°)"
        return {"ok": True, "rrel_deg": [round(math.degrees(v), 2) for v in x],
                "holdout_before_px": round(base, 3), "holdout_after_px": round(new, 3),
                "gain_pct": round(gain * 100, 1)}

    # ── 存取 ──
    def status(self):
        return {"fitted": bool(self.fitted), "n_obs": len(self.obs),
                "mode": ("已知工具零点(只解P)" if self.fix_off is not None else "偏移未知(联合解)"),
                "rms_px": (round(self.rms_px, 3) if self.rms_px is not None else None),
                "holdout_rms_px": (round(self.holdout_px, 3) if self.holdout_px is not None else None),
                "off_mm": [round(float(v) * 1000, 1) for v in self.off] if self.off is not None else None,
                "size_mm": [round(s * 1000, 1) for s in self.size], "img_wh": list(self.wh),
                "size_src": self.size_src, "rrel_src": self.rrel_src,
                "Rrel": np.round(self.Rrel, 5).tolist(),
                "diversity": self.diversity(),
                "src": "box3d_solver (自监督: 只用 YOLO 框 + 机器人位姿, 无人工测量/无深度/无手眼)"}

    def save(self, path=STATE_DEFAULT, extra=None):
        d = {"schema": "zmax.box3d.v1", "saved_at": time.strftime("%F %T"),
             "P": (None if self.P is None else np.asarray(self.P).tolist()),
             "off_m": (None if self.off is None else [float(v) for v in self.off]),
             "size_mm": [round(s * 1000, 3) for s in self.size], "img_wh": list(self.wh),
             "size_nominal_mm": [round(s * 1000, 3) for s in self.size_nominal],
             "size_src": self.size_src, "Rrel": np.asarray(self.Rrel).tolist(), "rrel_src": self.rrel_src,
             "K": (None if self.K is None else np.asarray(self.K).tolist()),
             "T_cam_from_base": self.T_cam_from_base,
             "fix_off_mode": bool(self.fix_off is not None),
             "rms_px": self.rms_px, "holdout_rms_px": self.holdout_px,
             "n_obs": len(self.obs), "diversity": self.diversity()}
        if extra:
            d.update(extra)
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return d

    @classmethod
    def load(cls, path=STATE_DEFAULT):
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception:                                                 # noqa: BLE001
            return None
        s = cls(size_mm=d.get("size_mm") or (40, 16, 12), img_wh=d.get("img_wh") or (640, 480))
        if d.get("size_nominal_mm"):
            s.size_nominal = tuple(float(v) / 1000.0 for v in d["size_nominal_mm"])
        s.size_src = d.get("size_src") or "标称"
        if d.get("Rrel"):
            s.Rrel = np.asarray(d["Rrel"], float).reshape(3, 3)
        s.rrel_src = d.get("rrel_src") or s.rrel_src
        if d.get("K"):
            s.K = np.asarray(d["K"], float).reshape(3, 3)
        s.T_cam_from_base = d.get("T_cam_from_base")
        s.P = (None if not d.get("P") else np.asarray(d["P"], float).reshape(3, 4))
        s.off = None if d.get("off_m") is None else np.asarray(d["off_m"], float)
        s.fix_off = (None if d.get("off_m") is None else np.asarray(d["off_m"], float)) if d.get("fix_off_mode") else None
        s.fitted = bool(d.get("P") is not None)
        s.rms_px, s.holdout_px = d.get("rms_px"), d.get("holdout_rms_px")
        return s


# ───────────────────────── 2D→3D 闭环伺服 (远粗近精 + 逆方差融合) ─────────────────────────
class Box3DServo:
    """「2D→3D」反馈控制: 先粗估 → 靠近 → 重测 → 融合 → 收敛。

    为什么是反馈而不是一次算完 (老倪 2026-09-18): 单帧 2D→3D 必然有误差, 而且误差随距离增长——
        dist = a/span  ⇒  σ_dist = (dist/span)·σ_span = dist²·σ_span/a   (σ_dist ∝ 距离²)
      所以越靠近, 同一块框给出的绝对距离越准 (0.8m→~30mm, 0.2m→~2mm)。
      闭环做法: 每次观察都给 (X, σ); 按 1/σ² 加权融合历史 → 估计越走越准; 步长按 σ 收缩 → 收敛停机。

    用法:
        srv = Box3DServo(solver)
        srv.observe(box_px)            # 每帧/每次靠近后调一次
        plan = srv.plan()              # {err_m, X_fused, sigma_m, next_step_m, done}
    """

    def __init__(self, solver, *, tol_m=0.002, max_step_m=0.030, min_step_m=0.0015,
                 span_stop_px=None, sigma_span_px=0.5, keep=40):
        self.slv = solver
        self.tol_m = float(tol_m)              # 收敛判据: 融合 σ 小于它就算够了
        self.max_step_m = float(max_step_m)
        self.min_step_m = float(min_step_m)
        self.span_stop_px = span_stop_px       # 近到框跨度 ≥ 它就停 (可选硬门)
        self.sigma_span_px = float(sigma_span_px)
        self.keep = int(keep)
        self.meas = []
        self.last = {}
        self.iters = 0

    def observe(self, box_px, quat=None):
        m = self.slv.predict_mono_sigma(box_px, sigma_span_px=self.sigma_span_px, quat=quat)
        if not m:
            self.last = {"ok": False, "why": "解算器未标定 (还没有 P / size_a) → 先用 (框,机器人位姿) 标定"}
            return self.last
        self.meas.append(m)
        self.meas = self.meas[-self.keep:]
        Xf, sig = self.slv.fuse(self.meas)
        self.last = {"ok": True, "X": m["X"], "sigma_m": m["sigma_m"], "dist_m": m["dist_m"],
                     "span_px": m["span_px"], "X_fused": Xf, "sigma_fused_m": sig, "n_fused": len(self.meas)}
        return self.last

    def plan(self):
        """用融合估计给出下一步 (朝目标推进 min(最大步长, 剩余距离的一半)) + 停止判据"""
        if not self.last.get("ok"):
            return {"done": False, "ready": False, "why": self.last.get("why", "无观测")}
        X = np.asarray(self.last["X_fused"], float)
        sig = float(self.last["sigma_fused_m"])
        span = float(self.last["span_px"])
        self.iters += 1
        done = (sig <= self.tol_m) or (self.span_stop_px is not None and span >= self.span_stop_px)
        step = 0.0 if done else float(np.clip(0.5 * max(sig * 6.0, self.min_step_m),
                                              self.min_step_m, self.max_step_m))
        return {"done": bool(done), "ready": True, "X_fused": self.last["X_fused"],
                "sigma_fused_m": sig, "dist_m": self.last["dist_m"], "span_px": span,
                "next_step_m": round(step, 5), "iter": self.iters}

    def reset(self):
        self.meas, self.last, self.iters = [], {}, 0
