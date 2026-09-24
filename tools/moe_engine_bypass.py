#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧬 moe_engine_bypass.py — ①-2③ MOE 只读旁路进**真实引擎闭环** (每帧真调 · 不参与下发)

设计纪律 (integration-level-audit: 只读旁路 → 接管 → 硬件; 禁止跳级)
  · 每帧真调: 挂 `sim.env.step` (引擎 run() 循环里唯一每步一调的物理推进点), 计数必须 == 步数
  · 只读旁路: MOE 输出只记日志, 不回写 self._direct_act / _u_vec → **动作零影响**
  · 零回退实证: 同 seed 跑 对照(不挂钩) 与 旁路(挂钩) 两次, dist 序列逐位相同
  · 延迟预算: 分别记 render() 与 MOE forward 的耗时 (render 是取证仪表成本, 不算在模型账上)
  · 真阶段真值: 引擎 self.sched.stage() 作真值, 量 MOE 门控**自判阶段**能力 (不喂真值)

口径 (与训练逐项对齐, 2026-09-24 核对 stage_moe_backbone.py::main)
  obs     = sim._obs39() == env._get_obs()[:39]      ← 与 h5 observation (8715,39) 同源同义
  px      = env.render() → 224×224 → float/255 → CHW  ← 训练侧仅 /255, **无** mean/std 中心化
  mem     = zeros(13)                                ← 训练侧即 torch.zeros(B,13)
  stage_p = 变体A 均匀 1/7 (无先验 · 可部署口径) / 变体B 引擎真值 one-hot (上界参考 · 不可部署)

可用两个模型 (同一套旁路框架 → 引擎流上的同口径对照):
  --model moe    (①-2③) 阶段专家 MOE   · ckpt checkpoints/stage_moe/moe.pt
  --model dense  (①-3)  统一主干四头   · ckpt checkpoints/dense_sub25k_600/unified.pt
两模型 px 归一化口径不同 (训练侧如此, 必须各自对齐):
  moe   : px float/255 → CHW            (stage_moe_backbone 训练侧)
  dense : to_img() → /255 → (x-0.5)/0.5  (joint_unified_backbone 训练侧)

