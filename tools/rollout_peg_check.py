#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""插拔成功检测评估 (2026-08-07 老倪: 必须保证至少一次插拔成功)
加载模型 → peg-insert-side-v3 环境 rollout N 次 → 检测插入成功 (peg抬升+进孔)
用法: ./.venv/bin/python tools/rollout_peg_check.py --policy act --ckpt outputs/train/act_pegdata_1000/checkpoints --n 5
"""
import os, sys, argparse
import numpy as np

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default="act")
    ap.add_argument("--ckpt", default=None, help="checkpoint 目录 (默认走 load_policy)")
    ap.add_argument("--n", type=int, default=5, help="rollout 次数")
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--save", default=None, help="成功时保存帧到目录")
    args = ap.parse_args()

    os.chdir("/home/xspace/lerobot-smolvla-lew")
    sys.path.insert(0, "tools"); sys.path.insert(0, "src")
    import metaworld
    import rollout_video as rv

    if args.ckpt:
        import json
        # 临时把曲线 ckpt 指向目标 → load_policy
        cf = f"reports/train_curve_{args.policy}.json"
        d = json.load(open(cf))
        d["ckpt"] = args.ckpt
        json.dump(d, open(cf, "w"), ensure_ascii=False)
    pol = rv.load_policy(args.policy)[0]
    dev = next(pol.parameters()).device

    mt = metaworld.MT1("peg-insert-side-v3", seed=0)
    ok, lifts = 0, 0
    min_dist = 99.0
    for ep in range(args.n):
        env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
        env.set_task(mt.train_tasks[0]); env._freeze_rand_vec = False
        obs, _ = env.reset(seed=ep)
        peg_z0 = env.data.site_xpos[env.model.site("pegGrasp").id][2]
        hole = env.data.site_xpos[env.model.site("hole").id]
        lifted = inserted = False
        dists = []
        for i in range(args.steps):
            # obs 兼容: dict (observation.state) 或裸数组
            if isinstance(obs, dict):
                o = np.asarray(obs.get("observation.state", np.zeros(4)), dtype=np.float32).ravel()
                rgb = obs.get("observation.image")
            else:
                o = np.asarray(obs, dtype=np.float32).ravel()
                rgb = None
            o_full = np.asarray(env._get_obs(), dtype=np.float32).ravel()
            st_dim = 39 if o_full.size >= 39 else o.size
            st = o_full[:st_dim]
            if rgb is None:
                rgb = env.render()
            rgb = np.asarray(rgb)
            if rgb.ndim == 4 and rgb.shape[0] == 1:
                rgb = rgb[0]
            batch = {
                "observation.image": __import__("torch").from_numpy(
                    rgb[np.newaxis].transpose(0, 3, 1, 2) / 255.0).float().to(dev),
                "observation.state": __import__("torch").from_numpy(st).float().unsqueeze(0).to(dev),
            }
            with __import__("torch").no_grad():
                if hasattr(pol, "select_action"):
                    a = np.asarray(pol.select_action(batch).detach().cpu()).ravel()[:4]
                elif hasattr(pol, "forward") and hasattr(pol, "obs_dim"):
                    # 🐛 2026-08-07: ExpertMLP 纯 forward (无 select_action) — 39D 状态直出动作
                    import torch as _t
                    a = pol(_t.from_numpy(st).float().unsqueeze(0).to(dev)).detach().cpu().numpy().ravel()[:4]
                else:
                    break
            obs, _, term, trunc, _ = env.step(a)
            peg = env.data.site_xpos[env.model.site("pegGrasp").id]
            d_ = float(np.linalg.norm(peg - hole))
            dists.append(d_)
            if peg[2] - peg_z0 > 0.05:
                lifted = True
            if lifted and d_ < 0.05:
                inserted = True
            if term or trunc:
                break
        min_dist = min(min_dist, min(dists))
        ok += int(inserted)
        lifts += int(lifted)
        print(f"  ep{ep}: {'✅ 插入成功' if inserted else ('🟡 已抬起未插入' if lifted else '❌ 没抬起')} 最近距离 {min(dists):.3f}m", flush=True)
        if inserted and args.save:
            os.makedirs(args.save, exist_ok=True)
            from PIL import Image
            for j, f in enumerate(sorted(os.listdir(args.save))):
                os.remove(os.path.join(args.save, f))
            # 重放保存成功轨迹帧 (简化: 存最后帧)
            Image.fromarray((rgb * 255).astype(np.uint8)).save(os.path.join(args.save, "success_last.png"))
    print(f"\n🎯 {args.policy}: {ok}/{args.n} 次插入成功 ({ok/args.n:.0%}) | 抬起 {lifts}/{args.n} | 最小孔距 {min_dist:.3f}m")

if __name__ == "__main__":
    main()
