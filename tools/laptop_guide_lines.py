#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
laptop_guide_lines.py — 笔记本摄像头(local 路) 上的「世界水平辅助线」: **全部过横梁消失点**, 即与横梁平行。

老倪 2026-09-30 纠正原话: 「画的线不是以相机坐标系为轴, 要以世界坐标系为轴, 要平行于横梁, 你好好研究一下投影关系」

投影关系(本工具的依据):
  · 3D 中互相平行的直线, 在图像里**交于同一点**(消失点 VP)。所以"世界水平、且平行于横梁"的线
    ≠ 图像里 y 恒定的横线, 而是**过横梁消失点 VP_A 的斜线**。
  · VP_A 由**横梁自身的两条平行棱**(上棱亮线 / 下棱暗亮台阶)求交得到 —— 这两条棱在 3D 里平行、在图像里
    收敛, 是本视角下唯一可靠的平行证据(实测上棱 −4.04° / 下棱 −0.36°, 相隔 ~310px ⇒ VP ≈ (−750, 167),
    角度确定度 ~±0.5°)。⚠ 不可用"随便两族线求交"的自动拟合: 本视角下梁的上下棱近乎平行, VP 条件数极差,
    实测三次不同方法给出 144 / 248 / 286 三个答案 —— 那种解不能拿来画线。
  · 每条辅助线 = 过 VP_A 与该"层"锚点的直线, 锚点取该层实体特征实测直线上的点 ⇒ 线**平行于横梁**是构造保证。

落地: data/scene/overlay_spec.json → cameras.local.boxes, 元素
      {"origin":"guide","pts2d":[[x0,y0],[x1,y1]],"width":3,"no_label":true}
      (渲染器 2D 折线分支 + 真值带之上的补画通道, 保证不被底部状态带盖住)
用法:
  gui-venv311/bin/python tools/laptop_guide_lines.py --deploy        # 默认四层
  gui-venv311/bin/python tools/laptop_guide_lines.py --clear