用法
  MUJOCO_GL=egl ./gui-venv311/bin/python tools/moe_engine_bypass.py --seeds 0,1,2 --steps 600
  MUJOCO_GL=egl ./gui-venv311/bin/python tools/moe_engine_bypass.py --model dense --seeds 0,1,2
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("DISPLAY", ":0")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUI = os.path.join(ROOT, "tools", "gui")
for _p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "tools"), GUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.chdir(GUI)
os.environ.setdefault("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
os.environ.setdefault("LOCAL_DATASET_DIR", "/home/ubuntu/stable-wm-cache")
os.environ.setdefault("INTACT_RUNTIME", "root")
os.environ.setdefault("INTACT_POLICY", "intact_l4_current")
os.environ.setdefault("OMP_NUM_THREADS", "6")
# 🧊 冷记忆隔离 (同 ab_intent_line_closedloop): 热记忆会让同 seed 结果随历史漂移
if os.environ.get("AB_HOT_MEM") != "1":
    os.environ.setdefault("SS_MUSCLE_PATH", "/tmp/moe_bypass_mem_%d.json" % os.getpid())

SWM = "/home/ubuntu/stable-wm-cache"
TRAIN_STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入"]


def clean_stage(s: str) -> str:
    """引擎阶段名可能带推进后缀 ('下降 · 接触') → 取主阶段"""
    return str(s or "").replace("阶段 ", "").split("·")[0].strip()


def build_net(kind: str, ckpt: str, dev: str):
    """按训练侧口径建网 + 载权重。返回 (net, kind)"""
    import torch
    from transformers import AutoModel
    from joint_unified_backbone import MODEL
    trunk = AutoModel.from_pretrained(MODEL, dtype=torch.float32).vision_model
    if kind == "moe":
        from stage_moe_backbone import StageMoE, NS
        net = StageMoE(trunk, freeze=1).to(dev)
        tag = f"🧬 MOE (阶段专家 · 先验门控) · 阶段 {NS} = {'/'.join(TRAIN_STAGES)}"
    else:
        from joint_unified_backbone import Unified
        net = Unified(trunk, freeze=1).to(dev)
        tag = "🧠 统一主干四头 (密集 · 共享 SigLIP)"
    sd = torch.load(ckpt, map_location="cpu", weights_only=False)
    if isinstance(sd, dict) and "model" in sd and not any(k.startswith("trunk.") for k in sd):
        sd = sd["model"]                      # 兼容包装键
    r = net.load_state_dict(sd, strict=False)
    net.eval()
    n_hd = sum(p.numel() for p in net.parameters() if p.requires_grad)
    print(f"{tag}", flush=True)
    print(f"   已加载 {os.path.basename(ckpt)} (missing={len(r.missing_keys)} unexpected={len(r.unexpected_keys)})"
          f" · 可训参数 {n_hd/1e6:.2f}M", flush=True)
    return net, kind


def run_seed(seed: int, steps: int, net, dev: str, hook: bool, use_truth_prior: bool, tag: str,
             kind: str = "moe"):
    """跑一轮引擎闭环; hook=True 时每帧真调 MOE (只读)"""
    import torch
    import cv2
    from state_space_sim_real import RealStateSpaceSim

    sim = RealStateSpaceSim(seed=seed, vision=False, mode="insert", log=lambda *x: None)
    frames: list = []

    if hook:
        orig_step = sim.env.step

        def hooked(act):
            out = orig_step(act)
            rec = {"step": len(frames)}
            try:
                t0 = time.perf_counter()
                fr = np.asarray(sim._render_frame())
                rec["t_render_ms"] = (time.perf_counter() - t0) * 1000.0
                obs39 = np.asarray(sim._obs39(), dtype=np.float32).reshape(-1)[:39]
                px = cv2.resize(fr, (224, 224), interpolation=cv2.INTER_AREA)
                o = torch.from_numpy(obs39).to(dev).unsqueeze(0)
                mem = torch.zeros(1, 13, device=dev)
                stg = clean_stage(sim.sched.stage()) if getattr(sim, "sched", None) else ""
                t1 = time.perf_counter()
                with torch.no_grad():
                    if kind == "moe":
                        # 口径同 stage_moe_backbone 训练: px float/255 → CHW, 无中心化
                        x = torch.from_numpy(px).to(dev).float().div(255.0).permute(2, 0, 1).unsqueeze(0)
                        if use_truth_prior and stg in TRAIN_STAGES:
                            sp = torch.zeros(1, 7, device=dev)
                            sp[0, TRAIN_STAGES.index(stg)] = 1.0
                        else:
                            sp = torch.full((1, 7), 1.0 / 7.0, device=dev)   # 无先验 (不泄漏真值)
                        r = net(x, o, None, mem, sp, hard=True)
                        oh, gate, ex, u = r["o_hat"], r["gate"][0].tolist(), int(r["expert_id"][0]), r["u"]
                    else:
                        # 口径同 joint_unified_backbone 训练: to_img → /255 → (x-0.5)/0.5
                        from joint_unified_backbone import to_img
                        x = to_img(px[None]).to(dev)
                        r = net(x, o, None, mem)
                        oh, gate, ex, u = r["obs_hat"], None, None, r["u"]
                if dev == "cuda":
                    torch.cuda.synchronize()
                rec["t_moe_ms"] = (time.perf_counter() - t1) * 1000.0
                rec["obs"] = obs39.tolist()
                rec["stage_true"] = stg
                rec["gate"] = gate
                rec["expert"] = ex
                rec["o_hat"] = oh[0].detach().float().cpu().numpy().tolist()
                rec["u"] = u[0].detach().float().cpu().numpy().tolist()
                rec["ok"] = True
            except Exception as e:                                        # noqa: BLE001
                rec["ok"] = False
                rec["err"] = f"{type(e).__name__}: {e}"
            frames.append(rec)
            return out

        sim.env.step = hooked

    t0 = time.time()
    tr = sim.run(max_steps=steps)
    wall = time.time() - t0
    dist = np.asarray(tr.get("dist") or [], float)
    steps_n = int(len(tr.get("t", [])))
    out = {
        "seed": seed, "tag": tag, "steps": steps_n, "wall_s": round(wall, 1),
        "done": bool(tr.get("done", [False])[-1]),
        "insert_mm_end": round(float(dist[-1]) * 1000, 1) if dist.size else None,
        "insert_mm_min": round(float(dist.min()) * 1000, 1) if dist.size else None,
        "dist": [round(float(v) * 1000, 4) for v in dist.tolist()],
        "stages": [clean_stage(s) for s in (tr.get("stage") or [])],
        "moe_frames": frames,
    }
    return out


def summarize(res_by_seed: dict, n_steps_declared: int) -> dict:
    """延迟 / 自判阶段准确率 / 一步预测误差 (回放同一份逐帧日志, 不重复跑引擎)"""
    lat_moe, lat_rd, called, errs = [], [], 0, 0
    cm = {(t, p): 0 for t in TRAIN_STAGES for p in range(7)}
    per_stage = {s: [0, 0] for s in TRAIN_STAGES}
    non_train = 0
    has_gate = False
    dpred, dpersist = [], []
    n_tr = 0
    for sd, r in res_by_seed.items():
        fr = r.get("moe_frames") or []
        for i, f in enumerate(fr):
            called += 1
            if not f.get("ok"):
                errs += 1
                continue
            lat_moe.append(f["t_moe_ms"])
            lat_rd.append(f.get("t_render_ms", 0.0))
            st, ex = f["stage_true"], f.get("expert")
            if st in TRAIN_STAGES and ex is not None:
                has_gate = True
                n_tr += 1
                cm[(st, ex)] += 1
                per_stage[st][0] += 1
                per_stage[st][1] += int(TRAIN_STAGES.index(st) == ex)
            elif st not in TRAIN_STAGES:
                non_train += 1
            # 一步预测误差: MOE o_hat vs 下一帧真观测; 平凡基线 = 保持当前观测 (persistence)
            nxt = next((g["obs"] for g in fr[i + 1:] if g.get("ok")), None)
            if nxt is not None:
                oh = np.asarray(f["o_hat"], float)
                cu = np.asarray(f["obs"], float)
                nx = np.asarray(nxt, float)
                dpred.append(float(np.abs(oh - nx).mean()))
                dpersist.append(float(np.abs(cu - nx).mean()))

    def st(a):
        a = np.asarray(a, float)
        return {"n": int(a.size), "mean_ms": round(float(a.mean()), 2) if a.size else None,
                "p50_ms": round(float(np.percentile(a, 50)), 2) if a.size else None,
                "p95_ms": round(float(np.percentile(a, 95)), 2) if a.size else None}

    return {
        "frames_called": called, "frames_err": errs,
        "latency_moe": st(lat_moe), "latency_render": st(lat_rd),
        "implied_max_hz_moe_only": round(1000.0 / max(np.mean(lat_moe), 1e-9), 1) if lat_moe else None,
        "has_gate": has_gate,
        "stage_truth_frames": n_tr, "stage_non_train_frames": non_train,
        "gate_self_stage_acc": (round(sum(v[1] for v in per_stage.values()) / n_tr, 4) if (n_tr and has_gate) else None),
        "per_stage_acc": {k: round(v[1] / v[0], 4) if v[0] else None for k, v in per_stage.items()},
        "per_stage_n": {k: v[0] for k, v in per_stage.items()},
        "confusion_true_to_expert": {f"{t}->E{p}": c for (t, p), c in cm.items() if c},
        "one_step_pred_mae_moe": round(float(np.mean(dpred)), 5) if dpred else None,
        "one_step_pred_mae_persist": round(float(np.mean(dpersist)), 5) if dpersist else None,
        "one_step_pred_n": len(dpred),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="moe", choices=["moe", "dense"],
                    help="moe=阶段专家(①-2③) / dense=统一主干四头(①-3)")
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--steps", type=int, default=600)
    ap.add_argument("--ckpt", default="")
    ap.add_argument("--truth-seed", type=int, default=0, help="真值先验变体只跑这个 seed (上界参考)")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if not a.ckpt:
        a.ckpt = (f"{SWM}/checkpoints/stage_moe/moe.pt" if a.model == "moe"
                  else f"{SWM}/checkpoints/dense_sub25k_600/unified.pt")

    import torch
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    seeds = [int(x) for x in a.seeds.split(",") if x.strip()]
    print("=" * 78)
    print(f"🧬 {'①-2③ MOE' if a.model == 'moe' else '①-3 统一主干'} 只读旁路 · 真实引擎闭环 (每帧真调 · 动作零影响)")
    print(f"   model={a.model} seeds={seeds} steps_cap={a.steps} device={dev} ckpt={os.path.basename(a.ckpt)}")
    print("=" * 78, flush=True)
    net, kind = build_net(a.model, a.ckpt, dev)

    ctrl, byp, truth = {}, {}, {}
    for sd in seeds:
        c = run_seed(sd, a.steps, net, dev, hook=False, use_truth_prior=False, tag="control", kind=kind)
        print(f"  [对照] seed{sd}: {c['steps']} 步 · done={c['done']} · 末端 {c['insert_mm_end']}mm · {c['wall_s']}s", flush=True)
        ctrl[sd] = c
        b = run_seed(sd, a.steps, net, dev, hook=True, use_truth_prior=False, tag="bypass_uniform", kind=kind)
        print(f"  [旁路A] seed{sd}: {b['steps']} 步 · done={b['done']} · 末端 {b['insert_mm_end']}mm · "
              f"调 {len(b['moe_frames'])} 帧 · {b['wall_s']}s", flush=True)
        byp[sd] = b

    if a.truth_seed in seeds:
        t = run_seed(a.truth_seed, a.steps, net, dev, hook=True, use_truth_prior=True, tag="bypass_truth", kind=kind)
        print(f"  [旁路B真值先验·上界参考] seed{a.truth_seed}: {t['steps']} 步 · done={t['done']}", flush=True)
        truth[a.truth_seed] = t

    # ── 零回退: 同 seed 对照 vs 旁路 逐位比对 ──
    zero_reg = {}
    for sd in seeds:
        c, b = ctrl[sd], byp[sd]
        zero_reg[sd] = {
            "steps_equal": c["steps"] == b["steps"], "done_equal": c["done"] == b["done"],
            "dist_bitwise_equal": bool(np.array_equal(np.asarray(c["dist"]), np.asarray(b["dist"]))),
            "dist_max_abs_diff_mm": float(np.max(np.abs(np.asarray(c["dist"]) - np.asarray(b["dist"]))))
            if c["dist"] and len(c["dist"]) == len(b["dist"]) else None,
        }

    out = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "steps_cap": a.steps, "seeds": seeds,
        "device": dev, "ckpt": a.ckpt, "model": a.model,
        "caliber": {"obs": "sim._obs39() == env._get_obs()[:39] (与 h5 observation 同源)",
                    "px": "env.render() → 224×224 INTER_AREA → float/255 → CHW (无 mean/std, 同训练侧)",
                    "mem": "zeros(13) (训练侧即 zeros(B,13))",
                    "stage_p": "A=均匀1/7(无先验, 可部署) / B=引擎真值one-hot(上界参考, 不可部署)"},
        "summary": summarize(byp, a.steps),
        "summary_truth_prior": summarize(truth, a.steps) if (truth and kind == "moe") else None,
        "zero_regression": zero_reg,
        "runs": {"control": {str(k): {kk: vv for kk, vv in v.items() if kk != "moe_frames"} for k, v in ctrl.items()},
                 "bypass": {str(k): {kk: vv for kk, vv in v.items() if kk != "moe_frames"} for k, v in byp.items()}},
    }
    p = a.out or os.path.join(ROOT, "reports", "%s_bypass_%s.json"
                              % (a.model, time.strftime("%Y%m%d_%H%M%S")))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    s = out["summary"]
    print("\n" + "=" * 78)
    print(f"① 每帧真调: {s['frames_called']} 帧 (失败 {s['frames_err']}) · 延迟 {s['latency_moe']}")
    print(f"   渲染取证成本 {s['latency_render']} (仪表成本) · 单帧上限 ~{s['implied_max_hz_moe_only']} Hz"
          f" (引擎控制周期 100ms → 占预算 {round(s['latency_moe']['mean_ms']/100*100,1) if s['latency_moe']['mean_ms'] else None}%)")
    print(f"② 零回退: {json.dumps(zero_reg, ensure_ascii=False)}")
    if s["has_gate"]:
        print(f"③ 门控自判阶段 (无先验): acc {s['gate_self_stage_acc']} on {s['stage_truth_frames']} 训练段帧 "
              f"(非训练段 {s['stage_non_train_frames']}) · 逐段 {s['per_stage_acc']}")
    else:
        print(f"③ 无门控 (dense 模型); 训练段帧 {s['stage_truth_frames']} 非训练段 {s['stage_non_train_frames']}")
    print(f"   一步预测 MAE: MOE {s['one_step_pred_mae_moe']} vs 持久基线 {s['one_step_pred_mae_persist']} (n={s['one_step_pred_n']})")
    if out["summary_truth_prior"]:
        t = out["summary_truth_prior"]
        print(f"④ 真值先验上界参考: acc {t['gate_self_stage_acc']} · 一步预测 MAE {t['one_step_pred_mae_moe']}")
    print(f"📄 {p}")
    print("MOE_BYPASS_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
