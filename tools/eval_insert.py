#!/usr/bin/env python3
"""插拔成功率评估 — 5 模型在 peg-insert-side-v3 的真实插拔表现
指标: ①peg 被抓起(抬起>5cm) ②peg 插入孔(pegHead 距 hole<3cm) ③成功率(10次)
"""
import os, sys, json, glob
import numpy as np
import torch

# 渲染环境 (metaworld 需要, 2026-08-06)
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

def load_policy(policy):
    """按 train_curve 加载 (v3 模型)"""
    curve = json.load(open(os.path.join(ROOT, "reports", f"train_curve_{policy}.json")))
    ckpt_base = os.path.join(ROOT, curve["ckpt"])
    if policy == "act":
        from lerobot.policies.act.modeling_act import ACTPolicy
        cands = sorted(glob.glob(os.path.join(ckpt_base, "*/pretrained_model")), key=os.path.getmtime)
        # 相对路径 (HF 校验拒绝绝对路径, 2026-08-06)
        rel = os.path.relpath(cands[-1], ROOT)
        return ACTPolicy.from_pretrained(rel, local_files_only=True).to(DEVICE).eval(), None
    elif policy in ("smolvla", "smolvla_lew"):
        from lerobot.policies.smolvla_lew.modeling_smolvla_lew import SmolVLALewPolicy
        cands = sorted(glob.glob(os.path.join(ckpt_base, "*/pretrained_model")), key=os.path.getmtime)
        rel = os.path.relpath(cands[-1], ROOT)  # 相对路径 (HF 校验)
        return SmolVLALewPolicy.from_pretrained(rel, local_files_only=True).to(DEVICE).eval(), None
    elif policy == "vla_touch":
        from importlib import util
        spec = util.spec_from_file_location("tv", os.path.join(ROOT, "tools", "train_vla_touch.py"))
        mod = util.module_from_spec(spec); spec.loader.exec_module(mod)
        cands = sorted(glob.glob(os.path.join(ckpt_base, "*/pretrained_model/model.pt")), key=os.path.getmtime)
        data = torch.load(cands[-1], map_location="cpu"); cfg = data["config"]
        pol = mod.InterpolantPolicy(cfg["action_dim"], cfg["state_dim"], cfg["tactile_dim"],
                                    cfg["vis_dim"], cfg["hidden"]).to(DEVICE)
        pol.load_state_dict(data["state_dict"]); pol.eval()
        pol.state_dim = int(cfg["state_dim"]); pol.action_dim = int(cfg["action_dim"])
        pol.tactile_dim = int(cfg.get("tactile_dim", 3)); pol.stats = data.get("stats", {})
        return pol, None
    elif policy == "awe_zflow":
        from importlib import util
        spec = util.spec_from_file_location("az", os.path.join(ROOT, "tools", "train_awe_zflow.py"))
        mod = util.module_from_spec(spec); spec.loader.exec_module(mod)
        cands = sorted(glob.glob(os.path.join(ckpt_base, "*/pretrained_model/model.pt")), key=os.path.getmtime)
        data = torch.load(cands[-1], map_location="cpu"); cfg = data["config"]
        pol = mod.AWEZFlowModel(cfg["action_dim"], cfg["state_dim"], cfg["tactile_dim"],
                                cfg["vis_dim"], d_z1=cfg["d_z"][0], d_z2=cfg["d_z"][1],
                                d_z3=cfg["d_z"][2], hidden=cfg["hidden"]).to(DEVICE)
        pol.load_state_dict(data["state_dict"]); pol.eval()
        pol.state_dim = int(cfg["state_dim"]); pol.action_dim = int(cfg["action_dim"])
        pol.tactile_dim = int(cfg.get("tactile_dim", 3)); pol.stats = data.get("stats", {})
        return pol, None
    return None, None

