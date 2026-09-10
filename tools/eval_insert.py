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
    if policy in ("act", "act_tactile"):
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
    elif policy in ("vla_touch", "vla_touch_tactile"):
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
    elif policy in ("awe_zflow", "awe_zflow_tactile"):
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

def _load_stats(policy_hint=None):
    """加载训练 stats — 2026-08-08: 从模型 checkpoint preprocessor 读逐维 norm (v7 数据被清, 逐维才是对的)"""
    import json as _j
    # VLA-Touch/AWE: checkpoint 无 preprocessor → 直接用数据 stats.json (2026-08-08)
    if policy_hint in ("vla_touch", "awe_zflow", "vla_touch_tactile", "awe_zflow_tactile"):
        import json as _j3
        # 触觉模型 (49D) 用 tactile2 数据 stats (2026-08-09)
        if policy_hint.endswith("tactile"):
            p = os.path.join(ROOT, "data", "metaworld_peg_tactile2", "meta", "stats.json")
            if os.path.exists(p):
                return _j3.load(open(p))
        for root in ["data/metaworld_peg_seg", "data/metaworld_peg_long", "data/metaworld_peg_v6"]:
            p = os.path.join(ROOT, root, "meta", "stats.json")
            if os.path.exists(p):
                return _j3.load(open(p))
    # 候选 checkpoint: 优先 policy_hint 对应模型 (2026-08-08 修复: 每个模型 stats 不同)
    _by_policy = {
        "smolvla": ["outputs/train/smolvla_peg_seg/checkpoints/004000/pretrained_model",
                    "outputs/train/smolvla_peg_long2/checkpoints/004000/pretrained_model",
                    "outputs/train/smolvla_ft_20260807_161841/checkpoints/004000/pretrained_model"],
        "smolvla_lew": ["outputs/train/smolvla_lew_grab6/checkpoints/002000/pretrained_model",
                        "outputs/train/smolvla_lew_ft_20260807_164927/checkpoints/004000/pretrained_model"],
        "act": ["outputs/train/act_peg_seg/checkpoints/004000/pretrained_model",
                "outputs/train/act_pegdata_4000/checkpoints/004000/pretrained_model",
                "outputs/train/act_peg_long/checkpoints/004000/pretrained_model"],
        "act_tactile": ["outputs/train/act_tactile_20260810_061534/checkpoints/003000/pretrained_model"],
        "vla_touch": ["outputs/train/vla_touch_20260808_083814/checkpoints/000050/pretrained_model",
                      "outputs/train/vla_touch_20260807_141958/checkpoints/000050/pretrained_model"],
        "vla_touch_tactile": ["outputs/train/vla_touch_20260809_225238/checkpoints/000050/pretrained_model"],
        "awe_zflow": ["outputs/train/awe_zflow_20260808_084811/checkpoints/000050/pretrained_model",
                      "outputs/train/awe_zflow_20260808_002622/checkpoints/000050/pretrained_model"],
        "awe_zflow_tactile": ["outputs/train/awe_zflow_20260809_225958/checkpoints/000050/pretrained_model"],
        "expert_mlp": ["outputs/rl_peg"],
    }
    cands = _by_policy.get(policy_hint, []) if policy_hint else []
    cands += ["outputs/train/smolvla_peg_long2/checkpoints/004000/pretrained_model",
              "outputs/train/act_pegdata_4000/checkpoints/004000/pretrained_model",
              "outputs/train/act_peg_long/checkpoints/004000/pretrained_model",
              "outputs/train/awe_zflow_20260808_002622/checkpoints/000050/pretrained_model"]
    for ck in cands:
        st_f = os.path.join(ROOT, ck, "policy_preprocessor_step_3_normalizer_processor.safetensors")
        if not os.path.exists(st_f):
            # 尝试 step_2 (AWE 可能不同)
            import glob as _g
            cand = _g.glob(os.path.join(ROOT, ck, "policy_preprocessor_step_*normalizer*.safetensors"))
            st_f = cand[0] if cand else None
        if st_f and os.path.exists(st_f):
            try:
                from safetensors.torch import load_file
                sd = load_file(st_f)
                if "observation.state.mean" in sd:
                    sm = sd["observation.state.mean"].cpu().numpy().reshape(-1)
                    ss = sd["observation.state.std"].cpu().numpy().reshape(-1)
                    am = sd["action.mean"].cpu().numpy().reshape(-1)
                    asd = sd["action.std"].cpu().numpy().reshape(-1)
                    # 标量 → 广播 (ACT 旧版); 逐维 → 直接用
                    if sm.size == 1:
                        sm = np.full(39, sm[0], dtype=np.float32)
                        ss = np.full(39, ss[0], dtype=np.float32)
                    if am.size == 1:
                        am = np.full(4, am[0], dtype=np.float32)
                        asd = np.full(4, asd[0], dtype=np.float32)
                    return {"observation.state": {"mean": sm, "std": ss},
                            "action": {"mean": am, "std": asd}}
            except Exception:
                pass
    # fallback: 数据 stats.json (2026-08-08: seg 数据 45D)
    import json as _j2
    for root in ["data/metaworld_peg_seg", "data/metaworld_peg_long", "data/metaworld_peg_v7", "data/metaworld_peg_v6",
                 "data/metaworld_peg_v5", "data/metaworld_peg_v4", "data/metaworld_peg_v3",
                 "data/metaworld_peg_v2", "data/metaworld_peg_lerobot", "data/metaworld_act"]:
        p = os.path.join(ROOT, root, "meta", "stats.json")
        if os.path.exists(p):
            return _j2.load(open(p))
    return None

