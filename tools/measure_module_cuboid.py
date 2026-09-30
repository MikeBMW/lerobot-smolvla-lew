#!/usr/bin/env python3
"""把「光模块」量成真正的 3D 长方体(8 顶点), 不再拿 2D 像素框冒充。

老倪 2026-09-28: 「现在画的边界框都不对…光模块是一个3维的长方体, 要8个顶点,
                 画出8个顶点组成的长方体才行。先从光模块开始」

为什么旧的"实测"框也不对(两条硬伤):
  ① 尺寸/朝向是**标称值 + 轴对齐**(R=None): 料盘上的模块在画面里是斜的, 轴对齐长方体
     投影出来必然跟模块轮廓错开一截。
  ② 位置只取了颜色连通域的"框中心"深度, 拿到的是模块**顶面**的深度却当成体中心用。

本工具的量法(**只信传感器**):
  1. 锚框 = L5/YOLO 给的像素框(只当"往哪儿看"的搜索窗, 不当几何真值)
  2. 深度图里, 窗内**最近的一层**就是模块顶面(它比槽底更靠近相机) ⇒ 分出顶面掩膜
  3. 顶面像素逐点反投影到平面 z=z_top ⇒ base 系 XY 上的**真实足印**
  4. 足印做 minAreaRect ⇒ 量出长/宽/朝向(不是标称值, 是这帧量出来的)
  5. 高度 = 模块周围面的深度 - 顶面深度(实测台阶), 夹到 [3,30]mm, 量不到才用标称 12mm
  6. 8 顶点 = 顶面矩形(z_top) 与 底面矩形(z_top-H) ⇒ 真长方体; 朝向用第 4 步量到的角度
自检(每件都报): 8 顶点投回像素后, 顶面四边形与"深度分出的顶面掩膜"的 IoU。
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scene_overlay as SO                                              # noqa: E402

try:
    import cv2
except Exception as e:                                                  # noqa: BLE001
    print("需要 cv2:", e)
    sys.exit(2)

DEPTH_NPY = Path("/home/ubuntu/zmax_ss_remote/zmax_scene/depth_raw.npy")
DEPTH_META = Path("/home/ubuntu/zmax_ss_remote/zmax_scene/depth_meta.json")
KEY_HINT = ("光模块", "peg", "module")
MIN_D, MAX_D = 0.10, 1.20          # 工作距离(米), 之外的深度一律当无效


def Rz(deg: float) -> np.ndarray:
    t = np.deg2rad(deg)
    return np.array([[np.cos(t), -np.sin(t), 0.0],
                     [np.sin(t), np.cos(t), 0.0],
                     [0.0, 0.0, 1.0]])


def load_depth():
    if not DEPTH_NPY.exists():
        return None, None, {}
    dep = np.load(str(DEPTH_NPY))
    meta = json.loads(DEPTH_META.read_text(encoding="utf-8")) if DEPTH_META.exists() else {}
    return dep, float(meta.get("depth_scale", 0.0001)), meta


def module_top_mask(dep_m, x1, y1, x2, y2, near_band=0.006, margin=4, img=None):
    """窗内分出「光模块」的顶面掩膜。

    两条路子, 走错过一次, 记在这:
    · 深度最近层(v1, 已废弃作主路): 窗内取最近的一层 ⇒ 在平放的料盘上会退化成**一条横带**
      (平面相对相机的倾斜让"最近"落在窗外行的近边, 而不是模块本身)。实测它量到的是料盘前缘的凸筋。
    · 外观(v2, 主路): 模块是**金属亮条 + 底部绿光 LED**; 料盘是高饱和绿、槽底很暗 ⇒ 用"亮且不饱和
      ∪ 绿光"在锚窗内抠出来。锚框只负责"往哪儿看", 几何仍由深度定。
    """
    if img is None or dep_m is None:
        return None, None, None
    H, W = dep_m.shape
    wx1, wy1 = max(0, x1 - margin), max(0, y1 - margin)
    wx2, wy2 = min(W, x2 + margin), min(H, y2 + margin)
    win = dep_m[wy1:wy2, wx1:wx2]
    ok = np.isfinite(win) & (win > 0.10) & (win < 1.20)
    if ok.sum() < 50:
        return None, None, None
    sub = img[wy1:wy2, wx1:wx2]
    hsv = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    metal = (val > 105) & (sat < 95)                     # 金属亮条: 亮、不饱和
    led = (sat > 100) & (val > 110) & (hue > 30) & (hue < 95)   # 模块端口绿光
    m = (metal | led) & ok
    m8 = (m.astype(np.uint8)) * 255
    m8 = cv2.morphologyEx(m8, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=1)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(m8, 8)
    if n <= 1:
        return None, None, None
    # 取「离窗中心最近的、够大的」连通域 —— 模块就在锚框中间
    cy0, cx0 = (wy2 - wy1) / 2.0, (wx2 - wx1) / 2.0
    best, bd = None, 1e9
    for i in range(1, n):
        _x, _y, w, h, area = stats[i]
        if area < 150 or max(w, h) < 12:
            continue
        d = (cent[i][0] - cx0) ** 2 + (cent[i][1] - cy0) ** 2
        if d < bd:
            bd, best = d, i
    if best is None:
        return None, None, None
    comp = (lab == best)
    full = np.zeros((H, W), bool)
    full[wy1:wy2, wx1:wx2] = comp
    pv = win[comp & ok]
    z_top = float(np.median(pv)) if pv.size >= 30 else None
    z_sur = None
    return full, z_top, z_sur


def cam_pts_from_depth(u, v, d, K):
    """像素 + 相机系深度(m) → 相机系点云。RealSense 深度就是沿光轴的 z ⇒ 直接成点, 不用猜平面。"""
    u = np.asarray(u, float); v = np.asarray(v, float); d = np.asarray(d, float)
    return np.stack([(u - K["cx"]) / K["fx"] * d, (v - K["cy"]) / K["fy"] * d, d], 1)


def cam_to_base(P_cam, X, tcp7):
    """相机系点 → base 系(米)。base_to_cam 的逆式: P_b = R_g (R_x P_c + t_x) + t_g"""
    R_g = SO.quat_to_R(tcp7[3:7]); t_g = np.asarray(tcp7[:3], float)
    R_x, t_x = X[:3, :3], X[:3, 3]
    return ((R_g @ (R_x @ P_cam.T + t_x[:, None])).T + t_g)


def measure(img, dep_m, K, X, tcp7, anchors, near_band=0.006):
    H, W = img.shape[:2]
    out, rep = [], []
    for b in anchors:
        if not b.get("xyxy"):
            continue
        x1, y1, x2, y2 = [int(round(float(v))) for v in b["xyxy"]]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(W - 1, x2), min(H - 1, y2)
        if x2 - x1 < 8 or y2 - y1 < 8:
            continue
        mask, z_top_cam, z_sur_cam = module_top_mask(dep_m, x1, y1, x2, y2, near_band, img=img)
        rec = {"anchor": b.get("label"), "xyxy": [x1, y1, x2, y2]}
        if mask is None or z_top_cam is None:
            rec["err"] = "窗内抠不出模块(外观/深度不足)"
            rep.append(rec)
            continue
        ys, xs = np.nonzero(mask)
        if xs.size < 200:
            rec["err"] = "顶面像素太少(%d)" % xs.size
            rep.append(rec)
            continue
        d_top = dep_m[ys, xs]
        Pb = cam_to_base(cam_pts_from_depth(xs, ys, d_top, K), X, tcp7)   # 顶面点云(base, m)
        z_top_b = float(np.median(Pb[:, 2]))
        # 足印(base XY, mm): 顶面点云的水平投影 ⇒ 真实长宽与朝向
        rect = cv2.minAreaRect(np.ascontiguousarray(Pb[:, :2] * 1000.0).astype(np.float32))
        (rcx, rcy), (rw, rh), ang = rect
        if rw < rh:
            rw, rh = rh, rw
            ang += 90.0
        # 高度: 模块周围那圈(槽底/台面)的 base-z 中位 - 顶面 base-z
        yy, xx = np.nonzero(mask)
        ring = np.zeros((H, W), bool)
        ring[max(0, yy.min() - 9):yy.max() + 10, max(0, xx.min() - 9):xx.max() + 10] = True
        ring &= ~mask
        ry, rx = np.nonzero(ring)
        Hmm, n_ring = None, 0
        if ry.size:
            d_ring = dep_m[ry, rx]
            okr = np.isfinite(d_ring) & (d_ring > 0.10) & (d_ring < 1.20)
            if okr.sum() >= 50:
                Pbr = cam_to_base(cam_pts_from_depth(rx[okr], ry[okr], d_ring[okr], K), X, tcp7)
                Hmm = float(np.clip((z_top_b - float(np.median(Pbr[:, 2]))) * 1000.0, 3.0, 30.0))
                n_ring = int(okr.sum())
        rec.update(px_top=int(mask.sum()), z_top_b_mm=round(z_top_b * 1000, 1),
                   z_top_cam_mm=round(z_top_cam * 1000, 1), ring_px=n_ring,
                   w_mm=round(float(rw), 1), h_mm=round(float(rh), 1),
                   H_mm=(round(Hmm, 1) if Hmm else None), angle_deg=round(float(ang), 1),
                   base_xy_mm=[round(float(rcx), 1), round(float(rcy), 1)])
        out.append({"label": b.get("label"), "box": {
            "center": [float(rcx) / 1000.0, float(rcy) / 1000.0,
                       z_top_b - (Hmm or 12.0) / 2000.0],
            "size": [round(float(rw), 1), round(float(rh), 1), round(Hmm or 12.0, 1)],
            "R": Rz(ang).tolist(),
        }, "rec": rec, "mask": mask, "rect": (rcx, rcy, rw, rh, ang), "z_top": z_top_b})
    return out, rep


def robust_depth(dep_m, u, v, r=5, fallback=None):
    """(u,v) 邻域 r 像素内的稳健深度(丢掉 0 值/超量程)。D405 在反光/阴影处会出 0。"""
    H, W = dep_m.shape
    u0, u1 = max(0, u - r), min(W, u + r + 1)
    v0, v1 = max(0, v - r), min(H, v + r + 1)
    p = dep_m[v0:v1, u0:u1]
    ok = np.isfinite(p) & (p > MIN_D) & (p < MAX_D)
    if ok.sum() < 8:
        return fallback
    return float(np.median(p[ok]))


def measure_anchor(img, dep_m, K, X, tcp7, anchors):
    """主路(2026-09-28 定): 锚框几何 × 深度定 3D。

    为什么不用"掩膜分块"(v1/v2 都栽了, 见文件头): 深度最近层退化成横带; 外观掩膜帧间漂移,
    且 D405 的 0 深度会经形态学闭运算漏进来(把足印拉成 375mm)。锚框 = 用户看到的物体轮廓,
    几何由深度给 ⇒ 又稳又对得上画面。
    """
    H, W = img.shape[:2]
    out, rep = [], []
    for b in anchors:
        if not b.get("xyxy"):
            continue
        x1, y1, x2, y2 = [int(round(float(v))) for v in b["xyxy"]]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(W - 1, x2), min(H - 1, y2)
        rec = {"anchor": b.get("label"), "xyxy": [x1, y1, x2, y2]}
        if x2 - x1 < 10 or y2 - y1 < 10:
            rec["err"] = "锚框太小"; rep.append(rec); continue
        # 位置基准: 框中心 40% 区域的有效深度中位
        cw, ch = max(4, int((x2 - x1) * 0.4)), max(4, int((y2 - y1) * 0.4))
        ccx, ccy = (x1 + x2) // 2, (y1 + y2) // 2
        patch = dep_m[ccy - ch // 2:ccy + ch // 2 + 1, ccx - cw // 2:ccx + cw // 2 + 1]
        ok = np.isfinite(patch) & (patch > MIN_D) & (patch < MAX_D)
        if ok.sum() < 20:
            rec["err"] = "中心区深度无效"; rep.append(rec); continue
        d_mid = float(np.median(patch[ok]))
        # 四角深度: 不能直接取角点邻域中位 —— 角上会吃到框外的台面/槽壁(更远), 足印被拉长 3 倍。
        # 做法: 框内取出"物体自己那层"(±20mm 带内)的像素, 拟合深度平面 d=a·u+b·v+c,
        #       再把四个角代入平面 ⇒ 角点深度与物体面共面, 稳且可复算。
        yy, xx = np.nonzero(np.ones_like(dep_m[y1:y2 + 1, x1:x2 + 1], bool))
        yy = yy + y1; xx = xx + x1
        dd = dep_m[yy, xx]
        good = np.isfinite(dd) & (dd > MIN_D) & (dd < MAX_D) & (np.abs(dd - d_mid) < 0.020)
        a_coef = None
        if good.sum() >= 60:
            A = np.stack([xx[good].astype(float), yy[good].astype(float), np.ones(int(good.sum()))], 1)
            try:
                sol, *_ = np.linalg.lstsq(A, dd[good].astype(float), rcond=None)
                a_coef = sol
            except Exception:                                                   # noqa: BLE001
                a_coef = None
        cpx = [(x1, y1), (x2, y1), (x2 - 1, y2), (x1, y2 - 1)]
        if a_coef is not None:
            ds = [float(np.clip(a_coef[0] * u + a_coef[1] * v + a_coef[2], MIN_D, MAX_D)) for (u, v) in cpx]
            plane = "拟合深度平面"
        else:                                                                   # 退化: 回退邻域稳健深度
            ds = [robust_depth(dep_m, u, v, r=6, fallback=d_mid) or d_mid for (u, v) in cpx]
            plane = "角点邻域中位(平面拟合失败)"
        Pb = cam_to_base(cam_pts_from_depth([c[0] for c in cpx], [c[1] for c in cpx], ds, K), X, tcp7)
        z_obj = float(np.median(Pb[:, 2]))
        rect = cv2.minAreaRect(np.ascontiguousarray(Pb[:, :2] * 1000.0).astype(np.float32))
        (rcx, rcy), (rw, rh), ang = rect
        if rw < rh:
            rw, rh = rh, rw
            ang += 90.0
        # 高度: 锚框外扩一圈(槽底/台面)的 base-z 中位 - 模块面 base-z 中位
        Hmm, n_ring = None, 0
        band = np.zeros((H, W), bool)
        band[max(0, y1 - 20):min(H, y2 + 20), max(0, x1 - 20):min(W, x2 + 20)] = True
        band[max(0, y1 - 2):min(H, y2 + 2), max(0, x1 - 2):min(W, x2 + 2)] = False
        by, bx = np.nonzero(band)
        dv = dep_m[by, bx]
        oki = np.isfinite(dv) & (dv > MIN_D) & (dv < MAX_D)
        if oki.sum() >= 50:
            Pbr = cam_to_base(cam_pts_from_depth(bx[oki], by[oki], dv[oki], K), X, tcp7)
            # 高度 = 模块面 - **周围最深的那个面**(槽底): 模块通常坐在凹槽里, 用中位会量到台面(比它还高)
            z_floor = float(np.percentile(Pbr[:, 2], 20))
            Hmm = float(np.clip((z_obj - z_floor) * 1000.0, 2.0, 40.0))
            n_ring = int(oki.sum())
        rec.update(d_mid_mm=round(d_mid * 1000, 1), corner_d_mm=[round(d * 1000, 1) for d in ds],
                   corner_depth_src=plane, z_obj_mm=round(z_obj * 1000, 1), ring_px=n_ring,
                   w_mm=round(float(rw), 1), h_mm=round(float(rh), 1),
                   H_mm=(round(Hmm, 1) if Hmm else None), angle_deg=round(float(ang), 1),
                   base_xy_mm=[round(float(rcx), 1), round(float(rcy), 1)])
        out.append({"label": b.get("label"), "box": {
            "center": [float(rcx) / 1000.0, float(rcy) / 1000.0, z_obj - (Hmm or 12.0) / 2000.0],
            "size": [round(float(rw), 1), round(float(rh), 1), round(Hmm or 12.0, 1)],
            "R": Rz(ang).tolist(),
        }, "rec": rec, "anchor": (x1, y1, x2, y2)})
    return out, rep


def detect_modules_auto(img, dep_m, K, X, tcp7, min_area=400, max_ar=9.0):
    """新视角下的**自足**检测(不依赖 L5 锚框): 画面里模块 = 亮金属条 ∪ 绿模块头。

    这一版是给"相机凑近、模块看得很清"的视角用的(实测深度中位 ~195mm)。做法:
      ① 亮且不饱和(金属条) ∪ 绿且够亮(模块头) → 形态学闭运算
      ② 连通域按 面积/长宽比(细长条) 过滤, 丢掉料盘筋/槽口/桌面
      ③ 每个连通域的像素 → 深度(±20mm 带内) → base 系点云 → XY 足印 minAreaRect
      ④ 高度 = 物面 base z - 周围最深面(P20) 的 base z
    自检: 反投影回像素的 xyxy 与连通域 bbox 的 IoU(位置/尺寸一致)。
    """
    H, W = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    ok = np.isfinite(dep_m) & (dep_m > MIN_D) & (dep_m < MAX_D)
    metal = (val > 110) & (sat < 95)
    green = (hue > 35) & (hue < 95) & (sat > 70) & (val > 70)
    m = ((metal | green) & ok).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8), iterations=2)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(m, 8)
    out, rep = [], []
    for i in range(1, n):
        bx, by, bw, bh, area = stats[i]
        if area < min_area or bw < 10 or bh < 10:
            continue
        ar = max(bw, bh) / max(1, min(bw, bh))
        if ar < 1.6 or ar > max_ar:
            continue
        comp = (lab == i)
        ys, xs = np.nonzero(comp)
        d = dep_m[ys, xs]
        oki = np.isfinite(d) & (d > MIN_D) & (d < MAX_D)
        if oki.sum() < 200:
            continue
        d_mid = float(np.median(d[oki]))
        band = np.abs(d - d_mid) < 0.020                     # 物体自己那层(排除背景/槽底)
        if band.sum() < 150:
            continue
        Pb = cam_to_base(cam_pts_from_depth(xs[band], ys[band], d[band], K), X, tcp7)
        z_obj = float(np.median(Pb[:, 2]))
        rect = cv2.minAreaRect(np.ascontiguousarray(Pb[:, :2] * 1000.0).astype(np.float32))
        (rcx, rcy), (rw, rh), ang = rect
        if rw < rh:
            rw, rh = rh, rw
            ang += 90.0
        # 高度: 连通域外扩一圈里最深那层的 base z
        ring = np.zeros((H, W), bool)
        ring[max(0, by - 18):min(H, by + bh + 18), max(0, bx - 18):min(W, bx + bw + 18)] = True
        ring[by:by + bh, bx:bx + bw] = False
        ry, rx = np.nonzero(ring)
        Hmm = None
        dv = dep_m[ry, rx]
        oki2 = np.isfinite(dv) & (dv > MIN_D) & (dv < MAX_D)
        if oki2.sum() >= 50:
            Pbr = cam_to_base(cam_pts_from_depth(rx[oki2], ry[oki2], dv[oki2], K), X, tcp7)
            Hmm = float(np.clip((z_obj - float(np.percentile(Pbr[:, 2], 20))) * 1000.0, 2.0, 40.0))
        box = {"center": [float(rcx) / 1000.0, float(rcy) / 1000.0, z_obj - (Hmm or 12.0) / 2000.0],
               "size": [round(float(rw), 1), round(float(rh), 1), round(Hmm or 12.0, 1)],
               "R": Rz(ang).tolist()}
        c8 = SO.box3d_corners(box["center"], box["size"], box["R"])
        uv = SO.cam_to_px(SO.base_to_cam(c8, X, tcp7), K)
        ux0, uy0 = float(uv[:, 0].min()), float(uv[:, 1].min())
        ux1, uy1 = float(uv[:, 0].max()), float(uv[:, 1].max())
        ix0, iy0 = max(bx, ux0), max(by, uy0)
        ix1, iy1 = min(bx + bw, ux1), min(by + bh, uy1)
        inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
        uni = max(1e-6, bw * bh + (ux1 - ux0) * (uy1 - uy0) - inter)
        out.append({"box": box, "uv": uv, "anchor": (bx, by, bx + bw, by + bh),
                    "rec": {"d_mid_mm": round(d_mid * 1000, 1), "z_obj_mm": round(z_obj * 1000, 1),
                            "px": int(comp.sum()), "w_mm": round(float(rw), 1),
                            "h_mm": round(float(rh), 1), "H_mm": round(Hmm, 1) if Hmm else None,
                            "angle_deg": round(float(ang), 1), "iou_box": round(inter / uni, 3),
                            "base_xy_mm": [round(float(rcx), 1), round(float(rcy), 1)]}})
    out.sort(key=lambda it: it["rec"]["base_xy_mm"][0])
    return out, rep


def refine_in_window(img, dep_m, K, X, tcp7, px_box, band=0.006, pad=8):
    """在给定像素窗内, 按**深度分层**把物体那层抠出来 → 量足印。

    为什么用窗而不用"全图外观分割"(2026-09-28 实测): 这台相机近距离时**光照极不均** ——
    同帧左模块的金属条 V=239, 右模块的 V=76(背光), 右模块的绿光还过曝成白色(V=255,S=42)。
    任何"亮金属∪绿光"的阈值都会一边漏一边错。深度分层不受光照影响。
    窗从哪来: 已量到的 3D 盒投影回像素(物体在 base 系不动 ⇒ 相机移动后投影仍是准的)。
    """
    H, W = dep_m.shape
    x1, y1, x2, y2 = [int(round(v)) for v in px_box]
    x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
    x2, y2 = min(W, x2 + pad), min(H, y2 + pad)
    if x2 - x1 < 12 or y2 - y1 < 12:
        return None
    win = dep_m[y1:y2, x1:x2]
    ok = np.isfinite(win) & (win > MIN_D) & (win < MAX_D)
    if ok.sum() < 200:
        return None
    cw, ch = max(4, (x2 - x1) // 4), max(4, (y2 - y1) // 4)          # 中心 1/4 区域当"物体面"
    ccx, ccy = (x2 - x1) // 2, (y2 - y1) // 2
    core = win[ccy - ch:ccy + ch, ccx - cw:ccx + cw]
    cok = np.isfinite(core) & (core > MIN_D) & (core < MAX_D)
    if cok.sum() < 40:
        return None
    d_obj = float(np.median(core[cok]))
    # ── 分割: 三条路都试过, 记在这(近距离视角的实测依据) ──
    #   ✗ 深度分层(±6mm): 台面 114.8mm 与模块面 118~122mm 只差 4mm ⇒ 把台面一起吃进来(足印 212×71mm)
    #   ✗ 相对拟合平面的凸起: 料盘是"筋+槽"的格子, 一个平面代表不了它 ⇒ 把半个窗都当凸起(15.7k px)
    #   ✓ 灰度: 本视角下模块条是**亮的**(逐行剖面: 条上灰度 130~255, 料盘 50~90) ⇒ Otsu 自适应阈值
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)[y1:y2, x1:x2]
    gv = gray[ok]
    _th = 105.0
    if gv.size >= 200:
        try:
            _t, _ = cv2.threshold(gv.astype(np.uint8), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            _th = max(95.0, min(200.0, float(_t)))
        except Exception:                                                   # noqa: BLE001
            pass
    m = ((gray >= _th) & ok).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8), 1)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(m, 8)
    if n <= 1:
        return None
    # 取包含窗中心的那块(拿不到就取最大块)
    ci = int(lab[ccy, ccx])
    if ci == 0:
        ci = 1 + int(np.argmax(stats[1:, 4]))
    comp = (lab == ci)
    if comp.sum() < 200:
        return None
    ys, xs = np.nonzero(comp)
    ys = ys + y1; xs = xs + x1
    d = dep_m[ys, xs]
    P = cam_to_base(cam_pts_from_depth(xs, ys, d, K), X, tcp7)
    z_obj = float(np.median(P[:, 2]))
    rect = cv2.minAreaRect(np.ascontiguousarray(P[:, :2] * 1000.0).astype(np.float32))
    (rcx, rcy), (rw, rh), ang = rect
    if rw < rh:
        rw, rh = rh, rw
        ang += 90.0
    # 高度: 窗内(挖掉物体)最深那层
    ring = np.zeros((H, W), bool)
    ring[y1:y2, x1:x2] = True
    ring[ys.min():ys.max() + 1, xs.min():xs.max() + 1] = False
    ry, rx = np.nonzero(ring)
    Hmm = None
    if ry.size:
        dv = dep_m[ry, rx]
        oki = np.isfinite(dv) & (dv > MIN_D) & (dv < MAX_D)
        if oki.sum() >= 50:
            Pbr = cam_to_base(cam_pts_from_depth(rx[oki], ry[oki], dv[oki], K), X, tcp7)
            Hmm = float(np.clip((z_obj - float(np.percentile(Pbr[:, 2], 20))) * 1000.0, 2.0, 40.0))
    box = {"center": [float(rcx) / 1000.0, float(rcy) / 1000.0, z_obj - (Hmm or 12.0) / 2000.0],
           "size": [round(float(rw), 1), round(float(rh), 1), round(Hmm or 12.0, 1)],
           "R": Rz(ang).tolist()}
    return {"box": box, "px_box": (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())),
            "rec": {"d_obj_mm": round(d_obj * 1000, 1), "z_obj_mm": round(z_obj * 1000, 1),
                    "px": int(comp.sum()), "w_mm": round(float(rw), 1), "h_mm": round(float(rh), 1),
                    "H_mm": round(Hmm, 1) if Hmm else None, "angle_deg": round(float(ang), 1),
                    "base_xy_mm": [round(float(rcx), 1), round(float(rcy), 1)]}}


def row_prior_from_box(box, K, X, tcp7, W=640, H=480):
    """把"已量到的盒子"投影成**逐行先验**: 每行的预期中心与预期像素宽(用顶面四角插值)。

    为什么要逐行先验: 2 号模块是"白色过曝条 + 绿 PCB", 只看边缘强度会在两条结构之间跳
    (角度量成 12°, 长 67mm)。拿上一次的盒子当先验 ⇒ 每行知道"应该在哪、大概多宽",
    再让边缘把它拉准 —— 既有先验的稳定, 又有测量的真实。
    """
    c8 = SO.box3d_corners(box["center"], box["size"], box.get("R"))
    uv = SO.cam_to_px(SO.base_to_cam(c8, X, tcp7), K)
    top_idx = [1, 3, 7, 5]                                  # 顶面四角(与 EDGES/面染色同口径)
    q = uv[top_idx]
    out = {}
    if not np.isfinite(q).all():
        return out
    ys = q[:, 1]
    ylo, yhi = int(max(0, np.floor(ys.min()))), int(min(H - 1, np.ceil(ys.max())))
    for y in range(ylo, yhi + 1):
        xs = []
        for i in range(4):
            a, b = q[i], q[(i + 1) % 4]
            if (a[1] - y) * (b[1] - y) <= 0:                 # 该行与这条边相交
                t = 0.0 if abs(b[1] - a[1]) < 1e-9 else (y - a[1]) / (b[1] - a[1])
                if -0.05 <= t <= 1.05:
                    xs.append(a[0] + t * (b[0] - a[0]))
        if len(xs) >= 2:
            out[y] = (0.5 * (min(xs) + max(xs)), max(xs) - min(xs))
    return out


def _profile_once(gray, dep_m, K, px_box, MIN_D, MAX_D, prior=None, transpose=False):
    """单方向扫描: transpose=False 逐行扫(物体在画面里是竖的), True 逐列扫(物体是横的)。"""
    if transpose:
        gray = gray.T.copy()
        dep_m = dep_m.T.copy()
        px_box = (px_box[1], px_box[0], px_box[3], px_box[2])
    H, W = gray.shape
    x1, y1, x2, y2 = [int(round(v)) for v in px_box]
    x1, y1 = max(2, x1), max(2, y1)
    x2, y2 = min(W - 2, x2), min(H - 2, y2)
    cx_exp = (x1 + x2) // 2
    rows = []
    for y in range(y1, y2 + 1):
        prof = gray[y, x1:x2 + 1]
        gd = np.abs(np.diff(prof))
        if gd.size < 6:
            continue
        cx_y, w_pri = (prior[y] if (prior and y in prior) else (cx_exp, 30.0))
        thr = max(12.0, float(gd.max()) * 0.35)
        pk = [i for i in range(1, gd.size - 1)
              if gd[i] >= thr and gd[i] >= gd[i - 1] and gd[i] >= gd[i + 1]]
        if len(pk) < 2:
            continue
        best = None
        for a in range(len(pk) - 1):
            for b in range(a + 1, len(pk)):
                pa, pb = pk[a] + x1, pk[b] + x1
                wpx = pb - pa
                if not (6 <= wpx <= 95):
                    continue
                c = 0.5 * (pa + pb)
                strong = gd[pk[a]] + gd[pk[b]]
                score = -strong + 0.5 * abs(c - cx_y) + 0.6 * abs(wpx - w_pri)
                if best is None or score < best[0]:
                    best = (score, pa, pb, c, wpx)
        if best is None:
            continue
        _, pa, pb, c, wpx = best
        seg = dep_m[y, int(pa):int(pb) + 1]
        good = (seg > MIN_D) & (seg < MAX_D)
        d = float(np.median(seg[good])) if good.any() else np.nan
        rows.append((y, pa, pb, c, wpx, d))
    return rows


def measure_by_profile(img, dep_m, K, X, tcp7, px_box, prior=None, axis="auto"):
    """**逐行剖面**量细条(近距离视角唯一稳的办法, 2026-09-28)。

    为什么不用阈值分割: 同一帧里模块条 y=140 行灰度 130~255(亮), y=100 行只有 117~120(比料盘 130 还暗)
    —— 光照在这台相机上极不均(金属条左亮右暗、绿光过曝成白 255), 任何"亮/绿"阈值都会一边漏一边错。
    逐行找**边缘**(梯度峰)则不受绝对灰度影响: 条的两侧一定是一对强梯度。

    做法: 在窗内逐行取灰度剖面 → 找离预期中心最近的**一对**强梯度峰 → 每行得 中心/半宽;
          行内统计取中位(抗离群) → 宽度用该行深度换算; 长度 = 连续检出行数 × 深度/焦距;
          角度 = 沿轴两点各自反投影到 base 系后的连线方向(真量出来的, 不是猜的)。
    """
    H, W = dep_m.shape
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    _tp = False
    if axis == "auto":
        # **判轴**: 相机被机械臂转过后, 同一个模块在画面里可能是竖的也可能是横的(实测踩过:
        # 竖着扫一个横着的模块 ⇒ 逐行凑出的"一对边"全是垃圾, 长度量成 20~50mm 且角度乱跳)。
        # 两个方向都扫一遍, 取"有效行更多 × 宽度更稳"的那个。
        _bs = None
        for _t in (False, True):
            _r = _profile_once(g, dep_m, K, px_box, MIN_D, MAX_D, prior=prior, transpose=_t)
            if len(_r) < 15:
                continue
            _w = np.array([r[4] for r in _r], float)
            _score = (len(_r)) / (1.0 + float(np.std(_w)))
            if _bs is None or _score > _bs[0]:
                _bs = (_score, _t, _r)
        if _bs is None:
            return None
        _tp, rows = _bs[1], _bs[2]
    else:
        _tp = (axis == "h")
        rows = _profile_once(g, dep_m, K, px_box, MIN_D, MAX_D, prior=prior, transpose=_tp)
    if len(rows) < 15:
        return None
    ws = np.array([r[4] for r in rows], float)
    ws_ok = ws[(ws > np.percentile(ws, 20)) & (ws < np.percentile(ws, 80))]
    rows = [r for r in rows if np.percentile(ws, 20) <= r[4] <= np.percentile(ws, 80)]
    ys = np.array([r[0] for r in rows], float)
    cs = np.array([r[3] for r in rows], float)
    ds = np.array([r[5] for r in rows], float)
    # 分段: 允许 ≤25 行的空洞(模块中段会被反光/过曝打断, 断开就整段截短会把长度量成一半), 取最长的一段
    _gaps = np.diff(ys)
    _brk = np.nonzero(_gaps > 25)[0]
    _st = np.concatenate([[0], _brk + 1])
    _en = np.concatenate([_brk, [len(ys) - 1]])
    _best = int(np.argmax([ys[_en[k]] - ys[_st[k]] for k in range(len(_st))]))
    _s, _e = int(_st[_best]), int(_en[_best]) + 1
    rows = rows[_s:_e]
    ys = np.array([r[0] for r in rows], float)
    cs = np.array([r[3] for r in rows], float)
    ds = np.array([r[5] for r in rows], float)
    if len(rows) < 15:
        return None
    # ② 一致性过滤: 逐行中心对"中心-行"直线拟合的残差 ≤5px 且宽度在中位 ±35% 内 —— 把
    #    "窗里其它东西凑出来的一对边"(会把长度拉到槽外、把轴线拧歪)剔掉
    for _ in range(2):
        A = np.stack([ys, np.ones(len(ys))], 1)
        try:
            sol, *_ = np.linalg.lstsq(A, cs, rcond=None)
        except Exception:                                                   # noqa: BLE001
            break
        resid = np.abs(cs - (sol[0] * ys + sol[1]))
        wmed = float(np.median([r[4] for r in rows]))
        keep = (resid <= 5.0) & np.array([abs(r[4] - wmed) <= 0.35 * wmed for r in rows])
        if keep.sum() < 15:
            break
        rows = [r for r, k in zip(rows, keep) if k]
        ys = np.array([r[0] for r in rows], float)
        cs = np.array([r[3] for r in rows], float)
        ds = np.array([r[5] for r in rows], float)
    A = np.stack([ys, np.ones(len(ys))], 1)
    sol, *_ = np.linalg.lstsq(A, cs, rcond=None)
    ct = float(sol[0] * ys.min() + sol[1])
    cb = float(sol[0] * ys.max() + sol[1])
    d_med = float(np.nanmedian(ds))
    fx = float(K["fx"]); fy = float(K["fy"])
    w_px = float(np.median([r[4] for r in rows]))
    # 横扫(_tp)时扫出的"宽度"是画面的竖向 ⇒ 用 fy 换算; 长度方向用 fx
    w_mm = w_px * d_med / (fy if _tp else fx) * 1000.0
    l_mm = (ys.max() - ys.min() + 1) * d_med / (fx if _tp else fy) * 1000.0
    # 真实像素坐标: 竖扫 (u,v)=(cs,ys); 横扫 (u,v)=(ys,cs)
    U, V = (ys, cs) if _tp else (cs, ys)
    # 角度: 沿轴取头尾两点, 各自按本行深度反投影到 base, 连线方向
    top = rows[0]; bot = rows[-1]
    d_t = top[5] if np.isfinite(top[5]) else d_med
    d_b = bot[5] if np.isfinite(bot[5]) else d_med
    _ut, _vt = (top[0], ct) if _tp else (ct, top[0])
    _ub, _vb = (bot[0], cb) if _tp else (cb, bot[0])
    P = cam_to_base(cam_pts_from_depth(np.array([_ut, _ub], float),
                                       np.array([_vt, _vb], float),
                                       np.array([d_t, d_b], float), K), X, tcp7)
    dy = P[1][1] - P[0][1]; dx = P[1][0] - P[0][0]
    ang = float(np.degrees(np.arctan2(dy, dx)))
    # 高度: 窗内挖掉条子后的最深面(槽底) vs 条面
    x1, y1, x2, y2 = [int(round(v)) for v in px_box]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(W - 1, x2), min(H - 1, y2)
    ring = np.zeros((H, W), bool)
    ring[y1:y2 + 1, x1:x2 + 1] = True
    ring[int(V.min()):int(V.max()) + 1, int(U.min() - w_px / 2) - 2:int(U.max() + w_px / 2) + 2] = False
    ry, rx = np.nonzero(ring)
    Hmm = 12.0
    dv = dep_m[ry, rx]
    oki = np.isfinite(dv) & (dv > MIN_D) & (dv < MAX_D)
    if oki.sum() >= 50:
        Pbr = cam_to_base(cam_pts_from_depth(rx[oki], ry[oki], dv[oki], K), X, tcp7)
        Pm = cam_to_base(cam_pts_from_depth(U, V, ds, K), X, tcp7)
        Hmm = float(np.clip((float(np.median(Pm[:, 2])) - float(np.percentile(Pbr[:, 2], 20))) * 1000.0,
                            2.0, 40.0))
    Pc = cam_to_base(cam_pts_from_depth(np.array([float(np.median(U))]),
                                       np.array([float(np.median(V))]),
                                       np.array([d_med]), K), X, tcp7)
    box = {"center": [float(Pc[0][0]), float(Pc[0][1]), float(Pc[0][2]) - Hmm / 2000.0],
           "size": [round(l_mm, 1), round(w_mm, 1), round(Hmm, 1)],
           "R": Rz(ang).tolist()}
    return {"box": box, "px_box": (int(U.min() - w_px / 2), int(V.min()),
                                   int(U.max() + w_px / 2), int(V.max())),
            "rec": {"d_obj_mm": round(d_med * 1000, 1), "z_obj_mm": round(float(Pc[0][2]) * 1000, 1),
                    "px": int(len(rows)), "w_mm": round(w_mm, 1), "h_mm": round(l_mm, 1),
                    "H_mm": round(Hmm, 1), "angle_deg": round(ang, 1),
                    "w_px": round(w_px, 1), "rows": len(rows), "axis": "h" if _tp else "v",
                    "base_xy_mm": [round(float(Pc[0][0]) * 1000, 1), round(float(Pc[0][1]) * 1000, 1)]}}


def green_anchors(img, dep_m, min_area=250):
    """绿底座当锚点: 当前视角里**光模块的绿色部分**是最干净的特征(实测无假阳性:
    高饱和绿只有模块有, 料盘/圆孔/桌面都不绿), 比 L5 的 2D 框可靠。

    返回每个绿块的 (bbox, 模块搜索窗): 窗 = 绿块 bbox 向上扩 3.5 倍高(模块本体从绿底座
    向上伸出), 左右各留半个绿宽。物体朝向由剖面法自己量。
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    ok = np.isfinite(dep_m) & (dep_m > MIN_D) & (dep_m < MAX_D)
    g = ((hue > 35) & (hue < 95) & (sat > 60) & (val > 60) & ok).astype(np.uint8) * 255
    g = cv2.morphologyEx(g, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), 1)
    n, lab, st, ce = cv2.connectedComponentsWithStats(g, 8)
    H, W = img.shape[:2]
    out = []
    for i in range(1, n):
        x, y, w, h, ar = st[i]
        if ar < min_area or w < 8 or h < 6:
            continue
        x1 = max(0, int(x - 0.35 * w)); x2 = min(W - 1, int(x + w + 0.35 * w))
        y1 = max(0, int(y - 4.5 * h)); y2 = min(H - 1, int(y + h * 1.2))
        out.append({"green_bbox": (int(x), int(y), int(w), int(h)), "win": (x1, y1, x2, y2),
                    "green_px": int(ar), "cx": float(ce[i][0]), "cy": float(ce[i][1])})
    out.sort(key=lambda d: d["cx"])
    return out


