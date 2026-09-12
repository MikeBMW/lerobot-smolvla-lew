# -*- coding: utf-8 -*-
"""🧪 Step 0 探针: 引擎**真实渲染帧** → INTACT 节点 → 潜空间曲线 + 五道闸 (旁路, 不接引擎)

为什么这么设计 (老倪 2026-09-12 拍板的顺序):
  你的两步走 = ① 先让 INTACT 出 action (屏蔽流形) ② 再接流形。
  但在此之前必须先解决**真实性前置**: 节点原来的 l4_episode 数据源观测是"依 meta 合成的
  运动序列"(该 npz 无渲染帧) —— 拿合成观测喂模型 = 蒙眼出动作 = 假结论。
  本探针只做旁路: 引擎跑 L4 全链拿**真实渲染帧** (corner2 相机 480² → 224²), 逐帧喂节点,
  记录潜空间 z_t / |Δ|=|z_goal−z_t| 与阶段名的关系。**不接 u_ff、不接流形** (Step 1/2 才做)。

五道闸 (不过就是没过, 不许口头宣布成功):
  G1 每步 chunk 非零 且 非常量 且 随观测变化 (零动作/常量 = 假推理)
  G2 潜空间导出成功: z_t/z_goal 存在、维度=192、非零
  G3 |Δ| 沿 接近→对位→下降→抓取→插入 呈**下降趋势** (Spearman ρ < 0, 这是 goal 意图有意义的最低证据)
  G4 观测来源全部 = engine_render (没有任何合成观测混入)
  G5 candidate_sequences == 0 (零搜索; 有候选搜索就不是 Direct)

用法:
  gui-venv311/bin/python tools/intact_render_probe.py --seed 0 --samples 20 --device cpu
  (--device cpu 默认: 与同机训练共用显卡时避免抢显存; 有富余显存可传 cuda)
"""
import argparse
import json
import os
import statistics as st
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("MUJOCO_GL", "glfw")
# 权重/数据缓存指向本机已有目录 (跨会话共用, 避免 worker 走 HF 重新下载 GB 级资产)
_CACHE = os.environ.get("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
if os.path.isdir(_CACHE):
    os.environ.setdefault("STABLEWM_HOME", _CACHE)
    os.environ.setdefault("LOCAL_DATASET_DIR", _CACHE)
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
import gen_l4_demo_video as G  # noqa: E402

import numpy as np  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REP = os.path.join(ROOT, "reports")
sys.path.insert(0, os.path.join(ROOT, "src"))
IMG = 224


def spearman(x, y):
    """秩相关 (不依赖 scipy)。"""
    def rank(v):
        idx = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for pos, i in enumerate(idx):
            r[i] = float(pos)
        return r
    rx, ry = rank(list(x)), rank(list(y))
    mx, my = st.mean(rx), st.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return (num / den) if den > 1e-12 else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--samples", type=int, default=20, help="沿链等距采样帧数")
    ap.add_argument("--horizon", type=int, default=8)
    ap.add_argument("--device", default=os.environ.get("INTACT_DEVICE", "cpu"))
    ap.add_argument("--task", default=os.environ.get("INTACT_TASK", "pusht"))
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    import cv2                                            # noqa: PLC0415
    from lerobot.manifold.intact_node import IntactNode, IntactRuntime   # noqa: PLC0415

    print(f"═══ Step0 探针: 引擎真实渲染帧 → INTACT (task={a.task}, device={a.device}) ═══", flush=True)
    print("── 1) 引擎跑 L4 全链 (真实渲染, record=True) ──", flush=True)
    t0 = time.time()
    demo = G.L4Demo(seed=a.seed, record=True, mani_yaw=True)
    try:
        ok, meta = demo.run_all()
    finally:
        frames = list(getattr(demo, "frames", []))
        stages = list((getattr(demo, "tr", {}) or {}).get("stage", []))
        try:
            demo.env.close()
        except Exception:
            pass
    print(f"   引擎完成: success={ok} steps={meta.get('steps')} · "
          f"渲染帧 {len(frames)} · 阶段记录 {len(stages)} · {time.time()-t0:.0f}s", flush=True)
    if not frames:
        print("❌ 没有渲染帧 → 无法做真实性验证 (中止, 不拿合成观测凑数)")
        return 2

    n = len(frames)
    aligned = len(frames) == len(stages)
    # 帧→阶段映射: 引擎里 frames 只在渲染步追加 (1630), 而 tr 每步都记 (4692) → 长度不等。
    #   诚实做法: 按比例映射 (标 "估算"), 不假装逐帧对齐。
    def stage_of(i: int) -> str:
        if not stages:
            return "?"
        if aligned:
            return stages[min(i, len(stages) - 1)]
        j = int(round(i * (len(stages) - 1) / max(1, len(frames) - 1)))
        return stages[j]

    print(f"   帧/阶段: 渲染帧 {len(frames)} vs 步记录 {len(stages)} → "
          f"{'逐帧严格对齐' if aligned else '按比例映射阶段名 (诚实标注: 估算, 非逐帧对齐)'}", flush=True)

    # 2) goal 帧 = 全链最后一帧 (任务完成态) → 224 (同样转 CHW)
    goal = cv2.resize(np.asarray(frames[-1]), (IMG, IMG),
                      interpolation=cv2.INTER_AREA).transpose(2, 0, 1).astype(np.float32)

    # 3) 节点 (真权重, 潜空间导出)
    rt = IntactRuntime(task=a.task, device=a.device)
    node = IntactNode(horizon=a.horizon, runtime=rt)
    node.set_goal(goal)
    d0 = node.diagnostics()
    print(f"   节点就绪: trained={d0['trained']} latent_dim={d0['latent_dim']} "
          f"policy={d0['policy']}", flush=True)
    if not node.runtime.trained:
        print(f"❌ 模型未就绪: {node.runtime.reason} (中止)")
        node.close()
        return 3

    # 4) 沿链等距采样 → 逐帧真前向
    idxs = sorted({int(round(i * (n - 1) / max(1, a.samples - 1))) for i in range(a.samples)})
    rows = []
    for k, i in enumerate(idxs):
        _img = np.asarray(frames[i])
        # 引擎渲染帧是 HWC (480²,3) → 节点契约是 [T,C,H,W] (CHW), 先转置再缩放
        fr = cv2.resize(_img, (IMG, IMG), interpolation=cv2.INTER_AREA).transpose(2, 0, 1).astype(np.float32)
        _t = time.perf_counter()
        out = node.step(fr, obs_source="engine_render")
        _dt = (time.perf_counter() - _t) * 1000.0
        diag = out.diagnostics
        zt = None if not out.latent else out.latent.get("z_t")
        dl = None if not out.latent else out.latent.get("delta")
        rows.append({
            "i": i, "stage": stage_of(i),
            "chunk_shape": list(np.asarray(out.chunk).shape),
            "chunk_nonzero": int(np.count_nonzero(out.chunk)),
            "chunk_std": round(float(np.std(out.chunk)), 5),
            "latent_ok": bool(zt is not None),
            "z_norm": round(float(np.linalg.norm(zt)), 4) if zt is not None else None,
            "intent_norm": round(float(np.linalg.norm(dl)), 4) if dl is not None else None,
            "latency_ms": round(_dt, 1),
            "cand_seq": diag.get("candidate_sequences"),
            "obs_source": out.obs_source, "trained": bool(out.trained),
        })
        print(f"   [{k+1:2d}/{len(idxs)}] i={i:5d} {rows[-1]['stage'][:22]:22s} "
              f"|z|={rows[-1]['z_norm']} |Δ|={rows[-1]['intent_norm']} "
              f"chunk{rows[-1]['chunk_shape']} nz={rows[-1]['chunk_nonzero']} "
              f"std={rows[-1]['chunk_std']:.4f}", flush=True)

    lat = node.diagnostics()
    node.close()

    # 5) 五道闸
    g1 = all(r["chunk_nonzero"] > 0 and r["chunk_std"] > 1e-6 for r in rows) \
        and len({r["chunk_std"] for r in rows}) > 1
    g2 = all(r["latent_ok"] for r in rows) and lat["latent_dim"] == 192
    x = list(range(len(rows)))
    y = [r["intent_norm"] for r in rows]
    have_y = all(v is not None for v in y)
    # ★ 诚实处理退化点: 最后采样帧 == goal 帧 → z_goal≡z_t → |Δ|≡0 是**构造性**的, 不是模型行为。
    #   所以同时给"含末点"和"剔除末点"两个 ρ, 判据用后者 (真正的趋势检验)。
    rho_all = round(spearman(x, y), 4) if have_y else None
    rho_wo = round(spearman(x[:-1], y[:-1]), 4) if have_y and len(y) > 3 else None
    g3 = (rho_wo is not None) and rho_wo < 0.0
    g4 = all(r["obs_source"] == "engine_render" for r in rows)
    g5 = all((r["cand_seq"] in (None, 0.0, 0)) for r in rows)
    gates = {
        "G1_chunk_real": bool(g1), "G2_latent_exported_192": bool(g2),
        "G3_intent_decreasing": bool(g3), "G4_obs_engine_render": bool(g4),
        "G5_zero_search": bool(g5),
    }

    # 6) 按阶段汇总 |Δ| (给"随相位下降"一个可读的表)
    bystage: dict = {}
    for r in rows:
        if r["intent_norm"] is None:
            continue
        bystage.setdefault(r["stage"], []).append(r["intent_norm"])
    stage_table = {k: {"n": len(v), "intent_norm_mean": round(st.mean(v), 4)} for k, v in bystage.items()}

    print("\n═══ 五道闸 ═══")
    for k, v in gates.items():
        print(f"   {'✅' if v else '❌'} {k}")
    print(f"   |Δ| 与进度 Spearman ρ = {rho_wo} (剔除末点; 期望 < 0 = 越接近目标意图越短) · "
          f"含末点 ρ={rho_all} (末点构造性为 0, 仅供参考)")
    print("\n═══ 按阶段 |Δ|=|z_goal−z_t| ═══")
    for k, v in stage_table.items():
        print(f"   {k[:24]:24s} n={v['n']:2d}  |Δ|={v['intent_norm_mean']}")

    rec = {"meta": {"ts": time.strftime("%F %T"), "seed": a.seed, "samples": len(rows),
                    "device": a.device, "task": a.task, "horizon": a.horizon,
                    "engine_success": bool(ok), "engine_steps": meta.get("steps"),
                    "frames": len(frames), "frame_stage_aligned": bool(aligned),
                    "obs_source": "engine_render (corner2 真实渲染 480²→224²)",
                    "bypass": "未接 u_ff / 未接流形 (Step 0 只做旁路取证)",
                    "note": "z_t/z_goal = 模型 get_action 内部 encode 原值截获 (非重新推导)"},
           "gates": gates, "spearman_progress_vs_intent": rho_wo,
           "spearman_with_last_degenerate_point": rho_all,
           "stage_intent": stage_table, "rows": rows}
    out = a.out or os.path.join(REP, f"intact_step0_probe_{time.strftime('%Y%m%d_%H%M%S')}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    print(f"\n   → {out}")
    print(f"   闸通过数: {sum(1 for v in gates.values() if v)}/5")
    return 0 if all(gates.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