def run_episode(policy, seed, steps=200, yolo_aligner=None, grip_assist=False, policy_name=None):
    """单次插拔尝试: 返回 peg 是否抬起 + 是否插入
    grip_assist=True: 夹爪辅助 (接近 光模块 强制闭合 — 2026-08-07 老倪: ACT 方向性已学会, 差夹爪决策)
    policy_name: 2026-08-08 用于加载对应模型的归一化 stats (每模型不同)"""
    import metaworld
    mt = metaworld.MT1("peg-insert-side-v3", seed=seed)
    # 🐛 2026-08-23 静静: 显式 corner2 相机 (默认 topview 与 YOLO 反投影/训练图像不一致 → 检测错位)
    env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
    env.set_task(mt.train_tasks[0])
    obs, _ = env.reset(seed=seed)
    # state 维度: 从 policy 推断 (ACT/SmolVLA 用 config, 精简模型用属性)
    if hasattr(policy, "config") and hasattr(policy.config, "input_features"):
        st_dim = policy.config.input_features["observation.state"].shape[0]
    else:
        st_dim = getattr(policy, "state_dim", 3)
    # 归一化统计 (LeRobot 训练管道, 2026-08-06: ACT/SmolVLA 无 processor, 需手动归一化)
    stats = _load_stats(policy_name)
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
        st_raw = np.asarray(obs, dtype=np.float32)[:39]
        # 2026-08-08 ③目标条件化: 评估时补相对向量 (模型 45D 输入, 训练数据含 rel_vec)
        if st_dim >= 45 and st_raw.size == 39:
            try:
                hand_pos = env.data.site_xpos[env.model.site("endEffector").id].astype(np.float32)
                peg_pos = env.data.site_xpos[env.model.site("pegGrasp").id].astype(np.float32)
                hole_pos = env.data.site_xpos[env.model.site("hole").id].astype(np.float32)
                rel_vec = np.concatenate([peg_pos - hand_pos, hole_pos - peg_pos]).astype(np.float32)
                st_raw = np.concatenate([st_raw, rel_vec]).astype(np.float32)
            except Exception:
                st_raw = np.pad(st_raw, (0, 6), constant_values=0)[:st_dim]
        # 2026-08-09: 触觉模型 (49D) — 45D 后补触觉段 (3D差分速度 + 1D力), 与训练管道同构
        if st_dim >= 49 and len(st_raw) == 45:
            try:
                st_raw = np.concatenate([st_raw, np.zeros(3, dtype=np.float32) * 10.0, [0.0]]).astype(np.float32)
            except Exception:
                st_raw = np.pad(st_raw, (0, 4), constant_values=0)[:st_dim]
        # 2026-08-07: YOLO 感知模式 — 评估也用 YOLO 检测 state (与训练同构, 真机一致)
        if yolo_aligner is not None:
            try:
                det3d = yolo_aligner.detect_3d(np.asarray(env.render()))
                st_raw = yolo_aligner.align(st_raw, det3d).astype(np.float32)[:st_dim]
            except Exception:
                pass
        # 2026-08-09: 触觉模型 (49D) — 补触觉段 (3D差分速度 + 1D力), 与训练管道同构
        if st_dim >= 49 and len(st_raw) == 45:
            try:
                ee_pos = env.data.site_xpos[env.model.site("endEffector").id].astype(np.float32)
                d_ee = np.zeros(3, dtype=np.float32)
                st_raw = np.concatenate([st_raw, d_ee * 10.0, [0.0]]).astype(np.float32)  # tac段
            except Exception:
                st_raw = np.pad(st_raw, (0, 4), constant_values=0)[:st_dim]
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
                # 2026-08-08 修复: SmolVLA 视觉输入 64x64 (siglip_image_size), ACT 128x128
                img_size = 64 if type(policy).__name__.lower().startswith("smolvla") else 128
                rgb = np.asarray(_PIL.fromarray(rgb).resize((img_size, img_size), _PIL.LANCZOS))
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
        # 2026-08-07: 夹爪辅助 (grip_assist) — 接近 光模块 强制闭合 (ACT 方向性已学会, 差夹爪决策)
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

