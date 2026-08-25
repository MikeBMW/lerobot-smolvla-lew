#!/usr/bin/env python3
"""🎯 状态空间六层源码 直接驱动 metaworld — 同源 episode 生成器 (2026-08-25 老倪)

老倪反馈: 「3D 状态空间的视角和操作视频的内容、角度、轨迹都不一样」
根因: 操作视频 = metaworld MuJoCo + 双脑策略的真实 episode; 3D 视图 = 状态空间那套
      纯 numpy 引擎自己的轨迹 → 两套物理两套控制器, 轨迹不可能一致。
本脚本 = 唯一真解: 让状态空间六层真实源码 (perception/parallel/dynamics/cognition/
safety/execution) 直接算 action 去 step metaworld, obs 全部来自 env 真实状态,
接触力用 MuJoCo 真实接触力 (mj_contactForce, 不是估算代理)。一次运行同时产出:
  · trace npz  — 每步真实 hand/peg/销头/孔位 + 八阶段 + 全部处理层向量 (3D 视图数据源)
  · mp4 视频   — 同一条 episode 的 corner2 相机画面 (操作视频)
  · 相机外参   — corner2 的 pos/forward/right/up (3D 视图相机精确对齐, 含 roll)
→ 3D 视图与操作视频 同一条轨迹 · 同一套动作 · 同一个视角。

用法:
  MUJOCO_GL=egl gui-venv311/bin/python tools/gen_ss_metaworld_episode.py [--seed 0] [--no-video]
输出:
  reports/ss_episode_latest.npz / .mp4  (+ 带时间戳副本)
"""
import argparse
import os
import sys
import time

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("MUJOCO_EGL_DEVICE", "0")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

import numpy as np  # noqa: E402
import mujoco  # noqa: E402

from train_full_pipeline import make_env, get_obs  # noqa: E402
from state_space_sim import StateSpaceSim  # noqa: E402

A_LIMIT = 0.6        # 安全限幅上限 (m/s)
F_REF = 25.0         # 接触力归一化参考 (N)
# ⚠️ 2026-08-25 实测: metaworld 一步 = 12.5ms, 默认 max_path_length=500 → 只有 6.25s,
#   而状态空间六层 (慢通道主导 w_ff=0.3, Kp=1.2) 走完整插拔需要 ~20s → 必须放长 episode,
#   否则永远卡在「下降」。放长 = 只改 episode 长度, 不动控制器增益 (不作弊)。
MAX_STEPS = 2600
RENDER_EVERY = 4     # 录帧间隔 (2600/4 = 650 帧 ≈ 26s @25fps)
# 阶段子目标高度。⚠️ 2026-08-25 实测: metaworld 的 endEffector site 在两指之间但指尖
#   还往下伸 ~2cm → 手要停在 pegGrasp **上方 0.022m** 两指才正好夹住插销 (train_full_pipeline
#   的 grasp_target() 同样是 pegGrasp+2cm); 再往下压只会把插销压到台面 (接触力饱和 25N)。
H_APPROACH, H_ALIGN, H_GRASP_POSE, H_LIFT = 0.10, 0.055, 0.022, 0.16
# 夹持建立阈值: 实测夹住 0.03m 插销时闭合度饱和 0.70 (夹爪合不到底) → 0.60
GRASP_TH = 0.60


def quat2mat(q):
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ])


def camera_frame(m, name="corner2"):
    """corner2 相机世界位姿 → (pos, forward, right, up) — 视频里做了 np.rot90(k=2),
    等价于 right/up 同时取反 (画面 180° 旋转), 这里直接返回旋转后的等效基底。"""
    cid = m.camera(name).id
    pos = np.array(m.cam_pos[cid], dtype=float)
    R = quat2mat(np.array(m.cam_quat[cid], dtype=float))
    fwd = -R[:, 2]
    up = R[:, 1]
    right = R[:, 0]
    return pos, fwd, -right, -up          # rot180 等效基底


