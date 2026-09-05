#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z-MAX 光模块数据集生成器 · peg-insert-side-v3 官方专家采样 (2026-08-07 老倪: 不是光模块的数据)
用 metaworld 官方专家策略 SawyerPegInsertionSideV3Policy 采样成功轨迹,
输出: data/metaworld_peg/train.npz + val.npz (图像 128x128 + state 39D + action 4D)
用法: ./.venv/bin/python tools/gen_peg_data.py --eps 60 --out data/metaworld_peg
"""
import os, sys, json, argparse
import numpy as np

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eps", type=int, default=60, help="采样 episode 数 (只保留插入成功)")
    ap.add_argument("--out", default="data/metaworld_peg")
    ap.add_argument("--img", type=int, default=128, help="图像尺寸")
    ap.add_argument("--camera", default="corner2", help="相机视角 (与视频一致)")
    args = ap.parse_args()

    import metaworld
    from metaworld.policies.sawyer_peg_insertion_side_v3_policy import SawyerPegInsertionSideV3Policy

    mt = metaworld.MT1("peg-insert-side-v3", seed=0)
    expert = SawyerPegInsertionSideV3Policy()

    images, states, actions, eps_ids = [], [], [], []
    ok = 0
    ep_idx = 0
    t0 = __import__("time").time()
    while ok < args.eps and ep_idx < args.eps * 4:
        env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name=args.camera)
        env.set_task(mt.train_tasks[0])
        env._freeze_rand_vec = False
        obs, _ = env.reset(seed=ep_idx % 50)
        ep_idx += 1
        peg_z0 = env.data.site_xpos[env.model.site("pegGrasp").id][2]
        hole = env.data.site_xpos[env.model.site("hole").id]
        lifted = inserted = False
        ep_imgs, ep_st, ep_ac = [], [], []
        max_steps = 150 if ep_idx % 4 else 300  # 2026-08-07: 失败轨迹 150 步提前终止 (渲染慢)
        for i in range(max_steps):
            o = np.asarray(env._get_obs(), dtype=np.float32).ravel()  # 39D
            a = np.asarray(expert.get_action(o.astype(np.float64)), dtype=np.float32).ravel()[:4]
            ep_st.append(o); ep_ac.append(a)
            # 图像: obs 里 observation.image (V3)
            img = None
            if isinstance(obs, dict):
                oi = obs.get("observation.image")
                if oi is not None:
                    oi = np.asarray(oi)
                    if oi.ndim == 3 and oi.shape[2] == 3:
                        img = oi
                    elif oi.ndim == 4 and oi.shape[0] == 1:
                        img = oi[0]
            if img is None:
                img = env.render()
            if img.dtype != np.uint8:
                img = (img * 255).astype(np.uint8)
            from PIL import Image
            img = np.asarray(Image.fromarray(img).resize((args.img, args.img)), dtype=np.float32) / 255.0
            ep_imgs.append(img.transpose(2, 0, 1) if img.ndim == 3 and img.shape[-1] == 3 else img)
            obs, _, term, trunc, _ = env.step(a)
            peg = env.data.site_xpos[env.model.site("pegGrasp").id]
            if peg[2] - peg_z0 > 0.05:
                lifted = True
            if lifted and np.linalg.norm(peg - hole) < 0.05:
                inserted = True
            if term or trunc:
                break
        if inserted:
            ok += 1
            images.extend(ep_imgs); states.extend(ep_st); actions.extend(ep_ac)
            eps_ids.extend([ok - 1] * len(ep_imgs))
        if ep_idx % 10 == 0:
            print(f"  采样 {ep_idx} ep, 成功 {ok}/{args.eps} ({__import__('time').time()-t0:.0f}s)", flush=True)
    if not images:
        print("❌ 没有成功轨迹! 检查专家策略/环境")
        sys.exit(1)

    images = np.stack(images); states = np.stack(states); actions = np.stack(actions)
    eps_ids = np.array(eps_ids)
    n = len(images)
    print(f"✅ 成功 {ok} eps, 共 {n} 帧 | 图像 {images.shape} state {states.shape} action {actions.shape}")

    # 按 episode 划分 train/val (20%)
    uniq_eps = np.unique(eps_ids)
    rng = np.random.RandomState(42)
    n_val = max(1, int(len(uniq_eps) * 0.2))
    val_eps = set(rng.choice(uniq_eps, n_val, replace=False))
    val_mask = np.isin(eps_ids, list(val_eps))
    os.makedirs(args.out, exist_ok=True)
    for name, mask in [("train", ~val_mask), ("val", val_mask)]:
        np.savez_compressed(os.path.join(args.out, f"{name}.npz"),
                            observations=images[mask], states=states[mask],
                            actions=actions[mask],
                            task_name="zmax_peg_insert_side",
                            fps=10)
        print(f"  {name}.npz: {mask.sum()} 帧 ({mask.sum()/n:.0%})")
    meta = {"task": "peg-insert-side-v3", "success_eps": ok, "n_eps_total": ep_idx,
            "camera": args.camera, "img_size": args.img, "generated": __import__("time").strftime("%Y-%m-%d %H:%M")}
    json.dump(meta, open(os.path.join(args.out, "meta.json"), "w"), ensure_ascii=False, indent=2)
    print(f"🎯 光模块数据集完成: {args.out}/  (meta.json: {meta})")

if __name__ == "__main__":
    main()
