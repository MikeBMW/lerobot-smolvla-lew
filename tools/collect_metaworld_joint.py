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


def load_policy(task, policy_mode):
    """加载专家策略 (metaworld 自带 scripted policy)"""
    if policy_mode != "expert":
        return None
    name = f"sawyer_{task.replace('-', '_')}_policy"
    try:
        import importlib
        mod = importlib.import_module(f"metaworld.policies.{name}")
        cls = getattr(mod, "".join(p.capitalize() for p in name.split("_")))
        return cls()
    except Exception as ex:
        print(f"⚠️ 专家策略 {name} 加载失败 ({ex}) → 回退随机策略")
        return None


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
    ap.add_argument("--policy", default="expert", choices=("expert", "random"),
                    help="expert=metaworld脚本策略(高质量演示), random=随机动作")
    args = ap.parse_args()

    np.random.seed(args.seed)
    mt = metaworld.MT1(args.task)
    env = mt.train_classes[args.task]()
    env.set_task(mt.train_tasks[0])
    env.seed(args.seed)
    renderer = mujoco.Renderer(env.model, args.img, args.img)
    policy = load_policy(args.task, args.policy)
    print(f"策略: {'🎯 expert 脚本策略' if policy else '🎲 random 随机动作'}")

    states, actions, imgs, ep_ids = [], [], [], []
    for ep in range(args.episodes):
        obs, _ = env.reset()
        prev_qpos = None
        for t in range(args.steps):
            # 执行: expert 脚本策略 (高质量演示) 或 默认 4D 随机动作
            if policy is not None:
                act = policy.get_action(obs) if not isinstance(obs, tuple) else policy.get_action(obs[0])
            else:
                act = env.action_space.sample()
            obs, rew, term, trunc, info = env.step(act)
            qpos = env.data.qpos.copy()
            # state: 前6关节角 (6D, 对齐 Orin n_joint=6; 不含夹爪维度)
            st = qpos[0:6].astype(np.float32)
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