def contact_forces(m, d, peg_ids, hand_ids, table_ids=frozenset()):
    """MuJoCo 真实接触力 (mj_contactForce) 分两路返回 (f_env, f_grasp)。

    ⚠️ 2026-08-25 实测教训: 原来把"涉及 peg 或 夹爪的全部接触力"加成一个数 →
    夹爪夹住插销后夹持力持续 25N 以上, force_norm 饱和 1.0 ⇒ 抬起/转移/插入 三段
    接触概率恒 1.00、残差恒 1.0001, 「接触」信号彻底失去区分度 (调度器收到的是常量)。
    正确语义:
      f_grasp = peg ↔ 夹爪   (夹持力 — 判"夹住了没有")
      f_env   = peg/夹爪 ↔ 环境(桌面/带孔盒等)  (环境接触力 — 判"碰到孔沿/插进去了")
    进 obs 触觉 + 残差的是 f_env; f_grasp 单独作为夹持证据。
    """
    f_env = 0.0
    f_grasp = 0.0
    f6 = np.zeros(6, dtype=float)
    watched = peg_ids | hand_ids
    for i in range(d.ncon):
        c = d.contact[i]
        b1 = int(m.geom_bodyid[c.geom1])
        b2 = int(m.geom_bodyid[c.geom2])
        if b1 not in watched and b2 not in watched:
            continue
        mujoco.mj_contactForce(m, d, i, f6)
        mag = float(np.linalg.norm(f6[:3]))
        pair = {b1, b2}
        if pair & peg_ids and pair & hand_ids:
            f_grasp += mag          # 夹持: peg ↔ 夹爪(指垫)
        elif pair <= hand_ids:
            continue                # 夹爪各连杆自碰撞 — 既不是夹持也不是环境
        elif pair & peg_ids and pair & table_ids:
            # ⚠️ 2026-08-25 实测: 插销静置在台面上的自重支撑力 ≈1N 被算成"环境接触" →
            #   自由移动段环境接触恒 0.039 常量底噪, 把真实接触事件(顶孔沿)埋掉。
            #   自重支撑不是操作接触 → 排除。
            continue
        else:
            f_env += mag            # 环境: peg/夹爪 ↔ 带孔盒(孔沿) / 夹爪 ↔ 台面
    return f_env, f_grasp


def site(m, d, name):
    return np.array(d.site_xpos[m.site(name).id], dtype=float)


