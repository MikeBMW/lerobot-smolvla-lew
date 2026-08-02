#!/usr/bin/env python3
"""
MetaWorld joint 观测数据采集 (2026-08-02)
用 Sawyer 7轴机器人 (metaworld) 采集关节空间数据, 与 Orin 产线对齐:
  state  = qpos[0:6] 前6关节角 + 夹爪归一化距离 → 7D (对齐 Orin 7D)
  action = 关节速度差分 qpos[0:6] 逐帧差 → 6D (对齐 Orin 6D)
  image  = offscreen render 64×64 (对齐 Orin 64×64)

用法:
  .venv/bin/python tools/collect_metaworld_joint.py --task reach-v3 \
      --episodes 10 --steps 100 --out data/metaworld_joint.npz
"""
import argparse
import numpy as np
import mujoco
import metaworld

GRIPPER_MAX = 0.1  # 夹爪最大开合距离 (metaworld 归一化用)


def gripper_norm(env):
    """夹爪两指距离 → 0-1 归一化"""
    fr = env.data.body("rightclaw").xpos
    fl = env.data.body("leftclaw").xpos
    return float(np.clip(np.linalg.norm(fr - fl) / GRIPPER_MAX, 0.0, 1.0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="reach-v3")
    ap.add_argument("--episodes", type=int, default=10)
    ap.add_argument("--steps", type=int, default=100, help="每 episode 最大步数")
    ap.add_argument("--out", default="data/metaworld_joint.npz")
    ap.add_argument("--img", type=int, default=64, help="渲染图像尺寸 (对齐 Orin 64)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    np.random.seed(args.seed)
    mt = metaworld.MT1(args.task)
    env = mt.train_classes[args.task]()
    env.set_task(mt.train_tasks[0])
    env.seed(args.seed)
    renderer = mujoco.Renderer(env.model, args.img, args.img)

    states, actions, imgs, ep_ids = [], [], [], []
    for ep in range(args.episodes):
        obs, _ = env.reset()
        prev_qpos = None
        for t in range(args.steps):
            # 执行: 默认 4D 末端随机动作 (无 joint action 模式, 用末端控制驱动仿真)
            act = env.action_space.sample()
            obs, rew, term, trunc, info = env.step(act)
            qpos = env.data.qpos.copy()
            # state: 前6关节角 + 夹爪 (7D, 对齐 Orin)
            st = np.concatenate([qpos[0:6].astype(np.float32),
                                 [np.float32(gripper_norm(env))]])
            # action: 关节速度差分 (6D, 对齐 Orin) — 首帧用零
            if prev_qpos is None:
                ac = np.zeros(6, dtype=np.float32)
            else:
                ac = (qpos[0:6] - prev_qpos[0:6]).astype(np.float32)
            prev_qpos = qpos.copy()
            img = renderer.render().copy()  # (H,W,3) uint8
            states.append(st)
            actions.append(ac)
            imgs.append(img.astype(np.float32) / 255.0)  # 0-1 CHW 由转换器处理
            ep_ids.append(ep)
            if trunc or term:
                break
        print(f"  ep {ep}: {len([e for e in ep_ids if e == ep])} 帧", flush=True)

    n = len(states)
    # npz_to_lerobot 期望 CHW
    imgs_arr = np.stack(imgs).transpose(0, 3, 1, 2).astype(np.float32)
    out = args.out
    np.savez_compressed(out,
                        observations=imgs_arr,
                        states=np.stack(states),
                        actions=np.stack(actions),
                        task_name=np.array(args.task),
                        fps=np.array(30))
    print(f"✅ 采集完成: {out} · {n}帧 / {args.episodes}ep · "
          f"state{np.stack(states).shape[1]}D action{np.stack(actions).shape[1]}D img{imgs_arr.shape[1:]}")


if __name__ == "__main__":
    main()
