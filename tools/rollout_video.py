#!/usr/bin/env python3
"""🎥 三模型推理效果对比 — metaworld 环境 rollout 生成视频帧序列 (2026-08-05 老倪需求)
用法:
    .venv/bin/python tools/rollout_video.py --policy act --steps 120 --out reports/rollout_act
    .venv/bin/python tools/rollout_video.py --policy smolvla --steps 120 --out reports/rollout_smolvla
    .venv/bin/python tools/rollout_video.py --policy smolvla_lew --steps 120 --out reports/rollout_smolvla_lew
输出: <out>/frame_%04d.png (观测帧) + <out>/actions.npy (动作) + <out>/info.json (帧数/耗时/平均动作幅度)
GUI: 推理对比对话框读 reports/rollout_<policy>/ 三个目录, 3 窗口同步播放
"""
import argparse, json, os, sys, time
import numpy as np
import torch
from pathlib import Path

# 渲染必须的 GL 环境 (在 import mujoco/metaworld 前设置, WSLg X0 socket)
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")
os.environ.setdefault("MUJOCO_EGL_DEVICE", "0")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

def _load_preprocessor_stats(pm: str):
    """从 checkpoint preprocessor 读归一化 stats — 2026-08-06: preprocessor 可能坏(2D state/像素级action),
    改用数据 stats.json (与训练一致)"""
    import json as _j
    # 优先数据 stats.json (正确来源)
    for root in ["data/metaworld_peg_v5", "data/metaworld_peg_v4", "data/metaworld_peg_v3"]:
        p = os.path.join(ROOT, root, "meta", "stats.json")
        if os.path.exists(p):
            try:
                d = _j.load(open(p))
                return {"action.mean": np.array(d["action"]["mean"], dtype=np.float32),
                        "action.std": np.array(d["action"]["std"], dtype=np.float32),
                        "observation.state.mean": np.array(d["observation.state"]["mean"], dtype=np.float32),
                        "observation.state.std": np.array(d["observation.state"]["std"], dtype=np.float32)}
            except Exception:
                pass
    # 兜底: preprocessor
    import glob as _g
    try:
        from safetensors.torch import load_file
        hits = _g.glob(os.path.join(pm, "policy_preprocessor_step_*normalizer*.safetensors"))
        if not hits:
            return None
        d = load_file(hits[-1])
        return {k: v.numpy() for k, v in d.items()}
    except Exception:
        return None