def run_episode(seed=0, want_video=True, log=print):
    env = make_env(seed)
    m, d = env.model, env.data
    ss = StateSpaceSim(log=lambda *a: None)      # 复用六层真实源码 + 八阶段调度器
    #   (估计器增益 K=0.2 由 StateSpaceSim 内部设定 — 观测噪声 5mm 下 K=0.5 会抖 7.4 倍)
    # 八阶段调度器: 夹持阈值按 metaworld 实测标定 (夹住实物后开度不可能到 0)
    sched = ss.cognition.ActionModulator(grasp_th=GRASP_TH)
    ss.sched = sched

    o = get_obs(env)
    hand = o[0:3].astype(float)
    peg = site(m, d, "pegGrasp")
    peg_head = site(m, d, "pegHead")
    hole_mouth = site(m, d, "hole")
    goal = site(m, d, "goal")
    peg_z0 = float(peg[2])
    peg_body = {int(m.body("peg").id)}
    # ⚠️ 2026-08-25 实测 (tools/probe_contacts.py): 真正夹住插销的是**指垫** rightpad/leftpad,
    #   只列 hand/rightclaw/leftclaw 会把夹持力误判成"环境接触" → f_env 饱和 1.0,
    #   抬起/转移/插入 接触概率恒 1.00 失去区分度。夹爪 body 必须列全 (含 pad/wrist)。
    hand_bodies = {int(m.body(n).id) for n in
                   ("hand", "rightclaw", "leftclaw", "rightpad", "leftpad",
                    "right_hand", "right_wrist")
                   if _has_body(m, n)}
    table_bodies = {int(m.body(n).id) for n in ("tablelink", "table")
                    if _has_body(m, n)}

    ctrl_dt = float(m.opt.timestep) * int(env.frame_skip)
    # action[:3] 单位 = action_scale(0.01m)/步; u 是速度指令(m/s) → 精确换算 u*ctrl_dt/scale
    a_gain = ctrl_dt / float(env.action_scale)
    env.max_path_length = MAX_STEPS + 10          # 放长 episode (默认 500 步会截断)
    log(f"🧮 状态空间六层 → metaworld peg-insert-side-v3 (seed={seed}) "
        f"控制步长 {ctrl_dt * 1000:.1f}ms  动作缩放 {env.action_scale}  "
        f"速度→动作增益 {a_gain:.3f}  episode 上限 {MAX_STEPS} 步 ({MAX_STEPS * ctrl_dt:.1f}s)")

    latent = np.concatenate([hand, [0.0]])
    u_prev = np.zeros(4)      # 上一步实际下发的控制量 (卡尔曼预测输入, 不能用 u_ff)
    res_ema = None            # 残差 EMA (反馈前滤波, 去掉观测噪声)
    prev18 = None
    tr = {k: [] for k in ("t", "x", "peg", "peg_head", "gripper", "stage", "done",
                          "dist", "u_ff", "u_sat", "residual", "contact_p", "force",
                          "force_grasp", "target", "grasped", "obs",
                          "u_ff_vec", "u_fb_vec", "u_fuse_vec", "u_limit_vec", "u_exec_vec",
                          "latent_vec", "corrected_vec", "residual_vec", "z_k_vec", "v_vec",
                          "prior_vec")}
    frames = []
    v_est = np.zeros(3)
    grasped = False
    success = False

    for step in range(MAX_STEPS):
        # ── 真实状态 (全部来自 env, 不是仿真编造) ──
        hand_new = o[0:3].astype(float)
        v_est = (hand_new - hand) / ctrl_dt if step else np.zeros(3)
        hand = hand_new
        peg = site(m, d, "pegGrasp")
        peg_head = site(m, d, "pegHead")
        grip_open = float(o[3])                    # 1=张开
        gripper = float(np.clip(1.0 - grip_open, 0.0, 1.0))   # 本工程约定: 1=闭合
        f_env, f_grasp = contact_forces(m, d, peg_body, hand_bodies, table_bodies)
        force_norm = float(np.clip(f_env / F_REF, 0.0, 1.0))          # 环境接触 → 感知/残差
        grasp_norm = float(np.clip(f_grasp / F_REF, 0.0, 1.0))        # 夹持力 (单独一路)
        force6 = np.zeros(6)
        force6[2] = f_env

        # ── 阶段子目标 (八阶段) ──
        st = sched.stage()
        head_off = peg_head - hand
        if st == "接近":
            target = peg + np.array([0, 0, H_APPROACH])
        elif st == "对位":
            target = peg + np.array([0, 0, H_ALIGN])
        elif st == "下降":
            target = peg + np.array([0, 0, H_GRASP_POSE])      # 下到抓握位姿 (两指夹住插销)
        elif st == "抓取":
            target = peg + np.array([0, 0, H_GRASP_POSE])      # 原位保持, 只闭夹爪
        elif st == "抬起":
            target = np.array([peg[0], peg[1], peg_z0 + H_LIFT])
        elif st == "转移":
            target = hole_mouth - head_off + np.array([0, 0, 0.03])
        else:
            target = goal - head_off

        # ── 感知: 43D obs (39D 视觉[含当前阶段目标] + 4D 触觉) ──
        cur18 = np.concatenate([hand, [gripper], v_est, peg, goal, np.zeros(3), np.zeros(2)])
        prev = prev18 if prev18 is not None else cur18
        visual39 = np.concatenate([cur18, prev, target])
        tactile4 = np.array([gripper, 1.0 if force_norm > 0.05 else 0.0, 0.0, 0.0])
        obs43 = ss.perception.fuse_sensors(visual39, force6, tactile4)
        prev18 = cur18

        # ── 六层链路 (与状态空间画布完全一致) ──
        u_ff = ss.accel.forward(obs43)
        # 🐛 2026-08-25: 卡尔曼预测输入 = 上一步**真正下发**的控制量 (原来错用 u_ff 前馈建议,
        #   两者模长差 3.12 倍 → 预测拿没执行的动作外推, 白送预测误差)
        act4 = np.concatenate([u_prev[:3], [0.0]])
        latent_pred = ss.est.predict(latent, act4)
        prior = ss.dyn.predict(latent, act4)
        z_k = np.concatenate([ss.world.observe(hand), [force_norm]])
        corrected, residual = ss.cognition.state_correction(prior, z_k, K=0.5)
        residual = np.asarray(residual, dtype=float).copy()
        residual[3] = force_norm
        r_scalar = float(np.linalg.norm(residual))
        contact_p = float(ss.cognition.contact_probability(r_scalar, gain=8.0))
        latent = ss.est.update(latent_pred, corrected)
        # 🌫 反馈用滤波后的残差 (瞬时残差 96% 是 5mm 观测噪声, 直接反馈=注入噪声)
        res_ema = (0.85 * res_ema + 0.15 * residual) if res_ema is not None else residual.copy()
        u_fb = np.concatenate([np.clip(0.5 * res_ema[:3], -0.5, 0.5), [0.0]])
        u, stage_txt = sched.decide(u_ff, u_fb, contact_p, r_scalar)
        if np.ndim(u) == 0:
            u = np.zeros(4)
        u = np.asarray(u, dtype=float).copy()
        u[3] = sched.gripper_cmd(u_ff[3])
        u_sat = np.asarray(ss.safety.saturate(u, limit=A_LIMIT), dtype=float).copy()
        u_sat[3] = u[3]
        u_exec = np.asarray(ss.execr.execute(u_sat), dtype=float)
        if u_exec.ndim == 0:
            u_exec = np.zeros(4)
        u_prev = u_exec.copy()          # 供下一步卡尔曼预测使用

        # ── 动作 → metaworld: 速度指令(m/s) × 控制步长 ÷ 动作缩放(0.01m) = 无量纲 action ──
        action = np.zeros(4)
        action[:3] = np.clip(u_exec[:3] * a_gain, -1.0, 1.0)
        action[3] = 1.0 if u_exec[3] > 0.5 else -1.0
        env.step(action)
        o = get_obs(env)

        # ── 真实证据 → 八阶段推进 ──
        peg_now = site(m, d, "pegGrasp")
        head_now = site(m, d, "pegHead")
        d_xy = float(np.linalg.norm(hand[:2] - peg_now[:2]))
        dist_h = float(np.linalg.norm(head_now[:2] - hole_mouth[:2]))
        depth = float(np.linalg.norm(head_now - goal))
        lifted = float(peg_now[2] - peg_z0)
        grasped = grasped or (gripper > 0.5 and lifted > 0.01)
        # 几何证据: 已下到抓握位姿 (水平对准 + 高度到位) → 可以闭爪
        at_pose = bool(d_xy < 0.025
                       and abs(hand[2] - (peg_now[2] + H_GRASP_POSE)) < 0.008) or grasp_norm > 0.02
        sched.advance(contact_p=contact_p, dist_h=dist_h, gripper=gripper,
                      depth=depth, d_xy=d_xy, lifted=lifted, at_grasp_pose=at_pose)
        done = sched.stage() == "完成"
        success = success or done

        # ── 记录 (3D 视图数据源) ──
        tr["t"].append(round(step * ctrl_dt, 4))
        tr["x"].append(hand.copy())
        tr["peg"].append(peg_now.copy())
        tr["peg_head"].append(head_now.copy())
        tr["gripper"].append(gripper)
        tr["stage"].append(stage_txt if sched.stage() in stage_txt else f"阶段 {sched.stage()}")
        tr["done"].append(done)
        tr["dist"].append(dist_h if grasped else d_xy)
        tr["u_ff"].append(float(np.linalg.norm(u_ff[:3])))
        tr["u_sat"].append(float(np.linalg.norm(u_exec[:3])))
        tr["residual"].append(r_scalar)
        tr["contact_p"].append(contact_p)
        tr["force"].append(force_norm)
        tr["force_grasp"].append(grasp_norm)
        tr["target"].append(np.asarray(target, dtype=float).copy())
        tr["grasped"].append(bool(grasped))
        tr["obs"].append(obs43.copy())
        tr["u_ff_vec"].append(np.asarray(u_ff, dtype=float).copy())
        tr["u_fb_vec"].append(np.asarray(u_fb, dtype=float).copy())
        tr["u_fuse_vec"].append(np.asarray(u, dtype=float).copy())
        tr["u_limit_vec"].append(u_sat.copy())
        tr["u_exec_vec"].append(u_exec.copy())
        tr["prior_vec"].append(np.asarray(prior, dtype=float).copy())
        tr["latent_vec"].append(np.asarray(latent, dtype=float).copy())
        tr["corrected_vec"].append(np.asarray(corrected, dtype=float).copy())
        tr["residual_vec"].append(residual.copy())
        tr["z_k_vec"].append(np.asarray(z_k, dtype=float).copy())
        tr["v_vec"].append(v_est.copy())

        if want_video and step % RENDER_EVERY == 0:
            img = env.render()
            if img is not None:
                frames.append(np.rot90(np.asarray(img), k=2))   # 与操作视频同一朝向
        if done:
            break

    cam_pos, cam_fwd, cam_right, cam_up = camera_frame(m, "corner2")
    meta = dict(seed=seed, ctrl_dt=ctrl_dt, success=bool(success),
                stage_final=sched.stage(), steps=len(tr["t"]),
                cam_pos=cam_pos, cam_fwd=cam_fwd, cam_right=cam_right, cam_up=cam_up,
                cam_fovy=float(m.cam_fovy[m.camera("corner2").id]),
                peg0=site(m, d, "pegGrasp") * 0 + np.asarray(tr["peg"][0]),
                hole_mouth=hole_mouth, goal=goal,
                box_center=np.array(d.xpos[m.body("box").id], dtype=float),
                table_center=np.array(d.xpos[m.body("tablelink").id], dtype=float),
                peg_head_off=np.asarray(tr["peg_head"][0]) - np.asarray(tr["peg"][0]),
                history=[f"{s}: {r}" for s, r in sched.history])
    env.close()
    return tr, meta, frames


