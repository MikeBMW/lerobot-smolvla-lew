#!/usr/bin/env python3
"""🖼 3D 视图真实渲染像素校验 (DISPLAY=:0, 需要 GL) — 金色插销到底在哪

在关键帧 (起始/抓取前/抓取后/插入完成) 抓 framebuffer, 统计金色插销像素质心,
与"插销世界坐标的相机投影"逐帧比对 → 证明 3D 视图里插销真的先在台面、后随手走。
用法: DISPLAY=:0 gui-venv311/bin/python tools/probe_view_render.py
"""
import os
import sys

GUI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "gui")
sys.path.insert(0, GUI)
os.environ.setdefault("DISPLAY", ":0")

import numpy as np  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402
from PyQt5.QtGui import QVector3D  # noqa: E402

app = QApplication(sys.argv)
import ss_dreamview as sdv  # noqa: E402

# 数据源 = 与操作视频同源的 metaworld episode trace (没有则退回 numpy 引擎)
tr, meta = sdv.load_episode()
if tr is None:
    from state_space_sim import StateSpaceSim
    tr = StateSpaceSim(log=lambda *a: None).run()
    meta = None
    print("⚠️ 无同源 trace → 用 numpy 引擎轨迹")
else:
    print(f"同源 episode: seed={meta['seed']} · {meta['steps']} 步 · 终态 {meta['stage_final']}")
n = len(tr["x"])
import numpy as _np
gi = next((i for i, g in enumerate(_np.asarray(tr["grasped"]).astype(bool)) if g), 0)

dv = sdv.DreamView3D(tr)
dv.resize(1000, 700)
dv.show()
# ⚠️ 关掉所有动作/接触图层: 融合指令箭头是金黄(255,199,31)、接触热力球是橙(255,102,0),
#    都落在"金色插销"掩码里 → 不关层测出来的质心是插销+箭头混合 (实测偏 66px 就是这个坑)
for _k in ("uff", "ufb", "ufuse", "ulimit", "latent", "contact", "traj", "yolo"):
    try:
        dv._toggle_layer(_k, False)
    except Exception:
        pass
for _ in range(10):
    app.processEvents()
view = dv.view
vm = view.viewMatrix()
FOV = float(view.opts.get("fov", 60.0))


def project(p, W, H):
    """复用 ss_dreamview.project_world (唯一投影实现) → 像素坐标"""
    s = sdv.project_world(view, p)
    return None if s is None else (s[0] * W, s[1] * H)


def gold_centroid(img_arr):
    """金色插销像素质心 + 数量。掩码放宽到 r>110: 插销用 shader='shaded' 有光照,
    背光面的金色会被压暗到 (120,90,15) 一带, 严格阈值只能抓到高光的十几个像素。
    ⚠️ 调用前必须关掉 ufuse(金黄箭头)/contact(橙球) 图层, 否则质心是混合值。"""
    r, g, b = img_arr[:, :, 0].astype(int), img_arr[:, :, 1].astype(int), img_arr[:, :, 2].astype(int)
    m = (r > 90) & (g > 0.60 * r) & (g < 0.95 * r) & (b < 0.40 * r)
    cnt = int(m.sum())
    if cnt == 0:
        return 0, None
    ys, xs = np.nonzero(m)
    return cnt, (float(xs.mean()), float(ys.mean()))


_pegz = _np.asarray(tr["peg"], float)[:, 2]
_top = int(_np.argmax(_pegz))          # 插销举得最高的那一帧 (抬起/转移中)
frames = [("起始 (手空着)", 0),
          ("抓取前一刻", max(0, gi - 5)),
          ("提起最高", _top),
          ("插入完成", n - 1)]
print(f"仿真 {n} 帧, 抓取发生在帧 {gi}\n")
print(f"{'关键帧':<14} {'帧号':>6} {'金像素数':>8} {'金质心(px)':>18} {'插销投影(px)':>18} {'偏差px':>7} {'阶段':<6}")
print("-" * 88)
ok = True
for name, idx in frames:
    dv._update_frame(idx)
    for _ in range(4):
        app.processEvents()
    qimg = view.grabFramebuffer()
    W, H = qimg.width(), qimg.height()
    ptr = qimg.bits()
    ptr.setsize(qimg.byteCount())
    arr = np.frombuffer(ptr, np.uint8).reshape(H, qimg.bytesPerLine() // 4, 4)[:, :W, :3]
    arr = arr[:, :, ::-1]          # BGR → RGB
    cnt, cen = gold_centroid(arr)
    peg = np.asarray(tr["peg"][idx]) + dv._peg_center_off
    exp = project(peg, W, H)
    dev = (float(np.hypot(cen[0] - exp[0], cen[1] - exp[1])) if (cen and exp) else -1)
    stage = tr["stage"][idx].replace("阶段 ", "").split(" · ")[0]
    print(f"{name:<14} {idx:>6} {cnt:>8} "
          f"{f'({cen[0]:.0f},{cen[1]:.0f})' if cen else '—':>18} "
          f"{f'({exp[0]:.0f},{exp[1]:.0f})' if exp else '—':>18} {dev:>7.0f} {stage:<6}")
    if cnt < 10 or dev < 0 or dev > 40:
        ok = False

# 抓取前后: 插销世界坐标是否真的从台面(不动) → 随手动
peg0 = np.asarray(tr["peg"][0])
peg_pre = np.asarray(tr["peg"][max(0, gi - 5)])
peg_post = np.asarray(tr["peg"][int(np.argmax(np.asarray(tr["peg"], float)[:, 2]))])
still = float(np.linalg.norm(peg_pre - peg0))
moved = float(np.linalg.norm(peg_post - peg0))
print("\n═══ 判定 ═══")
print(f"  抓取前插销位移 {still * 1000:.1f}mm (应<20: 躺台面, 闭爪时手指会轻推)")
print(f"  抓取后插销位移 {moved * 1000:.1f}mm (应>80: 被抓起来了)")
print(f"  渲染金色插销像素与世界坐标投影一致 (偏差<40px): {'✅' if ok else '❌'}")
print(f"→ 总判定: {'✅ 3D 视图内容 = 完整插拔 (先抓销后插入)' if (ok and still < 0.02 and moved > 0.08) else '❌'}")
dv.close()
app.quit()