def load_policy(policy: str):
    """按 policy 加载已训练 checkpoint (train_curve_<policy>.json 记录 ckpt 路径)"""
    curve_path = os.path.join(ROOT, "reports", f"train_curve_{policy}.json")
    if not os.path.exists(curve_path):
        raise FileNotFoundError(f"无训练产物: {curve_path} (先训练 {policy})")
    ckpt_base = json.load(open(curve_path, encoding="utf-8")).get("ckpt", "")
    # 🐛 2026-08-06 修复: on_train 的 ts_dir 与 train_vla_touch/train_awe_zflow 内部
    # 生成的 ts 可能差几秒 → 记录路径不存在 → rollout 失败 (自动交付卡在这)
    # 兜底: glob 找最新同前缀目录
    base_dir = os.path.join(ROOT, ckpt_base)
    # 🐛 2026-08-07: expert_mlp 是 .pt 文件 (distill 保存) 非目录 → 特判
    if policy == "expert_mlp" and os.path.isfile(base_dir):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "distill_expert", os.path.join(ROOT, "tools", "distill_expert.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        data = torch.load(base_dir, map_location="cpu")
        pol = mod.ExpertMLP(int(data.get("obs_dim", 39)), int(data.get("act_dim", 4)))
        pol.load_state_dict(data["model"])
        pol.obs_dim = int(data.get("obs_dim", 39))
        pol.state_dim = pol.obs_dim  # 🐛 2026-08-07: st_dim 推断用 obs_dim (默认2 致 forward 失败)
        pol.action_dim = int(data.get("act_dim", 4))
        pol.eval()
        return pol, base_dir
    if not os.path.isdir(base_dir):
        import glob as _g
        prefix = os.path.basename(os.path.dirname(ckpt_base)).rsplit("_", 1)[0]  # vla_touch_20260806_180350 → vla_touch_20260806
        hits = sorted(_g.glob(os.path.join(ROOT, "outputs", "train", f"{prefix}_*", "checkpoints")),
                      key=os.path.getmtime)
        if hits:
            base_dir = hits[-1]
    # last → pretrained_model 目录
    cands = [
        os.path.join(base_dir, "last", "pretrained_model"),
        os.path.join(base_dir, "000150", "pretrained_model"),
        os.path.join(base_dir, "000300", "pretrained_model"),
        os.path.join(base_dir, "000050", "pretrained_model"),
    ]
    pm = next((p for p in cands if os.path.isdir(p)), None)
    if pm is None:
        raise FileNotFoundError(f"checkpoint 不存在: {ckpt_base}")
    # ACT 用 act factory; smolvla 系用 smolvla_lew
    if policy == "act":
        from lerobot.policies.act.modeling_act import ACTPolicy
        pol = ACTPolicy.from_pretrained(pm, local_files_only=True)
        # 从 checkpoint preprocessor 读归一化 stats (2026-08-06: ACT 输出归一化, 需反归一化)
        _st = _load_preprocessor_stats(pm)
        if _st:
            pol.stats = {"a_mean": _st["action.mean"], "a_std": _st["action.std"],
                         "s_mean": _st["observation.state.mean"], "s_std": _st["observation.state.std"]}
    elif policy == "smolvla" or policy == "smolvla_lew":
        from lerobot.policies.smolvla_lew.modeling_smolvla_lew import SmolVLALewPolicy
        pol = SmolVLALewPolicy.from_pretrained(pm, local_files_only=True)
        _st = _load_preprocessor_stats(pm)
        if _st:
            pol.stats = {"a_mean": _st["action.mean"], "a_std": _st["action.std"],
                         "s_mean": _st["observation.state.mean"], "s_std": _st["observation.state.std"]}
    elif policy == "vla_touch":
        import importlib.util
        spec = importlib.util.spec_from_file_location("train_vla_touch", os.path.join(ROOT, "tools", "train_vla_touch.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        data = torch.load(Path(pm) / "model.pt", map_location="cpu")
        cfg = data["config"]
        pol = mod.InterpolantPolicy(cfg["action_dim"], cfg["state_dim"], cfg["tactile_dim"],
                                    cfg["vis_dim"], cfg["hidden"])
        pol.load_state_dict(data["state_dict"])
        pol.state_dim = int(cfg["state_dim"])  # rollout 维度推断
        pol.action_dim = int(cfg["action_dim"])
        pol.tactile_dim = int(cfg.get("tactile_dim", 3))
        pol.eval()
    elif policy == "awe_zflow":
        import importlib.util
        spec = importlib.util.spec_from_file_location("train_awe_zflow", os.path.join(ROOT, "tools", "train_awe_zflow.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        data = torch.load(Path(pm) / "model.pt", map_location="cpu")
        cfg = data["config"]
        pol = mod.AWEZFlowModel(cfg["action_dim"], cfg["state_dim"], cfg["tactile_dim"],
                                cfg["vis_dim"], d_z1=cfg["d_z"][0], d_z2=cfg["d_z"][1],
                                d_z3=cfg["d_z"][2], hidden=cfg["hidden"])
        pol.load_state_dict(data["state_dict"])
        pol.state_dim = int(cfg["state_dim"])
        pol.action_dim = int(cfg["action_dim"])
        pol.tactile_dim = int(cfg.get("tactile_dim", 3))
        # 归一化统计 (训练管道一致, 2026-08-06 修复: 输入必须归一化否则输出饱和)
        pol.stats = data.get("stats", {})
        pol.eval()
    else:
        from lerobot.policies.smolvla_lew.modeling_smolvla_lew import SmolVLALewPolicy
        pol = SmolVLALewPolicy.from_pretrained(pm, local_files_only=True)
    pol.eval()
    return pol, pm

def run_rollout(policy, steps: int, out_dir: str, seed: int = 0, task_name: str = "push-v3",
                camera: str = "corner", rotate_ccw: bool = False):
    """metaworld V3 环境 rollout: 每个 episode 重置, 推理 select_action 步进, 存观测帧"""
    import metaworld
    from PIL import Image
    os.makedirs(out_dir, exist_ok=True)
    # metaworld V3: task 环境 + 指定相机视角 (corner=斜侧看插销)
    from metaworld.env_dict import ALL_V3_ENVIRONMENTS
    env_cls = ALL_V3_ENVIRONMENTS[task_name]
    env = env_cls(render_mode="rgb_array", camera_name=camera)  # camera_name 必须构造时传入!
    env._freeze_rand_vec = False  # 允许随机初始化
    mt1 = metaworld.MT1(task_name, seed=seed)
    env.set_task(mt1.train_tasks[0])  # V3 必需: set_task 后才能 step
    env.reset(seed=seed)
    frames, actions = [], []
    obs, _info = env.reset()
    act_hist = None  # AWE 自回归动作历史
    t0 = time.time()
    for i in range(steps):
        # 取 RGB 帧: 优先 obs 里的真渲染图 (V3 observation.image = 相机视图), 兜底 env.render()
        rgb = None
        try:
            oimg = obs.get("observation.image") if isinstance(obs, dict) else None
            if oimg is not None:
                oimg = np.asarray(oimg)
                if oimg.ndim == 3 and oimg.shape[2] == 3 and oimg.var() > 1:
                    rgb = oimg
                elif oimg.ndim == 4 and oimg.shape[0] == 1:
                    rgb = oimg[0].transpose(1, 2, 0) if oimg.shape[1] == 3 else oimg[0]
        except Exception:
            pass
        if rgb is None:
            try:
                rgb = env.render()  # (H,W,3) uint8
            except Exception:
                rgb = None
        if rgb is None:
            rgb = np.zeros((480, 640, 3), dtype=np.uint8)
        if rgb.dtype != np.uint8:
            rgb = (rgb * 255).astype(np.uint8)
        if rgb.ndim == 3 and rgb.shape[2] == 3 and rgb.shape[0] < 100:
            rgb = np.asarray(Image.fromarray(rgb).resize((640, 480)))
        # 逆时针水平旋转 (老倪要求: 视频方向转正, 2026-08-06; 再转90°=共180° k=2)
        if rotate_ccw:
            rgb = np.rot90(rgb, k=2)
        frames.append(rgb)
        # 模型推理 (用 env obs 视觉 + state)
        act = np.zeros(env.action_space.shape, dtype=float)
        try:
            cfg = getattr(policy, "config", None)
            if cfg is not None and hasattr(cfg, "input_features"):
                st_dim = cfg.input_features["observation.state"].shape[0]
            else:
                # 精简模型 (vla_touch/awe): 从 model.pt config 推断
                st_dim = int(getattr(policy, "state_dim", 2) or 2)
            # ACT 权重可能是 2D (热启动残留, config 3D 但权重 2D) — 2026-08-06 修复
            if hasattr(policy, "model") and hasattr(policy.model, "encoder_robot_state_input_proj"):
                w_dim = policy.model.encoder_robot_state_input_proj.weight.shape[1]
                if w_dim != st_dim:
                    print(f"⚠️ state 维度修正: config={st_dim} → 权重={w_dim}")
                    st_dim = w_dim
            # 🐛 2026-08-07: V3 环境 obs 是 dict (observation.state/image) —
            #   np.asarray(dict) → 0维对象数组 → state 全零 → 所有模型推理异常/动作≈0
            if isinstance(obs, dict):
                _st_raw = np.asarray(obs.get("observation.state", np.zeros(st_dim, dtype=np.float32)), dtype=np.float32)
            else:
                _st_raw = np.asarray(obs, dtype=np.float32)
            st = _st_raw[:st_dim] if _st_raw.ndim == 1 and _st_raw.size >= st_dim else np.zeros(st_dim, dtype=np.float32)
            dev = next(policy.parameters()).device
            # AWE/ACT: 输入归一化 (训练管道一致) — 🐛 2026-08-07: stats 可能旧 3D 而
            #   state 39D (完整观测) → (39,) - (3,) 广播异常 → 维度不足补零
            if hasattr(policy, "stats") and policy.stats.get("s_mean") is not None:
                sm = np.array(policy.stats["s_mean"], dtype=np.float32)
                ss = np.array(policy.stats["s_std"], dtype=np.float32) + 1e-6
                if sm.size >= st_dim:
                    sm, ss = sm[:st_dim], ss[:st_dim]
                else:
                    sm = np.pad(sm, (0, st_dim - sm.size))
                    ss = np.pad(ss, (0, st_dim - ss.size)) + 1e-6  # 补零区防除0 NaN
                st = (st - sm) / ss
            batch = {
                "observation.image": torch.from_numpy(rgb[np.newaxis].transpose(0, 3, 1, 2) / 255.0).float().to(dev),
                "observation.state": torch.from_numpy(st).float().unsqueeze(0).to(dev),
            }
            # ACT: 39D 完整观测 = robot(3) + env(36) → 拆分 (2026-08-07: 广播 39 vs 3 修复 —
            #   ACTPolicy 期望 observation.environment_state; 从权重维度推断 robot/env 维)
            _env_proj = None
            if hasattr(policy, "model") and hasattr(policy.model, "encoder_env_state_input_proj"):
                _env_proj = policy.model.encoder_env_state_input_proj.weight.shape[1]
            if _env_proj and st.shape[0] >= 3 + _env_proj:
                batch["observation.state"] = torch.from_numpy(st[:3]).float().unsqueeze(0).to(dev)
                batch["observation.environment_state"] = torch.from_numpy(st[3:3 + _env_proj]).float().unsqueeze(0).to(dev)
            with torch.no_grad():
                if hasattr(policy, "select_action"):
                    pred = policy.select_action(batch)
                elif hasattr(policy, "obs_dim") and not hasattr(policy, "model"):
                    # 🐛 2026-08-07: ExpertMLP 纯 forward (39D 状态直出动作)
                    pred = policy(batch["observation.state"])
                elif hasattr(policy, "_cond"):  # vla_touch: interpolant 采样
                    tac_dim = getattr(policy, "tactile_dim", 3) or 3
                    tac = torch.zeros((1, tac_dim), dtype=torch.float32, device=dev)
                    cond = policy._cond(batch["observation.state"], tac, None)
                    # 🐛 2026-08-06: x0 用上一帧动作 (插值起点, 与训练 q_sample 一致) —
                    #   之前 randn*0.1 纯噪声 → 扩散从噪声出发走不到动作空间 → 动作幅度小
                    act_dim = getattr(policy, "action_dim", 4) or 4
                    if act_hist is not None:
                        x0 = act_hist.to(dev).float()
                    else:
                        x0 = torch.zeros((1, act_dim), dtype=torch.float32, device=dev)
                    pred = policy.sample(x0, cond, diffuse_steps=10)
                else:  # awe_zflow: 直接 forward (动作历史=上一帧动作, 自回归)
                    tac_dim = getattr(policy, "tactile_dim", 3) or 3
                    act_dim = getattr(policy, "action_dim", 4) or 4
                    ah = act_hist.to(dev) if act_hist is not None else batch["observation.state"].new_zeros((1, act_dim))
                    pred = policy(batch["observation.state"], batch["observation.state"].new_zeros((1, tac_dim)), ah, None)
                    if isinstance(pred, tuple):
                        pred = pred[0]
            if isinstance(pred, torch.Tensor):
                pred = pred.detach().cpu()
            a = np.asarray(pred).ravel()
            # AWE: 输出反归一化 (归一化空间 → 真实动作)
            if hasattr(policy, "stats") and policy.stats.get("a_mean") is not None and a.size:
                am = np.array(policy.stats["a_mean"], dtype=np.float32)[: a.size]
                asd = np.array(policy.stats["a_std"], dtype=np.float32)[: a.size] + 1e-6
                a = a * asd + am
            if a.size >= act.size:
                act[:] = a[: act.size]
            else:
                act[: a.size] = a
        except Exception as ex:
            import traceback as _tb
            print(f"⚠️ 推理异常({policy.__class__.__name__}): {ex}")
            _tb.print_exc(limit=3)  # 2026-08-07 诊断: 定位 39 vs 3 广播来源
            pass  # 推理失败用零动作 (视频仍展示环境)
        actions.append(act)
        # 更新 AWE 动作历史 (归一化空间, 与训练一致)
        act_hist = torch.from_numpy(np.asarray(act, dtype=np.float32)[:4]).float().unsqueeze(0)
        obs, _, terminated, truncated, _ = env.step(act)
        if terminated or truncated:
            obs = env.reset()
    dur = time.time() - t0
    # 存帧
    for i, f in enumerate(frames):
        Image.fromarray(f).save(os.path.join(out_dir, f"frame_{i:04d}.png"))
    np.save(os.path.join(out_dir, "actions.npy"), np.array(actions, dtype=float))
    info = {"frames": len(frames), "seconds": round(dur, 2), "fps": round(len(frames) / dur, 2),
            "action_mean": round(float(np.mean(np.abs(actions))), 4) if actions else 0.0}
    json.dump(info, open(os.path.join(out_dir, "info.json"), "w", encoding="utf-8"), indent=1)
    print(f"✅ rollout 完成: {out_dir} · {len(frames)}帧 · {info['fps']}fps · 动作均值 {info['action_mean']}")
    return info

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", choices=["act", "smolvla", "smolvla_lew", "vla_touch", "awe_zflow",
                                        "expert_mlp", "expert_policy"], default="act")
    ap.add_argument("--steps", type=int, default=120)
    ap.add_argument("--out", default=None)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--task", default="push-v3")
    ap.add_argument("--camera", default="corner", help="corner/topview/behindGripper/gripperPOV")
    ap.add_argument("--rotate-ccw", action="store_true", help="逆时针水平旋转90° (方向转正)")
    a = ap.parse_args()
    out = a.out or os.path.join(ROOT, "reports", f"rollout_{a.policy}")
    pol, pm = load_policy(a.policy)
    print(f"🎥 推理 {a.policy} · checkpoint: {os.path.basename(pm)} · task={a.task} · cam={a.camera} · rot90={a.rotate_ccw}")
    run_rollout(pol, a.steps, out, a.seed, a.task, a.camera, a.rotate_ccw)

if __name__ == "__main__":
    main()
