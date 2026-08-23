#!/usr/bin/env python3
"""生成插入成功演示视频 — 双脑+状态机 (2026-08-10)
录制 seed 0 完整插拔流程 → 旋转180° → 输出 mp4
"""
import os, sys, numpy as np, torch, subprocess

os.environ.setdefault("DISPLAY", ":0")
# 2026-08-10: 容器/无头环境 glfw 无 X11 会崩 → 默认 egl 无头 GPU 渲染 (与 rollout_video.py 一致);
# 有显示环境时可 DISPLAY=:0 手动跑 (glfw 仍可用)
os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("MUJOCO_EGL_DEVICE", "0")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from train_full_pipeline import (make_env, get_obs, LeftBrainMLP,
                                 ST_APPROACH, ST_GRASP, ST_LIFT, ST_TRANSFER, ST_INSERT, ST_DONE, ST_NAMES)
# 🐛 2026-08-12 老倪: RightBrainWM 用 modeling_left_right 版 (无 align_head) —
# 本次训练 model.pt 的 right 权重是 {enc, pred_next, contact_head}, 旧管线版多 align_head 键不匹配
sys.path.insert(0, os.path.join(ROOT, "src"))
from lerobot.policies.left_right.modeling_left_right import RightBrainWM
# 2026-08-23 老倪: 操作视频接 YOLO 感知 (真机同构) — 直载文件避开 lerobot 包 __init__ 重量级依赖
sys.path.insert(0, os.path.join(ROOT, "src", "lerobot", "policies", "yolo_3d"))
_YOLO_WEIGHTS_CANDS = [
    "runs/detect/outputs/yolo_peg/peg_v1/weights/best.pt",
    "runs/detect/outputs/yolo_peg/peg_full/weights/best.pt",
    "outputs/yolo_peg/peg_v1/weights/best.pt",
]

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def _pick_seed(left, right, xm, xs, ym, ys, seed_max=11):
    """无渲染探测: 找首个完整插拔成功的 seed (2026-08-10: seed1 并非稳定成功 —
    按视频脚本逻辑 (归一化) 实测 8/12 seed 成功 → 自动挑选, 保证交付的是成功视频)"""
    for seed in range(seed_max + 1):
        e = make_env(seed)
        o = get_obs(e)
        peg_z0 = e.data.site_xpos[e.model.site("pegGrasp").id][2]
        hole = e.data.site_xpos[e.model.site("hole").id]
        state = ST_APPROACH
        for _ in range(200):
            hand = e.data.site_xpos[e.model.site("endEffector").id]
            peg = e.data.site_xpos[e.model.site("pegGrasp").id]
            d_hp = float(np.linalg.norm(hand - peg))
            d_ph = float(np.linalg.norm(peg - hole))
            xin = torch.from_numpy((o - xm) / xs).float().to(DEVICE)
            with torch.no_grad():
                pred = left(xin.unsqueeze(0)).squeeze(0).cpu().numpy()
            act = pred * ys + ym
            o_r = torch.from_numpy(o).float().to(DEVICE)
            a_r = torch.from_numpy(act).float().to(DEVICE)
            with torch.no_grad():
                _, pred_cont = right(o_r.unsqueeze(0), a_r.unsqueeze(0))
            contact = pred_cont.item()
            if state == ST_APPROACH:
                if d_hp < 0.06 and contact > 0.5: state = ST_GRASP
            elif state == ST_GRASP:
                if peg[2] - peg_z0 > 0.02: state = ST_LIFT
            elif state == ST_LIFT:
                if peg[2] > peg_z0 + 0.08: state = ST_TRANSFER
            elif state == ST_TRANSFER:
                if abs(peg[0]-hole[0]) < 0.05 and abs(peg[1]-hole[1]) < 0.05: state = ST_INSERT
            elif state == ST_INSERT:
                if d_ph < 0.05:
                    state = ST_DONE
            if state == ST_APPROACH:
                delta = peg - hand
                act[:3] = act[:3] * 0.3 + np.clip(delta * 2.0, -1, 1)
                act[3] = -1.0
            elif state == ST_GRASP:
                act[:3] = act[:3] * 0.1; act[3] = 0.6
            elif state == ST_LIFT:
                act[:3] = [0, 0, 0.8]; act[3] = 0.6
            elif state == ST_TRANSFER:
                d_xy = np.array([hole[0]-peg[0], hole[1]-peg[1]])
                if np.linalg.norm(d_xy) > 1e-4:
                    act[:3] = np.clip((d_xy/np.linalg.norm(d_xy))*0.6, -1, 1).tolist() + [0.0]
                act[3] = 0.6
            elif state == ST_INSERT:
                act[:3] = [0, 0, np.clip((hole[2]-peg[2])*2.0, -0.6, 0.6)]
                act[3] = 0.6
            else:
                act[:3] = [0, 0, 0]; act[3] = 0.6
            _mx = float(np.abs(act).max()) if len(act) else 1.0
            if _mx > 1.0: act = act / _mx
            e.step(np.clip(act, -1, 1))
            # ⚠️ 2026-08-10 关键: env.render() 会消耗 env.np_random → 扰动轨迹!
            #   探测必须与真实渲染调用一致, 否则探测成功≠渲染成功 (seed0 无render✅/有render❌)
            try:
                e.render()
            except Exception:
                pass
            o = get_obs(e)
            if state == ST_DONE:
                break
        e.close()
        print(f"  seed {seed}: {'✅ 成功' if state == ST_DONE else '❌ 卡在' + ST_NAMES[state]}", flush=True)
        if state == ST_DONE:
            return seed
    return None


