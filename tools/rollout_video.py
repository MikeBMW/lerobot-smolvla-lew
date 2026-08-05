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

def load_policy(policy: str):
    """按 policy 加载已训练 checkpoint (train_curve_<policy>.json 记录 ckpt 路径)"""
    curve_path = os.path.join(ROOT, "reports", f"train_curve_{policy}.json")
    if not os.path.exists(curve_path):
        raise FileNotFoundError(f"无训练产物: {curve_path} (先训练 {policy})")
    ckpt_base = json.load(open(curve_path, encoding="utf-8")).get("ckpt", "")
    # last → pretrained_model 目录
    cands = [
        os.path.join(ROOT, ckpt_base, "last", "pretrained_model"),
        os.path.join(ROOT, ckpt_base, "000150", "pretrained_model"),
        os.path.join(ROOT, ckpt_base, "000300", "pretrained_model"),
        os.path.join(ROOT, ckpt_base, "000050", "pretrained_model"),
    ]
    pm = next((p for p in cands if os.path.isdir(p)), None)
    if pm is None:
        raise FileNotFoundError(f"checkpoint 不存在: {ckpt_base}")
    # ACT 用 act factory; smolvla 系用 smolvla_lew
    if policy == "act":
        from lerobot.policies.act.modeling_act import ACTPolicy
        pol = ACTPolicy.from_pretrained(pm, local_files_only=True)
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
        pol.eval()
    elif policy == "awe_zflow":
        import importlib.util
        spec = importlib.util.spec_from_file_location("train_awe_zflow", os.path.join(ROOT, "tools", "train_awe_zflow.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        data = torch.load(Path(pm) / "model.pt", map_location="cpu")
        cfg = data["config"]
        pol = mod.AWEZFlowModel(cfg["action_dim"], cfg["state_dim"], cfg["tactile_dim"],
                                cfg["vis_dim"], hidden=cfg["hidden"])
        pol.load_state_dict(data["state_dict"])
        pol.state_dim = int(cfg["state_dim"])
        pol.action_dim = int(cfg["action_dim"])
        pol.eval()
    else:
        from lerobot.policies.smolvla_lew.modeling_smolvla_lew import SmolVLALewPolicy
        pol = SmolVLALewPolicy.from_pretrained(pm, local_files_only=True)
    pol.eval()
    return pol, pm

def run_rollout(policy, steps: int, out_dir: str, seed: int = 0, task_name: str = "push-v3"):
    """metaworld V3 环境 rollout: 每个 episode 重置, 推理 select_action 步进, 存观测帧"""
    import metaworld
    from PIL import Image
    os.makedirs(out_dir, exist_ok=True)
    # metaworld V3: push-v3 (与 metaworld_act 数据集同族) — 标准 V3 用法
    from metaworld.env_dict import ALL_V3_ENVIRONMENTS
    env_cls = ALL_V3_ENVIRONMENTS[task_name]
    env = env_cls(render_mode="rgb_array")  # 必须 rgb_array 模式, 否则 render 全黑
    env._freeze_rand_vec = False  # 允许随机初始化
    mt1 = metaworld.MT1(task_name, seed=seed)
    env.set_task(mt1.train_tasks[0])  # V3 必需: set_task 后才能 step
    env.reset(seed=seed)
    frames, actions = [], []
    obs, _info = env.reset()
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
            st_vec = np.asarray(obs, dtype=np.float32)
            st = st_vec[:st_dim] if st_vec.ndim == 1 else np.zeros(st_dim, dtype=np.float32)
            dev = next(policy.parameters()).device
            batch = {
                "observation.image": torch.from_numpy(rgb[np.newaxis].transpose(0, 3, 1, 2) / 255.0).float().to(dev),
                "observation.state": torch.from_numpy(st).float().unsqueeze(0).to(dev),
            }
            with torch.no_grad():
                if hasattr(policy, "select_action"):
                    pred = policy.select_action(batch)
                elif hasattr(policy, "_cond"):  # vla_touch: interpolant 采样
                    tac = torch.zeros((1, 3), dtype=torch.float32, device=dev)
                    cond = policy._cond(batch["observation.state"], tac, None)
                    x0 = torch.randn_like(batch["observation.state"].new_zeros((1, policy.action_dim))) * 0.1
                    pred = policy.sample(x0, cond, diffuse_steps=10)
                else:  # awe_zflow: 直接 forward
                    ah = batch["observation.state"].new_zeros((1, 2))
                    pred = policy(batch["observation.state"], tac_zero := batch["observation.state"].new_zeros((1, 3)), ah, None)
                    if isinstance(pred, tuple):
                        pred = pred[0]
            if isinstance(pred, torch.Tensor):
                pred = pred.detach().cpu()
            a = np.asarray(pred).ravel()
            if a.size >= act.size:
                act[:] = a[: act.size]
            else:
                act[: a.size] = a
        except Exception as ex:
            import traceback as _tb
            print(f"⚠️ 推理异常({policy.__class__.__name__}): {ex}")
            pass  # 推理失败用零动作 (视频仍展示环境)
        actions.append(act)
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
    ap.add_argument("--policy", choices=["act", "smolvla", "smolvla_lew", "vla_touch", "awe_zflow"], default="act")
    ap.add_argument("--steps", type=int, default=120)
    ap.add_argument("--out", default=None)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--task", default="push-v3")
    a = ap.parse_args()
    out = a.out or os.path.join(ROOT, "reports", f"rollout_{a.policy}")
    pol, pm = load_policy(a.policy)
    print(f"🎥 推理 {a.policy} · checkpoint: {os.path.basename(pm)} · task={a.task}")
    run_rollout(pol, a.steps, out, a.seed, a.task)

if __name__ == "__main__":
    main()
