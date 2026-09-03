#!/usr/bin/env python3
"""真实 YOLO 感知视频 — 六层控制器真闭环逐帧渲染 + detect_3d (2026-09-04 老倪: 要看真实感知效果)
每帧: metaworld render 原图 + YOLO 2D 框 (hand/peg/hole + conf) + det3d 3D 坐标 + 状态条
驱动: RealStateSpaceSim(vision=True) — 每帧真实渲染检测, 不节流不冻结不造假
用法: gui-venv311/bin/python tools/gen_real_yolo_video.py [seed] [max_steps]
输出: data/real_yolo_perception_<seed>.mp4
"""
import os, sys, subprocess, tempfile, argparse
import numpy as np

os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
sys.path.insert(0, os.path.join(ROOT, "src", "lerobot", "policies", "yolo_3d"))

CLR = {"hand": (0, 255, 0), "peg": (255, 200, 0), "hole": (255, 80, 255)}  # BGR 画布

def draw_frame(img_rgb, sim, step, st_snap):
    """原图 + YOLO 框 + 3D 值 + 状态条"""
    import cv2
    frame = np.ascontiguousarray(img_rgb)          # 480x480 RGB
    H, W = frame.shape[:2]
    vis = sim._vis
    boxes = vis.get("boxes")
    det3d = vis.get("det3d", {})
    res = getattr(sim._aligner, "_last_res", None)
    names = res.names if res is not None else {}
    if boxes is not None:
        for b in boxes.boxes:
            cls = names.get(int(b.cls), "?")
            conf = float(b.conf)
            x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
            # detect_3d 的框在 rot90(k=2) 帧 → 转回原图坐标 (180°: u' = W-u)
            x1, x2 = W - x2, W - x1
            y1, y2 = H - y2, H - y1
            col = CLR.get(cls, (255, 255, 255))
            cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), col, 2)
            d3 = det3d.get(cls)
            tag = f"{cls} {conf:.2f}"
            if d3 is not None:
                tag += f" [{d3[0]:.3f},{d3[1]:.3f},{d3[2]:.3f}]"
            cv2.putText(frame, tag, (int(x1), max(16, int(y1) - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, col, 1, cv2.LINE_AA)
    # 顶部状态条 (该帧快照, 非末态)
    bar = (f"step {step} | {st_snap['stage']} | grasped={int(st_snap['grasped'])} "
           f"grp={st_snap['gripper']:.2f}")
    cv2.putText(frame, bar, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1, cv2.LINE_AA)
    # 底部 3D 汇总 (控制用值: hand 编码器 / peg 视觉 / hole 视觉)
    hp = st_snap["x"]
    pp = vis.get("peg")
    hh = vis.get("hole")
    line = (f"hand(编码器) [{hp[0]:.3f},{hp[1]:.3f},{hp[2]:.3f}]  "
            f"peg(视觉) {('['+','.join(f'{v:.3f}' for v in pp)+']') if pp is not None else '未检出'}  "
            f"hole(视觉) {('['+','.join(f'{v:.3f}' for v in hh)+']') if hh is not None else '未检出'}")
    cv2.putText(frame, line, (6, H - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 220, 0), 1, cv2.LINE_AA)
    return frame

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("seed", type=int, nargs="?", default=100)
    ap.add_argument("max_steps", type=int, nargs="?", default=360)
    a = ap.parse_args()

    sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
    from state_space_sim_real import RealStateSpaceSim
    sim = RealStateSpaceSim(seed=a.seed, vision=True, vision_every=1)
    # 用 hook: 每步 _vis_refresh 已存 img/boxes → 在 run() 循环外逐帧取? 需要 run 内回调 —
    # 直接手动驱动 (复刻 run 主循环成本高) → 用 run() 后 _vis 只剩末帧.
    # 方案: monkey-patch _vis_refresh 收集每帧 → 但 img 检测后即弃. 改为 patch run 太侵入.
    # 折中: 继承 + 覆写 _vis_refresh 收集帧
    frames = []
    orig = sim._vis_refresh
    def collect():
        orig()
        frames.append((len(frames), sim._vis.get("img"), dict(sim._vis),
                       {"stage": sim.sched.stage(), "grasped": sim.grasped,
                        "gripper": sim.gripper, "x": sim.x.copy()}))
    sim._vis_refresh = collect
    tr = sim.run(max_steps=a.max_steps)
    print(f"完成: {tr['done'][-1]} · 帧数 {len(frames)}", flush=True)

    # 合成视频 (控时长: ≤400 帧 @ 8fps)
    import cv2
    tmpdir = tempfile.mkdtemp(prefix="ryolo_")
    sel = frames
    if len(sel) > 400:
        sel = frames[:: max(1, len(frames) // 400)]
    for i, (stp, img, vs, st_snap) in enumerate(sel):
        if img is None:
            continue
        sim._vis = vs                      # 恢复该帧 vis (含 boxes/det3d/peg/hole)
        fr = draw_frame(img, sim, stp, st_snap)
        cv2.imwrite(os.path.join(tmpdir, f"f{i:05d}.png"), fr)
        if i % 60 == 0:
            print(f"  帧 {i}/{len(sel)}", flush=True)
    out = os.path.join(ROOT, "data", f"real_yolo_perception_{a.seed}.mp4")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-framerate", "8", "-i",
                    os.path.join(tmpdir, "f%05d.png"), "-pix_fmt", "yuv420p", out],
                   check=True, capture_output=True)
    print(f"🎥 视频: {out}")
    import shutil; shutil.rmtree(tmpdir, ignore_errors=True)

if __name__ == "__main__":
    main()
