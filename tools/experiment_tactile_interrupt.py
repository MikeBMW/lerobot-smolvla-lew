#!/usr/bin/env python3
"""触觉中断实验 — 证明 AWE "预测中决策" 优于 VLA-Touch "触觉反应式"
场景 (2026-08-06 老倪要求):
  peg-insert-side-v3 插销任务, 前 30 帧真触觉, 30 帧后触觉中断 (传感器故障)
  VLA-Touch: 触觉是唯一条件源 → 中断后输入全零 → 决策退化
  AWE: 世界模型(GRU)预测接触演化 → 中断后靠潜状态预测继续决策
指标: 末端→hole 距离 / 触觉中断前后动作退化幅度 / 插入成功率
"""
import os, sys, json, glob
import numpy as np
import torch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

def load_models():
    from importlib import util
    models = {}
    for key, mod_name, cls_name in [("vla_touch", "train_vla_touch", "InterpolantPolicy"),
                                    ("awe_zflow", "train_awe_zflow", "AWEZFlowModel")]:
        curve = json.load(open(os.path.join(ROOT, "reports", f"train_curve_{key}.json")))
        cands = sorted(glob.glob(os.path.join(ROOT, curve["ckpt"], "*/pretrained_model/model.pt")),
                       key=os.path.getmtime)
        if not cands:
            print(f"⚠️ {key} 无 model.pt"); continue
        spec = util.spec_from_file_location(mod_name, os.path.join(ROOT, "tools", f"{mod_name}.py"))
        mod = util.module_from_spec(spec); spec.loader.exec_module(mod)
        data = torch.load(cands[-1], map_location="cpu")
        cfg = data["config"]
        if key == "awe_zflow":
            pol = getattr(mod, cls_name)(cfg["action_dim"], cfg["state_dim"], cfg["tactile_dim"],
                                         cfg["vis_dim"], d_z1=cfg["d_z"][0], d_z2=cfg["d_z"][1],
                                         d_z3=cfg["d_z"][2], hidden=cfg["hidden"]).to(DEVICE)
        else:
            pol = getattr(mod, cls_name)(cfg["action_dim"], cfg["state_dim"], cfg["tactile_dim"],
                                         cfg["vis_dim"], cfg["hidden"]).to(DEVICE)
        pol.load_state_dict(data["state_dict"])
        pol.state_dim = int(cfg["state_dim"]); pol.action_dim = int(cfg["action_dim"])
        pol.tactile_dim = int(cfg.get("tactile_dim", 3))
        pol.stats = data.get("stats", {})  # AWE 归一化统计
        pol.eval()
        models[key] = pol
    return models