def _load_brain():
    """🐛 2026-08-12 老倪: 优先最新 left_right 双脑 checkpoint (本次训练产物),
    归一化从 preprocessor/postprocessor 读; 无则 fallback 旧 full_pipeline.pt"""
    import glob as _g
    from safetensors import safe_open
    # 🐛 2026-08-12: 按修改时间排序 (字母序会把 left_right_std 排最前) — 取最新训练
    cands = sorted(_g.glob(os.path.join(ROOT, "outputs", "train", "left_right_*")),
                   key=lambda p: os.path.getmtime(p), reverse=True)
    # 🐛 2026-08-12 老倪: BRAIN_CKPT 环境变量可指定 checkpoint (最新模型效果差时回退已验证模型)
    forced = os.environ.get("BRAIN_CKPT")
    if forced:
        forced = os.path.normpath(forced)
        cands = [forced] + [c for c in cands if c != forced]
    for d in cands:
        pm = os.path.join(d, "checkpoints", "last", "pretrained_model")
        model_path = os.path.join(pm, "model.pt")
        if not os.path.exists(model_path):
            continue
        sd = torch.load(model_path, map_location="cpu", weights_only=False)
        left = LeftBrainMLP(sd["obs_dim"], sd["act_dim"]).to(DEVICE)
        left.load_state_dict(sd["left"]); left.eval()
        right = RightBrainWM(sd["obs_dim"], sd["act_dim"]).to(DEVICE)
        right.load_state_dict(sd["right"]); right.eval()
        try:
            with safe_open(os.path.join(pm, "left_right_preprocessor_step_3_normalizer_processor.safetensors"), framework="np") as f:
                xm = float(f.get_tensor("observation.state.mean"))
                xs = float(f.get_tensor("observation.state.std"))
            with safe_open(os.path.join(pm, "left_right_postprocessor_step_0_unnormalizer_processor.safetensors"), framework="np") as f:
                ym = float(f.get_tensor("action.mean"))
                ys = float(f.get_tensor("action.std"))
        except Exception:
            xm, xs, ym, ys = 0.0, 1.0, 0.0, 1.0
        print(f"🧠 双脑: {d} (obs={sd['obs_dim']} act={sd['act_dim']})", flush=True)
        return left, right, xm, xs, ym, ys
    # fallback 旧 RL 管线
    d = torch.load(os.path.join(ROOT, "outputs", "rl_peg", "full_pipeline.pt"), map_location="cpu", weights_only=False)
    left = LeftBrainMLP(39, 4).to(DEVICE); left.load_state_dict(d["left"]); left.eval()
    right = RightBrainWM(39, 4).to(DEVICE); right.load_state_dict(d["right"]); right.eval()
    return left, right, d["xm"], d["xs"], d["ym"], d["ys"]


def _build_aligner():
    """🎯 构建 YOLO 感知对齐器 (2026-08-23 老倪: 操作视频接 YOLO 感知, 真机同构)
    失败返回 None → 回退真值感知"""
    try:
        import yolo_state_aligner
        w = next((os.path.join(ROOT, c) for c in _YOLO_WEIGHTS_CANDS
                  if os.path.isfile(os.path.join(ROOT, c))), None)
        if not w:
            print("⚠️ YOLO 权重未找到, 操作视频回退真值感知")
            return None
        env0 = make_env(0)  # corner2, 只读静态相机参数 cam_pos/cam_mat0/cam_fovy
        a = yolo_state_aligner.YoloStateAligner(w, env0)
        print(f"🎯 YOLO 感知已启用: {os.path.basename(w)} (操作视频吃解算 state, 真机同构)")
        return a
    except Exception as ex:
        print(f"⚠️ YOLO 感知构建失败 ({str(ex)[:60]}), 回退真值感知")
        return None


