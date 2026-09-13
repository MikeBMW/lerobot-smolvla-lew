#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌍 INTACT × Z-MAX 引擎 光模块插拔 L4 桥 (跑在 gui-venv311, 模型经 INTACT venv 子进程)

老倪 2026-09-13 需求: "把红色小方块的抓取实验, 改造成光模块的抓取插拔实验" ——
L4 链条数据源/中间/硬件层/视频四个节点保持**同构**, 只把任务从 cube (stable-world OGBCube)
换成 **光模块插拔 (Z-MAX 六层引擎 RealStateSpaceSim + metaworld peg-insert-side 真物理)**。

层次 (与 cube 链一一对应):
  · 数据源层 = 引擎渲染图像   → 本桥逐帧写 spool/step_%06d.jpg (224², 真图, EGL 离屏渲染)
  · 中间      = INTACT 策略   → 本域微调权重 (u 口径数据集训练), 零搜索, 模型动作真下发
  · 硬件层    = Z-MAX 引擎    → sim.env.step(模型动作): metaworld 真接触/夹持/插入动力学
  · 视频      = 从引擎取出    → 480² 逐帧 mp4 (解析链对照 + 模型直驱), overlay 打标真模型在环

与 tools/intact_direct_rollout.py (Step 1 口径) 的关系:
  同一套“模型动作 → env.step, 没有解析控制器”的契约, 同一 RealStateSpaceSim, 同一 INTACT 节点封装。
  **唯一新增** = u 口径反变换: v4 数据集的动作列是引擎控制向量 sim._u_vec (xyz 速度 m/s + 夹爪
  [-1..1]), 而 env.step 收的是 ±1 动作 → 用**引擎自己那套约定**(state_space_sim_real.py:1183/1198,
  act[:3]=clip(u[:3]/K_ACT) · act[3]=CLOSE if u[3]>0.5) 还原。不是新控制律, 是量纲逆运算。
  若统计 json 的 action_space == "env", 则直接 clip(±1) 下发 (与 install_direct_act 完全一致)。

诚实口径: 本桥只报真跑结果 (done / 插入深度 mm / 模型真推理次数 / 视频); 不做任何"看着像成功"
的加工。模型在环成功 = 引擎自己判 done=True + AOI(若 full 模式)。

