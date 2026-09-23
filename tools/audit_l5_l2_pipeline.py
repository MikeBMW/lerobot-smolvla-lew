#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L5→L4→L3→L2 模型 pipeline 拉通审计 —— 仿真端真跑取证

三层证据 (不是"双击自检"):
  ① 单次全链真跑: 真帧(引擎渲染) + 真权重 (L2=detect.yolo 在役权重, L4=node.unified/node.intact)
  ② 引擎每帧调用: RealStateSpaceSim 挂 PipelineNode, SS_L4_INTACT=1 → 逐帧真推理 + w 融合
  ③ L2 收口: 上层提案是否真过 sched.decide + safety.saturate (veto 计数) → 唯一出口

输出: docs/pipeline_audit_<ts>.json (机器可读证据)
"""
import json
import os
import sys
import time

REPO = "/home/ubuntu/lerobot-smolvla-lew"
for _p in (REPO + "/tools", REPO + "/tools/gui", REPO + "/src"):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np  # noqa: E402

TS = time.strftime("%Y%m%d_%H%M%S")
EVID = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "repo": REPO}


def hr(t):
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78, flush=True)


# ══════════════ ① 单次全链真跑 (真帧 + 真权重) ══════════════

def part_a(img, obs39, tag, spec_kw, extra=None):
    from multi_layer_pipeline import Pipeline, build_default_spec  # noqa: PLC0415
    spec = build_default_spec(**spec_kw)
    if extra:
        spec.update(extra)
    t0 = time.time()
    p = Pipeline(spec)
    out = p.run(img=img, obs39=obs39)
    dt = (time.time() - t0) * 1000
    print(p.report(out))
    row = {"tag": tag, "total_ms": round(dt, 1), "layers": {}}
    for k, o in out.items():
        n = len(np.asarray(o.data.get("chunk"))) if o.data.get("chunk") is not None else (
            len(o.data.get("u_ff")) if o.data.get("u_ff") is not None else 0)
        row["layers"][k] = {"ok": bool(o.ok), "src": o.src, "conf": round(float(o.conf), 4),
                            "ms": round(float(o.latency_ms), 2), "n_out": int(n),
                            "err": o.err[:120]}
    l4 = out.get("L4")
    if l4 is not None and l4.ok and l4.data.get("chunk") is not None:
        c = np.asarray(l4.data["chunk"], float)
        row["l4_chunk"] = {"shape": list(c.shape), "norm": round(float(np.linalg.norm(c)), 4),
                           "nonzero_frac": round(float(np.mean(np.abs(c) > 1e-6)), 3),
                           "per_step_change": round(float(np.mean(np.abs(np.diff(c, axis=0)))), 4)
                           if c.shape[0] > 1 else None}
    if out.get("L4") is not None and out["L4"].data.get("vote"):
        row["vote"] = out["L4"].data["vote"]
    print("  ▶ 汇总: " + json.dumps(row, ensure_ascii=False)[:600])
    return row


# ══════════════ ② 引擎每帧调用 (PipelineNode + SS_L4_INTACT=1) ══════════════

class RecordingPipelineNode:
    """包一层 PipelineNode: 记录每帧各层 src/ok/conf/耗时 (证"每帧真调用")"""

    def __init__(self, inner):
        self._inner = inner
        self.frames = []          # 每帧: {frame_std, layers:{k:{src,ok,conf,ms}}}

    def __getattr__(self, k):
        return getattr(self._inner, k)

    def step(self, fr, obs_source=None, skill_ctx=None):
        out = self._inner.step(fr, obs_source=obs_source, skill_ctx=skill_ctx)
        layers = getattr(out, "layers", None) or {}
        self.frames.append({
            "frame_std": round(float(np.asarray(fr).std()), 2),
            "layers": {k: {"src": v.src, "ok": bool(v.ok), "conf": round(float(v.conf), 4),
                           "ms": round(float(v.latency_ms), 2)} for k, v in layers.items()},
        })
        return out


def part_b(seed=104, max_steps=400):
    os.environ["SS_L4_INTACT"] = "1"           # 接管档 (不设=逐位零变化)
    os.environ.setdefault("SS_INTACT_EVERY", "8")
    os.environ.pop("SS_L4_INTACT_SHADOW", None)
    from multi_layer_pipeline import PipelineNode, build_default_spec  # noqa: PLC0415
    from state_space_sim_real import RealStateSpaceSim               # noqa: PLC0415

    spec = build_default_spec(L2="detect.stub", L4="node.unified")
    spec["L4"] = {"impl": "node.unified", "on": True, "combine": "vote",
                  "peers": ["node.intact"]}
    sim = RealStateSpaceSim(seed=seed, vision=False, mode="insert", log=lambda *a: None)
    node = RecordingPipelineNode(PipelineNode(spec=spec, sim=sim))
    sim.attach_intact(node, None)
    t0 = time.time()
    tr = sim.run(max_steps=max_steps)
    wall = time.time() - t0

    st = dict(getattr(sim, "_l4_stats", {}) or {})
    done = bool(tr["done"][-1]) if tr.get("done") else False
    n = len(node.frames)
    src_seq = [f["layers"].get("L4", {}).get("src", "?") for f in node.frames]
    l4_src_hist = {s: src_seq.count(s) for s in sorted(set(src_seq))}
    # 各层"真出结果"次数
    layer_ok = {}
    for f in node.frames:
        for k, v in f["layers"].items():
            d = layer_ok.setdefault(k, {"calls": 0, "ok": 0, "src": set()})
            d["calls"] += 1
            d["ok"] += int(v["ok"])
            d["src"].add(v["src"])
    layer_ok = {k: {"calls": v["calls"], "ok": v["ok"], "src": sorted(v["src"])}
                for k, v in layer_ok.items()}
    row = {
        "seed": seed, "max_steps": max_steps, "steps_run": len(tr["t"]), "wall_s": round(wall, 1),
        "done": done, "insert_mm": round(float(tr["dist"][-1]) * 1000, 1) if tr.get("dist") else None,
        "pipeline_frames": n,
        "engine_calls": st.get("calls", 0), "chunk_reuse": st.get("reuse", 0),
        "refused": st.get("refused", 0), "w_zero": st.get("w_zero", 0), "blend": st.get("blend", 0),
        "l2_veto": st.get("l2_veto", 0), "l2_veto_dir": st.get("l2_veto_dir", 0),
        "l2_veto_mag": st.get("l2_veto_mag", 0),
        "u_ff_src": st.get("u_ff_src"), "err": st.get("err"), "w_last": st.get("w_last"),
        "l4_src_hist": l4_src_hist, "layer_ok": layer_ok,
        "frame_std_min": min((f["frame_std"] for f in node.frames), default=None),
        "frame_std_max": max((f["frame_std"] for f in node.frames), default=None),
    }
    print("  ▶ " + json.dumps(row, ensure_ascii=False)[:1400])
    return row, sim, node


def main():
    hr("①-A 单次全链真跑 · 真帧(引擎渲染) + 在役权重")
    max_steps = int(os.environ.get("AUDIT_STEPS", "400"))
    row_b, sim, node = part_b(max_steps=max_steps)
    EVID["engine_per_frame"] = row_b

    # 从引擎拿"真渲染帧 + 真 obs39"
    try:
        import cv2  # noqa: PLC0415
        fr = np.asarray(sim._render_frame())
        img = cv2.resize(fr, (224, 224), interpolation=cv2.INTER_AREA).astype(np.uint8)
        obs39 = np.asarray(sim._last_obs39, float).ravel()[:39].astype(np.float32)
        print("  真帧 shape=%s mean=%.1f std=%.1f | obs39[:4]=%s"
              % (img.shape, img.mean(), img.std(), np.round(obs39[:4], 4)))
        EVID["real_frame"] = {"shape": list(img.shape), "mean": round(float(img.mean()), 2),
                              "std": round(float(img.std()), 2),
                              "obs39_first4": [round(float(x), 4) for x in obs39[:4]]}
    except Exception as e:                                            # noqa: BLE001
        print("  ⚠️ 取真帧失败: %s" % e)
        img = np.zeros((224, 224, 3), np.uint8)
        obs39 = np.zeros(39, np.float32)

    hr("①-B 全链真跑 · L2=detect.yolo(在役权重,真YOLO) + L4=node.unified(真ckpt)")
    EVID["A_yolo_unified"] = part_a(img, obs39, "yolo+unified",
                                    dict(L2="detect.yolo", L4="node.unified"))
    hr("①-C 全链真跑 · L4=vote[node.unified, node.intact] (并联仲裁)")
    EVID["B_vote"] = part_a(img, obs39, "vote(unified,intact)",
                            dict(L2="detect.yolo", L4="node.unified"),
                            extra={"L4": {"impl": "node.unified", "on": True,
                                          "combine": "vote", "peers": ["node.intact"]}})
    hr("①-D 消融对照 · L4=null (L3 应报无上游 chunk)")
    EVID["C_ablation"] = part_a(img, obs39, "L4=null", dict(L2="detect.stub", L4="null"))

    out = os.path.join(REPO, "docs", "pipeline_audit_%s.json" % TS)
    json.dump(EVID, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n✅ 证据已落盘: %s" % out)


if __name__ == "__main__":
    main()
