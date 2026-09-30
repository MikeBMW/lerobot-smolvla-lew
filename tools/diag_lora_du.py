# -*- coding: utf-8 -*-
"""🔬 diag_lora_du.py — 「新 LoRA 为何不改指令」逐帧 Δu 增量诊断 (2026-09-24)

老倪交接单「下次接手第一件事」的取证工具。候选根因:
  ① 归一化 stats 不同源   ② 直连线 scale/阈值把增量压没   ③ 只训 200 步 + 基座冻结 → 增量近零
判据全部逐帧取实测, 不靠推断:
  · Δu_raw   = ‖L4 原始意图 u − 解析链 u‖      ← 策略本身有没有产生不同意图 (l4_u_ff_vec)
  · Δu_final = ‖最终 u_ff − 解析链 u_ff‖       ← 是否真的改变了下发指令 (u_ff_vec)
  · Δu_exec  = ‖执行 u − 解析链执行 u‖         ← 过收口闸后还剩多少 (u_exec_vec)
  · 逐位相等帧占比 (allclose(atol=0,rtol=0)) + 各维 |Δ| 均值
  · l4_w / l4_gate / 直连线 w 分布              ← 增量是否被融合权重/势场闸门吃掉
副产物: 每臂每 seed 的逐帧序列存 npz, 供跨 policy 对比 (current vs v6lora 的原始意图差)。

隔离口径 (与 ab_l4_policy_multiseed.sh 同口径, 但更强):
  · 每 (arm,seed) 独立冷记忆文件 (SS_MUSCLE_PATH 按 arm+seed 派生) → 排除肌肉记忆跨臂污染
  · 每 policy 一个进程 (INTACT_POLICY 在进程启动时定), 两次运行由 shell 顺序驱动

用法:
  INTACT_POLICY=intact_l4_v6lora_200 MUJOCO_GL=egl ./gui-venv311/bin/python \
      tools/diag_lora_du.py --seeds 0,1,2 --steps 180
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter

import numpy as np

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("DISPLAY", ":0")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUI = os.path.join(ROOT, "tools", "gui")
for _p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "tools"), GUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.chdir(GUI)
for _k, _v in (("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache"),
               ("LOCAL_DATASET_DIR", "/home/ubuntu/stable-wm-cache"),
               ("INTACT_RUNTIME", "root"), ("INTACT_POLICY", "intact_l4_current"),
               ("OMP_NUM_THREADS", "6")):
    os.environ.setdefault(_k, _v)

# 臂: (L4直驱?, 直连线?, 注入权重)  — 与 ab_intent_line_closedloop.py 完全同名同义
ARMS = {"analytic": (False, False, 0.0),
        "direct":   (True, False, 0.0),
        "line_w1":  (True, True, 1.0)}


def hh(a) -> str:
    a = np.ascontiguousarray(np.asarray(a, float))
    return hashlib.sha256(a.tobytes()).hexdigest()[:16]


def sha256_file(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:16]


def policy_fingerprint(pol: str) -> dict:
    """取证: 本进程真正加载的权重文件 (路径 + sha256 + 大小) — 防「跑的不是它」。"""
    d = os.path.join(os.environ.get("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache"),
                     "checkpoints", pol)
    out = {"policy": pol, "dir": d, "exists": os.path.isdir(d), "pt": {}}
    if not out["exists"]:
        return out
    for f in sorted(os.listdir(d)):
        if f.endswith(".pt"):
            p = os.path.join(d, f)
            out["pt"][f] = {"mb": round(os.path.getsize(p) / 1e6, 1), "sha256_16": sha256_file(p)}
    return out


def run_arm(seed: int, arm: str, steps: int) -> dict:
    l4, line, w = ARMS[arm]
    if l4:
        os.environ["SS_L4_INTACT"] = "1"
    else:
        os.environ.pop("SS_L4_INTACT", None)
    if line:
        os.environ["SS_L4_INTENT_LINE"] = "1"
        os.environ["SS_L4_INTENT_LINE_W"] = str(w)
    else:
        os.environ.pop("SS_L4_INTENT_LINE", None)
        os.environ.pop("SS_L4_INTENT_LINE_W", None)
    os.environ.pop("SS_L4_INTACT_STAGES", None)
    # 🧊 冷记忆隔离: 每 (arm, seed) 一份 → 排除「越练越顺」跨臂污染
    os.environ["SS_MUSCLE_PATH"] = f"/tmp/diag_du_{os.getpid()}_{arm}_{seed}.json"
    try:
        os.remove(os.environ["SS_MUSCLE_PATH"])
    except OSError:
        pass

    from state_space_sim_real import RealStateSpaceSim
    from lerobot.manifold.intact_node import IntactNode, IntactRuntime
    t0 = time.time()
    sim = RealStateSpaceSim(seed=seed, vision=False, mode="insert", log=lambda *x: None)
    node = IntactNode(horizon=8, runtime=IntactRuntime(task="pusht", device="cpu"))
    sim.attach_intact(node)                       # 与 A/B 同口径: 解析臂也挂节点 (env 决定是否生效)
    tr = sim.run(max_steps=steps)

    def ser(key):
        v = tr.get(key) or []
        return [None if x is None else np.asarray(x, float).ravel() for x in v]

    stg = [str(x).replace("阶段 ", "") for x in (tr.get("stage") or [])]
    rec = {
        "seed": seed, "arm": arm, "n": len(tr.get("t", [])),
        "stage_counts": dict(Counter(stg)),
        "done": bool((tr.get("done") or [False])[-1]),
        "u_ff": ser("u_ff_vec"), "u_exec": ser("u_exec_vec"),
        "l4_u": ser("l4_u_ff_vec"), "il_u": ser("il_u_ff_vec"),
        "l4_w": [float(x) for x in (tr.get("l4_w") or [])],
        "il_w": [float(x) for x in (tr.get("il_w") or [])],
        "l4_gate": [float(x) for x in (tr.get("l4_gate") or [])],
        # 🛡 闸门内部量 (判定"被闸掉"的具体原因: cos<0 方向否决 / mag>1.5 幅值否决)
        "l4_cos": [float(x) for x in (tr.get("l4_cos") or []) if x is not None],
        "l4_mag": [float(x) for x in (tr.get("l4_mag_ratio") or []) if x is not None],
        "l4_cos_pre": [float(x) for x in (tr.get("l4_cos_pre_align") or []) if x is not None],
        "l4_sum": sim.l4_intact_summary(),
        "il_sum": sim.l4_intent_line_summary(),
        "sec": round(time.time() - t0, 1),
    }
    return rec


def first_ok(series):
    for x in series:
        if x is not None and x.size:
            return x
    return None


def nz(series, idx: int):
    x = series[idx] if idx < len(series) else None
    return None if x is None or x.size == 0 else x


def metrics(base_series, arm_series, dims=None):
    """逐帧对齐比较: 逐位相等帧数 / ‖Δ‖ 统计 / 各维 |Δ| 均值。"""
    n = min(len(base_series), len(arm_series))
    same, dn, per_dim, idx_same = 0, [], [], []
    for i in range(n):
        a, b = base_series[i], arm_series[i]
        if a is None or b is None or a.size == 0 or b.size == 0:
            continue
        k = min(a.size, b.size) if dims is None else dims
        a, b = a[:k], b[:k]
        if np.array_equal(a, b):
            same += 1
            idx_same.append(i)
        d = b - a
        dn.append(float(np.linalg.norm(d)))
        per_dim.append(np.abs(d))
    if not dn:
        return {"frames": 0}
    P = np.stack(per_dim)
    return {"frames": len(dn), "identical_frames": same,
            "identical_frac": round(same / len(dn), 3),
            "d_norm_mean": round(float(np.mean(dn)), 8),
            "d_norm_max": round(float(np.max(dn)), 8),
            "d_norm_nonzero_frac": round(float(np.mean(np.asarray(dn) > 0)), 3),
            "per_dim_abs_mean": [round(float(x), 8) for x in P.mean(axis=0)],
            "first_identical_idx": idx_same[:5]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--steps", type=int, default=180)
    ap.add_argument("--arms", default="analytic,direct,line_w1")
    a = ap.parse_args()
    seeds = [int(x) for x in a.seeds.split(",") if x.strip()]
    arms = [x.strip() for x in a.arms.split(",") if x.strip()]
    pol = os.environ.get("INTACT_POLICY")
    ts = time.strftime("%Y%m%d_%H%M%S")
    outdir = os.path.join(ROOT, "reports")
    os.makedirs(outdir, exist_ok=True)
    jp = os.path.join(outdir, f"diag_lora_du_{ts}_{pol}.json")
    npz = os.path.join(outdir, f"diag_lora_du_{ts}_{pol}.npz")

    def say(s):
        print(s, flush=True)

    fp = policy_fingerprint(pol)
    say(f"===== Δu 增量诊断 · INTACT_POLICY={pol} · steps={a.steps} =====")
    say(f"[权重指纹] {json.dumps(fp, ensure_ascii=False)}")

    runs, store = {}, {}
    for sd in seeds:
        for arm in arms:
            try:
                r = run_arm(sd, arm, a.steps)
            except Exception as e:                                        # noqa: BLE001
                say(f"[seed{sd} {arm:8s}] ❌ {type(e).__name__}: {e}")
                runs[f"{sd}:{arm}"] = {"error": f"{type(e).__name__}: {e}"}
                continue
            runs[f"{sd}:{arm}"] = {k: v for k, v in r.items()
                                   if k not in ("u_ff", "u_exec", "l4_u", "il_u")}
            store[f"{sd}:{arm}"] = r
            ls, ils = r["l4_sum"], r["il_sum"]
            say(f"[seed{sd} {arm:8s}] n={r['n']} done={r['done']} {r['sec']}s · "
                f"L4(calls={ls.get('calls')} blend={ls.get('blend')} w_zero={ls.get('w_zero')} "
                f"refused={ls.get('refused')} w={ls.get('w')} src={ls.get('u_ff_src')} err={ls.get('err')}) · "
                f"直连线(ran={ils.get('ran')} applied={ils.get('applied')} w_last={ils.get('w_last')})")

    # ── 对照: 每 seed 的解析链锚 ─────────────────────────────────────────────
    say("\n===== Δu 逐帧对照 (基准=同 seed 解析链 analytic) =====")
    cmp_all = {}
    for sd in seeds:
        base = store.get(f"{sd}:analytic")
        if base is None:
            say(f"[seed{sd}] 无解析链基准, 跳过")
            continue
        for arm in arms:
            if arm == "analytic":
                continue
            r = store.get(f"{sd}:{arm}")
            if r is None:
                continue
            m_final = metrics(base["u_ff"], r["u_ff"])
            m_exec = metrics(base["u_exec"], r["u_exec"])
            m_raw = metrics(base["u_ff"], r["l4_u"])
            cmp_all[f"{sd}:{arm}"] = {"final": m_final, "exec": m_exec, "raw_l4": m_raw}
            say(f"[seed{sd} {arm:8s}]")
            say(f"   Δu_final : {json.dumps(m_final, ensure_ascii=False)}")
            say(f"   Δu_exec  : d_mean={m_exec.get('d_norm_mean')} d_max={m_exec.get('d_norm_max')} "
                f"逐位相同帧={m_exec.get('identical_frames')}/{m_exec.get('frames')}")
            say(f"   Δu_rawL4 : d_mean={m_raw.get('d_norm_mean')} d_max={m_raw.get('d_norm_max')} "
                f"逐位相同帧={m_raw.get('identical_frames')}/{m_raw.get('frames')} "
                f"非零帧占比={m_raw.get('d_norm_nonzero_frac')}")
            lw = np.asarray(r["l4_w"], float) if r["l4_w"] else np.zeros(1)
            gw = Counter(r["l4_gate"]) if r["l4_gate"] else {}
            say(f"   L4融合w  : 均值={lw.mean():.4f} >0帧={int((lw > 0).sum())}/{lw.size} "
                f"max={lw.max():.4f} · gate计数={dict(gw)}")
            if r.get("l4_cos"):
                c = np.asarray(r["l4_cos"], float)
                m = np.asarray(r["l4_mag"], float) if r.get("l4_mag") else np.zeros(1)
                say(f"   闸门量   : cos 中位={np.median(c):.3f} 负帧={int((c < 0).sum())}/{c.size} "
                    f"· mag比 中位={np.median(m):.3f} >1.5帧={int((m > 1.5).sum())}/{m.size} "
                    f"· 否决明细(方向/幅值)={r['l4_sum'].get('l2_veto_dir')}/{r['l4_sum'].get('l2_veto_mag')}")
            if r.get("l4_cos_pre"):
                cp = np.asarray(r["l4_cos_pre"], float)
                say(f"   对齐前cos: 中位={np.median(cp):.3f} 负帧={int((cp < 0).sum())}/{cp.size}")
            # 原始意图自身幅度 (与解析链是否同量级)
            fa = first_ok(r["l4_u"])
            fb = first_ok(base["u_ff"])
            if fa is not None and fb is not None:
                k = min(fa.size, fb.size)
                say(f"   首帧|u|  : L4原始={np.abs(fa[:k]).round(5).tolist()} vs 解析={np.abs(fb[:k]).round(5).tolist()}")

    blobs = {}
    for k, r in store.items():
        for tag in ("u_ff", "u_exec", "l4_u"):
            series = r[tag]
            arr = np.full((max(1, len(series)), 1), np.nan)
            for i, x in enumerate(series):
                if x is not None and np.asarray(x).size:
                    arr[i, 0] = float(np.linalg.norm(np.asarray(x, float)[:3]))
            blobs[f"{k.replace(':', '_')}__{tag}"] = arr
    blobs["meta"] = np.array([json.dumps({"policy": pol, "ts": ts, "steps": a.steps,
                                          "seeds": seeds, "arms": arms},
                                         ensure_ascii=False)], dtype=object)
    np.savez_compressed(npz, **blobs)
    json.dump({"ts": ts, "policy": pol, "steps": a.steps, "policy_fingerprint": fp,
               "runs": runs, "compare": cmp_all},
              open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    say(f"\n→ 报告 {jp}\n→ 序列 {npz}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
