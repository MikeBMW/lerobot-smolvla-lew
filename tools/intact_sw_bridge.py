#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌍 INTACT × stable-world 仿真世界引擎桥 (在 INTACT venv + paper_runtime 下跑)

老倪 2026-09-13 需求: 把「单独运行的 INTACT debug 任务」集成进状态空间画布 ——
  · 数据源层 = INTACT 环境渲染的图像 (本桥逐帧把 env 渲染帧写成 jpg)
  · 中间      = INTACT 策略 (论文权重 cube, 零搜索 prior_only, 与 ② debug 同口径)
  · 硬件层    = stable-world 仿真世界引擎 (动作真下发 env.step + 官方渲染视频)

与 paper_runtime/eval.py 逐行同源 (同一 World / 同一 load_pretrained / 同一 PriorOnlySolver /
同一 img_transform / 同一 _extract_init_goal + _apply_callables)，唯一区别 = 逐帧流式输出。

输出 (给画布节点消费):
  --spool  DIR      每步渲染帧 step_000123.jpg (224×224 RGB, 真图)
  --status PATH     JSON 每步覆写: {ok, stage, step, ep, action, done, success,
                    frame, frame_std, model_calls, succ, task, ckpt, video}
  --video-dir DIR   结束后用 stable-world 官方 save_panel_videos 出 3 面板 mp4
                    (agent | dataset | goal) = 「从 stable world 取出的渲染视频」
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time

RT = "/home/ubuntu/INTACT-JEPA/paper_runtime"
REPO = "/home/ubuntu/INTACT-JEPA"

TASKS = {
    "cube": {
        "config": "cube", "ckpt": "recovery_delta_full_cube_s3072",
        "dataset": "ogbench/cube_single_expert",
        "world": {"env_name": "swm/OGBCube-v0", "env_type": "single", "ob_type": "states",
                  "multiview": False, "width": 224, "height": 224,
                  "visualize_info": False, "terminate_at_goal": True},
        "callables": [
            {"method": "set_state", "args": {"qpos": {"value": "qpos"}, "qvel": {"value": "qvel"}}},
            {"method": "set_target_pos", "args": {
                "cube_id": {"value": 0, "in_dataset": False},
                "target_pos": {"value": "goal_privileged_block_0_pos"},
                "target_quat": {"value": "goal_privileged_block_0_quat"}}},
        ],
    },
}


