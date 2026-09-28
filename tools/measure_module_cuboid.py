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
    anchors = [b for b in (spec.get("cameras", {}).get(a.cam, {}).get("boxes") or [])
               if b.get("xyxy") and b.get("origin") in ("vlm", "det")
               and any(k in str(b.get("label", "")) for k in keys)]
    print(f"锚框 {len(anchors)} 个: {[b.get('label') for b in anchors]}")
    if not anchors:
        print("没有锚框 ⇒ 先跑 gen_overlay_from_vlm"); sys.exit(3)

    items, rep = measure_anchor(img, dep_m, K, X, tcp7, anchors)

    # 自检: 8 顶点投回像素的 xyxy 与锚框 IoU(位置/尺寸对得上画面的硬证据) + base-z 平面性
    dbg = Path("/home/ubuntu/.hermes/cache/scratch/mod_dbg")
    dbg.mkdir(parents=True, exist_ok=True)
    vis = img.copy()
    print(f"\n{'锚':<10}{'框px':>9}{'中心深度':>9}{'base面z':>9}{'长mm':>8}{'宽mm':>8}{'高mm':>7}"
          f"{'角度°':>8}{'框IoU':>7}{'环px':>6}")
    keeps = []
    for i, it in enumerate(items, 1):
        r = it["rec"]
        c8 = SO.box3d_corners(it["box"]["center"], it["box"]["size"], it["box"]["R"])
        uv = SO.cam_to_px(SO.base_to_cam(c8, X, tcp7), K)
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
        keeps.append({"origin": "meas", "label": lbl, "box3d": it["box"],
                      "note": ("锚框像素几何 × 深度定 3D: 中心深度 %.1fmm → base 面 z=%.1fmm · "
                               "尺寸 %.1f×%.1f×%.1fmm(量出来的, 非标称) · 朝向 %.1f°(量出来的, 非轴对齐) · "
                               "框投影 IoU %.2f") % (r["d_mid_mm"], r["z_obj_mm"], r["w_mm"],
                                                  r["h_mm"], r["H_mm"], r["angle_deg"], iou)})
        bw, bh = x2 - x1, y2 - y1
        print(f"{str(r['anchor'])[:9]:<10}{bw:>4}×{bh:<4}{r['d_mid_mm']:>9.1f}{r['z_obj_mm']:>9.1f}"
              f"{r['w_mm']:>8.1f}{r['h_mm']:>8.1f}{str(r['H_mm']):>7}{r['angle_deg']:>8.1f}"
              f"{iou:>7.2f}{r['ring_px']:>6}")
        for (i0, j0) in SO.EDGES:
            cv2.line(vis, (int(uv[i0][0]), int(uv[i0][1])), (int(uv[j0][0]), int(uv[j0][1])),
                     (230, 0, 230), 2, cv2.LINE_AA)
        for p in uv:
            cv2.circle(vis, (int(p[0]), int(p[1])), 4, (0, 255, 255), -1)
        cv2.rectangle(vis, (x1, y1), (x2, y2), (255, 200, 0), 1)
    for r in rep:
        print(f"  ✗ {r.get('anchor')}: {r.get('err')}")
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
