#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🤖 INTACT 标准机器人驱动桥 (在 INTACT venv + paper_runtime 下跑)

"符合 INTACT 标准的机器人" = 原项目论文权重**原生**对应、能在其原生环境里被 zero-search
直接驱动的机器人 (不是我们域内微调的 sawyer)。注册表见 ROBOTS:

  reacher  | swm/ReacherDMControl-v0 | DMControl 两连杆臂 · qpos_match | 关节动作
  pusht    | swm/PushT-v1            | 2D 推块 (圆形推头)              | 2D + 夹爪
  cube     | OGBench cube-single     | **3D 机械臂推方块**              | 7维关节
  tworoom  | OGBench tworoom         | 两房间点质量导航                 | 2D

关键实现约束 (都是实测踩出来的, 不许改):
  · 论文权重必须用 paper_runtime 运行时 (根运行时会报 module.InverseTransitionActor 找不到)
  · 论文运行时的零搜索求解器叫 **prior_only** (根仓库 direct_solver 与论文 actor 命名不兼容)
  · 数据集必须落在 $STABLEWM_HOME/datasets/ 下 (pusht_expert_train.h5 / dmc/reacher_random.h5 /
    cube_single_expert.h5 / tworoom.h5)

命令 (行式 JSON 协议, 与 intact_worker 同款):
  # 列机器人 (给 UI 用)
  .venv/bin/python tools/intact_native_robot.py --list
  # 跑一轮: 出官方渲染视频 + 逐集结果 (JSON)
  .venv/bin/python tools/intact_native_robot.py --run --robot tworoom --episodes 2 --video-dir DIR
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

REPO = "/home/ubuntu/INTACT-JEPA"
RT = os.path.join(REPO, "paper_runtime")
STATE_FILE = "/home/ubuntu/lerobot-smolvla-lew/data/intact_robot_state.json"

# INTACT 标准机器人注册表 (名称 → 元数据; 官方成绩来自我们本机实测)
ROBOTS = {
    "reacher": {"env": "swm/ReacherDMControl-v0", "task": "qpos_match", "kind": "DMControl 两连杆臂",
                "action": "关节 (qpos_match)", "dataset": "dmc/reacher_random.h5",
                "ckpt": "recovery_delta_full_reacher_s3072", "official": "97.0% (论文 97.0)"},
    "pusht": {"env": "swm/PushT-v1", "task": "push", "kind": "2D 推块",
              "action": "2D + 夹爪", "dataset": "pusht_expert_train.h5",
              "ckpt": "recovery_delta_full_pusht_s3072", "official": "79.3% (论文 79.67)"},
    "cube": {"env": "OGBench cube-single", "task": "cube", "kind": "3D 机械臂推方块",
             "action": "7 维关节", "dataset": "ogbench/cube_single_expert.h5",
             "ckpt": "recovery_delta_full_cube_s3072", "official": "83.3% (本机 6 集实测)"},
    "tworoom": {"env": "OGBench tworoom", "task": "tworoom", "kind": "两房间导航",
                "action": "2D", "dataset": "tworoom.h5",
                "ckpt": "recovery_delta_full_tworoom_s3072", "official": "100% (本机 6 集实测)"},
}


def _state_dir():
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)


