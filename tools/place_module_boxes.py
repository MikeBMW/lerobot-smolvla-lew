#!/usr/bin/env python3
"""视角换了以后**重新摆放**光模块的 3D 长方体(全部实测, 不猜)。

依据链(每条都量出来, 都有取证图):
  ① **锚点 = 绿手把**: 当前视角下只有光模块有高饱和绿, 绿掩膜无假阳性(实测命中 2 件)。
  ② **朝向 = 手把自身长轴**: 手把沿模块长轴伸出 ⇒ 对手把掩膜做 minAreaRect, 取长轴两端,
     各自按自身深度反投影到 base 系, 两点连线方向 = 模块长轴朝向。当帧重测, 不吃旧值。
     (踩过: 相机被机械臂转过以后模块在画面里会从"竖的"变"横的", 照抄上一视角的 -175° 会拧 90°)
  ③ **位置 = 手把像素中位深度** 反投影到 base(手把中心)。
  ④ **尺寸 = 91.0 × 18.6mm**(两视角各自独立量到同一量级: 89.9 / 84.9 / 92.8mm; 宽 17.3~18.6mm),
     高 20mm(近距视角实测台阶)。中心 = 手把中心沿长轴朝本体侧偏 (长/2 − 15mm)。
  ⑤ 写盘用 merge_origin(只换 meas), 不整体覆盖; 旧 vlm 的 2D 光模块框位置已不对 ⇒ 标删。
"""
import argparse
import sys
import time
import numpy as np, cv2
sys.path.insert(0, "/home/ubuntu/zmax/tools")
import scene_overlay as SO
from measure_module_cuboid import load_depth, cam_to_base, cam_pts_from_depth, Rz, MIN_D, MAX_D

MOD_L, MOD_W, MOD_H = 91.0, 18.6, 20.0     # mm — 两视角互证实测
TAIL_OFF = 15.0                            # mm — 手把中心到模块尾端(图像实测)


