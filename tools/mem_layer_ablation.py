# -*- coding: utf-8 -*-
"""🧲➡️📊 记忆层逐层打开 · 同口径对照 (AB, 老倪口径: 每条杆杆出同口径对照)

目的: 回答"逐步打开每层记忆, 性能到底变了没有" —— 同一组 seed / 同一 ckpt / 同一引擎口径, 只改
data/memory_layers.json 的开关, 跑四臂:

    arm   L2 L3 L4   含义
    off   0  0  0    纯模型直驱 (与现有 L4 链完全一致 = 基线)
    L2    1  0  0    + 肌肉记忆技能势场 (冠军轨迹管)
    L23   1  1  0    + 工艺流程势场 (时序加权, 相位按状态判)
    L234  1  1  1    + 物理工作空间 (孔壁障碍 + 世界模型项)

每臂输出: 模型真推理次数 · 介入步数/w̄ · 模型 done/插入深度 · 解析链对照 done/插入深度 · 视频目录
→ 汇总 reports/mem_layer_ablation.json (+ 结论表: 相对 off 的插入深度/成功率变化)

用法 (GUI venv, 模型走 CPU 不抢训练 GPU):
  ./gui-venv311/bin/python tools/mem_layer_ablation.py --seeds 0,1 --steps 900 --device cpu
  (可选) --ckpt <checkpoints 下 policy 名>  默认自动挑最新 v4/v5 微调权重
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
ARMS = [("off", {"L2": 0, "L3": 0, "L4": 0}),
        ("L2", {"L2": 1, "L3": 0, "L4": 0}),
        ("L23", {"L2": 1, "L3": 1, "L4": 0}),
        ("L234", {"L2": 1, "L3": 1, "L4": 1})]
GATES = os.path.join(ROOT, "data", "memory_layers.json")


def _set_gates(g):
    cur = {}
    if os.path.isfile(GATES):
        try:
            cur = json.load(open(GATES, encoding="utf-8")) or {}
        except Exception:                                              # noqa: BLE001
            cur = {}
    cur.update({k: int(v) for k, v in g.items()})
    cur["assembly"] = int(cur.get("assembly", 0))
    cur["updated"] = time.strftime("%F %T")
    os.makedirs(os.path.dirname(GATES), exist_ok=True)
    json.dump(cur, open(GATES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return cur


def _latest_ckpt():
    import glob
    cache = os.environ.get("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
    best = None
    for fam in ("intact_goal_optical_insert_v5", "intact_goal_optical_insert_v4"):
        for p in glob.glob(os.path.join(cache, "checkpoints", fam + "*_s3072", "weights_epoch_*.pt")):
            try:
                ep = int(os.path.basename(p).split("_")[-1].split(".")[0])
            except Exception:                                          # noqa: BLE001
                ep = -1
            key = (fam.endswith("v5"), ep)          # v5 优先, 再比 epoch
            if best is None or key > best[0]:
                best = (key, os.path.join(os.path.basename(os.path.dirname(p)),
                                          os.path.basename(p)))
    return best[1] if best else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="0,1")
    ap.add_argument("--steps", type=int, default=900)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--ckpt", default="")
    ap.add_argument("--mode", default="insert")
    ap.add_argument("--stats", default=os.path.join(ROOT, "reports", "optical_insert_v4_action_stats.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "reports", "mem_layer_ablation.json"))
    a = ap.parse_args()

    policy = a.ckpt or _latest_ckpt()
    if not policy:
        print("❌ 没找到微调权重 (checkpoints/intact_goal_optical_insert_v{4,5}*_s3072/weights_epoch_*.pt)")
        return 2
    saved = json.load(open(GATES, encoding="utf-8")) if os.path.isfile(GATES) else {}
    print(f"═══ 记忆层逐层打开 · 同口径对照 ═══")
    print(f"   权重 {policy} · seeds {a.seeds} · 模式 {a.mode} · 步数 {a.steps} · 设备 {a.device}")
    print(f"   原始开关 {saved} (跑完还原)")

    rows = []
    try:
        for arm, g in ARMS:
            _set_gates(g)
            st = f"/tmp/memab_{arm}_status.json"
            sp = f"/tmp/memab_{arm}_spool"
            vd = os.path.join(ROOT, "reports", "intact_sw", f"video_memab_{arm}")
            print(f"\n── 臂 {arm}: 开关 {_set_gates(g)}")
            cmd = [os.path.join(ROOT, "gui-venv311", "bin", "python"),
                   os.path.join(ROOT, "tools", "intact_sw_optical_bridge.py"),
                   "--task", "optical_insert", "--seeds", a.seeds, "--mode", a.mode,
                   "--max-steps", str(a.steps), "--device", a.device,
                   "--policy", policy, "--stats", a.stats,
                   "--spool", sp, "--status", st, "--video-dir", vd, "--baseline-full", "0"]
            t0 = time.time()
            r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=7200)
            try:
                d = json.load(open(st, encoding="utf-8"))
            except Exception as e:                                     # noqa: BLE001
                print(f"   ❌ 状态读不到: {e} · rc={r.returncode} · tail={r.stdout[-300:]}")
                continue
            mi = d.get("memory_intervene") or {}
            mod = [x for x in (d.get("rows") or []) if x.get("model")]
            ana = [x.get("analytic") or {} for x in (d.get("rows") or [])]
            row = {"arm": arm, "gates": g, "ckpt": policy,
                   "model_calls": d.get("model_calls"), "steps": d.get("steps"),
                   "intervene_steps": mi.get("steps_applied"), "w_mean": mi.get("w_mean"),
                   "model_succ": d.get("model_succ"), "model_success_rate": d.get("model_success_rate"),
                   "model_eps": [{"seed": m.get("seed"), "done": m.get("done"),
                                  "insert_mm": m.get("insert_mm"), "calls": m.get("model_calls"),
                                  "u_raw_std": m.get("u_raw_std")} for m in mod],
                   "analytic_eps": [{"seed": x.get("seed"), "done": x.get("done"),
                                     "insert_mm": x.get("insert_mm")} for x in ana],
                   "video_dir": vd, "sec": round(time.time() - t0, 1)}
            rows.append(row)
            print(f"   模型 {row['model_succ']}/{len(mod)} · 介入 {row['intervene_steps']} 步 "
                  f"(w̄={row['w_mean']}) · 插入 "
                  f"{[e['insert_mm'] for e in row['model_eps']]}mm · {row['sec']}s")
    finally:
        if os.path.isfile(GATES):
            json.dump(saved or {"L2": 0, "L3": 0, "L4": 0, "assembly": 0},
                      open(GATES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(f"\n   开关已还原: {saved}")

    if not rows:
        print("❌ 没有任何臂跑出结果")
        return 3
    base = rows[0]
    def _d(x):
        try:
            return float(x)
        except Exception:                                              # noqa: BLE001
            return float("nan")
    print("\n═══ 结论表 (同口径对照, 基线 = off) ═══")
    print(f"   {'臂':<6}{'模型成功':<10}{'介入步':<8}{'w̄':<8}{'插入深度(mm)':<22}{'vs off 深度改善'}")
    for r in rows:
        ins = [e["insert_mm"] for e in r["model_eps"] if e.get("insert_mm") is not None]
        bi = [e["insert_mm"] for e in base["model_eps"] if e.get("insert_mm") is not None]
        delta = (round(sum(ins) / max(len(ins), 1) - sum(bi) / max(len(bi), 1), 1)
                 if ins and bi else None)
        print(f"   {r['arm']:<6}{str(r['model_succ']) + '/' + str(len(r['model_eps'])):<10}"
              f"{str(r['intervene_steps']):<8}{str(r['w_mean']):<8}"
              f"{str([round(v,1) for v in ins]):<22}{delta}")
    json.dump({"ts": time.strftime("%F %T"), "policy": policy, "seeds": a.seeds,
               "mode": a.mode, "steps": a.steps, "device": a.device,
               "arms": rows, "baseline_arm": "off",
               "note": "同 seed/同 ckpt/同引擎口径, 只改记忆层开关; 解析链对照每臂都跑 (可达性基线); "
                       "插入深度越小越好 (插入终点≈65mm 为解析链成功水平)"},
              open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"   → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