def list_robots() -> int:
    """列机器人 + 本地可用性 (数据集/权重/视频证据), 供切换 UI 显示。"""
    cache = os.environ.get("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
    out = []
    for name, m in ROBOTS.items():
        ds = os.path.join(cache, "datasets", m["dataset"])
        ck = os.path.join(cache, "checkpoints", m["ckpt"], "weights_epoch_5.pt")
        vids = f"/home/ubuntu/lerobot-smolvla-lew/reports/intact_official/{name}"
        n_vid = len([f for f in os.listdir(vids)]) if os.path.isdir(vids) else 0
        out.append({**m, "name": name, "dataset_ready": os.path.isfile(ds),
                    "ckpt_ready": os.path.isfile(ck), "videos": n_vid,
                    "runnable": bool(os.path.isfile(ds) and os.path.isfile(ck))})
    print(json.dumps({"ok": True, "robots": out, "current": read_state().get("robot")},
                     ensure_ascii=False))
    return 0


def read_state() -> dict:
    try:
        return json.load(open(STATE_FILE, encoding="utf-8"))
    except Exception:
        return {}


def write_state(rb: str) -> dict:
    st = {"robot": rb, "ts": __import__("time").strftime("%F %T"),
          "meta": ROBOTS.get(rb, {})}
    _state_dir()
    json.dump(st, open(STATE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return st


def run_robot(robot: str, episodes: int, video_dir: str, extra: list[str]) -> int:
    """用原项目权重 + 原项目运行时跑一轮 (结果/视频与官方评测同口径)。"""
    if robot not in ROBOTS:
        print(json.dumps({"ok": False, "error": f"未知机器人 {robot!r}; 可选 {list(ROBOTS)}"},
                         ensure_ascii=False))
        return 2
    m = ROBOTS[robot]
    env = dict(os.environ)
    env.update({"INTACT_SKIP_PREFLIGHT": "1",
                "STABLEWM_HOME": env.get("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache"),
                "LOCAL_DATASET_DIR": env.get("LOCAL_DATASET_DIR", "/home/ubuntu/stable-wm-cache"),
                "HF_ENDPOINT": "https://hf-mirror.com", "MUJOCO_GL": "egl",
                "PYOPENGL_PLATFORM": "egl", "PYTHONPATH": RT,
                "HDF5_PLUGIN_PATH": "/home/ubuntu/.h5plugins"})
    cmd = [os.path.join(REPO, ".venv", "bin", "python"), os.path.join(RT, "eval.py"),
           f"--config-name={robot}", "solver=prior_only", f"policy={m['ckpt']}",
           "seed=42", f"eval.num_eval={int(episodes)}",
           f"output.filename=intact_native_{robot}_n{int(episodes)}.txt"] + list(extra)
    print(json.dumps({"ok": True, "stage": "start", "robot": robot, "env": m["env"],
                      "ckpt": m["ckpt"], "cmd": " ".join(cmd[-8:])}, ensure_ascii=False))
    cache = env["STABLEWM_HOME"]
    for f in __import__("glob").glob(os.path.join(cache, "env_*.mp4")):
        try:
            os.remove(f)
        except Exception:
            pass
    p = subprocess.run(cmd, cwd=RT, env=env, capture_output=True, text=True)
    tail = (p.stdout or "").strip().splitlines()[-12:]
    # 从输出里抓成功率
    sr = None
    for ln in reversed(tail):
        if "success_rate" in ln:
            try:
                sr = float(ln.split("success_rate':")[1].split(",")[0])
            except Exception:
                pass
            break
    vids = []
    if video_dir:
        os.makedirs(video_dir, exist_ok=True)
        for f in sorted(__import__("glob").glob(os.path.join(cache, "env_*.mp4"))):
            dst = os.path.join(video_dir, f"{robot}_{os.path.basename(f)}")
            try:
                __import__("shutil").copyfile(f, dst)
                vids.append(dst)
            except Exception:
                pass
    print(json.dumps({"ok": p.returncode == 0, "stage": "done", "robot": robot,
                      "success_rate": sr, "videos": vids, "rc": p.returncode,
                      "tail": tail}, ensure_ascii=False))
    return 0 if p.returncode == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--robot", default="")
    ap.add_argument("--episodes", type=int, default=2)
    ap.add_argument("--video-dir", default="/home/ubuntu/lerobot-smolvla-lew/reports/intact_native")
    ap.add_argument("--set-current", default="", help="写 state 文件 (切换节点用)")
    a, extra = ap.parse_known_args()
    if a.set_current:
        print(json.dumps({"ok": True, **write_state(a.set_current)}, ensure_ascii=False))
        return 0
    if a.list:
        return list_robots()
    if a.run:
        return run_robot(a.robot, a.episodes, a.video_dir, extra)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
