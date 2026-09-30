#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎥 INTACT 标准机器人 · 逐帧实况驱动器 (画布用)

在 INTACT venv + paper_runtime 下常驻: 加载原项目论文权重 → 在其原生环境里闭环绕环,
每步把**最新真帧**写成 jpg, 把状态 (步数/动作/奖励/done/成功率) 写成 json ——
画布上的「INTACT 机器人实况」窗口用 QTimer 轮询这两个文件显示 (避免二进制走 stdout)。

用法:
  .venv/bin/python tools/intact_native_worker.py --robot reacher --steps 200 \
      --frame /tmp/intact_live_reacher.jpg --status /tmp/intact_live_reacher.json
状态 json: {"step": n, "ep": k, "action": [...], "reward": r, "done": bool, "succ": 0/1,
            "frame": path, "frame_std": s, "model_calls": m, "robot": name, "env": ...}
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

RT = "/home/ubuntu/INTACT-JEPA/paper_runtime"
REPO = "/home/ubuntu/INTACT-JEPA"

# 与 intact_native_robot.py 保持同一注册表口径
ROBOTS = {
    "reacher": {"env_name": "swm/ReacherDMControl-v0", "task": "qpos_match",
                "max_episode_steps": 100, "ckpt": "recovery_delta_full_reacher_s3072"},
    "pusht": {"env_name": "swm/PushT-v1", "task": None,
              "max_episode_steps": 50, "ckpt": "recovery_delta_full_pusht_s3072"},
    "cube": {"env_name": "OGBench cube-single", "task": None,
             "max_episode_steps": 200, "ckpt": "recovery_delta_full_cube_s3072"},
    "tworoom": {"env_name": "OGBench tworoom", "task": None,
                "max_episode_steps": 200, "ckpt": "recovery_delta_full_tworoom_s3072"},
}


def _write_status(path, d):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--robot", default="reacher")
    ap.add_argument("--steps", type=int, default=200, help="0=一直跑 (画布实况)")
    ap.add_argument("--frame", default="/tmp/intact_live.jpg")
    ap.add_argument("--status", default="/tmp/intact_live.json")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--device", default="cuda")
    a = ap.parse_args()

    os.chdir(RT)
    sys.path.insert(0, RT)
    cache = os.environ.setdefault("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
    os.environ.setdefault("LOCAL_DATASET_DIR", cache)
    os.environ.setdefault("MUJOCO_GL", "egl")
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")

    import numpy as np
    import cv2
    import stable_worldmodel as swm

    r = ROBOTS[a.robot]
    _write_status(a.status, {"ok": False, "stage": "load", "robot": a.robot, "env": r["env_name"]})

    # ① 世界 (原生环境)
    max_steps = int(r["max_episode_steps"]) * 2
    world = swm.World(env_name=r["env_name"], num_envs=1, max_episode_steps=max_steps,
                      **({"task": r["task"]} if r["task"] else {}), image_shape=(224, 224))

    # ② 模型 (原项目论文权重)
    model = swm.policy.AutoCostModel(r["ckpt"]) if hasattr(swm.policy, "AutoCostModel") else None
    if model is None:                      # 兜底: 走仓库自己的加载器
        from utils import load_model_from_folder      # paper_runtime/utils.py
        model = load_model_from_folder(r["ckpt"])
    if hasattr(model, "to"):
        model = model.to(a.device)
    model.eval()

    obs, _ = world.reset(seed=a.seed) if isinstance(world.reset(seed=a.seed), tuple) else (world.reset(seed=a.seed), None)
    # 注: 不同版本 reset 返回 (obs, info) 或 obs; 上面这行兼容两种写法
    ep, succ, step = 0, 0, 0
    try:
        policy = swm.policy.WorldModelPolicy(model, horizon=5, action_block=5, device=a.device)
    except Exception:
        policy = None

    t0 = time.time()
    while a.steps == 0 or step < a.steps:
        if policy is not None:
            act = policy.act(obs) if hasattr(policy, "act") else policy(obs)
        else:
            act = model.get_action(obs, horizon=5) if hasattr(model, "get_action") else None
        out = world.step(act)
        obs = out[0] if isinstance(out, tuple) else out
        rew = float(np.asarray(out[1]).reshape(-1)[0]) if isinstance(out, tuple) and len(out) > 1 else 0.0
        done = bool(np.asarray(out[2]).reshape(-1)[0]) if isinstance(out, tuple) and len(out) > 2 else False
        img = None
        try:
            frames = world.render()
            img = np.asarray(frames[0] if isinstance(frames, (list, tuple)) else frames)
        except Exception:
            try:
                img = np.asarray(world.envs.envs[0].render())
            except Exception:
                img = None
        std = None
        if img is not None and img.size:
            std = float(img.std())
            cv2.imwrite(a.frame, cv2.cvtColor(img, cv2.COLOR_RGB2BGR) if img.shape[2] == 3 else img)
        step += 1
        if done:
            ep += 1
            succ += 1 if rew > 0 else 0
        _write_status(a.status, {"ok": True, "stage": "run", "robot": a.robot, "env": r["env_name"],
                                 "ckpt": r["ckpt"], "step": step, "ep": ep, "succ": succ,
                                 "success_rate": (round(100.0 * succ / max(ep, 1), 1) if ep else None),
                                 "action": (np.asarray(act).reshape(-1)[:8].round(4).tolist()
                                            if act is not None else None),
                                 "reward": round(rew, 4), "done": done,
                                 "frame": a.frame, "frame_std": (round(std, 2) if std else None),
                                 "model_calls": step, "elapsed": round(time.time() - t0, 1)})
    _write_status(a.status, {"ok": True, "stage": "done", "robot": a.robot, "step": step,
                             "ep": ep, "succ": succ, "frame": a.frame})
    return 0


if __name__ == "__main__":
    sys.exit(main())