def _has_body(m, name):
    try:
        m.body(name)
        return True
    except Exception:
        return False


def save(tr, meta, frames, tag=None):
    rep = os.path.join(ROOT, "reports")
    os.makedirs(rep, exist_ok=True)
    tag = tag or time.strftime("%Y%m%d_%H%M%S")
    npz = os.path.join(rep, f"ss_episode_{tag}.npz")
    arrs = {k: np.asarray(v, dtype=object if k == "stage" else float)
            for k, v in tr.items()}
    meta = dict(meta)
    meta["episode_tag"] = tag          # 同源标记: npz 与 mp4 必须同 tag
    np.savez_compressed(npz, meta=np.array([meta], dtype=object), **arrs)
    out = {"npz": npz}
    # ⚠️ 2026-08-25: 只有「带视频」的运行才能覆盖 latest —
    #   --no-video 跑法只产 npz, 若也覆盖 latest 就会出现「npz 与 mp4 不是同一条 episode」,
    #   3D 视图和操作视频悄悄错位且无人报警 (同源保证被静默破坏)。
    if not frames:
        print(f"ℹ️ --no-video 运行: 只写 {os.path.basename(npz)}, 不覆盖 latest "
              f"(latest 必须 npz+mp4 成对同源)")
        return out
    latest = os.path.join(rep, "ss_episode_latest.npz")
    np.savez_compressed(latest, meta=np.array([meta], dtype=object), **arrs)
    out["latest"] = latest
    if frames:
        import subprocess
        import tempfile
        import cv2
        tmp = tempfile.mkdtemp(prefix="ss_ep_")
        for i, fr in enumerate(frames):
            cv2.imwrite(os.path.join(tmp, f"f{i:05d}.png"), cv2.cvtColor(fr, cv2.COLOR_RGB2BGR))
        mp4 = os.path.join(rep, f"ss_episode_{tag}.mp4")
        subprocess.run(["ffmpeg", "-y", "-framerate", "25", "-i", os.path.join(tmp, "f%05d.png"),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23",
                        "-loglevel", "error", mp4], check=True)
        import shutil
        shutil.copyfile(mp4, os.path.join(rep, "ss_episode_latest.mp4"))
        shutil.rmtree(tmp, ignore_errors=True)
        out["mp4"] = mp4
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--seeds", type=int, default=6, help="失败自动换 seed 的最大尝试数")
    ap.add_argument("--no-video", action="store_true")
    a = ap.parse_args()
    best = None
    for k in range(a.seeds):
        seed = a.seed + k
        tr, meta, frames = run_episode(seed, not a.no_video)
        stages = [s.replace("阶段 ", "").split(" · ")[0] for s in tr["stage"]]
        uniq = []
        for s in stages:
            if not uniq or uniq[-1] != s:
                uniq.append(s)
        print(f"seed {seed}: {meta['steps']} 步 · 终态 {meta['stage_final']} · "
              f"success={meta['success']} · 阶段链 {'→'.join(dict.fromkeys(stages))}", flush=True)
        if best is None or len(set(stages)) > len(set(best[3])):
            best = (tr, meta, frames, stages)
        if meta["success"]:
            break
    tr, meta, frames, stages = best
    out = save(tr, meta, frames)
    # --no-video 时 save() 故意不写 latest (保证 latest 的 npz/mp4 成对同源) → 打印用 .get
    print(f"\n✅ trace: {out.get('latest') or out['npz']}  "
          f"({meta['steps']} 步, 终态 {meta['stage_final']})")
    if "mp4" in out:
        print(f"🎬 视频: {out['mp4']} ({len(frames)} 帧, 与 trace 同一条 episode)")
    print("阶段推进证据:")
    for h in meta["history"]:
        print("  →", h)


if __name__ == "__main__":
    main()