def handles(img, dep_m, min_area=250, min_ar=1.20):
    """绿手把: 绿掩膜 → 连通域 → 面积/细长比过滤 → minAreaRect 给朝向与两端深度。"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    ok = np.isfinite(dep_m) & (dep_m > MIN_D) & (dep_m < MAX_D)
    g = ((hue > 35) & (hue < 95) & (sat > 60) & (val > 60) & ok).astype(np.uint8) * 255
    g = cv2.morphologyEx(g, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), 1)
    n, lab, st, ce = cv2.connectedComponentsWithStats(g, 8)

    def _d(pt):
        u, v = int(round(pt[0])), int(round(pt[1]))
        seg = dep_m[max(0, v - 3):v + 4, max(0, u - 3):u + 4]
        good = (seg > MIN_D) & (seg < MAX_D)
        return float(np.median(seg[good])) if good.any() else float("nan")

    out = []
    for i in range(1, n):
        x, y, w, h, ar = st[i]
        if ar < min_area:
            continue
        cnts, _ = cv2.findContours((lab == i).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            continue
        (rc), (rw, rh), ra = cv2.minAreaRect(max(cnts, key=cv2.contourArea))
        if max(rw, rh) / max(1e-6, min(rw, rh)) < min_ar:
            continue
        # OpenCV 的 minAreaRect: **宽边**方向 = (cos ra, sin ra); 长边在 rw<rh 时要再转 90°。
        # (踩过: 不判这点会把"长轴"取成短边方向 ⇒ 量出来的模块朝向差 90°)
        if rw >= rh:
            ax = np.array([np.cos(np.radians(ra)), np.sin(np.radians(ra))])
        else:
            ax = np.array([-np.sin(np.radians(ra)), np.cos(np.radians(ra))])
        L = max(rw, rh) / 2.0
        p1, p2 = np.array(rc) - ax * L, np.array(rc) + ax * L
        out.append({"bbox": (int(x), int(y), int(w), int(h)), "area": int(ar),
                    "center_px": (float(rc[0]), float(rc[1])), "rect": (float(rw), float(rh), float(ra)),
                    "aspect": float(max(rw, rh) / max(1e-6, min(rw, rh))),
                    "p1": p1, "p2": p2, "d1": _d(p1), "d2": _d(p2),
                    "d_med": _d(np.array(rc)), "long_px": float(max(rw, rh))})
    out.sort(key=lambda d: d["center_px"][0])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--min-area", type=int, default=250)
    a = ap.parse_args()
    img = cv2.imdecode(np.frombuffer(SO.fetch_frame("arm"), np.uint8), cv2.IMREAD_COLOR)
    dep, scale, meta = load_depth(); dep_m = dep.astype(np.float32) * scale
    K = SO.load_intrinsics(640, 480); he = SO.load_handeye()
    if not he.get("ok"):
        print("手眼外参不可用:", he.get("why")); return 2
    X = he["X"]; tcp = SO.read_tcp(timeout=20, allow_ssh=False)
    print(f"帧龄 {time.time() - float(meta.get('t', 0)):.1f}s · TCP=({tcp[0]:.4f},{tcp[1]:.4f},{tcp[2]:.4f})")
    hs = handles(img, dep_m, min_area=a.min_area)
    print(f"绿手把 {len(hs)} 件: " + " | ".join(
        f"{h['bbox']} 细长{h['aspect']:.2f} 长{h['long_px']:.0f}px 深{h['d_med']*1000:.0f}mm" for h in hs))
    if not hs:
        print("没找到绿手把 ⇒ 模块不在这一帧里(或绿被反光过曝成白)"); return 3
    # 朝向: 手把接近方的时候 minAreaRect 的长轴不可靠(实测 1.29 细长比的手把给出 -68.7°, 而
    # 细长比 2.10 的给出 +2.9°) ⇒ **只用细长的手把定朝向**, 再按"同型号件朝向一致"套给所有模块。
    angs = []
    for i, h in enumerate(hs, 1):
        if h["aspect"] < 1.6 or not (np.isfinite(h["d1"]) and np.isfinite(h["d2"])):
            continue
        P = cam_to_base(cam_pts_from_depth(np.array([h["p1"][0], h["p2"][0]]),
                                           np.array([h["p1"][1], h["p2"][1]]),
                                           np.array([h["d1"], h["d2"]]), K), X, tcp)
        u = P[1][:2] - P[0][:2]
        nu = float(np.linalg.norm(u))
        if nu < 1e-6:
            continue
        u = u / nu
        v = float(np.degrees(np.arctan2(u[1], u[0])))
        v = v - 180.0 if v > 90.0 else (v + 180.0 if v < -90.0 else v)
        angs.append(v)
        print(f"  · 手把#{i} 细长{h['aspect']:.2f} → 长轴 {v:+.1f}° (作为朝向依据)")
    if not angs:
        print("没有可靠朝向(手把都太方) ⇒ 先手工给 --angle 或用别的方法定轴"); return 4
    ang = float(np.median(angs))
    print(f"朝向取 {len(angs)} 个可靠手把的中位: {ang:+.1f}° (模块在 base 系不动, 同型号件朝向一致)")
    keeps, vis = [], img.copy()
    u = np.array([np.cos(np.radians(ang)), np.sin(np.radians(ang))])
    for i, h in enumerate(hs, 1):
        if not np.isfinite(h["d_med"]):
            print(f"  #{i} 手把深度缺失, 跳过"); continue
        c_h = cam_to_base(cam_pts_from_depth(np.array([h["center_px"][0]]),
                                             np.array([h["center_px"][1]]),
                                             np.array([h["d_med"]]), K), X, tcp)[0]
        # 盒中心 = 手把中心沿长轴朝"本体侧"偏 (L/2 - TAIL_OFF)。
        # 本体侧怎么定: 手把在模块一端, 本体朝另一侧 ⇒ 把两个候选盒子都投影到画面, 取
        # **投影区域内灰度更高**的那侧 —— 模块的金属本体比空槽亮(实测: 金属 130~255, 空槽 50~90)。
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        cands = []
        for sgn in (+1, -1):
            c = c_h[:2] + sgn * u * (MOD_L / 2 - TAIL_OFF) / 1000.0
            box = {"center": [float(c[0]), float(c[1]), float(c_h[2]) - MOD_H / 2000.0],
                   "size": [MOD_L, MOD_W, MOD_H], "R": Rz(ang).tolist()}
            c8 = SO.box3d_corners(box["center"], box["size"], box["R"])
            uv = SO.cam_to_px(SO.base_to_cam(c8, X, tcp), K)
            if not np.isfinite(uv).all():
                continue
            m = np.zeros(gray.shape, np.uint8)
            cv2.fillConvexPoly(m, np.int32(cv2.convexHull(np.float32(uv))), 255)
            sel = m > 0
            bri = float(np.mean(gray[sel])) if sel.any() else 0.0
            cands.append((bri, int(sgn), box, uv))
        if not cands:
            print(f"  #{i} 投影不出画面, 跳过"); continue
        cands.sort(key=lambda t: -t[0])           # 灰度更高的一侧 = 本体侧
        _, sgn, box, uv = cands[0]
        keeps.append({"origin": "meas", "label": f"光模块·实测{i}", "box3d": box,
                      "note": ("锚=绿手把 · 位置=手把中位深度 %.1fmm 反投影 base · "
                               "朝向=手把 minAreaRect 长轴两端反投影连线 %.1f°(当帧实测) · "
                               "尺寸 %.0f×%.0f×%.0fmm(两视角互证实测) · 中心=手把中心沿长轴偏 %.0fmm")
                              % (h["d_med"] * 1000, ang, MOD_L, MOD_W, MOD_H, MOD_L / 2 - TAIL_OFF)})
        print(f"  #{i} 手把{h['bbox']} 深{h['d_med']*1000:.0f}mm 长轴 {ang:+.1f}° → 盒中心 base "
              f"({box['center'][0]*1000:.0f},{box['center'][1]*1000:.0f},{box['center'][2]*1000:.0f})mm 符号{sgn:+d}")
        for (i0, j0) in SO.EDGES:
            cv2.line(vis, tuple(np.int32(uv[i0])), tuple(np.int32(uv[j0])), (230, 0, 230), 2, cv2.LINE_AA)
        for p in uv:
            cv2.circle(vis, (int(p[0]), int(p[1])), 3, (0, 255, 255), -1)
        x, y, w, hh = h["bbox"]
        cv2.rectangle(vis, (x - 5, y - 5), (x + w + 5, y + hh + 5), (255, 200, 0), 1)
        cx0, cy0 = int(uv[:, 0].mean()), int(uv[:, 1].mean())
        cv2.imwrite("/home/ubuntu/.hermes/cache/scratch/place_%d.png" % i,
                    cv2.resize(vis[max(0, cy0 - 150):cy0 + 150, max(0, cx0 - 130):cx0 + 130],
                               None, fx=2.5, fy=2.5, interpolation=cv2.INTER_NEAREST))
    if a.apply and keeps:
        spec = SO.load_spec()
        spec = SO.merge_origin(spec, "arm", "meas", keeps,
                               {"by": "place_module_boxes.py", "at": time.strftime("%F %T")})
        cam = spec.setdefault("cameras", {}).setdefault("arm", {})
        dele = cam.setdefault("deleted", [])
        for b in (cam.get("boxes") or []):
            if b.get("origin") == "vlm" and "光模块" in str(b.get("label", "")):
                bid = "%s|%s" % (b.get("origin"), b.get("label"))
                if bid not in dele:
                    dele.append(bid)
        SO.save_spec(spec)
        print(f"已写盘: meas {len(keeps)} 条(旧 vlm 光模块 2D 框标删)")
    else:
        print("\n(--apply 才写盘)  取证图: place_*.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