def _json_safe(v):
    import numpy as np
    if isinstance(v, dict):
        return {str(k): _json_safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    if isinstance(v, np.ndarray):
        return v.tolist()
    if isinstance(v, np.generic):
        return v.item()
    return v


def _write_status(path, d):
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_json_safe(d), f, ensure_ascii=False)
    os.replace(tmp, path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="cube", choices=sorted(TASKS))
    ap.add_argument("--episodes", type=int, default=2, help="跑几个回合")
    ap.add_argument("--eval-budget", type=int, default=50, help="每回合步数 (与官方 config 一致 =50)")
    ap.add_argument("--goal-offset", type=int, default=25)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--spool", default="/tmp/intact_sw_frames")
    ap.add_argument("--status", default="/tmp/intact_sw_status.json")
    ap.add_argument("--video-dir", default="")
    ap.add_argument("--sample-every", type=int, default=1, help="每 N 步落一帧 (省盘)")
    a = ap.parse_args()

    T = TASKS[a.task]
    os.makedirs(a.spool, exist_ok=True)
    os.chdir(RT)
    sys.path.insert(0, RT)
    cache = os.environ.setdefault("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
    os.environ.setdefault("LOCAL_DATASET_DIR", cache)
    os.environ.setdefault("MUJOCO_GL", "egl")
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    os.environ.setdefault("PYTHONPATH", f"{RT}:{REPO}")

    st = {"ok": False, "stage": "boot", "task": a.task, "ckpt": T["ckpt"],
          "env": T["world"]["env_name"], "spool": a.spool}
    _write_status(a.status, st)

    import numpy as np
    import torch
    import stable_worldmodel as swm
    import stable_pretraining as spt
    from torchvision.transforms import v2 as transforms
    from stable_worldmodel.world.world import _extract_init_goal, _apply_callables
    from prior_only_solver import PriorOnlySolver
    from PIL import Image

    def img_transform():
        return transforms.Compose([
            transforms.ToImage(), transforms.ToDtype(torch.float32, scale=True),
            transforms.Normalize(**spt.data.dataset_stats.ImageNet),
            transforms.Resize(size=224)])

    # ① 世界 (原生环境) —— 与 config/eval/cube.yaml 的 world 段一致
    st["stage"] = "world"
    _write_status(a.status, st)
    world = swm.World(num_envs=1, max_episode_steps=2 * a.eval_budget,
                      image_shape=(224, 224), **T["world"])

    # ② 数据集 (只取动作归一化统计 + 起始状态/目标)
    st["stage"] = "dataset"
    _write_status(a.status, st)
    dataset = swm.data.HDF5Dataset(T["dataset"], keys_to_cache=["action"], cache_dir=cache)
    process = {}
    from sklearn.preprocessing import StandardScaler
    act = dataset.get_col_data("action")
    act = act[~np.isnan(act).any(axis=1)]
    sc = StandardScaler().fit(act)
    process["action"] = sc

    # ③ 论文权重 (官方加载路径) + 零搜索求解器
    st["stage"] = "model"
    _write_status(a.status, st)
    model = swm.wm.utils.load_pretrained(T["ckpt"])
    model = model.to(a.device).eval()
    model.requires_grad_(False)
    model.interpolate_pos_encoding = True
    if hasattr(model, "set_actor_warmstart"):
        model.set_actor_warmstart(True)
    ckpt_dir = os.path.join(cache, "checkpoints", T["ckpt"])
    solver = PriorOnlySolver(model=model, batch_size=1, num_samples=1, var_scale=0.0,
                             n_steps=0, topk=1, device=a.device, seed=a.seed)
    plan = swm.PlanConfig(horizon=5, receding_horizon=5, action_block=5)
    policy = swm.policy.WorldModelPolicy(solver=solver, config=plan, process=process,
                                        transform={"pixels": img_transform(), "goal": img_transform()})

    # 动作流记录 (包 get_action, 与真实下发动作逐位一致)
    last = {"action": None, "calls": 0}
    _orig = policy.get_action

    def _wrap(info_dict, **kw):
        act = _orig(info_dict, **kw)
        last["action"] = np.asarray(act).reshape(-1).round(5).tolist()
        last["calls"] += 1
        return act
    policy.get_action = _wrap

    # ④ 采样起点 —— 与官方 eval.py:201-218 完全同法 (随机合法起始行)
    col = "episode_idx" if "episode_idx" in dataset.column_names else "ep_idx"
    ep_data = dataset.get_col_data(col)
    step_idx = dataset.get_col_data("step_idx")
    ep_indices, _ = np.unique(ep_data, return_index=True)
    ep_len = np.array([int(np.max(step_idx[ep_data == e])) + 1 for e in ep_indices])
    max_start = ep_len - a.goal_offset - 1
    mstart = {int(e): int(m) for e, m in zip(ep_indices, max_start)}
    valid_mask = step_idx <= np.array([mstart[int(e)] for e in ep_data])
    valid_indices = np.nonzero(valid_mask)[0]
    g = np.random.default_rng(a.seed)
    pick = np.sort(valid_indices[g.choice(len(valid_indices) - 1, size=max(a.episodes, 1), replace=False)])
    sel_eps = [int(ep_data[r]) for r in pick]
    sel_starts = [int(step_idx[r]) for r in pick]
    st.update({"stage": "run", "valid_start_points": int(valid_mask.sum()),
               "episodes": len(sel_eps), "eval_episodes": sel_eps, "start_steps": sel_starts,
               "ckpt_path": ckpt_dir, "ckpt_file": os.path.join(ckpt_dir, "weights_epoch_5.pt"),
               "terminate_at_goal": bool(T["world"].get("terminate_at_goal", False))})
    _write_status(a.status, st)

    world.set_policy(policy)
    all_frames, ep_succ, gstep = [], 0, 0
    t0 = time.time()
    for k, (ep_id, s0) in enumerate(zip(sel_eps, sel_starts)):
        init_state, goal_state, dataset_videos = _extract_init_goal(dataset, [ep_id], [s0], a.goal_offset)
        world.reset(seed=init_state.get("seed"))
        _apply_callables(world.envs.envs[0].unwrapped, T["callables"],
                         {kk: v[0] for kk, v in {**init_state, **goal_state}.items()})
        shape_prefix = world.infos["pixels"].shape[:2]
        for src in (init_state, goal_state):
            for kk, v in src.items():
                if kk in world.infos or kk in goal_state:
                    world.infos[kk] = np.broadcast_to(v[:, None, ...], shape_prefix + v.shape[1:]).copy()
        goal_snapshot = {kk: world.infos[kk].copy() for kk in goal_state}
        frames = []

        def on_step(w, ep=ep_id, frames=frames, goal_snapshot=goal_snapshot):
            nonlocal gstep
            w.infos.update(copy.deepcopy(goal_snapshot))
            f = w.infos["pixels"][0]
            f = f[-1] if f.ndim > 3 else f
            fr = np.asarray(f).copy()
            if fr.dtype != np.uint8:
                fr = np.clip(fr * 255.0, 0, 255).astype(np.uint8)
            frames.append(fr)
            all_frames.append(fr)
            if gstep % a.sample_every == 0:
                Image.fromarray(fr).save(os.path.join(a.spool, f"step_{gstep:06d}.jpg"), quality=88)
            st.update({"ok": True, "stage": "run", "step": gstep, "ep": ep, "ep_index": k,
                       "start_step": s0, "action": last["action"], "model_calls": last["calls"],
                       "done": bool(w.terminateds[0]),
                       "frame": os.path.join(a.spool, f"step_{gstep:06d}.jpg"),
                       "frame_std": round(float(fr.std()), 2),
                       "elapsed": round(time.time() - t0, 1)})
            _write_status(a.status, st)
            gstep += 1

        world._run(max_steps=a.eval_budget, mode="wait", on_step=on_step)
        ok_ep = int(bool(np.any(world.terminateds)))
        ep_succ += ok_ep
        # 官方渲染视频 (agent | dataset | goal) —— 每个回合一份
        if a.video_dir and frames:
            try:
                os.makedirs(a.video_dir, exist_ok=True)
                from stable_worldmodel.plot import save_panel_videos
                tmpd = os.path.join(a.video_dir, "_tmp")
                save_panel_videos(tmpd, {"agent": [frames], "dataset": [dataset_videos[0]],
                                         "goal": goal_state["goal"][:1]}, fps=15)
                src = os.path.join(tmpd, "env_0.mp4")
                dst = os.path.join(a.video_dir, f"{a.task}_sw_ep{k}_seed{a.seed}.mp4")
                if os.path.exists(src):
                    os.replace(src, dst)
                    st["video"] = dst
                os.rmdir(tmpd)
            except Exception as e:                                  # noqa: BLE001
                st["video_err"] = f"{type(e).__name__}: {e}"
        st.update({"ep_done": k, "ep_success": ok_ep, "succ": ep_succ,
                   "success_rate": round(100.0 * ep_succ / (k + 1), 1), "steps": len(all_frames)})
        _write_status(a.status, st)

    # ⑤ 合集 (所有回合 agent 帧连播) = 「从 stable world 取出的渲染视频」
    if a.video_dir and all_frames:
        try:
            import subprocess
            listf = os.path.join(a.video_dir, "concat.txt")
            showcase = os.path.join(a.video_dir, f"{a.task}_sw_showcase_seed{a.seed}.mp4")
            per_ep = sorted([os.path.join(a.video_dir, x) for x in os.listdir(a.video_dir)
                             if x.startswith(f"{a.task}_sw_ep") and x.endswith(".mp4")])
            if per_ep:
                with open(listf, "w") as fh:
                    for p in per_ep:
                        fh.write(f"file '{p}'\n")
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
                                "-i", listf, "-c", "copy", showcase], check=False, timeout=120)
                if os.path.exists(showcase):
                    st["showcase"] = showcase
        except Exception as e:                                          # noqa: BLE001
            st["showcase_err"] = f"{type(e).__name__}: {e}"

    st.update({"ok": True, "stage": "done", "steps": len(all_frames), "ep_done": len(sel_eps),
               "succ": ep_succ, "success_rate": round(100.0 * ep_succ / max(len(sel_eps), 1), 1),
               "model_calls": last["calls"], "zero_search": True,
               "frame": os.path.join(a.spool, "step_%06d.jpg" % max(len(all_frames) - 1, 0)),
               "frame_std": round(float(np.mean([f.std() for f in all_frames])), 2) if all_frames else None,
               "elapsed": round(time.time() - t0, 1)})
    _write_status(a.status, st)
    print(json.dumps(_json_safe(st), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