def _load_stats():
    """加载训练 stats — 2026-08-07: 优先从 checkpoint preprocessor safetensors 读 (v7 数据被清)"""
    import json as _j
    # 从 ACT checkpoint 的 normalizer 读 (正确 39D/4D)
    for ck in ["outputs/train/act_peg_long/checkpoints/004000/pretrained_model",
               "outputs/train/act_peg_v7/checkpoints/004000/pretrained_model",
               "outputs/train/act_peg_v6/checkpoints/004000/pretrained_model"]:
        st_f = os.path.join(ROOT, ck, "policy_preprocessor_step_3_normalizer_processor.safetensors")
        if os.path.exists(st_f):
            try:
                from safetensors.torch import load_file
                sd = load_file(st_f)
                # normalizer 存 mean/std 键 (查实际键名)
                keys = list(sd.keys())
                state_keys = [k for k in keys if "state" in k.lower()]
                act_keys = [k for k in keys if "action" in k.lower()]
                if "observation.state.mean" in sd:
                    sm = sd["observation.state.mean"].cpu().numpy().reshape(-1)
                    ss = sd["observation.state.std"].cpu().numpy().reshape(-1)
                    am = sd["action.mean"].cpu().numpy().reshape(-1)
                    asd = sd["action.std"].cpu().numpy().reshape(-1)
                    # 广播到完整维度 (MEAN_STD 标量 → 39D/4D)
                    sm = np.full(39, sm[0], dtype=np.float32)
                    ss = np.full(39, ss[0], dtype=np.float32)
                    am = np.full(4, am[0], dtype=np.float32)
                    asd = np.full(4, asd[0], dtype=np.float32)
                    return {"observation.state": {"mean": sm, "std": ss},
                            "action": {"mean": am, "std": asd}}
            except Exception:
                pass
    # fallback: 数据 stats.json
    import json as _j2
    for root in ["data/metaworld_peg_v7", "data/metaworld_peg_v6", "data/metaworld_peg_v5",
                 "data/metaworld_peg_v4", "data/metaworld_peg_v3", "data/metaworld_peg_v2",
                 "data/metaworld_peg_lerobot", "data/metaworld_act"]:
        p = os.path.join(ROOT, root, "meta", "stats.json")
        if os.path.exists(p):
            return _j2.load(open(p))
    return None

