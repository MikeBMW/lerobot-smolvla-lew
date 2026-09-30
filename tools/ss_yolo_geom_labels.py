#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_yolo_geom_labels.py — 仿真数据的 YOLO 几何自动标注 (无需人工拖框, 无需手眼标定)

原理: `gen_ss_metaworld_episode.py` 生成的 episode 里每帧都有 3D 真值 (x/peg/peg_head/target)
      且 meta 存了该次渲染的相机位姿与视场 (cam_pos/cam_fwd/cam_right/cam_up/cam_fovy=60)。
      ⇒ 世界点 -> 像平面 的投影是精确的, 把光模块/插槽的 3D 有向盒 8 角点投影取外接矩形 = 标注框。

与真机侧的关系: 真机用 tools/real_autolabel.py (机器人当标定物, DLT 解投影 + 运动差分取中心);
                仿真侧不需要标定, 直接用引擎给的相机参数 —— 但**必须同一渲染口径**(渲染尺寸/相机参数
                从 episode 的 meta 读, 不要写死)。

用法:
  # 纯数学自检 (不需要引擎/GPU, 立刻可跑)
  gui-venv311/bin/python tools/ss_yolo_geom_labels.py --selftest
  # 标注单条 episode → json (每帧 peg/槽 两类框)
  gui-venv311/bin/python tools/ss_yolo_geom_labels.py --episode ~/zmax_data/ss_sim_20260921/ep_s1.npz \
      --img-w 640 --img-h 480 --out reports/yolo_labels_ep_s1.json