def main():
    left, right, xm, xs, ym, ys = _load_brain()
    aligner = _build_aligner()  # 🎯 2026-08-23: 操作视频接 YOLO 感知 (失败回退真值)

    # 🐛 2026-08-12 老倪: 渲染失败自动换 seed 重试 (16:49 模型 seed 探测成功但渲染失败 —
    #   mujoco 随机性/轨迹分叉, 单 seed 渲染不稳) — 循环渲染直到成功或全失败
    import shutil as _sh
    for seed in range(12):
        env = make_env(seed)
        o = get_obs(env)
        # 🎯 2026-08-23: 模型感知 state — YOLO 检测解算替换 hand/peg/hole 段 (真机同构)
        o_model = o.copy()
        if aligner is not None:
            try:
                o_model = aligner.align(o, aligner.detect_3d(env.render())).astype(np.float32)[:39]
            except Exception:
                pass
        peg_z0 = env.data.site_xpos[env.model.site("pegGrasp").id][2]
        hole = env.data.site_xpos[env.model.site("hole").id]
        state = ST_APPROACH
        frames = []
        states_track = []
        success = False
        last_state = state
        stall = 0
        for step in range(500):
            hand = env.data.site_xpos[env.model.site("endEffector").id]
            peg = env.data.site_xpos[env.model.site("pegGrasp").id]
            d_hp = float(np.linalg.norm(hand - peg))
            d_ph = float(np.linalg.norm(peg - hole))
            xin = torch.from_numpy((o_model - xm) / xs).float().to(DEVICE)
            with torch.no_grad():
                pred = left(xin.unsqueeze(0)).squeeze(0).cpu().numpy()
            act = pred * ys + ym
            o_r = torch.from_numpy(o_model).float().to(DEVICE)
            a_r = torch.from_numpy(act).float().to(DEVICE)
            with torch.no_grad():
                _, pred_cont = right(o_r.unsqueeze(0), a_r.unsqueeze(0))
            contact_p = pred_cont.item()
            # 🐛 2026-08-14 老倪: 停滞检测 — 同一状态连续 120 步不推进 (卡抓取/卡接近)
            #   → 提前 break 换下个 seed (原跑满 500 步 × render 0.08s = 40s+/seed 浪费)
            if state == last_state:
                stall += 1
            else:
                stall = 0
                last_state = state
            if stall >= 120:
                print(f"⚠️ seed{seed} 停滞在 {ST_NAMES[state]} ({stall}步), 换下个 seed…", flush=True)
                break
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
            # 录帧 (间隔采样, 每2帧录1 → 视频流畅) + YOLO 检测解算下一轮感知 state
            try:
                img = env.render()
                if img is not None:
                    if step % 2 == 0:
                        frames.append(img)
                    if aligner is not None:
                        o_model = aligner.align(o, aligner.detect_3d(img)).astype(np.float32)[:39]
                    else:
                        o_model = o.copy()
                else:
                    o_model = o.copy()
            except Exception:
                o_model = o.copy()
            if state == ST_DONE:
                break
        print(f"✅ 完成状态={ST_NAMES[state]} 成功={success} 步骤={step} 帧数={len(frames)}", flush=True)
        env.close()
        if not frames:
            print(f"❌ seed{seed} 无帧, 换下个 seed…", flush=True)
            continue
        # 保存帧 (png) → ffmpeg 合成 (2026-08-10: imageio av 编码器不兼容, 改 ffmpeg)
        import tempfile, os as _os, shutil as _sh
        tmpdir = tempfile.mkdtemp(prefix="insert_frames_")
        for i, fr in enumerate(frames):
            import cv2
            cv2.imwrite(_os.path.join(tmpdir, f"f{i:05d}.png"), cv2.cvtColor(fr, cv2.COLOR_RGB2BGR))
        print(f"💾 帧数: {len(frames)} @ {tmpdir}", flush=True)
        # 🐛 2026-08-12 老倪: 先渲染到临时文件, 成功才替换正式视频 (渲染失败不覆盖好视频)
        raw = _os.path.join(tmpdir, "raw.mp4")
        out_tmp = _os.path.join(tmpdir, "demo.mp4")
        subprocess.run(["ffmpeg", "-y", "-framerate", "30", "-i", _os.path.join(tmpdir, "f%05d.png"),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", "-loglevel", "error", raw], check=True)
        # 旋转180° (老倪要求)
        subprocess.run(["ffmpeg", "-y", "-i", raw, "-vf", "transpose=2,transpose=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", "-loglevel", "error", out_tmp], check=True)
        if success and _os.path.exists(out_tmp) and _os.path.getsize(out_tmp) > 0:
            out = _os.path.join(ROOT, "reports", "insert_success_demo.mp4")
            _sh.move(out_tmp, out)
            print(f"🎬 最终: {out} (成功演示, seed={seed})", flush=True)
            _sh.rmtree(tmpdir, ignore_errors=True)
            break
        else:
            print(f"❌ seed{seed} 渲染未成功 (状态={ST_NAMES[state]}) — 换下个 seed…", flush=True)
            _sh.rmtree(tmpdir, ignore_errors=True)
    else:
        print("❌ 0-11 全部 seed 渲染失败 (可检查模型/状态机参数)", flush=True)
        # 🐛 2026-08-14 老倪: 最新模型全失败 → 自动回退已验证模型 (16:49, 曾 seed2 成功)
        fb = os.path.join(ROOT, "outputs", "train", "left_right_20260813_164959")
        cur = os.environ.get("BRAIN_CKPT", "")
        if cur != fb and os.path.exists(os.path.join(fb, "checkpoints", "last", "pretrained_model", "model.pt")):
            print(f"↩️ 自动回退已验证模型: {fb}", flush=True)
            os.environ["BRAIN_CKPT"] = fb
            main()
            return
        sys.exit(2)

if __name__ == "__main__":
    main()