def project_top_quad(corners, K, X, tcp7):
    """盒的 8 角点 → 像素; 返回顶面(索引 1,3,7,5)四边形的像素点"""
    Pc = SO.base_to_cam(np.asarray(corners, float), X, tcp7)
    uv = SO.cam_to_px(Pc, K)
    return uv[[1, 3, 7, 5], :]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", default="arm")
    ap.add_argument("--apply", action="store_true", help="把量到的长方体写进 spec(origin=meas)")
    ap.add_argument("--hide-2d", action="store_true", help="把 2D 的大模型光模块框标为已删(免得和 3D 打架)")
    ap.add_argument("--near-band", type=float, default=0.006, help="顶面深度容差(米)")
    ap.add_argument("--labels", default="光模块", help="要量的标签关键字(逗号分隔)")
    ap.add_argument("--auto", action="store_true",
                    help="不靠 L5 锚框: 当前视角下直接按外观(亮金属∪绿模块头)检测模块(相机凑近时用)")
    ap.add_argument("--min-area", type=int, default=400, help="--auto 的连通域最小面积")
    ap.add_argument("--from-meas", action="store_true",
                    help="用已量到的 meas 盒投影当窗, 深度分层精修(相机移动后重画用这个)")
    ap.add_argument("--green", action="store_true",
                    help="按'绿底座'锚点重测(视角换了以后最稳的锚; 绿块当锚比 L5 的 2D 框可靠)")
    ap.add_argument("--band", type=float, default=0.006, help="--from-meas 的深度层容差(米)")
    ap.add_argument("--no-consensus", dest="consensus", action="store_false",
                    help="关掉同类件共识尺寸(默认开: 同型号多件取长宽中位, 位置/朝向各自测)")
    a = ap.parse_args()

    raw = SO.fetch_frame(a.cam)
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR) if raw else None
    if img is None:
        print("取不到相机帧"); sys.exit(2)
    H, W = img.shape[:2]
    dep, scale, meta = load_depth()
    if dep is None:
        print("无深度文件"); sys.exit(2)
    dep_m = dep.astype(np.float32) * scale
    if dep_m.shape[:2] != (H, W):
        print(f"深度尺寸 {dep_m.shape} 与画面 {(H, W)} 不一致"); sys.exit(2)
    K = SO.load_intrinsics(W, H)
    _he = SO.load_handeye()
    if not _he.get("ok"):
        print("手眼外参不可用:", _he.get("why"))
        sys.exit(2)
    X = _he["X"]
    tcp7 = SO.read_tcp(timeout=20, allow_ssh=False)
    if tcp7 is None:
        print("拿不到 TCP 真值"); sys.exit(2)
    age = time.time() - float(meta.get("t") or 0)
    print(f"画面 {W}×{H} · 深度帧龄 {age:.1f}s (valid {meta.get('valid_pct')}%) · "
          f"TCP=({tcp7[0]:.4f},{tcp7[1]:.4f},{tcp7[2]:.4f})")

    spec = SO.load_spec()
    keys = tuple(k.strip() for k in a.labels.split(",") if k.strip())
    if a.from_meas:
        prev = [b for b in (spec.get("cameras", {}).get(a.cam, {}).get("boxes") or [])
                if b.get("origin") == "meas" and b.get("box3d")]
        print(f"已量到的 meas 盒 {len(prev)} 件 → 投影当窗, 深度分层精修")
        if not prev:
            print("没有 meas 盒可当窗 ⇒ 先跑一次(用 L5 锚框或 --auto)"); sys.exit(3)
        items, rep = [], []
        for b in prev:
            b3 = b["box3d"]
            c8 = SO.box3d_corners(b3["center"], b3.get("size", [1, 1, 1]), b3.get("R"))
            uv = SO.cam_to_px(SO.base_to_cam(c8, X, tcp7), K)
            if not np.isfinite(uv).all():
                rep.append({"anchor": b.get("label"), "err": "投影出画/无穷"}); continue
            px_box = (float(uv[:, 0].min()), float(uv[:, 1].min()),
                      float(uv[:, 0].max()), float(uv[:, 1].max()))
            r = measure_by_profile(img, dep_m, K, X, tcp7, px_box)
            r2 = None
            if r is not None:
                r2 = measure_by_profile(img, dep_m, K, X, tcp7, px_box,
                                        prior=row_prior_from_box(r["box"], K, X, tcp7))
            cands = [c for c in (r, r2) if c is not None]
            if not cands:
                rep.append({"anchor": b.get("label"), "err": "窗内分不出细条"}); continue
            prev_R = b3.get("R")
            if prev_R is not None and len(cands) == 2:
                ap = abs(np.arctan2(prev_R[1][0], prev_R[0][0]))
                d = []
                for c in cands:
                    _ang = abs(np.arctan2(c["box"]["R"][1][0], c["box"]["R"][0][0]))
                    dd = abs(_ang - ap); dd = min(dd, abs(np.pi - dd))
                    d.append(dd)
                pick = int(np.argmin(d))
            else:
                pick = 0
            r = cands[pick]
            rep.append({"anchor": b.get("label"), "err": None, "cands": len(cands),
                        "picked": pick + 1, "lens": [c["rec"]["h_mm"] for c in cands],
                        "wids": [c["rec"]["w_mm"] for c in cands]})
            if r is None:
                rep.append({"anchor": b.get("label"), "err": "窗内分不出物体层"}); continue
            r["label"] = b.get("label")
            r["prev"] = b3
            r["anchor"] = (int(px_box[0]), int(px_box[1]), int(px_box[2]), int(px_box[3]))
            items.append(r)
    elif a.green:
        an = green_anchors(img, dep_m, min_area=a.min_area)
        print(f"--green(绿底座锚点): 命中 {len(an)} 件 "
              f"{[tuple(d['green_bbox']) for d in an]}")
        if not an:
            print("没找到绿底座 ⇒ 换 --auto / --from-meas"); sys.exit(3)
        items, rep = [], []
        for d in an:
            px_box = d["win"]
            gx, gy, gw, gh = d["green_bbox"]
            # 逐行先验: 模块本体从绿底座**正上方**伸出, 宽度 ≈ 绿底座宽(同口径: 绿底座宽=模块宽,
            # 与上一视角量到的 17.3~18.4mm 吻合)。这样剖面法只在"该在的地方、该有的宽度"附近找边缘。
            pri = {y: (d["cx"], float(gw)) for y in range(int(px_box[1]), int(px_box[3]) + 1)}
            c1 = measure_by_profile(img, dep_m, K, X, tcp7, px_box, prior=pri)
            c2 = measure_by_profile(img, dep_m, K, X, tcp7, px_box,
                                    prior=row_prior_from_box(c1["box"], K, X, tcp7)) if c1 else None
            cands = [c for c in (c1, c2) if c is not None]
            if not cands:
                rep.append({"anchor": str(d["green_bbox"]), "err": "窗内分不出细条"}); continue
            # 没有"上一次的盒子"可参照: 模块是**长条(实测全长的候选 ~90mm)**, 绿手把只占 ~35mm ⇒
            # 取更长的那个候选(短候选=只抠到手把)。两件同型号, 尺寸再走同类件共识收敛。
            pick = int(np.argmax([c["rec"]["h_mm"] for c in cands]))
            r = cands[pick]
            r["anchor"] = px_box
            r["green_bbox"] = d["green_bbox"]
            items.append(r)
            rep.append({"anchor": str(d["green_bbox"]), "err": None, "cands": len(cands),
                        "lens": [round(c["rec"]["h_mm"], 1) for c in cands], "picked": pick + 1})
        items.sort(key=lambda it: it["rec"]["base_xy_mm"][0])
    elif a.auto:
        items, rep = detect_modules_auto(img, dep_m, K, X, tcp7, min_area=a.min_area)
        print(f"--auto(外观自足检测): 命中 {len(items)} 件细长模块")
    else:
        anchors = [b for b in (spec.get("cameras", {}).get(a.cam, {}).get("boxes") or [])
                   if b.get("xyxy") and b.get("origin") in ("vlm", "det")
                   and any(k in str(b.get("label", "")) for k in keys)]
        print(f"锚框 {len(anchors)} 个: {[b.get('label') for b in anchors]}")
        if not anchors:
            print("没有锚框 ⇒ 用 --auto, 或先跑 gen_overlay_from_vlm"); sys.exit(3)
        items, rep = measure_anchor(img, dep_m, K, X, tcp7, anchors)

    # 自检: 8 顶点投回像素的 xyxy 与锚框 IoU(位置/尺寸对得上画面的硬证据) + base-z 平面性
    dbg = Path("/home/ubuntu/.hermes/cache/scratch/mod_dbg")
    dbg.mkdir(parents=True, exist_ok=True)
    vis = img.copy()
    print(f"\n{'锚':<10}{'框px':>9}{'中心深度':>9}{'base面z':>9}{'长mm':>8}{'宽mm':>8}{'高mm':>7}"
          f"{'角度°':>8}{'框IoU':>7}{'环px':>6}")
    keeps = []
    # 同类件共识尺寸: 两件是**同型号**光模块, 位置/朝向各自单独测, 长宽取两件的共识(中位)。
    # 单件测量受反光/过曝/弱边影响会有 ±20% 抖动(实测同一个模块两遍量出 39.7 与 84.9mm);
    # 同型号两件的冗余能把尺寸钉住 —— 两件独立量到 84.9 与 84.9mm 就是这么来的。
    if a.consensus and len(items) >= 2:
        _L = float(np.median([it["box"]["size"][0] for it in items]))
        _W = float(np.median([it["box"]["size"][1] for it in items]))
        _Hs = [float(it["box"]["size"][2]) for it in items]
        # 高也取共识: 两件同型号 ⇒ 盒子高应该一样。取"较大"的那个(一个模块的环采样可能没吃到
        # 槽底, 高度被量成 ~2mm; 同型号两件的最大值比中位更稳), 相差 ≤4mm 就用中位。
        _H = float(max(_Hs)) if (max(_Hs) - min(_Hs)) > 4.0 else float(np.median(_Hs))
        for it in items:
            _old = float(it["box"]["size"][2])
            it["box"]["size"][0] = round(_L, 1)
            it["box"]["size"][1] = round(_W, 1)
            it["box"]["size"][2] = round(_H, 1)
            it["box"]["center"][2] += (_old - _H) / 2000.0     # 顶面不动, 中心随高度下移
        print(f"\n同类件共识尺寸: 长 {_L:.1f} × 宽 {_W:.1f} × 高 {_H:.1f}mm "
              f"(两件中位/取大; 位置与朝向仍各自实测)")
    for i, it in enumerate(items, 1):
        r = it["rec"]
        r.setdefault("anchor", it.get("anchor"))
        c8 = SO.box3d_corners(it["box"]["center"], it["box"]["size"], it["box"]["R"])
        uv = SO.cam_to_px(SO.base_to_cam(c8, X, tcp7), K)
        if not np.isfinite(uv).all():
            rep.append({"anchor": str(it.get("anchor")), "err": "投影 NaN(该件量测失败, 已跳过)"})
            continue
        x1, y1, x2, y2 = it["anchor"]
        ux0, uy0 = float(uv[:, 0].min()), float(uv[:, 1].min())
        ux1, uy1 = float(uv[:, 0].max()), float(uv[:, 1].max())
        ix0, iy0 = max(x1, ux0), max(y1, uy0)
        ix1, iy1 = min(x2, ux1), min(y2, uy1)
        inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
        uni = max(1e-6, (x2 - x1) * (y2 - y1) + (ux1 - ux0) * (uy1 - uy0) - inter)
        iou = inter / uni
        r["iou_box"] = round(iou, 3)
        lbl = "光模块·实测%d" % i
        _dmid = r.get("d_mid_mm", r.get("d_obj_mm"))
        keeps.append({"origin": "meas", "label": it.get("label") or lbl, "box3d": it["box"],
                      "note": ("锚框/投影窗 × 深度分层实测 3D: 物体面深度 %.1fmm → base 面 z=%.1fmm · "
                               "尺寸 %.1f×%.1f×%.1fmm(量出来的, 非标称) · 朝向 %.1f°(量出来的, 非轴对齐) · "
                               "框投影 IoU %.2f") % (_dmid, r["z_obj_mm"], r["w_mm"],
                                                  r["h_mm"], r["H_mm"], r["angle_deg"], iou)})
        bw, bh = x2 - x1, y2 - y1
        print(f"{str(r['anchor'])[:9]:<10}{bw:>4}×{bh:<4}{_dmid:>9.1f}{r['z_obj_mm']:>9.1f}"
              f"{r['w_mm']:>8.1f}{r['h_mm']:>8.1f}{str(r['H_mm']):>7}{r['angle_deg']:>8.1f}"
              f"{iou:>7.2f}{r.get('ring_px', r.get('px', '')):>6}")
        for (i0, j0) in SO.EDGES:
            cv2.line(vis, (int(uv[i0][0]), int(uv[i0][1])), (int(uv[j0][0]), int(uv[j0][1])),
                     (230, 0, 230), 2, cv2.LINE_AA)
        for p in uv:
            cv2.circle(vis, (int(p[0]), int(p[1])), 4, (0, 255, 255), -1)
        cv2.rectangle(vis, (x1, y1), (x2, y2), (255, 200, 0), 1)
    for r in rep:
        if r.get("err"):
            print(f"  ✗ {r.get('anchor')}: {r.get('err')}")
    for r in rep:
        if r.get("err") is None and r.get("cands"):
            _w = r.get("wids") or "-"
            print(f"  · {r['anchor']}: {r['cands']} 遍 (长候选 {r['lens']} / 宽 {_w}) → 取第 {r['picked']} 遍")
    for k, it in enumerate(items, 1):
        x1, y1, x2, y2 = it["anchor"]
        bx1, by1 = max(0, x1 - 35), max(0, y1 - 35)
        bx2, by2 = min(W, x2 + 35), min(H, y2 + 35)
        cv2.imwrite(str(dbg / f"meas{k}_box.png"),
                    cv2.resize(vis[by1:by2, bx1:bx2], None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST))
    print(f"\n取证图: {dbg}/meas*_box.png (紫=量出的 8 顶点长方体, 黄=顶点, 青=锚框)")

    if a.apply and keeps:
        spec = SO.merge_origin(spec, a.cam, "meas", keeps,
                               {"by": "measure_module_cuboid.py", "at": time.strftime("%F %T")})
        if a.hide_2d:
            # 与 draw_overlay 里 _bid() 同口径: origin|label, 重名按出现顺序加 #2/#3…
            ids, cnt = [], {}
            for b in (spec.get("cameras", {}).get(a.cam, {}).get("boxes") or []):
                base = "%s|%s" % (b.get("origin", "?"), b.get("label", "?"))
                k = cnt.get(base, 0) + 1
                cnt[base] = k
                ids.append((base if k == 1 else "%s#%d" % (base, k), b))
            dl = set((spec.get("deleted") or {}).get(a.cam) or [])
            for bid, b in ids:
                if b.get("origin") == "vlm" and any(k in str(b.get("label", "")) for k in keys):
                    dl.add(bid)
            spec.setdefault("deleted", {})[a.cam] = sorted(dl)
        SO.save_spec(spec)
        print("已写入 spec: meas %d 件%s" % (len(keeps), " · 同时把 2D 大模型光模块框标为已删" if a.hide_2d else ""))
    elif not a.apply:
        print("\n(--apply 才会写盘)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
