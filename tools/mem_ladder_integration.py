# -*- coding: utf-8 -*-
"""🧲📊 记忆层集成阶梯 (L2 准确性 → L3 调度 → L4 抗干扰 → 总装) · 同口径 + 可续跑 + 不后退历史

老倪 2026-09-13: "开始集成 L2肌肉记忆 L3流程记忆 L4工作记忆 和总装记忆… 要稳步推进, 从 L2 到 L3 再到
L4 … 我要看到最终的成功抗干扰的插拔, 且高效稳定的结果 … 能力要稳步提升, 不要有波动。数据一致性最重要。"

设计 (每一格都能回答"能力是怎么变的"):
  ① **数据一致性 preflight** — 每次跑先冻结 一份 manifest: 反归一化 stats 文件 (含 sha256 + action_space),
     权重文件 sha256 + epoch, 记忆层开关快照, 引擎/桥/势场 源码 sha256 + git rev, seeds/cap/steps 口径。
     同 manifest_hash 的结果才可横向比较; manifest 变了 = 换了一批条件, 历史行分开记。
  ② **运行矩阵 (可续跑)** — 臂 × 干扰档 × seed。任一格跑完就 append 到 runs.jsonl;
     重跑同一 manifest 会自动跳过已完成的格 (断点续跑, 不重复烧机时)。
       臂: off / L2 / L23 / L234 / assy(总装仲裁)
       干扰档: none(引擎 cap=l3, 无注入) / disturb(引擎 cap=l4, **真注入**来料移位/转向 + 恢复预算×2)
       → 抗干扰能力 = succ(disturb) / succ(none) (同 seed 同权重, 只差是否注入 = 同口径)
  ③ **阶梯闸 (不后退是第一优先)**:
       N1 准确性: L2 在无干扰下 成功率 ≥ off 且 平均插入深度不差于 off+2mm
       N2 调度:   L23 ≥ L2 (成功率不降, 平均插入深度不劣化 >2mm)
       N3 抗干扰: L234 在**干扰档** 成功率 ≥ L234 无干扰 − 1/n_seeds, 且 ≥ off 干扰档
       N4 总装:   assy 干扰档 ≥ 其它任一臂干扰档
       N5 高效零搜索: 每行 zero_search=True (candidate_sequences=0), 模型调用/步 ≤ 1.05, 记录 P95 步耗时
       N6 稳定:   逐臂跨 seed 插入深度 std 报出 (>25mm 标"波动大", 不算通过)
  ④ **历史 (能力怎么提升的)**: 每行 append 到 ladder_history.csv (含 manifest_hash/ckpt/代码版本),
     跨 ckpt (v4→v5) 的同一格可直接对比 → 能力提升/回退一眼可见。

用法 (GUI venv; 模型走 CPU 不抢训练 GPU):
  ./gui-venv311/bin/python tools/mem_ladder_integration.py --seeds 0,1 --steps 1000
  ./gui-venv311/bin/python tools/mem_ladder_integration.py --seeds 0,1,2 --arms off,L2,L23,L234,assy \
        --disturbs none,disturb --ckpt intact_goal_optical_insert_v5_s3072/weights_epoch_4.pt
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
OUTDIR = os.path.join(ROOT, "reports", "mem_ladder")
GATES = os.path.join(ROOT, "data", "memory_layers.json")
RUNS = os.path.join(OUTDIR, "runs.jsonl")
HIST = os.path.join(OUTDIR, "ladder_history.csv")
STATS = os.path.join(ROOT, "reports", "optical_insert_v4_action_stats.json")

ARMS = [("off",  {"L2": 0, "L3": 0, "L4": 0, "assembly": 0}),
        ("L2",   {"L2": 1, "L3": 0, "L4": 0, "assembly": 0}),
        ("L23",  {"L2": 1, "L3": 1, "L4": 0, "assembly": 0}),
        ("L234", {"L2": 1, "L3": 1, "L4": 1, "assembly": 0}),
        ("assy", {"L2": 1, "L3": 1, "L4": 1, "assembly": 1})]
DISTURBS = [("none", "l3"), ("disturb", "l4")]      # cap=l3 无注入 / cap=l4 真注入干扰

# ── 🐛 2026-09-14 数据一致性修复 (实测抓到的真问题) ──
#   同一 seed / 同 cap / 同权重 / 同代码, 解析链结果却从 65.26mm(done) 漂到 58.02mm(not done) ——
#   原因是**记忆状态文件是可变状态**: 引擎每跑一局都可能把成功轨迹固化进 data/muscle_memory.json
#   (还有 assembly_memory.json 台账 / shared_memory.json), 而这些文件既不在 manifest 里, 也不会在
#   格与格之间复位 → 后面的格看到的"记忆"和前面的格不一样 ⇒ 同口径被悄悄破坏。
#   修法: ① 把记忆状态文件 + 引擎读的 models/*.pt 纳入 manifest sha256 ② 每格开跑前把记忆状态
#   **复位到本 manifest 的快照** (所有格起点一致), 跑完把该格产生的状态另存为 artifact (不丢证据)。
STATE_FILES = ["data/muscle_memory.json", "data/assembly_memory.json", "data/shared_memory.json",
               "data/memory_layers.json"]


# ─────────────── ① 数据一致性 ───────────────
def _sha(p: str, n: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(n)
            if not b:
                break
            h.update(b)
    return h.hexdigest()[:16]


def latest_ckpt() -> str:
    """v5 优先 (新), 再比 epoch; 返回 checkpoints 下的相对路径 (policy 名)。"""
    import glob as _g
    cache = os.environ.get("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
    best = None
    for fam in ("intact_goal_optical_insert_v5", "intact_goal_optical_insert_v4"):
        for p in _g.glob(os.path.join(cache, "checkpoints", fam + "*_s3072", "weights_epoch_*.pt")):
            try:
                ep = int(os.path.basename(p).split("_")[-1].split(".")[0])
            except Exception:                                        # noqa: BLE001
                ep = -1
            key = (fam.endswith("v5"), ep)
            if best is None or key > best[0]:
                best = (key, f"{os.path.basename(os.path.dirname(p))}/{os.path.basename(p)}")
    return best[1] if best else ""


def _rehash(m: dict) -> str:
    body = json.dumps({k: v for k, v in m.items() if k != "ts"}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(body.encode()).hexdigest()[:12]


def build_manifest(policy: str, seeds, steps: int, mode: str, device: str,
                   state_hashes: dict | None = None) -> dict:
    cache = os.environ.get("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
    ck = os.path.join(cache, "checkpoints", policy) if policy else ""
    m = {"ts": time.strftime("%F %T"), "policy": policy,
         "ckpt_sha256_16": _sha(ck) if ck and os.path.isfile(ck) else None,
         "ckpt_bytes": os.path.getsize(ck) if ck and os.path.isfile(ck) else None,
         "stats": os.path.basename(STATS), "stats_sha256_16": _sha(STATS) if os.path.isfile(STATS) else None,
         "seeds": seeds, "max_steps": steps, "mode": mode, "device": device,
         "gates": json.load(open(GATES, encoding="utf-8")) if os.path.isfile(GATES) else {},
         "state_sha256_16": (dict(state_hashes) if state_hashes is not None
                             else {rel: None for rel in STATE_FILES}),
         "models_sha256_16": {os.path.basename(p): _sha(p)
                              for p in sorted(glob.glob(os.path.join(ROOT, "models", "*.pt")))},
         "code": {}, "git": None}
    for rel in ("tools/gui/state_space_sim_real.py", "tools/intact_sw_optical_bridge.py",
                "src/lerobot/memory/potential_field.py", "src/lerobot/memory/mem_nodes.py",
                "tools/mem_ladder_integration.py"):
        p = os.path.join(ROOT, rel)
        m["code"][rel] = _sha(p) if os.path.isfile(p) else None
    try:
        m["git"] = subprocess.run(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"],
                                  capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:                                                # noqa: BLE001
        pass
    try:                                                             # stats 口径 (反归一化同源证据)
        d = json.load(open(STATS, encoding="utf-8"))
        m["stats_meta"] = {k: d.get(k) for k in ("action_space", "n_finite", "slot", "note")
                           if k in d}
    except Exception:                                                # noqa: BLE001
        pass
    m["manifest_hash"] = _rehash(m)
    return m


# ─────────────── ② 运行矩阵 ───────────────
def set_gates(g: dict) -> dict:
    cur = {}
    if os.path.isfile(GATES):
        try:
            cur = json.load(open(GATES, encoding="utf-8")) or {}
        except Exception:                                            # noqa: BLE001
            cur = {}
    cur.update({k: int(v) for k, v in g.items()})
    cur["updated"] = time.strftime("%F %T")
    json.dump(cur, open(GATES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return cur


def restore_gates(saved: dict) -> None:
    if isinstance(saved, dict) and saved:
        saved.pop("note", None)
        json.dump(saved, open(GATES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


# ── 记忆状态快照 / 复位 (同 manifest 所有格起点一致) ──
def snapshot_state(dst: str) -> dict:
    os.makedirs(dst, exist_ok=True)
    snap = {}
    for rel in STATE_FILES:
        src = os.path.join(ROOT, rel)
        if os.path.isfile(src):
            d = os.path.join(dst, os.path.basename(rel))
            shutil.copy2(src, d)
            snap[rel] = _sha(d)
        else:
            snap[rel] = None
    return snap


def restore_state(src: str) -> None:
    """把记忆状态复位到快照 (格与格之间必须一致, 否则同口径被悄悄破坏)。"""
    for rel in STATE_FILES:
        a = os.path.join(src, os.path.basename(rel))
        b = os.path.join(ROOT, rel)
        if os.path.isfile(a):
            os.makedirs(os.path.dirname(b) or ".", exist_ok=True)
            shutil.copy2(a, b)


def save_state_artifact(tag: str) -> dict:
    """跑完把该格产生的记忆状态另存 (证据不丢), 返回 sha 便于比较。"""
    out = {}
    for rel in STATE_FILES:
        p = os.path.join(ROOT, rel)
        if os.path.isfile(p):
            d = os.path.join(OUTDIR, "state_after", f"{tag}__{os.path.basename(rel)}")
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(p, d)
            out[rel] = _sha(p)
    return out


def done_keys() -> set:
    ks = set()
    if os.path.isfile(RUNS):
        for ln in open(RUNS, encoding="utf-8"):
            try:
                r = json.loads(ln)
                ks.add((r["manifest_hash"], r["arm"], r["disturb"], int(r["seed"])))
            except Exception:                                        # noqa: BLE001
                continue
    return ks


def run_cell(arm: str, gates: dict, disturb: str, cap: str, seed: int, policy: str,
             a, man: dict, snapdir: str = "") -> dict:
    set_gates(gates)
    if snapdir:
        restore_state(snapdir)          # 每格起点 = 本 manifest 的记忆快照 (同口径)
    tag = f"{arm}_{disturb}_s{seed}"
    stp = f"/tmp/memladder_{tag}_status.json"
    spool = f"/tmp/memladder_{tag}_spool"
    vdir = os.path.join(OUTDIR, "video", tag)
    os.makedirs(vdir, exist_ok=True)
    os.makedirs(spool, exist_ok=True)
    cmd = [os.path.join(ROOT, "gui-venv311", "bin", "python"),
           os.path.join(ROOT, "tools", "intact_sw_optical_bridge.py"),
           "--task", "optical_insert", "--seeds", str(seed), "--mode", a.mode,
           "--max-steps", str(a.steps), "--device", a.device, "--cap", cap,
           "--policy", policy, "--stats", STATS, "--infer-every", str(a.infer_every),
           "--chunk-step", str(a.chunk_step),
           "--spool", spool, "--status", stp, "--video-dir", vdir, "--baseline-full", "0"]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=a.cell_timeout)
        rc = r.returncode
        tail = (r.stdout or "")[-400:]
    except subprocess.TimeoutExpired:
        rc, tail = 124, f"timeout {a.cell_timeout}s"
    sec = round(time.time() - t0, 1)
    try:
        d = json.load(open(stp, encoding="utf-8"))
    except Exception as e:                                           # noqa: BLE001
        d = {"ok": False, "read_err": f"{type(e).__name__}: {e}"}
    # ⚠️ d["rows"] 的每一项是 {"seed":…, "analytic":{…}, "model":{…}} → 取 model 子字典
    mod = [x["model"] for x in (d.get("rows") or []) if isinstance(x.get("model"), dict)]
    ana = [x.get("analytic") or {} for x in (d.get("rows") or [])]
    mi = d.get("memory_intervene") or {}
    row = {"manifest_hash": man["manifest_hash"], "ts": time.strftime("%F %T"),
           "arm": arm, "gates": gates, "disturb": disturb, "cap": cap, "seed": int(seed),
           "ckpt": policy, "git": man.get("git"), "rc": rc, "seconds": sec,
           "model_calls": d.get("model_calls"), "steps": d.get("steps"),
           "model_succ": d.get("model_succ"), "model_success_rate": d.get("model_success_rate"),
           "zero_search": bool(d.get("zero_search")), "err": d.get("err"),
           "memory_intervene": mi,
           "model_eps": [{"seed": m.get("seed"), "done": m.get("done"), "insert_mm": m.get("insert_mm"),
                          "calls": m.get("model_calls"), "steps": m.get("steps"),
                          "u_raw_std": m.get("u_raw_std"), "disturb": m.get("disturb"),
                          "seconds": m.get("seconds")} for m in mod],
           "analytic_eps": [{"seed": x.get("seed"), "done": x.get("done"),
                             "insert_mm": x.get("insert_mm"), "disturb": x.get("disturb")} for x in ana],
           "cell_tail": tail if rc != 0 else ""}
    os.makedirs(OUTDIR, exist_ok=True)
    if snapdir:
        row["state_after"] = save_state_artifact(tag)   # 本格产生的记忆状态 (证据)
    with open(RUNS, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    try:                                                             # 帧不落库 (省磁盘), 视频留档
        shutil.rmtree(spool, ignore_errors=True)
    except Exception:                                                # noqa: BLE001
        pass
    return row


# ─────────────── ③ 汇总 + 阶梯闸 ───────────────
def agg(rows: list) -> dict:
    out = {}
    for r in rows:
        k = (r["arm"], r["disturb"])
        d = out.setdefault(k, {"n": 0, "succ": 0, "depths": [], "calls": 0, "recs": [],
                               "w_mean": [], "applied": 0, "sec": [], "steps": []})
        for m in (r.get("model_eps") or []):
            d["n"] += 1
            d["succ"] += int(bool(m.get("done")))
            if m.get("insert_mm") is not None:
                d["depths"].append(float(m["insert_mm"]))
            d["calls"] += int(m.get("calls") or 0)
            d["steps"].append(int(m.get("steps") or 0))
            d["recs"].append(m)
        mi = r.get("memory_intervene") or {}
        if mi.get("w_mean") is not None:
            d["w_mean"].append(float(mi["w_mean"]))
        d["applied"] += int(mi.get("steps_applied") or 0)
        d["sec"].append(float(r.get("seconds") or 0))
    for k, d in out.items():
        n = max(d["n"], 1)
        ds = d["depths"]
        d["succ_rate"] = round(100.0 * d["succ"] / n, 1)
        d["depth_mean"] = round(sum(ds) / len(ds), 1) if ds else None
        d["depth_std"] = round((sum((x - sum(ds) / len(ds)) ** 2 for x in ds) / len(ds)) ** 0.5, 1) if ds else None
        d["w_mean_avg"] = round(sum(d["w_mean"]) / len(d["w_mean"]), 4) if d["w_mean"] else None
        d["calls_per_step"] = round(d["calls"] / max(sum(d["steps"]), 1), 3)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="0,1")
    ap.add_argument("--steps", type=int, default=1000)
    ap.add_argument("--mode", default="insert")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--ckpt", default="")
    ap.add_argument("--arms", default="off,L2,L23,L234,assy")
    ap.add_argument("--disturbs", default="none,disturb")
    ap.add_argument("--infer-every", type=int, default=1)
    ap.add_argument("--chunk-step", type=int, default=0)
    ap.add_argument("--cell-timeout", type=int, default=5400)
    ap.add_argument("--outdir", default="", help="结果目录 (默认 reports/mem_ladder; 冒烟测试可指到 /tmp)")
    ap.add_argument("--no-freeze-state", dest="freeze_state", action="store_false",
                    help="不复位记忆状态快照 (默认复位; 关掉=接受记忆漂移, 不建议)")
    a = ap.parse_args()

    global OUTDIR, RUNS, HIST
    if a.outdir:
        OUTDIR = os.path.abspath(a.outdir)
        RUNS = os.path.join(OUTDIR, "runs.jsonl")
        HIST = os.path.join(OUTDIR, "ladder_history.csv")

    seeds = [int(x) for x in str(a.seeds).split(",") if x.strip()]
    arms = [t for t in ARMS if t[0] in {x.strip() for x in a.arms.split(",")}]
    dists = [t for t in DISTURBS if t[0] in {x.strip() for x in a.disturbs.split(",")}]
    policy = a.ckpt or latest_ckpt()
    if not policy:
        print("❌ 没有可用微调权重 (checkpoints/intact_goal_optical_insert_v{4,5}*_s3072/weights_epoch_*.pt)")
        return 2
    os.makedirs(OUTDIR, exist_ok=True)

    print("═" * 92)
    print("🧲 记忆层集成阶梯 (L2 准确性 → L3 调度 → L4 抗干扰 → 总装仲裁)")
    # 先算 core hash (不含记忆状态) → 快照目录名; 再把快照的 sha 并进 manifest 重算 hash
    man = build_manifest(policy, seeds, a.steps, a.mode, a.device)
    snapdir = ""
    if a.freeze_state:
        snapdir = os.path.join(OUTDIR, f"state_snap_{man['manifest_hash']}")
        if not (os.path.isdir(snapdir) and os.listdir(snapdir)):
            snapshot_state(snapdir)                    # 第一跑: 以当前记忆状态为本批起点
        man["state_sha256_16"] = {
            rel: (_sha(os.path.join(snapdir, os.path.basename(rel)))
                  if os.path.isfile(os.path.join(snapdir, os.path.basename(rel))) else None)
            for rel in STATE_FILES}
        man["state_snapshot_dir"] = os.path.relpath(snapdir, ROOT)
        man["manifest_hash"] = _rehash(man)
    mp = os.path.join(OUTDIR, f"manifest_{man['manifest_hash']}.json")
    json.dump(man, open(mp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"① 数据一致性 manifest → {os.path.relpath(mp, ROOT)}  (hash={man['manifest_hash']})")
    print(f"   权重 {policy} · sha256[:16]={man['ckpt_sha256_16']} · {man['ckpt_bytes']}B")
    print(f"   反归一化 {man['stats']} · sha256[:16]={man['stats_sha256_16']} · meta={man.get('stats_meta')}")
    print(f"   代码 git={man['git']} · 引擎/桥/势场 sha256[:16]="
          f"{[v for v in man['code'].values()]}")
    print(f"   记忆开关快照 {man['gates']}")
    print(f"   记忆状态快照 {man.get('state_sha256_16')} (目录 {man.get('state_snapshot_dir')}) "
          f"→ 每格开跑前复位, 所有格起点一致 (数据一致性)")
    print(f"② 矩阵: {len(arms)} 臂 × {len(dists)} 干扰档 × {len(seeds)} seed = "
          f"{len(arms) * len(dists) * len(seeds)} 格 · 步数 {a.steps} · 设备 {a.device}")

    saved = json.load(open(GATES, encoding="utf-8")) if os.path.isfile(GATES) else {}
    have = done_keys()
    rows, skipped = [], 0
    try:
        for arm, gates in arms:
            for disturb, cap in dists:
                for sd in seeds:
                    k = (man["manifest_hash"], arm, disturb, sd)
                    if k in have:
                        skipped += 1
                        print(f"   ⏭ 跳过 (已跑过) {arm}/{disturb}/seed{sd}")
                        continue
                    print(f"\n── 跑 {arm} · 干扰={disturb}(cap={cap}) · seed={sd} · 开关 {gates}")
                    row = run_cell(arm, gates, disturb, cap, sd, policy, a, man, snapdir=snapdir)
                    rows.append(row)
                    me = row["model_eps"][0] if row["model_eps"] else {}
                    print(f"   → done={me.get('done')} 插入={me.get('insert_mm')}mm "
                          f"调用={me.get('calls')} 步={me.get('steps')} "
                          f"介入={row['memory_intervene'].get('steps_applied')} "
                          f"w̄={row['memory_intervene'].get('w_mean')} · {row['seconds']}s "
                          f"· disturb={me.get('disturb')}")
    finally:
        restore_gates(saved)
        print(f"\n   记忆开关已还原: {saved}")

    # 汇总 (历史 manifest 的旧行也一并用上, 让"已跑过的格"参与统计)
    allrows = []
    if os.path.isfile(RUNS):
        for ln in open(RUNS, encoding="utf-8"):
            try:
                r = json.loads(ln)
            except Exception:                                        # noqa: BLE001
                continue
            if r["manifest_hash"] == man["manifest_hash"]:
                allrows.append(r)
    if not allrows:
        print("❌ 没有任何结果")
        return 3
    A = agg(allrows)

    print("\n" + "═" * 92)
    print("③ 同口径结果表 (成功率 = 模型直驱; 插入深度越小越接近孔底 65mm)")
    print(f"   {'臂':<6}{'干扰':<9}{'n':<4}{'成功':<6}{'成功率%':<9}{'深度均值':<9}{'深度std':<9}"
          f"{'调用/步':<9}{'介入步':<8}{'w̄':<8}{'秒/局'}")
    for (arm, dist), d in sorted(A.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        print(f"   {arm:<6}{dist:<9}{d['n']:<4}{d['succ']:<6}{str(d['succ_rate']):<9}"
              f"{str(d['depth_mean']):<9}{str(d['depth_std']):<9}{str(d['calls_per_step']):<9}"
              f"{str(d['applied']):<8}{str(d['w_mean_avg']):<8}"
              f"{round(sum(d['sec']) / max(len(d['sec']), 1))}")

    def sr(arm, dist):
        d = A.get((arm, dist))
        return d["succ_rate"] if d else None

    def dp(arm, dist):
        d = A.get((arm, dist))
        return d["depth_mean"] if d else None

    gates = []
    g1 = (sr("L2", "none") is not None and sr("off", "none") is not None
          and sr("L2", "none") >= sr("off", "none")
          and (dp("L2", "none") is None or dp("off", "none") is None
               or dp("L2", "none") <= dp("off", "none") + 2))
    gates.append(("N1 L2 准确性 (成功率≥off 且 深度不差 2mm)", g1,
                  f"off={sr('off','none')}% → L2={sr('L2','none')}% · 深度 {dp('off','none')}→{dp('L2','none')}"))
    g2 = sr("L23", "none") is not None and sr("L2", "none") is not None and sr("L23", "none") >= sr("L2", "none")
    gates.append(("N2 L3 调度 (L23 ≥ L2)", g2, f"L2={sr('L2','none')}% → L23={sr('L23','none')}%"))
    tol = 100.0 / max(len(seeds), 1)
    g3 = (sr("L234", "disturb") is not None and sr("L234", "none") is not None
          and sr("L234", "disturb") >= sr("L234", "none") - tol
          and sr("L234", "disturb") >= (sr("off", "disturb") or 0))
    gates.append(("N3 L4 抗干扰 (L234 干扰档 ≥ 自身无干扰 −1/n 且 ≥ off 干扰档)", g3,
                  f"L234 无干扰={sr('L234','none')}% / 干扰={sr('L234','disturb')}% · "
                  f"off 干扰={sr('off','disturb')}%"))
    others = [sr(x, "disturb") for x, _ in ARMS if x != "assy" and sr(x, "disturb") is not None]
    g4 = sr("assy", "disturb") is not None and others and sr("assy", "disturb") >= max(others)
    gates.append(("N4 总装 (assy 干扰档 ≥ 任一臂)", g4,
                  f"assy={sr('assy','disturb')}% vs max(其它)={max(others) if others else None}%"))
    zs = [(k, d["calls_per_step"]) for k, d in A.items()]
    g5 = all((d["calls_per_step"] or 0) <= 1.05 for _, d in A.items()) and all(
        r.get("zero_search") for r in allrows)
    gates.append(("N5 高效零搜索 (candidate_sequences=0 且 调用/步 ≤1.05)", g5, f"{zs}"))
    g6 = all(d["depth_std"] is None or d["depth_std"] <= 25 for d in A.values())
    gates.append(("N6 稳定 (跨 seed 深度 std ≤ 25mm)", g6,
                  f"{[(k, d['depth_std']) for k, d in sorted(A.items())]}"))

    print("\n④ 阶梯闸 (不后退第一)")
    for nm, ok, info in gates:
        print(f"   {'✅' if ok else '❌'} {nm}\n        {info}")

    ts = time.strftime("%Y%m%d_%H%M%S")
    summ = {"ts": time.strftime("%F %T"), "manifest": man, "n_runs": len(allrows),
            "new_runs": len(rows), "skipped": skipped, "agg": {f"{k[0]}|{k[1]}": v for k, v in A.items()},
            "gates": [{"name": n, "pass": bool(o), "info": i} for n, o, i in gates],
            "verdict": "PASS" if all(o for _, o, _ in gates) else "FAIL"}
    sp = os.path.join(OUTDIR, f"ladder_{ts}.json")
    json.dump(summ, open(sp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    new_hist = not os.path.isfile(HIST)
    with open(HIST, "a", encoding="utf-8") as f:
        if new_hist:
            f.write("ts,manifest,arm,disturb,n,succ,succ_rate,depth_mean,depth_std,calls_per_step,"
                    "intervene_steps,w_mean,seconds_per_ep,ckpt,git\n")
        for (arm, dist), d in sorted(A.items()):
            f.write(f"{summ['ts']},{man['manifest_hash']},{arm},{dist},{d['n']},{d['succ']},"
                    f"{d['succ_rate']},{d['depth_mean']},{d['depth_std']},{d['calls_per_step']},"
                    f"{d['applied']},{d['w_mean_avg']},"
                    f"{round(sum(d['sec']) / max(len(d['sec']), 1))},{policy},{man.get('git')}\n")
    print(f"\n   → 汇总 {os.path.relpath(sp, ROOT)} · 历史 {os.path.relpath(HIST, ROOT)} (append-only)")
    print(f"   阶梯结论: {summ['verdict']}")
    return 0 if summ["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
