# -*- coding: utf-8 -*-
"""🎯 Step 1 直驱 (老倪 2026-09-12 口径): **不更改任何逻辑, 直接复制 INTACT 项目**

原项目的控制逻辑就是一句话: policy 输出 action → `env.step(action)` → 下一步再输出。
本工具把它原样搬到本引擎上:
    · 观测   = 引擎真实渲染帧 (corner2 480² → 224² CHW) → INTACT 原生推理 (不改其代码)
    · 动作   = 模型输出的 action chunk → **直接作为 env 级动作** 交给 env.step
    · 中间   = 没有解析控制器 / 没有 u_ff / 没有标定 / 没有流形 —— 与原生项目完全一致
动作量纲说明 (为什么只做"逆归一化"这一步, 这不是标定):
   训练时 action 列被 z-score (INTACT train.py: get_column_stats + get_column_normalizer),
   action_dim = frameskip(2) × 4 = 8 → chunk 的 d0:4 = 第 t 拍动作(归一化), d4:8 = 第 t+1 拍。
   所以还原 = a_raw = z·std + mean (std/mean 取自训练数据集同口径), 再 clip 到 ±1 → env.step。
   —— 这是训练归一化的**数学逆运算**, 原项目 eval 也是这么做逆变换的, 不是新增映射逻辑。

控制流 (每步):
    sched.decide() 被包一层 → 先让引擎原有状态机走完(只取阶段标签, 其指令被丢弃)
                            → 渲染当前帧 → node.step → chunk
                            → sim._direct_act = a_raw  → 引擎用**模型动作**做 env.step

用法:
  # 单 seed 直驱 (默认用域内微调权重)
  ./gui-venv311/bin/python tools/intact_direct_rollout.py --seed 0 --max-steps 600
  # 多 seed + 同轮解析链对照 (同进程同口径)
  ./gui-venv311/bin/python tools/intact_direct_rollout.py --seeds 0,1,2,3 --max-steps 600
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
_CACHE = os.environ.get("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
if os.path.isdir(_CACHE):
    os.environ.setdefault("STABLEWM_HOME", _CACHE)
    os.environ.setdefault("LOCAL_DATASET_DIR", _CACHE)
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

IMG = 224
STATS_FILE = os.path.join(ROOT, "reports", "zmax_action_stats.json")


def load_stats(path: str):
    if not os.path.isfile(path):
        raise FileNotFoundError(f"缺动作归一化统计 {path} (由 INTACT 训练同口径生成, 不许手写)")
    d = json.load(open(path, encoding="utf-8"))
    return np.asarray(d["mean"], np.float32), np.asarray(d["std"], np.float32), d


def _mk_writer(path, size):
    """视频写手 (mp4, 10fps = 引擎控制频率)。失败返回 None (不静默: 调用方打印)。"""
    if not path:
        return None
    import cv2                                              # noqa: PLC0415
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10, size)
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


def analytic_rollout(seed, mode, max_steps, video_path=None):
    """解析链同 seed 跑一轮: 拿 ① 成功率(同口径对照) ② 成功态帧作 goal ③ (可选) 录像。"""
    import cv2                                              # noqa: PLC0415
    from state_space_sim_real import RealStateSpaceSim      # noqa: PLC0415
    fr = []
    wr = _mk_writer(video_path, (480, 480))
    n_written = [0]

    def _sink(s, act, o):
        f = np.asarray(s.env.render())
        fr.append(f)
        if wr is not None:
            st = str(getattr(s.sched, "stage", "") or "")
            wr.write(_overlay(f, [f"[解析链 对照] seed={seed} 步={n_written[0]}",
                                  f"阶段 {st[:16]}  实际下发 {np.round(np.asarray(act), 3).tolist()}"]))
            n_written[0] += 1

    sim = RealStateSpaceSim(seed=seed, vision=False, mode=mode, log=lambda *x: None)
    sim._frame_sink = _sink
    tr = sim.run(max_steps=max_steps)
    if wr is not None:
        wr.release()
        print(f"   🎬 对照视频: {video_path} ({n_written[0]} 帧)")
    done = bool(tr["done"][-1]) if tr.get("done") else False
    goal = None
    if fr:
        goal = cv2.resize(fr[-1], (IMG, IMG), interpolation=cv2.INTER_AREA) \
            .transpose(2, 0, 1).astype(np.float32)
    return {"done": done, "steps": len(tr["t"]), "frames": len(fr),
            "video": (video_path if wr is not None else None),
            "insert_mm": (round(float(tr["dist"][-1]) * 1000, 1) if tr.get("dist") else None)}, goal


def install_direct_act(sim, node, a_mean, a_std, infer_every=1, chunk_step=0, slot=0, unz=True,
                       rec=None, state=None):
    """把「INTACT 节点真推理 → 模型动作」装到引擎上 (原项目逻辑: 模型动作直接当 env 动作)。

    可复用: tools/intact_direct_rollout.py 与本控制台 L4 档 (「🤖 L4 用 INTACT 节点执行」) 共用。
      · 每次 reset 后 sched 才建好 → 这里包 decide: 每 infer_every 步真推理一次, 结果放
        sim._direct_act (引擎在 _direct_act 非 None 时用**模型动作**做 env.step, 不走 u_vec/K_ACT)。
      · 只允许一个变换: 训练归一化逆变换 a_raw = z·std + mean (与原项目 eval 同口径), clip ±1。
    返回 (rec, state) 便于调用方读取推理次数/原始动作。
    """
    import cv2                                              # noqa: PLC0415
    rec = rec if rec is not None else {"act": [], "raw": [], "stage": [], "chunk_norm": []}
    state = state if state is not None else {"n": 0, "calls": 0, "err": None}

    def _install(s):
        orig = s.sched.decide

        def dec(u_ff, u_fb, contact_p, r_scalar):
            u, stage = orig(u_ff, u_fb, contact_p, r_scalar)   # 只取阶段标签; 解析指令被丢弃
            step_i = state["n"]
            state["n"] += 1
            if step_i % max(1, infer_every) == 0 or getattr(s, "_dact_cache", None) is None:
                try:
                    frame = np.asarray(s.env.render())          # 真实渲染帧 (原项目也是真图)
                    fr = cv2.resize(frame, (IMG, IMG), interpolation=cv2.INTER_AREA) \
                        .transpose(2, 0, 1).astype(np.float32)
                    out = node.step(fr, obs_source="engine_render")
                    chunk = np.asarray(out.chunk, np.float32)
                    state["calls"] += 1
                    raw = chunk[min(chunk_step, len(chunk) - 1), slot * 4:(slot + 1) * 4]
                    act = (raw * a_std + a_mean) if unz else raw
                    s._dact_cache = np.clip(act, -1.0, 1.0)
                    rec["raw"].append(raw.copy())
                    rec["chunk_norm"].append(float(np.linalg.norm(chunk)))
                except Exception as e:                          # 模型/渲染失败 → 记错并停直驱
                    state["err"] = f"{type(e).__name__}: {e}"
                    s._dact_cache = np.zeros(4, np.float32)
            s._direct_act = s._dact_cache
            rec["act"].append(np.asarray(s._direct_act, float).copy())
            rec["stage"].append(str(stage))
            return u, stage

        s.sched.decide = dec

    _orig_reset = sim._reset

    def _patched_reset(seed_, *a, **kw):
        r = _orig_reset(seed_, *a, **kw)
        sim._direct_act = None
        sim._dact_cache = None
        _install(sim)                     # sched 在 _reset 里才建好 → 此刻包 decide
        return r

    sim._reset = _patched_reset
    return rec, state


def direct_rollout(seed, mode, max_steps, goal224, node, a_mean, a_std, unz,
                   chunk_step, slot, infer_every, tag, verbose=True, video_path=None):
    """模型直驱: 模型动作 → env.step, 无解析控制器。可选录像 (标出是真模型在下指令)。"""
    import cv2                                              # noqa: PLC0415
    from state_space_sim_real import RealStateSpaceSim      # noqa: PLC0415

    node.set_goal(goal224)
    sim = RealStateSpaceSim(seed=seed, vision=False, mode=mode, log=lambda *x: None)
    rec = {"act": [], "raw": [], "stage": [], "chunk_norm": []}
    state = {"n": 0, "calls": 0, "err": None}
    wr = _mk_writer(video_path, (480, 480))
    n_w = [0]

    def _sink(s, act, o):
        if wr is None:
            return
        st = str(getattr(getattr(s, "sched", None), "stage", "") or "")
        rd = "-"
        if rec["raw"]:
            _r = rec["raw"][-1]
            rd = ", ".join(f"{x:+.3f}" for x in _r[:3])
        wr.write(_overlay(np.asarray(s.env.render()), [
            f"[模型直驱] 真模型下发 · seed={seed} 步={n_w[0]} · 模型推理 {state['calls']} 次",
            f"阶段 {st[:16]}",
            f"模型原始动作(dx,dy,dz) {rd}  → 实际 env 动作 {np.round(np.asarray(act), 3).tolist()}"]))
        n_w[0] += 1

    sim._frame_sink = _sink

    install_direct_act(sim, node, a_mean, a_std, infer_every=infer_every, chunk_step=chunk_step,
                       slot=slot, unz=unz, rec=rec, state=state)
    t0 = time.time()
    tr = sim.run(max_steps=max_steps)
    if wr is not None:
        wr.release()
        print(f"   🎬 直驱视频: {video_path} ({n_w[0]} 帧)")
    done = bool(tr["done"][-1]) if tr.get("done") else False
    act = np.asarray(rec["act"], np.float32) if rec["act"] else np.zeros((0, 4), np.float32)
    out = {"tag": tag, "seed": seed, "done": done, "steps": len(tr["t"]),
           "insert_mm": (round(float(tr["dist"][-1]) * 1000, 1) if tr.get("dist") else None),
           "model_calls": state["calls"], "err": state["err"], "sec": round(time.time() - t0, 1),
           "act_mean": act.mean(0).round(4).tolist() if len(act) else None,
           "act_std": act.std(0).round(4).tolist() if len(act) else None,
           "act_absmax": np.abs(act).max(0).round(3).tolist() if len(act) else None,
           "stages": {s: rec["stage"].count(s) for s in sorted(set(rec["stage"]))}
           if rec["stage"] else {}}
    if verbose:
        print(f"   [{tag}] done={done} 步数={out['steps']} 插入={out['insert_mm']}mm · "
              f"模型真推理 {state['calls']} 次 · {out['sec']}s"
              + (f" · ⚠️ {state['err']}" if state["err"] else ""), flush=True)
    return out, act


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--seeds", default="")
    ap.add_argument("--mode", default="insert", choices=["insert", "full"])
    ap.add_argument("--max-steps", type=int, default=600)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--task", default="pusht")
    ap.add_argument("--horizon", type=int, default=8)
    ap.add_argument("--chunk-step", type=int, default=0, help="取 chunk 的第几步 (0=当下这一步)")
    ap.add_argument("--slot", type=int, default=0, help="8维=frameskip2×4维 → 0=第t拍, 1=第t+1拍")
    ap.add_argument("--infer-every", type=int, default=1, help="每 N 步真推理一次 (1=每步都推)")
    ap.add_argument("--no-unz", action="store_true", help="不做训练归一化逆变换 (对照实验)")
    ap.add_argument("--stats", default=STATS_FILE)
    ap.add_argument("--baseline", default="1", help="1=同轮跑解析链对照 (同口径)")
    ap.add_argument("--video-dir", default="", help="非空则录 mp4 到该目录 (解析链对照 + 模型直驱 各一段)")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    seeds = ([a.seed] if a.seed is not None else
             [int(x) for x in a.seeds.split(",") if x.strip()])
    if not seeds:
        seeds = [0]
    a_mean, a_std, s_meta = load_stats(a.stats)
    print(f"═══ Step 1 直驱: 模型动作 → env.step (无解析控制器) ═══")
    print(f"   引擎 mode={a.mode} · seeds={seeds} · max_steps={a.max_steps} · device={a.device}")
    print(f"   动作归一化逆变换: {s_meta['source']} "
          f"(n={s_meta['n_finite']}) → a_raw = z·std + mean   [unz={not a.no_unz}]")
    print(f"   chunk: step={a.chunk_step} slot={a.slot} (slot0=d_t, slot1=d_t+1) · "
          f"每 {a.infer_every} 步真推理一次")

    from lerobot.manifold.intact_node import IntactNode, IntactRuntime   # noqa: PLC0415
    rt = IntactRuntime(task=a.task, device=a.device)
    node = IntactNode(horizon=a.horizon, runtime=rt)
    if not node.runtime.trained:
        print(f"❌ INTACT 未就绪: {node.runtime.reason}")
        return 3
    print(f"   INTACT 就绪: policy={rt.policy_name or os.environ.get('INTACT_POLICY')} · "
          f"runtime={os.environ.get('INTACT_RUNTIME', 'auto')} · action_dim={node.action_dim} · "
          f"hist={node.hist_size}")

    rows, acts = [], {}
    ts = time.strftime("%Y%m%d_%H%M%S")
    for sd in seeds:
        base, goal = (None, None)
        v_base = v_direct = None
        if a.video_dir:
            v_base = os.path.join(a.video_dir, f"insert_解析链对照_seed{sd}_{ts}.mp4")
            v_direct = os.path.join(a.video_dir, f"insert_模型直驱_seed{sd}_{ts}.mp4")
        if str(a.baseline) == "1":
            base, goal = analytic_rollout(sd, a.mode, a.max_steps, video_path=v_base)
            print(f"   [解析链对照] seed={sd} done={base['done']} 步数={base['steps']} "
                  f"插入={base['insert_mm']}mm", flush=True)
        if goal is None:
            print(f"   seed={sd}: 解析链未产出帧 → 无法取 goal, 跳过")
            continue
        d_out, act = direct_rollout(sd, a.mode, a.max_steps, goal, node, a_mean, a_std,
                                    not a.no_unz, a.chunk_step, a.slot, a.infer_every,
                                    tag=("直驱" if not a.no_unz else "直驱(不做逆归一化)"),
                                    video_path=v_direct)
        rows.append({"seed": sd, "analytic": base, "direct": d_out,
                     "video_analytic": (base or {}).get("video"), "video_direct": d_out.get("video")})
        acts[sd] = act
    node.close()

    n = len(rows)
    if n:
        dsucc = sum(1 for r in rows if r["direct"]["done"])
        asucc = sum(1 for r in rows if (r["analytic"] or {}).get("done"))
        print(f"\n═══ 汇总 (n={n}) ═══")
        print(f"   解析链 (同轮同口径): {asucc}/{n} = {asucc/n:.2f}")
        print(f"   模型直驱 (本 Step 1) : {dsucc}/{n} = {dsucc/n:.2f}")
        calls = [r["direct"]["model_calls"] for r in rows]
        print(f"   模型真推理次数: {calls} · 错误: "
              f"{[r['direct']['err'] for r in rows if r['direct']['err']] or '无'}")
    tag = time.strftime("%Y%m%d_%H%M%S")
    out = a.out or os.path.join(ROOT, "reports", f"intact_direct_{tag}.json")
    json.dump({"meta": {"seeds": seeds, "mode": a.mode, "max_steps": a.max_steps,
                        "unz": not a.no_unz, "chunk_step": a.chunk_step, "slot": a.slot,
                        "infer_every": a.infer_every, "device": a.device,
                        "policy": os.environ.get("INTACT_POLICY", ""),
                        "runtime": os.environ.get("INTACT_RUNTIME", ""),
                        "obs_source": "engine_render 480²→224²(CHW)",
                        "stats": s_meta, "ts": time.strftime("%F %T")},
               "rows": rows}, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"   → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