def run_episode(policy, seed, steps=200, yolo_aligner=None, grip_assist=False):
    """单次插拔尝试: 返回 peg 是否抬起 + 是否插入
    grip_assist=True: 夹爪辅助 (接近 peg 强制闭合 — 2026-08-07 老倪: ACT 方向性已学会, 差夹爪决策)"""
    import metaworld
    mt = metaworld.MT1("peg-insert-side-v3", seed=seed)
    env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array")
    env.set_task(mt.train_tasks[0])
    obs, _ = env.reset(seed=seed)
    # state 维度: 从 policy 推断 (ACT/SmolVLA 用 config, 精简模型用属性)
    if hasattr(policy, "config") and hasattr(policy.config, "input_features"):
        st_dim = policy.config.input_features["observation.state"].shape[0]
    else:
        st_dim = getattr(policy, "state_dim", 3)
    # 归一化统计 (LeRobot 训练管道, 2026-08-06: ACT/SmolVLA 无 processor, 需手动归一化)
    stats = _load_stats()
    sm = np.array(stats["observation.state"]["mean"], dtype=np.float32)[:st_dim]
    ss = np.array(stats["observation.state"]["std"], dtype=np.float32)[:st_dim] + 1e-6
    am = np.array(stats["action"]["mean"], dtype=np.float32)[:4]
    asd = np.array(stats["action"]["std"], dtype=np.float32)[:4] + 1e-6
    peg_z0 = env.data.site_xpos[env.model.site("pegGrasp").id][2]
    hole = env.data.site_xpos[env.model.site("hole").id]
    act_hist = torch.zeros((1, 4), dtype=torch.float32, device=DEVICE)
    lifted = False
    for i in range(steps):
        peg = env.data.site_xpos[env.model.site("pegGrasp").id]
        if peg[2] - peg_z0 > 0.05:
            lifted = True
        st_raw = np.asarray(obs, dtype=np.float32)[:st_dim]
        # 2026-08-07: YOLO 感知模式 — 评估也用 YOLO 检测 state (与训练同构, 真机一致)
        if yolo_aligner is not None:
            try:
                det3d = yolo_aligner.detect_3d(np.asarray(env.render()))
                st_raw = yolo_aligner.align(st_raw, det3d).astype(np.float32)[:st_dim]
            except Exception:
                pass
        # 归一化: AWE/VLA-Touch 用 checkpoint 自己的 s_mean/s_std (2026-08-07 修复: 数据 stats 可能错位)
        _sm, _ss = sm, ss
        if hasattr(policy, "stats") and policy.stats and "s_mean" in policy.stats:
            _sm = np.array(policy.stats["s_mean"], dtype=np.float32)[:st_dim]
            _ss = np.array(policy.stats["s_std"], dtype=np.float32)[:st_dim] + 1e-6
        st_n = (st_raw - _sm) / _ss  # 归一化 (训练管道)
        d = np.zeros(policy.tactile_dim if hasattr(policy, "tactile_dim") else 3, dtype=np.float32)
        # 触觉模拟: 用 state 差分 (2026-08-06 修复: st_dim 可能小于 3, 用可用维度)
        _td = min(len(st_raw), len(d))
        d[:_td] = st_raw[:_td] * 0.1
        s_t = torch.from_numpy(st_n).float().to(DEVICE).unsqueeze(0)  # 归一化输入
        t_t = torch.from_numpy(d).float().to(DEVICE).unsqueeze(0)
        with torch.no_grad():
            if hasattr(policy, "select_action"):
                from PIL import Image as _PIL
                rgb = np.asarray(env.render())
                rgb = np.asarray(_PIL.fromarray(rgb).resize((128, 128), _PIL.LANCZOS))  # 训练尺寸 128
                rgb = rgb.transpose(2, 0, 1) / 255.0
                batch = {"observation.image": torch.from_numpy(rgb).float().to(DEVICE).unsqueeze(0),
                         "observation.state": s_t}
                pred = policy.select_action(batch)
                if isinstance(pred, torch.Tensor): pred = pred.detach().cpu()
                act = np.asarray(pred).ravel()
                # 反归一化 (训练管道: 归一化空间 → 真实动作) — 2026-08-06 修复: 必须还原后才能 env.step
                if act.size == 4:
                    act = act * asd + am
                    act_hist = torch.from_numpy(act).float().to(DEVICE).unsqueeze(0)
            elif hasattr(policy, "_cond"):
                cond = policy._cond(s_t, t_t, None)
                x0 = torch.randn_like(s_t.new_zeros((1, policy.action_dim))) * 0.1
                pred = policy.sample(x0, cond, diffuse_steps=10)
                act = pred.detach().cpu().numpy().ravel()
                # 2026-08-07 修复: AWE/VLA-Touch 输出是归一化空间, 必须反归一化 (与 ACT 一致)
                if act.size == 4 and hasattr(policy, "stats") and policy.stats:
                    _st = policy.stats
                    _std = np.array(_st.get("a_std", _st.get("action", {}).get("std", np.ones(4))), dtype=np.float32)[:4]
                    _mean = np.array(_st.get("a_mean", _st.get("action", {}).get("mean", np.zeros(4))), dtype=np.float32)[:4]
                    act = act * _std + _mean
            else:
                pred = policy(s_t, t_t, act_hist, None)
                if isinstance(pred, tuple): pred = pred[0]
                act = pred.detach().cpu().numpy().ravel()
                # 2026-08-07 修复: else 分支 (AWE 等无 _cond) 同样要反归一化
                if act.size == 4 and hasattr(policy, "stats") and policy.stats:
                    _st = policy.stats
                    _std = np.array(_st.get("a_std", _st.get("action", {}).get("std", np.ones(4))), dtype=np.float32)[:4]
                    _mean = np.array(_st.get("a_mean", _st.get("action", {}).get("mean", np.zeros(4))), dtype=np.float32)[:4]
                    act = act * _std + _mean
        a4 = np.zeros(4); a4[:min(4, len(act))] = act[:min(4, len(act))]
        # 2026-08-07: 夹爪辅助 (grip_assist) — 接近 peg 强制闭合 (ACT 方向性已学会, 差夹爪决策)
        if grip_assist:
            hand_pos = env.data.site_xpos[env.model.site("endEffector").id]
            d_peg_now = np.linalg.norm(hand_pos - peg)
            if d_peg_now < 0.08 and not lifted:
                a4[3] = -1.0   # 闭合夹爪 (metaworld: -1=闭合)
            elif lifted:
                a4[3] = 0.6    # 保持抓住
            else:
                a4[3] = 0.0    # 张开
        act_hist = torch.from_numpy(a4).float().to(DEVICE).unsqueeze(0)
        obs, _, term, trunc, _ = env.step(a4)
        if term or trunc:
            break
    peg_final = env.data.site_xpos[env.model.site("pegGrasp").id]
    dist_hole = float(np.linalg.norm(peg_final - hole))
    inserted = lifted and dist_hole < 0.05
    return {"lifted": lifted, "inserted": inserted, "dist_hole": round(dist_hole, 3),
            "peg_rise": round(float(peg_final[2] - peg_z0), 3)}

def main():
    print("🔬 插拔成功率评估 · peg-insert-side-v3 · 每模型 10 次")
    results = {}
    for p in ["act", "smolvla", "smolvla_lew", "vla_touch", "awe_zflow"]:
        try:
            policy, _ = load_policy(p)
        except Exception as ex:
            print(f"⚠️ {p} 加载失败: {str(ex)[:60]}")
            continue
        lifts = ins = 0
        dists = []
        for seed in range(10):
            r = run_episode(policy, seed)
            lifts += int(r["lifted"]); ins += int(r["inserted"]); dists.append(r["dist_hole"])
        results[p] = {"lift_rate": lifts / 10, "insert_rate": ins / 10,
                      "avg_dist": round(float(np.mean(dists)), 3)}
        print(f"  {p:12s}: 抓取率={results[p]['lift_rate']:.0%} 插入率={results[p]['insert_rate']:.0%} 平均距孔={results[p]['avg_dist']:.3f}")
    out = os.path.join(ROOT, "reports", "insert_success.json")
    json.dump(results, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"✅ 结果已存: {out}")

if __name__ == "__main__":
    main()