def run_interrupt(policy, key, interrupt_at=30, steps=100, seed=0):
    """前 interrupt_at 帧真触觉, 之后触觉中断 (全零)"""
    import metaworld
    mt = metaworld.MT1("peg-insert-side-v3", seed=seed)
    env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner")
    env.set_task(mt.train_tasks[0])
    obs, _ = env.reset(seed=seed)
    hole = env.data.site_xpos[env.model.site("hole").id]
    dists, amps = [], []
    act_hist = torch.zeros((1, 4), dtype=torch.float32, device=DEVICE)
    prev_act = None
    # AWE 归一化参数
    sm = np.array(policy.stats.get("s_mean", [0]*policy.state_dim), dtype=np.float32)[:policy.state_dim] if policy.stats.get("s_mean") else np.zeros(policy.state_dim, dtype=np.float32)
    ss = np.array(policy.stats.get("s_std", [1]*policy.state_dim), dtype=np.float32)[:policy.state_dim] + 1e-6 if policy.stats.get("s_std") else np.ones(policy.state_dim, dtype=np.float32)
    am = np.array(policy.stats.get("a_mean", [0]*4), dtype=np.float32)[:4] if policy.stats.get("a_mean") else np.zeros(4, dtype=np.float32)
    asd = np.array(policy.stats.get("a_std", [1]*4), dtype=np.float32)[:4] + 1e-6 if policy.stats.get("a_std") else np.ones(4, dtype=np.float32)

    for i in range(steps):
        ee = env.data.site_xpos[env.model.site("endEffector").id]
        dists.append(float(np.linalg.norm(ee - hole)))
        st_raw = np.asarray(obs, dtype=np.float32)[: policy.state_dim]
        # 触觉: 前 interrupt_at 帧真实 (差分力), 之后中断
        d = np.zeros(policy.tactile_dim, dtype=np.float32)
        if i < interrupt_at:
            d[:3] = st_raw[:3] * 0.1 if st_raw.shape[0] >= 3 else 0
            d[3] = 1.0
        # 触觉中断后 d 保持全零
        st = (st_raw - sm) / ss if policy.stats.get("s_mean") else st_raw
        s_t = torch.from_numpy(st).float().to(DEVICE).unsqueeze(0)
        t_t = torch.from_numpy(d).float().to(DEVICE).unsqueeze(0)
        with torch.no_grad():
            if hasattr(policy, "_cond"):
                cond = policy._cond(s_t, t_t, None)
                x0 = torch.randn_like(s_t.new_zeros((1, policy.action_dim))) * 0.1
                pred = policy.sample(x0, cond, diffuse_steps=10)
            else:
                pred = policy(s_t, t_t, act_hist, None)
                if isinstance(pred, tuple): pred = pred[0]
        act = pred.detach().cpu().numpy().ravel()
        if policy.stats.get("a_mean") and act.size:
            act = act * asd[:act.size] + am[:act.size]
        amps.append(float(np.abs(act).mean()))
        a4 = np.zeros(4); a4[:min(4, len(act))] = act[:min(4, len(act))]
        act_hist = torch.from_numpy(a4).float().to(DEVICE).unsqueeze(0)
        obs, _, term, trunc, _ = env.step(a4)
        if term or trunc:
            break
    # 指标
    pre = np.mean(dists[:interrupt_at]) if len(dists) > interrupt_at else dists[0]
    post = np.mean(dists[interrupt_at:]) if len(dists) > interrupt_at else dists[-1]
    amp_pre = np.mean(amps[:interrupt_at]) if amps else 0
    amp_post = np.mean(amps[interrupt_at:]) if len(amps) > interrupt_at else 0
    return {
        "init_dist": round(float(dists[0]), 4),
        "final_dist": round(float(dists[-1]), 4),
        "pre_dist": round(float(pre), 4),
        "post_dist": round(float(post), 4),
        "degration": round(float(post - pre), 4),      # 中断后距离恶化
        "amp_pre": round(float(amp_pre), 4),
        "amp_post": round(float(amp_post), 4),
        "amp_drop": round(float(amp_post - amp_pre), 4),  # 动作退化幅度
        "success": float(dists[-1] < 0.12),
    }

def main():
    print("🔬 触觉中断实验 · peg-insert-side-v3 · 前30帧真触觉 → 30帧后触觉中断")
    print("假设: VLA-Touch 触觉反应式 → 中断后退化; AWE 世界模型预测 → 补偿")
    models = load_models()
    results = {}
    for key in ["vla_touch", "awe_zflow"]:
        if key not in models: continue
        print(f"\n=== {key} ===")
        r = run_interrupt(models[key], key, interrupt_at=30, steps=100, seed=0)
        results[key] = r
        print(f"  初始距={r['init_dist']:.3f} → 最终距={r['final_dist']:.3f}")
        print(f"  中断前均距={r['pre_dist']:.3f} → 中断后均距={r['post_dist']:.3f} (恶化 {r['degration']:+.3f})")
        print(f"  动作: 前 {r['amp_pre']:.3f} → 后 {r['amp_post']:.3f} (下降 {r['amp_drop']:+.3f})")
        print(f"  成功率={r['success']}")
    print("\n══════ 结论 ══════")
    if "vla_touch" in results and "awe_zflow" in results:
        v, a = results["vla_touch"], results["awe_zflow"]
        print(f"  中断后距离恶化: VLA-Touch={v['degration']:+.3f} vs AWE={a['degration']:+.3f}")
        print(f"  动作退化: VLA-Touch={v['amp_drop']:+.3f} vs AWE={a['amp_drop']:+.3f}")
        winner = "AWE" if a["degration"] < v["degration"] else "VLA-Touch"
        print(f"  → {winner} 在触觉中断下退化更小 (预测中决策优势)")
    out = os.path.join(ROOT, "reports", "tactile_interrupt.json")
    json.dump(results, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"✅ 结果已存: {out}")

if __name__ == "__main__":
    main()
