# -*- coding: utf-8 -*-
"""
gen_state_space_video.py — 🎥 状态空间仿真操作视频 (2026-08-18 老倪)

把 state_space_sim 的完整轨迹渲染成 mp4:
  俯视图: 孔位(红圈) + 末端夹爪(张开/闭合) + 轨迹线 + 接触高亮 + 阶段/时间/距离 HUD
渲染: PyQt5 QPainter 逐帧画 QImage (零新依赖) → ffmpeg 合成 mp4 (25fps)

用法:
  python3 gen_state_space_video.py [输出.mp4]
"""
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# 🐛 QPainter 需要 QGuiApplication 实例 (无显示环境用 offscreen)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication
_QAPP = QApplication.instance() or QApplication([])
from state_space_sim import StateSpaceSim, HOLE_POS, D_CONTACT, D_INSERT

W, H = 960, 640          # 画布
FPS = 25
MARGIN = 70              # 边缘留白
# 世界坐标 → 画布: x∈[0.04,0.31] → [MARGIN, W-MARGIN]; y∈[-0.11,0.11] → [H-MARGIN, MARGIN]
X0_W, X1_W = 0.04, 0.31
Y0_W, Y1_W = -0.11, 0.11


def _sx(x): return MARGIN + (x - X0_W) / (X1_W - X0_W) * (W - 2 * MARGIN)
def _sy(y): return (H - MARGIN) - (y - Y0_W) / (Y1_W - Y0_W) * (H - 2 * MARGIN)


def _draw_text(p, img, text, x, y, size=16, color="#ffffff", bold=False):
    from PyQt5.QtGui import QFont, QColor
    f = QFont("DejaVu Sans", size)
    f.setBold(bold)
    p.setFont(f)
    p.setPen(QColor(color))
    p.drawText(int(x), int(y), text)


def render_frames(tr, out_dir):
    """渲染全部帧 → 返回帧文件列表 (PNG)"""
    from PyQt5.QtGui import QImage, QPainter, QColor, QPen, QBrush, QFont
    from PyQt5.QtCore import Qt, QPointF
    frames = []
    xs = np.asarray(tr["x"])          # (N,3)
    grippers = tr["gripper"]
    forces = tr["force"]
    stages = tr["stage"]
    t_arr = tr["t"]
    dists = tr["dist"]
    cps = tr["contact_p"]
    n = len(xs)
    # 采样: 最多 12s 视频 (25fps*12=300帧)
    n_out = min(n, FPS * 12)
    idxs = np.linspace(0, n - 1, n_out).astype(int)
    # 轨迹渐变: 旧→新 变亮
    for fi, i in enumerate(idxs):
        img = QImage(W, H, QImage.Format_RGB32)
        img.fill(QColor("#0d1117"))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        # 网格
        pen_g = QPen(QColor("#1e2740"), 1)
        for gx in np.arange(0.05, 0.31, 0.05):
            p.setPen(pen_g); p.drawLine(int(_sx(gx)), MARGIN, int(_sx(gx)), H - MARGIN)
        for gy in np.arange(-0.10, 0.11, 0.05):
            p.setPen(pen_g); p.drawLine(MARGIN, int(_sy(gy)), W - MARGIN, int(_sy(gy)))
        # 孔位 (红圈 + 十字)
        hx, hy = _sx(HOLE_POS[0]), _sy(HOLE_POS[1])
        p.setPen(QPen(QColor("#ff4444"), 3))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(hx, hy), 14, 14)
        p.drawLine(int(hx - 6), int(hy), int(hx + 6), int(hy))
        p.drawLine(int(hx), int(hy - 6), int(hx), int(hy + 6))
        # 轨迹线 (过去路径, 由暗到亮)
        for j in range(1, i + 1):
            if j < 2:
                continue
            a = j / max(1, i)
            col = QColor(88, 166, 255, int(40 + 180 * a))
            p.setPen(QPen(col, 2))
            p.drawLine(int(_sx(xs[j - 1][0])), int(_sy(xs[j - 1][1])),
                       int(_sx(xs[j][0])), int(_sy(xs[j][1])))
        # 末端夹爪 (矩形: 张开=宽, 闭合=窄; 接触=橙, 插入完成=绿)
        ex, ey = _sx(xs[i][0]), _sy(xs[i][1])
        g = grippers[i]
        jaw_w = 26 - 16 * g          # 张开 26px → 闭合 10px
        contact = forces[i] > 0.05
        done = bool(tr["done"][i])
        body = QColor("#ffd700") if done else (QColor("#f0883e") if contact else QColor("#58a6ff"))
        p.setBrush(QBrush(body))
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.drawRect(int(ex - jaw_w / 2), int(ey - 10), int(jaw_w), 20)
        # 夹爪瓣
        if g < 0.5:
            p.setPen(QPen(QColor("#8b949e"), 3))
            p.drawLine(int(ex - jaw_w / 2), int(ey - 10), int(ex - jaw_w / 2), int(ey + 10))
            p.drawLine(int(ex + jaw_w / 2), int(ey - 10), int(ex + jaw_w / 2), int(ey + 10))
        # HUD
        stage = stages[i].replace("阶段 ", "")
        _draw_text(p, img, f"t = {t_arr[i]:.2f}s", MARGIN, 34, 20, "#ffffff", True)
        _draw_text(p, img, f"距离孔位 {dists[i]:.4f} m", MARGIN, 60, 15, "#8b949e")
        _draw_text(p, img, f"接触概率 {cps[i]:.2f} · 接触力 {forces[i]:.2f}", MARGIN, 82, 15, "#8b949e")
        _draw_text(p, img, f"夹爪 {'闭合' if g > 0.85 else ('张开' if g < 0.3 else '夹紧中')} ({g:.0%})", MARGIN, 104, 15, "#8b949e")
        # 阶段徽标 (右上)
        st_col = {"接近": "#58a6ff", "抓取": "#f0883e", "插入": "#d29922",
                  "完成": "#3fb950", "否决": "#ff4444"}.get(stage.split()[0] if stage else "", "#8b949e")
        _draw_text(p, img, f"阶段: {stage}", W - MARGIN - 180, 34, 18, st_col, True)
        # 标题
        _draw_text(p, img, "🧮 状态空间仿真 · 光模块插拔", W // 2 - 120, H - 20, 13, "#3a3f4b")
        p.end()
        fp = os.path.join(out_dir, f"frame_{fi:04d}.png")
        img.save(fp)
        frames.append(fp)
    return frames


def make_video(tr, out_mp4):
    """渲染帧 + ffmpeg 合成 → 返回 mp4 路径"""
    out_dir = os.path.dirname(os.path.abspath(out_mp4))   # 输出目录 = mp4 所在目录
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
