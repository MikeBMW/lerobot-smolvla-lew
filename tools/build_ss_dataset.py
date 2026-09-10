#!/usr/bin/env python3
"""build_ss_dataset.py — 🧮 状态空间仿真 npz → LeRobot 数据集 (39D state / 4D action)

输入: data/ss_insert/*.npz (state_space_sim.export_dataset 产物, 每 npz 一个 episode)
输出: data/ss_insert_lerobot/ — 标准 LeRobot 数据集 (state-only, 无视频)
  features: observation.state (39, float32) + action (4, float32)
对齐 left_right 训练 (config_left_right.yaml: 39D obs / 4D action, n_obs_steps=1)。

用法: python3 tools/build_ss_dataset.py [npz目录] [输出目录]
"""
import glob
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

proj = Path(__file__).parent.parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else proj / "data" / "ss_insert"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else proj / "data" / "ss_insert_lerobot"
DATA = OUT / "data" / "chunk-000"
META = OUT / "meta" / "episodes" / "chunk-000"
DATA.mkdir(parents=True, exist_ok=True)
META.mkdir(parents=True, exist_ok=True)

STATE_DIM, ACTION_DIM, FPS = 39, 4, 50


def main():
    npzs = sorted(glob.glob(str(SRC / "*.npz")), key=os.path.getmtime)
    if not npzs:
        print(f"❌ 无 npz: {SRC} (先跑状态空间仿真导出数据集)")
        return
    frames_all, eps_all, total = [], [], 0
    for ei, npz in enumerate(npzs):
        d = np.load(npz, allow_pickle=True)
        S, A = np.asarray(d["states"], dtype=np.float32), np.asarray(d["actions"], dtype=np.float32)
        if S.ndim != 2 or S.shape[1] != STATE_DIM or A.shape[1] != ACTION_DIM:
            print(f"  ⚠️ {npz}: 维度异常 state{S.shape} action{A.shape}, 跳过")
            continue
        if len(S) != len(A):
            print(f"  ⚠️ {npz}: 帧数不齐 state{len(S)} action{len(A)}, 跳过")
            continue
        ok = bool(np.asarray(d["success"]).any()) if "success" in d else True
        for i in range(len(S)):
            frames_all.append({
                "observation.state": S[i].tolist(),
                "action": A[i].tolist(),
                "episode_index": ei,
                "frame_index": total,
                "timestamp": float(i / FPS),
                "next.reward": 0.0,
                "next.done": False,
                "next.success": bool(ok),
            })
            total += 1
        eps_all.append({"episode_index": ei, "length": len(S), "ok": ok})
        print(f"  ep{ei}: {len(S)}帧 · {'✅' if ok else '⚠️ 未完成'} · {os.path.basename(npz)}")
    if total == 0:
        print("❌ 无有效帧")
        return

    # parquet (float32 fixed-list)
    df = pd.DataFrame(frames_all)
    df["index"] = range(total)
    df["task_index"] = 0
    df["next.reward"] = df["next.reward"].astype("float32")
    df["next.done"] = df["next.done"].astype("bool")
    df["next.success"] = df["next.success"].astype("bool")
    states = np.stack(df["observation.state"].values).astype(np.float32)
    actions = np.stack(df["action"].values).astype(np.float32)
    schema = pa.schema([
        pa.field("observation.state", pa.list_(pa.float32(), STATE_DIM)),
        pa.field("action", pa.list_(pa.float32(), ACTION_DIM)),
        pa.field("episode_index", pa.int64()),
        pa.field("frame_index", pa.int64()),
        pa.field("timestamp", pa.float32()),
        pa.field("next.reward", pa.float32()),
        pa.field("next.done", pa.bool_()),
        pa.field("next.success", pa.bool_()),
        pa.field("index", pa.int64()),
        pa.field("task_index", pa.int64()),
    ])
    table = pa.Table.from_arrays([
        pa.array([pa.array(s, type=pa.float32()) for s in states], type=pa.list_(pa.float32(), STATE_DIM)),
        pa.array([pa.array(a, type=pa.float32()) for a in actions], type=pa.list_(pa.float32(), ACTION_DIM)),
        df["episode_index"].astype("int64").values,
        df["frame_index"].astype("int64").values,
        df["timestamp"].astype("float32").values,
        df["next.reward"].astype("float32").values,
        df["next.done"].values,
        df["next.success"].values,
        df["index"].astype("int64").values,
        df["task_index"].astype("int64").values,
    ], schema=schema)
    pq.write_table(table, DATA / "file-000.parquet")
    print(f"✅ parquet: {total}帧 ({len(eps_all)} episodes) → {DATA / 'file-000.parquet'}")

    # episodes
    eps = pd.DataFrame(eps_all)
    eps["episode_index"] = range(len(eps))
    start = 0
    for i, row in eps.iterrows():
        L = int(row["length"])
        eps.at[i, "dataset_from_index"] = start
        eps.at[i, "dataset_to_index"] = start + L - 1
        eps.at[i, "data/chunk_index"] = 0
        eps.at[i, "data/file_index"] = 0
        eps.at[i, "meta/episodes/chunk_index"] = 0
        eps.at[i, "meta/episodes/file_index"] = 0
        start += L
    for c in ["dataset_from_index", "dataset_to_index", "data/chunk_index", "data/file_index",
              "meta/episodes/chunk_index", "meta/episodes/file_index"]:
        eps[c] = eps[c].astype("int64")
    eps.to_parquet(META / "file-000.parquet")

    # info.json (state-only: 无 video_path/observation.image)
    state_names = ["hand_pos", "gripper", "hand_vel", "peg_pos", "hole_pos", "hole_quat", "pad"] + \
                  ["prev_hand_pos", "prev_gripper", "prev_peg_pos", "prev_hole_pos", "prev_pad"] + \
                  ["target_pos"]
    info = {
        "codebase_version": "v3.0",
        "robot_type": "zmax_ss_sim",
        "total_episodes": len(eps_all),
        "total_frames": total,
        "total_tasks": 1,
        "chunks_size": 100,
        "fps": FPS,
        "splits": {"train": f"0:{total}"},
        "data_path": "data/chunk-000/file-000.parquet",
        "features": {
            "observation.state": {"dtype": "float32", "shape": [STATE_DIM],
                                  "names": {"state": state_names}, "fps": FPS},
            "action": {"dtype": "float32", "shape": [ACTION_DIM],
                       "names": {"motors": ["dx", "dy", "dz", "gripper"]}, "fps": FPS},
            "episode_index": {"dtype": "int64", "shape": [1]},
            "frame_index": {"dtype": "int64", "shape": [1]},
            "timestamp": {"dtype": "float32", "shape": [1], "fps": FPS},
            "next.reward": {"dtype": "float32", "shape": [1]},
            "next.done": {"dtype": "bool", "shape": [1]},
            "next.success": {"dtype": "bool", "shape": [1]},
            "index": {"dtype": "int64", "shape": [1]},
            "task_index": {"dtype": "int64", "shape": [1]},
        },
    }
    (OUT / "meta" / "info.json").write_text(json.dumps(info, indent=1))
    # 🐛 2026-08-20 静静: 归一化 stats.json 必写! 缺 → 训练时 normalizer 恒等 (无归一化),
    #   推理用数据统计又不匹配 → 闭环跑飞; 有 stats → 训练/推理一致 (闭环 4/4 完成)
    stats = {
        "observation.state": {"mean": states.mean(0).tolist(), "std": states.std(0).tolist()},
        "action": {"mean": actions.mean(0).tolist(), "std": actions.std(0).tolist()},
    }
    (OUT / "meta" / "stats.json").write_text(json.dumps(stats))
    # 🐛 2026-08-25 静静: tasks.parquet 必写! lerobot 0.5.2 的 LeRobotDatasetMetadata._load_metadata
    #   会 load_tasks(meta/tasks.parquet), 缺 → FileNotFoundError → 误走 get_safe_version(HF Hub)
    #   报 "Network is unreachable"。state-only 数据集无语言任务, 写单个占位 task 即可。
    tasks_df = pd.DataFrame({"task_index": [0]}, index=pd.Index(["insert_peg"], name="task"))
    tasks_df.to_parquet(OUT / "meta" / "tasks.parquet")
    n_ok = sum(1 for e in eps_all if e["ok"])
    print(f"✅ 数据集: {OUT} · {len(eps_all)}ep/{total}帧 · 成功 {n_ok}/{len(eps_all)} · stats.json 已写")
    print("   训练: config_left_right.yaml (root 自动指向本目录) · policy=left_right")


if __name__ == "__main__":
    main()