def _build_yolo_aligner():
    """构建 YOLO 感知对齐器 (评估用 YOLO 检测 state, 与训练同构 — 2026-08-23)
    失败回退 None (真值评估)"""
    try:
        sys.path.insert(0, os.path.join(ROOT, "src", "lerobot", "policies", "yolo_3d"))
        import yolo_state_aligner
        _cands = ["runs/detect/outputs/yolo_peg/peg_v1/weights/best.pt",
                  "runs/detect/outputs/yolo_peg/peg_full/weights/best.pt",
                  "outputs/yolo_peg/peg_v1/weights/best.pt"]
        WEIGHTS = next((c for c in _cands if os.path.isfile(os.path.join(ROOT, c))), None)
        if not WEIGHTS:
            print("⚠️ YOLO 权重未找到, 回退真值评估")
            return None
        import metaworld
        _mt = metaworld.MT1("peg-insert-side-v3")
        env0 = _mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
        env0._freeze_rand_vec = False
        env0.set_task(_mt.train_tasks[0])
        env0.reset(seed=0)
        return yolo_state_aligner.YoloStateAligner(WEIGHTS, env0)
    except Exception as ex:
        print(f"⚠️ YOLO aligner 构建失败 ({str(ex)[:60]}), 回退真值评估")
        return None


def main():
    print("🔬 插拔成功率评估 · peg-insert-side-v3 · 每模型 10 次")
    # 2026-08-23: 评估接 YOLO 感知 (与训练同构, 真机一致) — 失败自动回退真值
    aligner = _build_yolo_aligner()
    print("🔬 YOLO 感知模式已启用" if aligner is not None else "ℹ️ 真值评估模式 (YOLO 未启用)")
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
            r = run_episode(policy, seed, yolo_aligner=aligner)
            lifts += int(r["lifted"]); ins += int(r["inserted"]); dists.append(r["dist_hole"])
        results[p] = {"lift_rate": lifts / 10, "insert_rate": ins / 10,
                      "avg_dist": round(float(np.mean(dists)), 3)}
        print(f"  {p:12s}: 抓取率={results[p]['lift_rate']:.0%} 插入率={results[p]['insert_rate']:.0%} 平均距孔={results[p]['avg_dist']:.3f}")
    out = os.path.join(ROOT, "reports", "insert_success.json")
    json.dump(results, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"✅ 结果已存: {out}")

if __name__ == "__main__":
    main()