"""
import argparse, json, math, os, shutil, time
import urllib.request
import cv2
import numpy as np

BASE = "http://127.0.0.1:8791"
Q = "?k=zmax-live"
SPEC = "/home/ubuntu/zmax_rel/data/scene/overlay_spec.json"
GUIDE_BGR = (255, 255, 0)          # 亮青, 与 ORIGIN_STYLE["guide"] 一致

# 每"层"的锚点来源: (名称, 台阶带 y 范围, x 范围, 说明)
LEVELS = [
    ("空间顶·横梁下沿", (126, 168), (318, 636), "上方横梁朝内那一面(下沿) —— 它就是内部空间的天花板", None),
    ("台面后沿",       (248, 280), (60, 300),  "左侧白色柜面/台面由暗到亮的分界(实测台阶 Δ≈-29)", 264),
    ("作业层·托盘后沿", (338, 372), (335, 500), "黑托盘后沿 —— 光模块摆放层的最远边界", None),
    ("空间底·工作面后沿", (392, 442), (335, 636), "白色工作面可见后沿(空间的地板线)", None),
]


def get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "zmax-guide/2.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def frame(name="local"):
    return cv2.imdecode(np.frombuffer(get("%s/snapshot/%s.jpg%s" % (BASE, name, Q)), np.uint8), cv2.IMREAD_COLOR)


def _ransac(P, min_sep=60, thr=3.0, iters=800, seed=7):
    if len(P) < 8:
        return None
    rng = np.random.default_rng(seed)
    best = None
    for _ in range(iters):
        i, j = rng.choice(len(P), 2, replace=False)
        if abs(P[i, 0] - P[j, 0]) < min_sep:
            continue
        m = (P[j, 1] - P[i, 1]) / (P[j, 0] - P[i, 0]); c = P[i, 1] - m * P[i, 0]
        r = np.abs(P[:, 1] - (m * P[:, 0] + c)); inl = r < thr
        if best is None or inl.sum() > best[0]:
            best = (int(inl.sum()), inl)
    if not best or best[0] < 8:
        return None
    m, c = np.polyfit(P[best[1], 0], P[best[1], 1], 1)
    return float(m), float(c), best[0], len(P)


def fit_step(g, ylo, yhi, xr, thr=6.5, step=5):
    """逐列找"暗->亮"最强台阶(实体边线的下沿) → RANSAC 直线"""
    pts = []
    for x in range(xr[0], min(xr[1], g.shape[1]), step):
        c = g[max(0, ylo - 6):yhi + 6, x - 2:x + 3].mean(1)
        d = np.diff(c); i = int(np.argmax(d))
        if d[i] > thr:
            pts.append((x, max(0, ylo - 6) + i + 1))
    if len(pts) < 8:
        return None
    return _ransac(np.array(pts, float))


def fit_bright(g, ylo, yhi, xr, step=5):
    """逐列找最亮行(梁的上棱是一条亮线) → RANSAC 直线"""
    pts = []
    for x in range(xr[0], min(xr[1], g.shape[1]), step):
        col = g[ylo:yhi, x - 2:x + 3].mean(1)
        y = int(np.argmax(col))
        if col[y] > 90:
            pts.append((x, ylo + y))
    if len(pts) < 8:
        return None
    return _ransac(np.array(pts, float))


def fit_beam_top(g, W):
    best = None
    for lo, hi in ((52, 100), (52, 120), (60, 130)):
        r = fit_bright(g, lo, hi, (318, min(636, W)))
        if r and (best is None or r[2] > best[2]):
            best = (r[0], r[1], r[2], r[3])
    return best


def solve_vp(m1, c1, m2, c2):
    if abs(m1 - m2) < 1e-4:
        return None
    x = (c2 - c1) / (m1 - m2)
    return float(x), float(m1 * x + c1)


def line_through_vp(vp, ax, ay, x0, x1):
    """过 VP 与锚点(ax,ay)的直线, 截到 [x0,x1]"""
    dx, dy = (ax - vp[0]), (ay - vp[1])
    if abs(dx) < 1e-6:
        return [[ax, float(x0)], [ax, float(x1)]]
    m = dy / dx
    return [[float(x0), float(vp[1] + m * (x0 - vp[0]))], [float(x1), float(vp[1] + m * (x1 - vp[0]))]]


def build(img):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    H, W = g.shape[:2]
    ft = fit_beam_top(g, W)
    fb = fit_step(g, 126, 168, (318, min(636, W)), thr=6.0)
    print("── 横梁两条平行棱(求消失点的证据) ──")
    if not ft or not fb:
        raise SystemExit("✗ 横梁棱线拟合失败, 不硬编坐标(免得又画错)")
    print("   上棱(亮线)  y=%.4fx+%.1f  倾角 %+.2f°  [内点 %d/%d]"
          % (ft[0], ft[1], math.degrees(math.atan(ft[0])), ft[2], ft[3]))
    print("   下棱(台阶)  y=%.4fx+%.1f  倾角 %+.2f°  [内点 %d/%d]"
          % (fb[0], fb[1], math.degrees(math.atan(fb[0])), fb[2], fb[3]))
    vp = solve_vp(ft[0], ft[1], fb[0], fb[1])
    if not vp:
        raise SystemExit("✗ 梁上下棱平行 ⇒ 本视角解不出消失点, 不画(如实报, 不硬编)")
    d = abs(ft[0] - fb[0])
    print("   ★ 消失点 VP_A = (%.0f, %.0f)   两棱斜率差 %.4f (抗噪: 差越大越准)" % (vp[0], vp[1], d))
    print("     参考: 相机水平线(地平线)必过 VP_A; 各层线的倾角由 VP_A 与该层高度共同决定\n")
    out = []
    for name, (ylo, yhi), xr, why, fixy in LEVELS:
        f = fit_step(g, ylo, yhi, xr)
        xm = int((xr[0] + min(xr[1], W)) / 2)
        if fixy is not None:
            # 该层有**强实测**锚点(单点台阶 Δ 很大)时以它为准: 弱拟合(内点少)会把锚点拉偏
            #   —— 2026-09-30 实测: 台面后沿特征线只有 11/30 内点、拟出 -13.8°, 锚点被拉到 y=297,
            #      而实测台阶就在 264 ⇒ 强证据优先, 位置差 33px 老倪一眼就能看出来。
            ay = float(fixy)
            print("   %-18s ⇒ 用**固定实测锚点** y=%.0f (弱拟合 %s)" % (name, ay, ("内点%d/%d" % (f[2], f[3])) if f else "失败"))
        elif f:
            ay = f[0] * xm + f[1]
        else:
            print("   %-18s 特征线拟合失败且无固定锚点 ⇒ 跳过(不猜)" % name); continue
        p = line_through_vp(vp, xm, ay, xr[0], min(xr[1], W))
        ang = math.degrees(math.atan2(p[1][1] - p[0][1], p[1][0] - p[0][0]))
        out.append({"name": name, "why": why, "anchor": [xm, round(ay, 1)], "pts2d": p,
                    "fit": {"m": f[0], "c": f[1], "ang": math.degrees(math.atan(f[0])), "inl": f[2], "n": f[3]},
                    "angle_deg": round(ang, 2), "y_at_anchor": round(ay, 1)})
        print("   %-18s 特征线倾角 %+6.2f°[内点%2d/%2d] ⇒ 锚点(%d, %.0f) ⇒ **辅助线倾角 %+6.2f°**"
              % (name, math.degrees(math.atan(f[0])), f[2], f[3], xm, ay, ang))
    return vp, out


def deploy(vp, lines, W, H):
    spec = json.load(open(SPEC, encoding="utf-8"))
    bak = "/home/ubuntu/zmax_data/overlay_spec.bak_guide_%s.json" % time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(SPEC, bak)
    loc = spec.setdefault("cameras", {}).setdefault("local", {})
    old = [b for b in loc.get("boxes", []) if b.get("origin") == "guide"]
    loc["boxes"] = [b for b in loc.get("boxes", []) if b.get("origin") != "guide"]
    for L in lines:
        loc["boxes"].append({"origin": "guide", "label": "世界水平·平行于横梁 | %s" % L["name"],
                             "pts2d": [[round(p[0], 1), round(p[1], 1)] for p in L["pts2d"]],
                             "width": 3, "no_label": True})
    dec = spec.setdefault("deleted", {}).setdefault("local", [])
    for b in old:
        k = "%s|%s" % (b.get("origin"), b.get("label", "")[:40])
        if k not in dec:
            dec.append(k)
    loc["by_origin"] = {}
    for b in loc["boxes"]:
        loc["by_origin"][b.get("origin")] = loc["by_origin"].get(b.get("origin"), 0) + 1
    spec["ts"] = time.time(); spec["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    spec.setdefault("sources", {})["guide"] = {
        "by": "tools/laptop_guide_lines.py", "cam": "local", "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "n": len(lines), "vanishing_point": [round(vp[0], 1), round(vp[1], 1)],
        "method": "世界水平线 = 过横梁消失点的斜线(投影关系), 非图像水平线",
        "lines": [{"name": L["name"], "angle_deg": L["angle_deg"], "anchor": L["anchor"]} for L in lines]}
    json.dump(spec, open(SPEC, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n   ✓ 写规格: local.boxes guide=%d (旧 %d 进 deleted) · 备份 %s" % (len(lines), len(old), bak))


def verify(lines, W, H, sleep=2.2):
    time.sleep(sleep)
    a, b = frame("local"), frame("overlay_local")
    m = (np.abs(b.astype(int) - np.array(GUIDE_BGR)).sum(2) < 170)
    tot = int(m.sum())
    print("   ── 核验: 叠加帧里 guide 色像素 %d (原始帧 %d) ⇒ 增量 %+d %s"
          % (tot, int(((np.abs(a.astype(int) - np.array(GUIDE_BGR)).sum(2) < 170).sum())),
             tot - int(((np.abs(a.astype(int) - np.array(GUIDE_BGR)).sum(2) < 170).sum())),
             "✓" if tot > 500 else "✗"))
    ys, xs = np.where(m)
    if len(xs) < 200:
        print("   ✗ 线上像素太少, 看不出方向"); return
    # 逐条核验: **只取落在该线 ±3px 内的像素**(按 y 窗口取会把别的线混进来 —— 2026-09-30 自己踩过)
    for L in lines:
        (x0, y0), (x1, y1) = L["pts2d"]
        msk = []
        for X, Y in zip(xs, ys):
            if X < min(x0, x1) - 2 or X > max(x0, x1) + 2:
                msk.append(False); continue
            yt = y0 + (y1 - y0) * (X - x0) / max(1e-6, (x1 - x0))
            msk.append(abs(Y - yt) <= 3.0)
        msk = np.array(msk)
        if msk.sum() < 60:
            print("      %-18s 该线像素不足(%d), 跳过角度核验" % (L["name"], int(msk.sum()))); continue
        sl = np.polyfit(xs[msk], ys[msk], 1)[0]
        got = math.degrees(math.atan(sl))
        print("      %-18s 目标 %+6.2f°  实测 %+6.2f°  差 %+.2f°  像素 %4d %s"
              % (L["name"], L["angle_deg"], got, got - L["angle_deg"], int(msk.sum()),
                 "✓" if abs(got - L["angle_deg"]) < 1.5 else "✗"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deploy", action="store_true")
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--out", default="/home/ubuntu/zmax_data/feishu_send/laptop_guide_lines.jpg")
    a = ap.parse_args()
    img = frame("local")
    if img is None:
        raise SystemExit("✗ 取不到 local 帧")
    H, W = img.shape[:2]
    print("   帧 %dx%d\n" % (W, H))
    if a.clear:
        deploy((0, 0), [], W, H); print("   ✓ 已清空"); return
    vp, lines = build(img)
    if not lines:
        raise SystemExit("✗ 一层都没拟合出来, 不落地")
    vis = img.copy()
    for i, L in enumerate(lines):
        p = np.round(np.array(L["pts2d"])).astype(np.int32)
        cv2.polylines(vis, [p], False, GUIDE_BGR, 3, cv2.LINE_AA)
        cv2.putText(vis, "L%d %s (%+.1f%%)" % (i + 1, L["name"], L["angle_deg"]),
                    (int(p[0][0]) + 4, int(min(p[:, 1])) - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.42, GUIDE_BGR, 1, cv2.LINE_AA)
    cv2.circle(vis, (int(round(vp[0])), int(round(vp[1]))), 6, (0, 0, 255), -1)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    cv2.imwrite(a.out, vis, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    print("   ✓ 渲染图 %s (红点=VP_A)" % a.out)
    if a.deploy:
        deploy(vp, lines, W, H)
        verify(lines, W, H)
    print("FILE " + a.out)


if __name__ == "__main__":
    main()
