#!/usr/bin/env python3
"""AWE vs VLA-Touch 区分性实验 — 证明"预测中决策"优势
实验设计 (2026-08-06 老倪要求: 怎么体现 AWE 比 VLA-Touch 好):
  场景: peg-insert-side-v3 插销 (多阶段: 接近→对准→插入)
  变量: 触觉信号质量 (0=无触觉 / 1=真触觉 / 2=噪声触觉 / 3=延迟触觉)
  假设: VLA-Touch 是触觉反应式 → 触觉质量差时退化;
        AWE 是世界模型预见式 → 用潜空间预测补偿, 抗触觉退化。
指标: 末端→hole 距离收敛 / 动作幅度 / 平滑度 / 成功率(距离<thr)
"""
import os, sys, json, glob, time
import numpy as np
import torch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

def load_models():
    """加载 vla_touch + awe_zflow (peg v2 训练)"""
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
            # AWE 用 d_z 潜空间 (train_awe_zflow.py 落盘格式)
            pol = getattr(mod, cls_name)(cfg["action_dim"], cfg["state_dim"], cfg["tactile_dim"],
                                         cfg["vis_dim"], d_z1=cfg["d_z"][0], d_z2=cfg["d_z"][1],
                                         d_z3=cfg["d_z"][2], hidden=cfg["hidden"]).to(DEVICE)
        else:
            pol = getattr(mod, cls_name)(cfg["action_dim"], cfg["state_dim"], cfg["tactile_dim"],
                                         cfg["vis_dim"], cfg["hidden"]).to(DEVICE)
        pol.load_state_dict(data["state_dict"])
        pol.state_dim = int(cfg["state_dim"]); pol.action_dim = int(cfg["action_dim"])
        pol.tactile_dim = int(cfg.get("tactile_dim", 3))
        pol.eval()
        models[key] = pol
    return models

def run_episode(policy, key, tac_mode, seed=0, steps=120):
    """单个 episode: 用指定触觉模式 rollout, 返回指标"""
    import metaworld
    mt = metaworld.MT1("peg-insert-side-v3", seed=seed)
    env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner")
    env.set_task(mt.train_tasks[0])
    obs, _ = env.reset(seed=seed)
    dists, amps, smooths = [], [], []
    prev_act = None
    act_hist = torch.zeros((1, 4), dtype=torch.float32, device=DEVICE)  # AWE 动作历史 (自回归)
    hole = env.data.site_xpos[env.model.site("hole").id]
    for i in range(steps):
        ee = env.data.site_xpos[env.model.site("endEffector").id]
        dists.append(np.linalg.norm(ee - hole))
        st = np.asarray(obs, dtype=np.float32)[: policy.state_dim]
        # 触觉模拟: 状态差分 → 力 (与训练同管道)
        d = np.zeros(policy.tactile_dim, dtype=np.float32)
        if tac_mode == "real":  # 真触觉 (差分力)
            d[:3] = (st[:3] if st.shape[0] >= 3 else 0) * 0.1
            d[3] = 1.0
        elif tac_mode == "noise":  # 噪声触觉
            d = np.random.randn(policy.tactile_dim).astype(np.float32) * 0.5
        elif tac_mode == "delay":  # 延迟触觉 (恒定错误值)
            d = np.full(policy.tactile_dim, 0.8, dtype=np.float32)
        # tac_mode=0 → 零触觉
        s_t = torch.from_numpy(st).float().to(DEVICE).unsqueeze(0)
        t_t = torch.from_numpy(d).float().to(DEVICE).unsqueeze(0)
        with torch.no_grad():
            if hasattr(policy, "_cond"):
                cond = policy._cond(s_t, t_t, None)
                x0 = torch.randn_like(s_t.new_zeros((1, policy.action_dim))) * 0.1
                pred = policy.sample(x0, cond, diffuse_steps=10)
            else:
                # AWE: 自回归动作历史 (世界模型预测未来需要历史)
                pred = policy(s_t, t_t, act_hist, None)
                if isinstance(pred, tuple): pred = pred[0]
        act = pred.detach().cpu().numpy().ravel()
        amps.append(np.abs(act).mean())
        if prev_act is not None:
            smooths.append(np.abs(act - prev_act).mean())
        prev_act = act.copy()
        a4 = np.zeros(4); a4[:min(4, len(act))] = act[:min(4, len(act))]
        # 更新 AWE 动作历史
        act_hist = torch.from_numpy(a4[:4]).float().to(DEVICE).unsqueeze(0)
        obs, _, term, trunc, _ = env.step(a4)
        if term or trunc:
            break
    final_dist = dists[-1] if dists else 999
    init_dist = dists[0] if dists else 999
    return {
        "init_dist": round(float(init_dist), 4),
        "final_dist": round(float(final_dist), 4),
        "improve": round(float(init_dist - final_dist), 4),
        "action_amp": round(float(np.mean(amps)), 4) if amps else 0,
        "smoothness": round(float(np.mean(smooths)), 4) if smooths else 0,
        "success": float(final_dist < 0.12),  # 到达 hole 附近 (插入成功阈值)
    }

def main():
    print("🔬 AWE vs VLA-Touch 区分性实验 · peg-insert-side-v3 · 触觉质量变量")
    models = load_models()
    tac_modes = [("无触觉", "zero"), ("真触觉", "real"), ("噪声触觉", "noise"), ("延迟触觉", "delay")]
    results = {}
    for key in ["vla_touch", "awe_zflow"]:
        if key not in models: continue
        results[key] = {}
        print(f"\n=== {key} ===")
        for label, mode in tac_modes:
            r = run_episode(models[key], key, mode, seed=0)
            results[key][mode] = r
            print(f"  [{label:6s}] 初始距={r['init_dist']:.3f} → 最终距={r['final_dist']:.3f} "
                  f"改进={r['improve']:+.3f} 动作={r['action_amp']:.3f} 平滑={r['smoothness']:.3f} 成功={r['success']}")
    # 总结: AWE 抗噪优势
    print("\n══════ 对比结论 ══════")
    if "vla_touch" in results and "awe_zflow" in results:
        for mode in ["zero", "real", "noise", "delay"]:
            v = results["vla_touch"].get(mode, {}).get("improve", 0)
            a = results["awe_zflow"].get(mode, {}).get("improve", 0)
            better = "AWE" if a > v else ("VLA-Touch" if v > a else "持平")
            print(f"  {mode:6s}: 改进 VLA-Touch={v:+.3f} vs AWE={a:+.3f} → {better}")
    out = os.path.join(ROOT, "reports", "awe_vs_vlat.json")
    json.dump(results, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"✅ 结果已存: {out}")

if __name__ == "__main__":
    main()
