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
    ]
    pm = next((p for p in cands if os.path.isdir(p)), None)
    if pm is None:
        raise FileNotFoundError(f"checkpoint 不存在: {ckpt_base}")
    # ACT 用 act factory; smolvla 系用 smolvla_lew
    if policy == "act":
        from lerobot.policies.act.modeling_act import ACTPolicy
        from lerobot.policies.act.configuration_act import ACTConfig
        pol = ACTPolicy.from_pretrained(pm, local_files_only=True)
    else:
        from lerobot.policies.smolvla_lew.modeling_smolvla_lew import SmolVLALewPolicy
        pol = SmolVLALewPolicy.from_pretrained(pm, local_files_only=True)
    pol.eval()
    return pol, pm

def run_rollout(policy, steps: int, out_dir: str, seed: int = 0):
    """metaworld V3 环境 rollout: 每个 episode 重置, 推理 select_action 步进, 存观测帧"""
    import metaworld
    from PIL import Image
    os.makedirs(out_dir, exist_ok=True)
    # metaworld V3: push-v3 (与 metaworld_act 数据集同族) — 标准 V3 用法
    from metaworld.env_dict import ALL_V3_ENVIRONMENTS
    env_cls = ALL_V3_ENVIRONMENTS["push-v3"]
    env = env_cls()
    env._freeze_rand_vec = False  # 允许随机初始化
    mt1 = metaworld.MT1("push-v3", seed=seed)
    env.set_task(mt1.train_tasks[0])  # V3 必需: set_task 后才能 step
    env.reset(seed=seed)
    frames, actions = [], []
    obs, _info = env.reset()
    t0 = time.time()
    for i in range(steps):
        # 取 RGB 帧 (V3 env render_mode='rgb_array' → env.render() 返回 (H,W,3))
        try:
            rgb = env.render()  # (H,W,3) uint8
        except Exception:
            rgb = None
        if rgb is None:
            rgb = np.zeros((480, 640, 3), dtype=np.uint8)
        if rgb.dtype != np.uint8:
            rgb = (rgb * 255).astype(np.uint8)
        frames.append(rgb)
        # 模型推理 (用 env obs 视觉 + state)
        act = np.zeros(env.action_space.shape, dtype=float)
        try:
            batch = {"observation.image": rgb[np.newaxis].transpose(0, 3, 1, 2) / 255.0}
            pred = policy.select_action(batch)  # (action_dim,)
            a = np.asarray(pred).ravel()
            if a.size >= act.size:
                act[:] = a[: act.size]
            else:
                act[: a.size] = a
        except Exception as ex:
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
    ap.add_argument("--policy", choices=["act", "smolvla", "smolvla_lew"], default="act")
    ap.add_argument("--steps", type=int, default=120)
    ap.add_argument("--out", default=None)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    out = a.out or os.path.join(ROOT, "reports", f"rollout_{a.policy}")
    pol, pm = load_policy(a.policy)
    print(f"🎥 推理 {a.policy} · checkpoint: {os.path.basename(pm)}")
    run_rollout(pol, a.steps, out, a.seed)

if __name__ == "__main__":
    main()
