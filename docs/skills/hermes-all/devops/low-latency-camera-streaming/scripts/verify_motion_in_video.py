#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证「视频里是否真的拍到了这次动作」—— 方向性光流版。

为什么不用相邻帧差：静止画面的传感器噪声就能让各动作窗口的帧差峰值都"看起来像在动"，
实测每个窗口都被判成"有位移"，而画面里根本没有目标。**必须比对方向。**

判据：把动作时间轴按每步切开，算每段首尾帧的中位光流向量：
  - 命令为 竖直类(抬升/下降) → 应给竖直主向，且两方向符号相反；
  - 命令为 水平类(向左/向右) → 应给水平主向，且两方向符号相反；
  - 幅值必须显著高于噪声底：静止画面 ≈ 0.0x px；真有位移是 3~5px 量级。

用法:
  python3 verify_motion_in_video.py <video.mp4> <timeline.txt> [--fps-hint 15]
时间轴格式（每行一次动作，空白分隔）: <起始epoch秒> <结束epoch秒> <步骤标签>
  标签含 抬升/上升/升/up 或 下降/降/down  → 视为竖直
  标签含 向右/右/right 或 向左/左/left    → 视为水平
  脚本会打印每步的 (dx,dy)/幅值/与命令是否一致，并给出总判定。
"""
import sys
import cv2
import numpy as np

VERT_KW = ("抬升", "上升", "升", "up")
DOWN_KW = ("下降", "降", "down")
RIGHT_KW = ("向右", "右", "right")
LEFT_KW = ("向左", "左", "left")
NOISE_FLOOR = 0.5  # px: 中位光流低于此值即视为"画面里没东西在动"


def classify(label):
    """返回 (期望轴, 期望正负号) —— 'v'=竖直 'h'=水平, 符号 +1/-1, 0=不确定"""
    low = label.lower()
    if any(k in label for k in VERT_KW) or "up" in low:
        return "v", -1  # 图像 y 轴向下为正 → 向上 = dy 负
    if any(k in label for k in DOWN_KW) or "down" in low:
        return "v", +1
    if any(k in label for k in RIGHT_KW) or "right" in low:
        return "h", +1
    if any(k in label for k in LEFT_KW) or "left" in low:
        return "h", -1
    return "?", 0


def load_timeline(path):
    tl = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            p = ln.split()
            if len(p) >= 3 and p[0][:1].isdigit():
                try:
                    tl.append((float(p[0]), float(p[1]), p[2]))
                except ValueError:
                    continue
    return tl


def step_flow(gray, ia, ib):
    """首尾帧中位光流 (dx, dy, mag)"""
    if ib - ia < 2:
        return None
    f0, f1 = gray[ia], gray[min(len(gray) - 1, ib - 1)]
    pts = cv2.goodFeaturesToTrack(f0, 120, 0.01, 8)
    if pts is None or len(pts) <= 5:
        return None
    p1, st, _ = cv2.calcOpticalFlowPyrLK(f0, f1, pts, None)
    if p1 is None:
        return None
    good = st.reshape(-1) == 1
    d = p1.reshape(-1, 2)[good] - pts.reshape(-1, 2)[good]
    if not len(d):
        return None
    dx, dy = float(np.median(d[:, 0])), float(np.median(d[:, 1]))
    return dx, dy, float(np.median(np.hypot(d[:, 0], d[:, 1])))


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    vpath, tpath = sys.argv[1], sys.argv[2]
    fps_hint = 15.0
    if "--fps-hint" in sys.argv:
        fps_hint = float(sys.argv[sys.argv.index("--fps-hint") + 1])

    tl = load_timeline(tpath)
    if not tl:
        print("时间轴为空或格式不符（需 '<起> <止> <标签>'）")
        return 1

    cap = cv2.VideoCapture(vpath)
    fps = cap.get(cv2.CAP_PROP_FPS) or fps_hint
    frames = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        frames.append(cv2.resize(fr, (320, 240)))
    cap.release()
    if len(frames) < 4:
        print("视频帧太少: %d" % len(frames))
        return 1

    gray = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
    # 录制起点 = 第一次动作前 8s（按需调整；这里沿用现场约定）
    TL0 = tl[0][0] - 8.0
    print("%s: %d 帧 · %.2f fps · 时长 %.1fs" % (vpath, len(frames), fps, len(frames) / fps))
    print("  %-8s %-6s %-16s %-8s %s" % ("步骤", "期望", "中位光流(dx,dy)", "幅值px", "判定"))

    n_ok = n_tested = 0
    for a, b, lab in tl:
        ia = max(0, min(len(frames) - 1, int((a - TL0) * fps)))
        ib = max(1, min(len(frames), int((b - TL0) * fps)))
        r = step_flow(gray, ia, ib)
        want_ax, want_sg = classify(lab)
        if r is None:
            print("  %-8s %-6s (无足够特征点)" % (lab, want_ax))
            continue
        dx, dy, mag = r
        n_tested += 1
        if want_ax == "?":
            verdict = "(命令方向未知, 只看幅值)"
            ok = mag > NOISE_FLOOR
        else:
            got_ax = "v" if abs(dy) > abs(dx) * 1.3 else ("h" if abs(dx) > abs(dy) * 1.3 else "?")
            got_sg = 1 if (dy if got_ax == "v" else dx) > 0 else -1
            ok = (got_ax == want_ax and got_sg == want_sg and mag > NOISE_FLOOR)
            verdict = "✅ 方向+符号一致" if ok else "✗ 不符或幅值过小"
        n_ok += 1 if ok else 0
        print("  %-8s %-6s (%+6.2f,%+6.2f) %-8.2f %s" % (lab, want_ax, dx, dy, mag, verdict))

    print()
    if not n_tested:
        print("总判定: 无法测（特征点不足）")
        return 1
    if n_ok == n_tested:
        print("总判定: ✅ 视频确实拍到了该动作（%d/%d 步方向匹配）" % (n_ok, n_tested))
        return 0
    if n_ok == 0:
        print("总判定: ✗ 画面里没有该动作 ⇒ **相机没对准目标**（不是位移太小）")
        return 1
    print("总判定: ⚠️ 部分匹配 %d/%d ⇒ 目标可能只在部分行程内可见（被遮挡/出画）" % (n_ok, n_tested))
    return 1


if __name__ == "__main__":
    sys.exit(main())
