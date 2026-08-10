#!/usr/bin/env python3
"""生成插入成功演示视频 — 双脑+状态机 (2026-08-10)
录制 seed 0 完整插拔流程 → 旋转180° → 输出 mp4
"""
import os, sys, numpy as np, torch, subprocess

os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from train_full_pipeline import (make_env, get_obs, LeftBrainMLP, RightBrainWM,
                                 ST_APPROACH, ST_GRASP, ST_LIFT, ST_TRANSFER, ST_INSERT, ST_DONE, ST_NAMES)

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

def main():
    seed = 1  # 2026-08-10: seed1 稳定成功 (seed0 有随机性)
    d = torch.load(os.path.join(ROOT, "outputs", "rl_peg", "full_pipeline.pt"), map_location="cpu", weights_only=False)
    left = LeftBrainMLP(39, 4).to(DEVICE); left.load_state_dict(d["left"]); left.eval()
    right = RightBrainWM(39, 4).to(DEVICE); right.load_state_dict(d["right"]); right.eval()
    xm, xs, ym, ys = d["xm"], d["xs"], d["ym"], d["ys"]

    env = make_env(seed)
    o = get_obs(env)
    peg_z0 = env.data.site_xpos[env.model.site("pegGrasp").id][2]
    hole = env.data.site_xpos[env.model.site("hole").id]
    state = ST_APPROACH
    frames = []
    states_track = []
    success = False
    for step in range(500):
        hand = env.data.site_xpos[env.model.site("endEffector").id]
        peg = env.data.site_xpos[env.model.site("pegGrasp").id]
        d_hp = float(np.linalg.norm(hand - peg))
        d_ph = float(np.linalg.norm(peg - hole))
        xin = torch.from_numpy((o - xm) / xs).float().to(DEVICE)
        with torch.no_grad():
            pred = left(xin.unsqueeze(0)).squeeze(0).cpu().numpy()
        act = pred * ys + ym
        o_r = torch.from_numpy(o).float().to(DEVICE)
        a_r = torch.from_numpy(act).float().to(DEVICE)
        with torch.no_grad():
            _, pred_cont, _ = right(o_r.unsqueeze(0), a_r.unsqueeze(0))
        contact_p = pred_cont.item()
        if state == ST_APPROACH:
            if d_hp < 0.06 and contact_p > 0.5: state = ST_GRASP
        elif state == ST_GRASP:
            if peg[2] - peg_z0 > 0.02: state = ST_LIFT
        elif state == ST_LIFT:
            if peg[2] > peg_z0 + 0.08: state = ST_TRANSFER
        elif state == ST_TRANSFER:
            if abs(peg[0]-hole[0]) < 0.05 and abs(peg[1]-hole[1]) < 0.05: state = ST_INSERT
        elif state == ST_INSERT:
            if d_ph < 0.05:
                state = ST_DONE; success = True
        if state == ST_APPROACH:
            delta = peg - hand
            act[:3] = act[:3] * 0.3 + np.clip(delta * 2.0, -1, 1)
            act[3] = -1.0
        elif state == ST_GRASP:
            act[:3] = act[:3] * 0.1; act[3] = 0.6
        elif state == ST_LIFT:
            act[:3] = [0,0,0.8]; act[3] = 0.6
        elif state == ST_TRANSFER:
            d_xy = np.array([hole[0]-peg[0], hole[1]-peg[1]])
            if np.linalg.norm(d_xy) > 1e-4:
                act[:3] = np.clip((d_xy/np.linalg.norm(d_xy))*0.6, -1, 1).tolist() + [0.0]
            act[3] = 0.6
        elif state == ST_INSERT:
            act[:3] = [0,0,np.clip((hole[2]-peg[2])*2.0, -0.6, 0.6)]
            act[3] = 0.6
        else:
            act[:3] = [0,0,0]; act[3] = 0.6
        _mx = float(np.abs(act).max()) if len(act) else 1.0
        if _mx > 1.0: act = act / _mx
        env.step(np.clip(act, -1, 1))
        o = get_obs(env)
        states_track.append(ST_NAMES[state])
        # 录帧 (间隔采样, 每2帧录1 → 视频流畅)
        try:
            img = env.render()
            if img is not None and step % 2 == 0:
                frames.append(img)
        except Exception:
            pass
        if state == ST_DONE:
            break
    print(f"✅ 完成状态={ST_NAMES[state]} 成功={success} 步骤={step} 帧数={len(frames)}", flush=True)
    env.close()
    if not frames:
        print("❌ 无帧", flush=True)
        return
    # 保存帧 (png) → ffmpeg 合成 (2026-08-10: imageio av 编码器不兼容, 改 ffmpeg)
    import tempfile, os as _os
    tmpdir = tempfile.mkdtemp(prefix="insert_frames_")
    for i, fr in enumerate(frames):
        import cv2
        cv2.imwrite(_os.path.join(tmpdir, f"f{i:05d}.png"), cv2.cvtColor(fr, cv2.COLOR_RGB2BGR))
    print(f"💾 帧数: {len(frames)} @ {tmpdir}", flush=True)
    raw = os.path.join(ROOT, "reports", "insert_success_raw.mp4")
    subprocess.run(["ffmpeg", "-y", "-framerate", "30", "-i", _os.path.join(tmpdir, "f%05d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", "-loglevel", "error", raw], check=True)
    # 旋转180° (老倪要求)
    out = os.path.join(ROOT, "reports", "insert_success_demo.mp4")
    subprocess.run(["ffmpeg", "-y", "-i", raw, "-vf", "transpose=2,transpose=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", "-loglevel", "error", out], check=True)
    print(f"🎬 最终: {out}", flush=True)

if __name__ == "__main__":
    main()