用法 (gui-venv311):
  ./gui-venv311/bin/python tools/intact_sw_optical_bridge.py \
      --seeds 0,1 --mode insert --max-steps 900 \
      --spool reports/intact_sw/frames --status reports/intact_sw/status.json \
      --video-dir reports/intact_sw/video \
      --stats reports/optical_insert_v4_action_stats.json \
      --policy intact_goal_optical_insert_v4_s3072/weights_epoch_0.pt --device cpu
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(TOOLS, "gui"))
os.environ.setdefault("MUJOCO_GL", os.environ.get("MUJOCO_GL", "egl"))
os.environ.setdefault("PYOPENGL_PLATFORM", os.environ.get("PYOPENGL_PLATFORM", "egl"))
_CACHE = os.environ.get("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
if os.path.isdir(_CACHE):
    os.environ.setdefault("STABLEWM_HOME", _CACHE)
    os.environ.setdefault("LOCAL_DATASET_DIR", _CACHE)
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

IMG = 224
# 引擎常量 (与 tools/gui/state_space_sim_real.py:172-176 同源; main() 里 import 后覆盖为真值)
K_ACT = 0.5
GRIP_CLOSE = 0.6
GRIP_OPEN = -1.0


def _json_safe(v):
    if isinstance(v, dict):
        return {str(k): _json_safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    if isinstance(v, np.ndarray):
        return v.tolist()
    if isinstance(v, np.generic):
        return v.item()
    return v


def _write_status(path, d):
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_json_safe(d), f, ensure_ascii=False)
    os.replace(tmp, path)


def _mk_writer(path, size, fps=10):
    if not path:
        return None
    import cv2                                              # noqa: PLC0415
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    return w if w.isOpened() else None


def _overlay(frame, lines):
    import cv2                                              # noqa: PLC0415
    f = frame.copy()
    y = 22
    for t in lines:
        cv2.putText(f, t, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(f, t, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1, cv2.LINE_AA)
        y += 22
    return f


def load_stats(path):
    if not os.path.isfile(path):
        raise FileNotFoundError(f"缺动作归一化统计 {path} (用 tools/action_stats_from_h5.py 现算, 不许手写)")
    d = json.load(open(path, encoding="utf-8"))
    return (np.asarray(d["mean"], np.float32), np.asarray(d["std"], np.float32),
            str(d.get("action_space", "env")), d)


def install_model_drive(sim, node, a_mean, a_std, action_space, k_act, clip_fn,
                        grip_close, grip_open, infer_every=1, chunk_step=0, slot=0,
                        rec=None, state=None):
    """把「INTACT 真推理 → 模型动作 → env.step」装到引擎上 (原项目逻辑, 无解析控制器)。

    实现方式 (不改引擎任何代码): 引擎每步末调用 _frame_sink(本桥的 sink); 在 sink 里做一次
    真推理, 把结果写 sim._direct_act → **下一步**引擎就用它做 env.step (引擎 1179 行的既有
    直驱入口, 非 None 时 act 直接取该值, 不经 u/K_ACT 与夹爪阈值化)。

    rec/state: 调用方可读的计数器 (真推理次数 / 原始动作 / 下发动作 / 阶段 / 错误), 不静默。
    """
    import cv2                                              # noqa: PLC0415
    rec = rec if rec is not None else {"raw": [], "act": [], "stage": [], "chunk_norm": []}
    state = state if state is not None else {"n": 0, "calls": 0, "err": None}

    def _infer(sim_, frame_bgr):
        frame = np.asarray(frame_bgr)
        fr = cv2.resize(frame, (IMG, IMG), interpolation=cv2.INTER_AREA) \
            .transpose(2, 0, 1).astype(np.float32)
        out = node.step(fr, obs_source="engine_render")     # INTACT 原生推理 (子进程, 真调用)
        chunk = np.asarray(out.chunk, np.float32)
        state["calls"] += 1
        rec["chunk_norm"].append(float(np.linalg.norm(chunk)))
        raw = chunk[min(chunk_step, len(chunk) - 1), slot * 4:(slot + 1) * 4]
        z = np.clip(np.asarray(raw, np.float64), -10.0, 10.0)
        u_raw = z * a_std + a_mean                          # 训练归一化的数学逆运算
        if action_space == "u":
            # u 口径 → env 动作: 引擎自己的约定 (state_space_sim_real.py:1183/1198)
            act = np.zeros(4, np.float64)
            act[:3] = np.clip(u_raw[:3] / max(k_act, 1e-6), -1.0, 1.0)
            act[3] = grip_close if u_raw[3] > 0.5 else grip_open
        else:
            act = clip_fn(u_raw, -1.0, 1.0)                 # env 口径: 与 install_direct_act 一致
        rec["raw"].append(np.asarray(u_raw, float).copy())
        return np.asarray(act, np.float64)

    return _infer, rec, state


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="optical_insert")
    ap.add_argument("--seeds", default="0,1")
    ap.add_argument("--mode", default="insert", choices=["insert", "full"],
                    help="引擎任务模式: insert=抓取→对位→插入; full=插→拔→AOI→放回 (全链)")
    ap.add_argument("--max-steps", type=int, default=900)
    ap.add_argument("--device", default="cpu", help="模型设备 (cpu 不与训练抢 GPU)")
    ap.add_argument("--spool", default=os.path.join(ROOT, "reports", "intact_sw", "frames"))
    ap.add_argument("--status", default=os.path.join(ROOT, "reports", "intact_sw", "status.json"))
    ap.add_argument("--video-dir", default=os.path.join(ROOT, "reports", "intact_sw", "video"))
    ap.add_argument("--stats", default=os.path.join(ROOT, "reports",
                                                    "optical_insert_v4_action_stats.json"))
    ap.add_argument("--policy", default=os.environ.get("INTACT_POLICY", ""),
                    help="INTACT 权重目录名/文件 (checkpoints/ 下), 同 INTACT_POLICY")
    ap.add_argument("--infer-every", type=int, default=1)
    ap.add_argument("--chunk-step", type=int, default=0)
    ap.add_argument("--slot", type=int, default=0, help="8维=frameskip2×4维: 0=第t拍, 1=第t+1拍")
    ap.add_argument("--baseline-full", type=int, default=1,
                    help="1 = 同 seed 另跑一轮解析链 full (插→拔→AOI) 作全链证据视频")
    ap.add_argument("--model-episodes", type=int, default=0, help="0 = 全部 seed 都做模型直驱")
    ap.add_argument("--goal-npy", default=os.path.join(ROOT, "reports", "intact_goal_frame_optical.npy"))
    a = ap.parse_args()

    seeds = [int(x) for x in str(a.seeds).split(",") if x.strip()]
    os.makedirs(a.spool, exist_ok=True)
    os.makedirs(a.video_dir, exist_ok=True)
    for p in (a.status + "l",):
        try:
            open(p, "w", encoding="utf-8").close()
        except Exception:
            pass
    try:
        for f in os.listdir(a.spool):           # 清上一轮帧 (互动查看器只读本轮)
            if f.endswith(".jpg"):
                os.remove(os.path.join(a.spool, f))
    except Exception:
        pass

    a_mean, a_std, action_space, s_meta = load_stats(a.stats)
    if a.policy:
        os.environ["INTACT_POLICY"] = a.policy
    os.environ.setdefault("INTACT_RUNTIME", "root")
    os.environ.setdefault("INTACT_SEED", "3072")

    st = {"ok": False, "stage": "boot", "task": a.task, "env": "metaworld/peg-insert-side-v3",
          "sim": "RealStateSpaceSim (Z-MAX 六层引擎)", "mode": a.mode, "seeds": seeds,
          "spool": a.spool, "action_space": action_space,
          "stats": os.path.basename(a.stats) if a.stats else "",
          "ckpt": os.environ.get("INTACT_POLICY", ""), "zero_search": True}
    _write_status(a.status, st)

    import cv2                                              # noqa: PLC0415
    from state_space_sim_real import (RealStateSpaceSim, K_ACT as _KA,   # noqa: PLC0415
                                      GRIP_CLOSE as _GC, GRIP_OPEN as _GO)
    from lerobot.manifold.intact_node import IntactNode, IntactRuntime   # noqa: PLC0415
    # 引擎常量为真值 (不写死副本): 标定/夹爪动作值改引擎一处即同步
    global K_ACT, GRIP_CLOSE, GRIP_OPEN
    K_ACT, GRIP_CLOSE, GRIP_OPEN = float(_KA), float(_GC), float(_GO)

    st["stage"] = "model"
    _write_status(a.status, st)
    rt = IntactRuntime(task="pusht", device=a.device)       # task 名=原项目注册名, 权重由 INTACT_POLICY 定
    node = IntactNode(horizon=8, runtime=rt)
    if not getattr(node.runtime, "trained", False):
        st.update({"stage": "error", "err": f"INTACT 未就绪: {getattr(node.runtime, 'reason', '?')}"})
        _write_status(a.status, st)
        print(json.dumps(_json_safe(st), ensure_ascii=False))
        return 3
    st.update({"model_ready": True, "action_dim": int(getattr(node, "action_dim", 0) or 0),
               "hist_size": int(getattr(node, "hist_size", 0) or 0),
               "ckpt_file": os.path.join(_CACHE, "checkpoints", os.environ.get("INTACT_POLICY", ""))})
    _write_status(a.status, st)
    print(f"✅ INTACT 就绪: policy={os.environ.get('INTACT_POLICY')} · runtime="
          f"{os.environ.get('INTACT_RUNTIME')} · action_dim={st['action_dim']} · device={a.device}")
    print(f"   动作反归一化: {os.path.basename(a.stats)} action_space={action_space} "
          f"(n_finite={s_meta.get('n_finite')}) · K_ACT={K_ACT}")

    gstep = [0]
    all_frames = []
    rows = []

    def analytic_rollout(seed, mode, video_path=None, tag=""):
        """同 seed 解析链: 取 ① 成功/插入深度(同口径对照) ② 末帧作 goal ③ (可选) 录像"""
        fr, dist = [], []
        wr = _mk_writer(video_path, (480, 480))
        nw = [0]

        def _sink(s, act, o):
            f = np.asarray(s.env.render())
            fr.append(f)
            try:
                dist.append(float(s._insert_depth()))
            except Exception:
                dist.append(0.0)
            if wr is not None:
                try:
                    _st = str(s.sched.stage())
                except Exception:
                    _st = "?"
                wr.write(_overlay(f, [f"[解析链{tag}] seed={seed} 步={nw[0]} 模式={mode}",
                                      f"阶段 {_st[:18]}",
                                      f"下发 {np.round(np.asarray(act), 3).tolist()} "
                                      f"插入深度 {dist[-1]*1000:.1f}mm"]))
                nw[0] += 1

        sim = RealStateSpaceSim(seed=seed, vision=False, mode=mode, log=lambda *x: None)
        sim._frame_sink = _sink
        tr = sim.run(max_steps=a.max_steps)
        if wr is not None:
            wr.release()
        _d = tr.get("done")
        done = bool(_d[-1]) if (_d is not None and len(_d)) else False
        meta = tr.get("_meta") or {}
        goal = None
        if fr:
            goal = cv2.resize(fr[-1], (IMG, IMG), interpolation=cv2.INTER_AREA) \
                .transpose(2, 0, 1).astype(np.float32)
        return ({"seed": seed, "mode": mode, "done": done, "steps": len(tr.get("t") or []),
                 "insert_mm": round(float(tr["dist"][-1]) * 1000, 2) if tr.get("dist") else None,
                 "aoi_ok": ((meta.get("aoi_report") or {}).get("ok")),
                 "video": video_path, "frames": len(fr),
                 "frame_std": round(float(np.mean([f.std() for f in fr])), 2) if fr else None},
                goal)

    def model_rollout(seed, goal224, ep_i, video_path=None):
        """模型直驱: 每步真推理 → env 动作 (u→act 约定) → env.step。无解析控制器。"""
        node.set_goal(goal224)
        sim = RealStateSpaceSim(seed=seed, vision=False, mode=a.mode, log=lambda *x: None)
        rec = {"raw": [], "act": [], "stage": [], "chunk_norm": []}
        state = {"n": 0, "calls": 0, "err": None}
        infer, rec, state = install_model_drive(
            sim, node, a_mean, a_std, action_space, K_ACT, np.clip,
            GRIP_CLOSE, GRIP_OPEN, infer_every=a.infer_every, chunk_step=a.chunk_step,
            slot=a.slot, rec=rec, state=state)
        wr = _mk_writer(video_path, (480, 480))
        fr_stats: list[float] = []
        served = [0]

        def _sink(s, act, o):
            # ① 真推理 (模型 → u 空间 → env 动作) ② 写 spool 帧 ③ 写 status/jsonl ④ 录像打标
            f = np.asarray(s.env.render())
            n_err = None
            try:
                act_new = infer(s, f)
                s._direct_act = act_new
                rec["act"].append(np.asarray(act_new, float).copy())
            except Exception as e:                                  # noqa: BLE001
                state["err"] = f"{type(e).__name__}: {e}"
                s._direct_act = np.array([0.0, 0.0, 0.0, GRIP_OPEN])  # 模型挂 → 原位保持, 不瞎冲
                n_err = state["err"]
            st_i = gstep[0]
            gstep[0] += 1
            fr224 = cv2.resize(f, (IMG, IMG), interpolation=cv2.INTER_AREA)
            fp = os.path.join(a.spool, f"step_{st_i:06d}.jpg")
            cv2.imwrite(fp, fr224, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
            all_frames.append(f)
            fr_stats.append(float(fr224.std()))
            try:
                _stg = str(s.sched.stage())
            except Exception:
                _stg = "?"
            rec["stage"].append(_stg)
            raw = np.round(rec["raw"][-1], 4).tolist() if rec["raw"] else None
            actl = np.round(np.asarray(s._direct_act, float), 4).tolist()
            try:
                im = float(s._insert_depth())
            except Exception:
                im = None
            live_done = bool(str(_stg).strip() == "完成")     # 引擎自己的 done 判据 (:1936)
            st.update({"ok": True, "stage": "run", "step": st_i, "ep_index": ep_i, "ep": seed,
                       "action": raw, "env_action": actl, "model_calls": state["calls"],
                       "done": live_done, "frame": fp, "frame_std": round(fr_stats[-1], 2),
                       "stage_label": _stg,
                       "insert_mm": (round(im * 1000, 2) if im is not None else None),
                       "err": n_err, "elapsed": round(time.time() - t0, 1)})
            _write_status(a.status, st)
            try:
                with open(a.status + "l", "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(_json_safe({
                        "step": st_i, "ep": seed, "ep_index": ep_i,
                        "frame": os.path.basename(fp), "action": raw, "env_action": actl,
                        "frame_std": st["frame_std"], "stage_label": _stg,
                        "insert_mm": st["insert_mm"], "model_calls": state["calls"]}),
                        ensure_ascii=False) + "\n")
            except Exception:
                pass
            if wr is not None:
                rd = ", ".join(f"{x:+.3f}" for x in (rec["raw"][-1][:3] if rec["raw"] else [0, 0, 0]))
                wr.write(_overlay(f, [
                    f"[模型直驱] 真模型在环 · seed={seed} 步={served[0]} · 真推理 {state['calls']} 次",
                    f"阶段 {_stg[:18]} · 插入深度 "
                    f"{(st['insert_mm'] if st['insert_mm'] is not None else 0):.1f}mm",
                    f"模型输出(u: dx,dy,dz) {rd} → env 动作 {actl}"]))
                served[0] += 1

        sim._frame_sink = _sink
        sim._direct_act = np.array([0.0, 0.0, 0.0, GRIP_OPEN])   # 首步=静止保持 (非专家动作)
        t0 = time.time()
        tr = sim.run(max_steps=a.max_steps)
        if wr is not None:
            wr.release()
        _d = tr.get("done")
        done = bool(_d[-1]) if (_d is not None and len(_d)) else False
        meta = tr.get("_meta") or {}
        act = np.asarray(rec["act"], np.float32) if rec["act"] else np.zeros((0, 4), np.float32)
        return {"seed": seed, "mode": a.mode, "done": done, "steps": len(tr.get("t") or []),
                "insert_mm": round(float(tr["dist"][-1]) * 1000, 2) if tr.get("dist") else None,
                "aoi_ok": ((meta.get("aoi_report") or {}).get("ok")),
                "model_calls": state["calls"], "err": state["err"], "video": video_path,
                "seconds": round(time.time() - t0, 1),
                "frame_std": round(float(np.mean(fr_stats)), 2) if fr_stats else None,
                "env_act_mean": act.mean(0).round(4).tolist() if len(act) else None,
                "env_act_std": act.std(0).round(4).tolist() if len(act) else None,
                "u_raw_mean": np.asarray(rec["raw"], np.float32).mean(0).round(4).tolist()
                if rec["raw"] else None,
                "u_raw_std": np.asarray(rec["raw"], np.float32).std(0).round(4).tolist()
                if rec["raw"] else None,
                "stages": {s: rec["stage"].count(s) for s in sorted(set(rec["stage"]))}
                if rec["stage"] else {}}

    t0 = time.time()
    n_model = a.model_episodes if a.model_episodes > 0 else len(seeds)
    msucc = bsucc = 0
    for k, sd in enumerate(seeds):
        st.update({"stage": "baseline", "ep_index": k, "seed_running": sd})
        _write_status(a.status, st)
        vbase = os.path.join(a.video_dir, f"{a.task}_解析链对照_seed{sd}.mp4")
        base, goal = analytic_rollout(sd, a.mode, video_path=vbase, tag=" 插入")
        bsucc += int(bool(base["done"]))
        if goal is not None and k == 0:
            np.save(a.goal_npy, goal)
        if a.baseline_full:                       # 全链证据: 插入→拔出→AOI→放回
            vfull = os.path.join(a.video_dir, f"{a.task}_解析链全链(插→拔→AOI)_seed{sd}.mp4")
            fbase, _ = analytic_rollout(sd, "full", video_path=vfull, tag=" 全链")
            base["full_chain"] = {kk: fbase[kk] for kk in
                                  ("done", "steps", "insert_mm", "aoi_ok", "video", "frame_std")}
        rows.append({"seed": sd, "analytic": base})
        st.update({"rows": rows, "succ": bsucc,
                   "success_rate": round(100.0 * bsucc / len(rows), 1)})
        _write_status(a.status, st)
        print(f"   [解析链] seed={sd} done={base['done']} 步数={base['steps']} "
              f"插入={base['insert_mm']}mm · 全链={((base.get('full_chain') or {}).get('done'))} "
              f"· 视频 {os.path.basename(vbase)}", flush=True)

        if goal is None or k >= n_model:
            continue
        vdir = os.path.join(a.video_dir, f"{a.task}_模型直驱_seed{sd}.mp4")
        out = model_rollout(sd, goal, k, video_path=vdir)
        msucc += int(bool(out["done"]))
        rows[-1]["model"] = out
        st.update({"model_eps": [r.get("model") for r in rows if r.get("model")],
                   "model_succ": msucc,
                   "model_success_rate": round(100.0 * msucc / (k + 1), 1),
                   "steps": gstep[0], "model_calls": st.get("model_calls", 0) + out["model_calls"]})
        _write_status(a.status, st)
        print(f"   [模型直驱] seed={sd} done={out['done']} 步数={out['steps']} "
              f"插入={out['insert_mm']}mm · 真推理 {out['model_calls']} 次 · {out['seconds']}s "
              f"· err={out['err']}", flush=True)

    # 合集 (逐帧实况连播) — 「从引擎取出的渲染视频」
    showcase = None
    try:
        per_ep = sorted([os.path.join(a.video_dir, x) for x in os.listdir(a.video_dir)
                         if x.endswith(".mp4") and a.task in x and "showcase" not in x])
        if per_ep:
            listf = os.path.join(a.video_dir, "concat_optical.txt")
            showcase = os.path.join(a.video_dir, f"{a.task}_showcase.mp4")
            with open(listf, "w") as fh:
                for p in per_ep:
                    fh.write(f"file '{os.path.abspath(p)}'\n")     # ffmpeg 相对路径按 list 文件目录解 → 用绝对路径
            import subprocess
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
                            "-i", listf, "-c", "copy", showcase], check=False, timeout=180)
            if not os.path.exists(showcase):
                showcase = None
    except Exception as e:                                          # noqa: BLE001
        st["showcase_err"] = f"{type(e).__name__}: {e}"

    n_done = len([r for r in rows if r.get("model") is not None])
    st.update({"ok": True, "stage": "done", "steps": gstep[0], "ep_done": len(rows),
               "eps": [r["seed"] for r in rows], "model_eps_done": n_done,
               "succ": bsucc, "success_rate": round(100.0 * bsucc / max(len(rows), 1), 1),
               "model_succ": msucc,
               "model_success_rate": (round(100.0 * msucc / n_done, 1) if n_done else None),
               "model_calls": sum((r.get("model") or {}).get("model_calls", 0) for r in rows),
               "video": (rows[-1].get("model") or {}).get("video") or rows[-1]["analytic"]["video"],
               "rows": rows, "showcase": showcase, "goal_npy": a.goal_npy,
               "frame_std": round(float(np.mean([f.std() for f in all_frames])), 2)
               if all_frames else None,
               "elapsed": round(time.time() - t0, 1)})
    st["honest_note"] = (
        f"L4 演示档小样本随机起点 (seeds={seeds}, mode={a.mode}), 非官方 100 局口径。"
        f"解析链对照 {bsucc}/{len(rows)} 成功 = 引擎本任务可达性; 模型直驱"
        f" {msucc}/{n_done or 0} 成功 = 本域微调权重真实水平 (不做任何加工)。")
    _write_status(a.status, st)
    print("\n" + json.dumps(_json_safe({k2: st[k2] for k2 in
                                        ("ok", "stage", "steps", "succ", "success_rate",
                                         "model_succ", "model_success_rate", "model_calls",
                                         "frame_std", "showcase", "honest_note")}),
                             ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