"""
from __future__ import annotations
import argparse, json, math, os, sys
import numpy as np

# 光模块尺寸 (metaworld 40×16mm 模块) —— 与数据集 meta 口径一致
PEG_LEN, PEG_WID, PEG_THK = 0.040, 0.016, 0.012
# 插槽开口 (含间隙) —— 用于"孔"类框
SLOT_LEN, SLOT_WID = 0.046, 0.022


def build_K(fovy_deg: float, W: int, H: int, fwd_up_dot_tol: float = 1e-3) -> np.ndarray:
    """针孔内参: 竖直视场 fovy + 图像尺寸 → K (像素单位, 主点在中心).

    仿真渲染器 (mujoco) 的 fovy 是**竖直**视场角 ⇒ fy 由 fovy 定, fx = fy (方形像素).
    """
    fy = 0.5 * H / math.tan(0.5 * math.radians(fovy_deg))
    fx = fy
    return np.array([[fx, 0.0, 0.5 * (W - 1)],
                     [0.0, fy, 0.5 * (H - 1)],
                     [0.0, 0.0, 1.0]], dtype=float)


def build_R_wc(cam_fwd: np.ndarray, cam_right: np.ndarray, cam_up: np.ndarray) -> np.ndarray:
    """世界→相机 旋转 (行 = 相机基在世界系下的分量).

    相机系约定: x 右, y 上, z **朝前** (OpenGL/针孔一致).
    """
    f = np.asarray(cam_fwd, float); f = f / np.linalg.norm(f)
    r = np.asarray(cam_right, float); r = r / np.linalg.norm(r)
    u = np.asarray(cam_up, float); u = u / np.linalg.norm(u)
    # 正交化 (引擎给的基一般已正交, 这里防数值漂移)
    f = f / np.linalg.norm(f)
    r = r - f * np.dot(r, f); r = r / np.linalg.norm(r)
    u = np.cross(f, r); u = u / np.linalg.norm(u)
    return np.stack([r, u, f], axis=0)


def project(points_world: np.ndarray, cam_pos, cam_fwd, cam_right, cam_up, K) -> tuple[np.ndarray, np.ndarray]:
    """世界点 (N,3) → 像素 (N,2) + 相机系 z (N,) . z<=0 = 在相机身后/平面外."""
    P = np.asarray(points_world, float).reshape(-1, 3)
    R = build_R_wc(cam_fwd, cam_right, cam_up)
    pc = (P - np.asarray(cam_pos, float)) @ R.T          # 世界→相机
    z = pc[:, 2]
    uv = np.full((len(P), 2), np.nan)
    ok = z > 1e-6
    if ok.any():
        pix = (pc[ok] @ K.T)
        uv[ok] = pix[:, :2] / pix[:, 2:3]
    return uv, z


def oriented_box(center, axis_z, axis_x, half_len, half_wid, half_thk) -> np.ndarray:
    """有向盒 8 角点. axis_z = 长轴单位向量, axis_x = 宽轴(会被正交化)."""
    z = np.asarray(axis_z, float); z = z / (np.linalg.norm(z) + 1e-12)
    x = np.asarray(axis_x, float)
    x = x - z * np.dot(x, z)
    n = np.linalg.norm(x)
    x = x / n if n > 1e-9 else np.array([1.0, 0, 0]) - z * z[0]
    x = x / (np.linalg.norm(x) + 1e-12)
    y = np.cross(z, x)
    c = np.asarray(center, float)
    pts = []
    for sz in (-1, 1):
        for sx in (-1, 1):
            for sy in (-1, 1):
                pts.append(c + sz * half_len * z + sx * half_wid * x + sy * half_thk * y)
    return np.asarray(pts)


def box_from_corners(corners_world, cam_pos, cam_fwd, cam_right, cam_up, K, W, H,
                     clip: bool = True, min_px: float = 2.0):
    """3D 角点 → 2D 轴对齐外接框 (x1,y1,x2,y2) + 合法性. 相机后方点会让框炸, 故用 z>0 过滤."""
    uv, z = project(corners_world, cam_pos, cam_fwd, cam_right, cam_up, K)
    m = np.isfinite(uv).all(axis=1) & (z > 1e-6)
    if m.sum() < 4:                       # 太少可见角点 → 不可靠, 丢弃
        return None
    p = uv[m]
    x1, y1 = float(p[:, 0].min()), float(p[:, 1].min())
    x2, y2 = float(p[:, 0].max()), float(p[:, 1].max())
    if clip:
        x1, y1 = max(x1, 0.0), max(y1, 0.0)
        x2, y2 = min(x2, float(W - 1)), min(y2, float(H - 1))
    if x2 - x1 < min_px or y2 - y1 < min_px:
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2, float(m.sum()))


def label_episode(ep_path: str, img_w: int, img_h: int) -> dict:
    d = np.load(ep_path, allow_pickle=True)
    meta = d["meta"][0] if "meta" in d.files else {}
    cam = dict(pos=meta["cam_pos"], fwd=meta["cam_fwd"], right=meta["cam_right"],
               up=meta["cam_up"], fovy=float(meta.get("cam_fovy", 60.0)))
    K = build_K(cam["fovy"], img_w, img_h)
    peg, peg_head, x = d["peg"], d["peg_head"], d["x"]
    target = d["target"] if "target" in d.files else None
    frames = []
    n = len(peg)
    for i in range(n):
        # 光模块长轴 = 夹爪(x) → 模块尖方向: 用 peg_head→peg 的方向
        axis = peg[i] - peg_head[i]
        items = []
        b = box_from_corners(oriented_box(peg[i], axis, np.array([1.0, 0, 0]),
                                          PEG_LEN / 2, PEG_WID / 2, PEG_THK / 2),
                             cam["pos"], cam["fwd"], cam["right"], cam["up"], K, img_w, img_h)
        if b: items.append({"cls": "peg", "xyxy": [round(v, 2) for v in b[:4]], "n_corners": int(b[4])})
        if target is not None:
            axis_t = np.array([0.0, 0.0, 1.0])      # 插槽开口朝上, 长轴按竖直取
            b2 = box_from_corners(oriented_box(target[i], axis_t, np.array([1.0, 0, 0]),
                                               SLOT_LEN / 2, SLOT_WID / 2, 0.010),
                                  cam["pos"], cam["fwd"], cam["right"], cam["up"], K, img_w, img_h)
            if b2: items.append({"cls": "slot", "xyxy": [round(v, 2) for v in b2[:4]], "n_corners": int(b2[4])})
        frames.append({"i": i, "stage": str(d["stage"][i]) if "stage" in d.files else "",
                       "boxes": items})
    return {"episode": os.path.basename(ep_path), "img_w": img_w, "img_h": img_h,
            "camera": {k: (v.tolist() if isinstance(v, np.ndarray)
                           else float(v) if isinstance(v, (np.floating, np.integer, float, int))
                           else v) for k, v in cam.items()},
            "n_frames": n, "frames": frames}


def selftest() -> int:
    """纯数学自检: ① 光轴上的点 → 图像中心 ② 右侧点 → 右侧 ③ 上侧点 → 上方
       ④ 已知深度反投影回原 3D ⑤ 相机后方的点被剔除"""
    W, H, fovy = 640, 480, 60.0
    K = build_K(fovy, W, H)
    cam_pos = np.array([0.0, 0.0, 1.0])
    fwd, right, up = np.array([0, 0, -1.0]), np.array([1.0, 0, 0]), np.array([0, 1.0, 0])
    ok = True
    # ① 光轴点 (0,0,0) 距相机 1m
    uv, z = project(np.array([[0.0, 0, 0]]), cam_pos, fwd, right, up, K)
    c = np.array([0.5 * (W - 1), 0.5 * (H - 1)])
    e1 = np.linalg.norm(uv[0] - c)
    print(f"  ① 光轴点→中心: uv={np.round(uv[0],3)} 期望≈{np.round(c,3)} 误差={e1:.6f}px {'✅' if e1<1e-6 else '❌'}")
    ok &= e1 < 1e-6
    # ② +x 世界点 → 图像右侧
    uv2, _ = project(np.array([[0.1, 0.0, 0.0]]), cam_pos, fwd, right, up, K)
    e2 = uv2[0][0] - c[0]
    print(f"  ② +x 点→右侧: Δu={e2:.3f}px (>0 才对) {'✅' if e2 > 0 else '❌'}")
    ok &= e2 > 0
    # ③ +y 世界点 → 图像上方 (v 变小)
    uv3, _ = project(np.array([[0.0, 0.1, 0.0]]), cam_pos, fwd, right, up, K)
    e3 = c[1] - uv3[0][1]
    print(f"  ③ +y 点→上方: Δv={e3:.3f}px (>0 才对) {'✅' if e3 > 0 else '❌'}")
    ok &= e3 > 0
    # ④ 反投影: 用 K 与深度把像素还原回 3D
    P = np.array([[0.03, -0.02, 0.05]])
    uv4, z4 = project(P, cam_pos, fwd, right, up, K)
    fx, fy, cx, cy = K[0, 0], K[1, 1], K[0, 2], K[1, 2]
    xc = (uv4[0][0] - cx) / fx * z4[0]; yc = (uv4[0][1] - cy) / fy * z4[0]
    R = build_R_wc(fwd, right, up)
    back = np.array([xc, yc, z4[0]]) @ R + cam_pos
    e4 = np.linalg.norm(back - P)
    print(f"  ④ 投影→反投影 往返误差: {e4:.3e} m {'✅' if e4 < 1e-9 else '❌'}")
    ok &= e4 < 1e-9
    # ⑤ 相机后方的点被剔除 (z<=0)
    uv5, z5 = project(np.array([[0.0, 0.0, 2.0]]), cam_pos, fwd, right, up, K)
    e5 = (not np.isfinite(uv5[0]).all()) and z5[0] < 0
    print(f"  ⑤ 相机后方点被剔除: z={z5[0]:.3f} uv={uv5[0]} {'✅' if e5 else '❌'}")
    ok &= e5
    # ⑥ 有向盒 8 角点数与中心
    box = oriented_box(np.array([0.0, 0, 0]), np.array([0, 0, 1.0]), np.array([1.0, 0, 0]), 0.02, 0.008, 0.006)
    ctr = box.mean(axis=0)
    e6 = box.shape == (8, 3) and np.linalg.norm(ctr) < 1e-12
    print(f"  ⑥ 有向盒: {box.shape} 角点均值={np.round(ctr,9)} {'✅' if e6 else '❌'}")
    ok &= e6
    print("自检:", "✅ 全部通过" if ok else "❌ 有失败项")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--episode", default="")
    ap.add_argument("--img-w", type=int, default=640)
    ap.add_argument("--img-h", type=int, default=480)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if not a.episode:
        ap.error("需要 --episode 或 --selftest")
    r = label_episode(a.episode, a.img_w, a.img_h)
    npeg = sum(1 for f in r["frames"] for b in f["boxes"] if b["cls"] == "peg")
    nslot = sum(1 for f in r["frames"] for b in f["boxes"] if b["cls"] == "slot")
    print(f"✅ {r['episode']}: {r['n_frames']} 帧 · peg 框 {npeg} · slot 框 {nslot}")
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        json.dump(r, open(a.out, "w"), ensure_ascii=False, indent=1)
        print(f"   → {a.out}")


if __name__ == "__main__":
    main()
