# -*- coding: utf-8 -*-
"""
gen_state_space_video.py — 🎥 状态空间仿真操作视频 (2026-08-18 老倪)

把 state_space_sim 的完整轨迹渲染成 mp4:
  俯视图: 孔位(红圈) + 末端夹爪(张开/闭合) + 轨迹线 + 接触高亮 + 阶段/时间/距离 HUD
渲染: Pillow (纯 Python, 线程安全 — 🐛 2026-08-18: QPainter 版在工作线程段错误
  QObject::killTimer / SIGSEGV, 弃用) → ffmpeg 合成 mp4 (25fps)

用法:
  python3 gen_state_space_video.py [输出.mp4]
"""
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from state_space_sim import StateSpaceSim, HOLE_POS

from PIL import Image, ImageDraw, ImageFont

W, H = 960, 640          # 画布
FPS = 25
MARGIN = 70              # 边缘留白
X0_W, X1_W = 0.04, 0.31
Y0_W, Y1_W = -0.11, 0.11

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
]
_FONT = next((f for f in _FONT_CANDIDATES if os.path.isfile(f)), _FONT_CANDIDATES[0])
_FONT_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"


def _sx(x): return MARGIN + (x - X0_W) / (X1_W - X0_W) * (W - 2 * MARGIN)
def _sy(y): return (H - MARGIN) - (y - Y0_W) / (Y1_W - Y0_W) * (H - 2 * MARGIN)


def _font(size, mono=False):
    try:
        return ImageFont.truetype(_FONT_MONO if mono else _FONT, size)
    except Exception:
        return ImageFont.load_default()


def render_frames(tr, out_dir):
    """渲染全部帧 → 返回帧文件列表 (PNG) — 纯 Pillow, 线程安全"""
    frames = []
    xs = np.asarray(tr["x"])          # (N,3)
    grippers = tr["gripper"]
    forces = tr["force"]
    stages = tr["stage"]
    t_arr = tr["t"]
    dists = tr["dist"]
    cps = tr["contact_p"]
    n = len(xs)
    n_out = min(n, FPS * 12)
    idxs = np.linspace(0, n - 1, n_out).astype(int)
    f_title = _font(16)
    f_hud = _font(15)
    f_big = _font(22, mono=True)
    for fi, i in enumerate(idxs):
        img = Image.new("RGB", (W, H), "#0d1117")
        d = ImageDraw.Draw(img)
        # 网格
        for gx in np.arange(0.05, 0.31, 0.05):
            d.line([(_sx(gx), MARGIN), (_sx(gx), H - MARGIN)], fill="#1e2740", width=1)
        for gy in np.arange(-0.10, 0.11, 0.05):
            d.line([(MARGIN, _sy(gy)), (W - MARGIN, _sy(gy))], fill="#1e2740", width=1)
        # 孔位 (红圈 + 十字)
        hx, hy = _sx(HOLE_POS[0]), _sy(HOLE_POS[1])
        d.ellipse([hx - 14, hy - 14, hx + 14, hy + 14], outline="#ff4444", width=3)
        d.line([hx - 6, hy, hx + 6, hy], fill="#ff4444", width=2)
        d.line([hx, hy - 6, hx, hy + 6], fill="#ff4444", width=2)
        # 轨迹线 (旧→新 渐亮)
        for j in range(2, i + 1):
            a = j / max(1, i)
            col = (int(40 + 120 * a), int(80 + 120 * a), 255)
            d.line([(_sx(xs[j - 1][0]), _sy(xs[j - 1][1])),
                    (_sx(xs[j][0]), _sy(xs[j][1]))], fill=col, width=2)
        # 末端夹爪
        ex, ey = _sx(xs[i][0]), _sy(xs[i][1])
        g = grippers[i]
        jaw_w = 26 - 16 * g
        contact = forces[i] > 0.05
        done = bool(tr["done"][i])
        body = "#ffd700" if done else ("#f0883e" if contact else "#58a6ff")
        d.rectangle([ex - jaw_w / 2, ey - 10, ex + jaw_w / 2, ey + 10],
                    fill=body, outline="#ffffff", width=2)
        if g < 0.5:   # 张开瓣
            d.line([ex - jaw_w / 2, ey - 10, ex - jaw_w / 2, ey + 10], fill="#8b949e", width=3)
            d.line([ex + jaw_w / 2, ey - 10, ex + jaw_w / 2, ey + 10], fill="#8b949e", width=3)
        # HUD
        stage = stages[i].replace("阶段 ", "")
        d.text((MARGIN, 16), f"t = {t_arr[i]:.2f}s", font=f_big, fill="#ffffff")
        d.text((MARGIN, 48), f"距离孔位 {dists[i]:.4f} m", font=f_hud, fill="#8b949e")
        d.text((MARGIN, 70), f"接触概率 {cps[i]:.2f} · 接触力 {forces[i]:.2f}", font=f_hud, fill="#8b949e")
        grip_txt = "闭合" if g > 0.85 else ("张开" if g < 0.3 else "夹紧中")
        d.text((MARGIN, 92), f"夹爪 {grip_txt} ({g:.0%})", font=f_hud, fill="#8b949e")
        st_col = {"接近": "#58a6ff", "抓取": "#f0883e", "插入": "#d29922",
                  "完成": "#3fb950", "否决": "#ff4444"}.get(stage.split()[0] if stage else "", "#8b949e")
        d.text((W - MARGIN - 200, 16), f"阶段: {stage}", font=f_big, fill=st_col)
        d.text((W // 2 - 110, H - 28), "状态空间仿真 · 光模块插拔", font=f_title, fill="#3a3f4b")
        fp = os.path.join(out_dir, f"frame_{fi:04d}.png")
        img.save(fp)
        frames.append(fp)
    return frames


def make_video(tr, out_mp4):
    """渲染帧 + ffmpeg 合成 → 返回 mp4 路径"""
    out_dir = os.path.dirname(os.path.abspath(out_mp4))
    os.makedirs(out_dir, exist_ok=True)
    tmp = os.path.join(out_dir, "_ss_frames")
    os.makedirs(tmp, exist_ok=True)
    for f in os.listdir(tmp):
        os.remove(os.path.join(tmp, f))
    frames = render_frames(tr, tmp)
    cmd = ["ffmpeg", "-y", "-framerate", str(FPS), "-i", os.path.join(tmp, "frame_%04d.png"),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", out_mp4]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr[-2000:] + "\n")
        raise RuntimeError(f"ffmpeg 失败 rc={r.returncode}")
    for f in frames:
        os.remove(f)
    os.rmdir(tmp)
    return out_mp4


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "reports",
        "state_space_sim.mp4")
    sim = StateSpaceSim()
    tr = sim.run()
    mp4 = make_video(tr, out)
    print(f"🎥 视频已生成: {mp4}")
    print(f"   仿真 {tr['t'][-1]:.2f}s · 插入{'完成' if tr['done'][-1] else '未完成'} · 帧数 {min(len(tr['x']), 300)}")
