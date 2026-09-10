#!/usr/bin/env python3
"""
npz → LeRobotDataset v3.0 转换器 (Z-MAX 数据链路治本, 2026-08-02)
把 metaworld / Orin 真实数据的 npz (states/actions/observations) 转成标准
LeRobotDataset 格式 (meta/info.json + data parquet + videos mp4 + episode 统计),
使 lerobot_train 训练出的模型 input_features 与真实数据维度一致。

用法:
  .venv/bin/python tools/npz_to_lerobot.py \
      --npz data/metaworld_act/train.npz --out data/metaworld_act_v2 \
      --task "Metaworld 抓取" --fps 30 --episode-frames 100
"""
import argparse, json, math, os, shutil
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

CHUNK = 1000  # 每 parquet 文件最大行数 (与 pusht 模板一致)


def img_to_hwc_uint8(obs):
    """CHW float(0-1) → HWC uint8(0-255)"""
    a = np.clip(obs, 0.0, 1.0) * 255.0
    return np.transpose(a, (1, 2, 0)).astype(np.uint8)


def stats_of(arr):
    a = np.asarray(arr, dtype=np.float64)
    return (float(a.min()), float(a.max()), float(a.mean()), float(a.std()), int(a.size))


def build_frames_parquet(states, actions, ep_idx, ep_frames, base_index, fps):
    """单 episode 帧数据 (state/action 固定列表 + 元数据列)"""
    n = len(states)
    rows = []
    for i in range(n):
        rows.append({
            "observation.state": states[i],
            "action": actions[i],
            "episode_index": ep_idx,
            "frame_index": i,
            "timestamp": i / fps,
            "next.reward": 0.0,
            "next.done": i == n - 1,
            "next.success": False,
            "index": base_index + i,
            "task_index": 0,
        })
    schema = pa.schema([
        ("observation.state", pa.list_(pa.float32(), len(states[0]))),
        ("action", pa.list_(pa.float32(), len(actions[0]))),
        ("episode_index", pa.int64()),
        ("frame_index", pa.int64()),
        ("timestamp", pa.float64()),
        ("next.reward", pa.float64()),
        ("next.done", pa.bool_()),
        ("next.success", pa.bool_()),
        ("index", pa.int64()),
        ("task_index", pa.int64()),
    ])
    return pa.Table.from_pylist(rows, schema=schema)


def write_video(path, obs_hwc_frames, fps):
    """图像帧序列 → mp4 (PyAV h264, LeRobotDataset 可解码)"""
    import av
    h, w = obs_hwc_frames[0].shape[:2]
    container = av.open(str(path), "w")
    stream = container.add_stream("h264", rate=fps)
    stream.width, stream.height = w, h
    stream.pix_fmt = "yuv420p"
    stream.thread_type = "AUTO"
    for f in obs_hwc_frames:
        frame = av.VideoFrame.from_ndarray(f, format="rgb24")
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--npz", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--task", default="zmax_task")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--episode-frames", type=int, default=100,
                    help="每 episode 帧数 (npz 无 episode 边界时按固定长度切分)")
    args = ap.parse_args()

    d = np.load(args.npz, allow_pickle=True)
    states = d["states"].astype(np.float32)
    actions = d["actions"].astype(np.float32)
    obs = d["observations"].astype(np.float32) if "observations" in d.files else None

    n = len(states)
    s_dim, a_dim = states.shape[1], actions.shape[1]
    h, w = (obs.shape[2], obs.shape[3]) if obs is not None else (0, 0)
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    (out / "meta" / "episodes" / "chunk-000").mkdir(parents=True)
    (out / "data" / "chunk-000").mkdir(parents=True)
    if obs is not None:
        (out / "videos" / "observation.image" / "chunk-000").mkdir(parents=True)

    # ── episode 切分 ──
    ef = args.episode_frames
    n_eps = math.ceil(n / ef)
    ep_rows = []            # episodes 表行
    frame_tables = []       # 每文件帧表
    base_index = 0
    vid_from = 0.0

    # 全部帧写入同一个视频文件 (v3.0 模板: 所有 episode 共用 file-000.mp4, timestamp 全局累计)
    if obs is not None:
        vpath = out / "videos" / "observation.image" / "chunk-000" / "file-000.mp4"
        write_video(vpath, [img_to_hwc_uint8(obs[i]) for i in range(n)], args.fps)

    for ei in range(n_eps):
        s, e = ei * ef, min((ei + 1) * ef, n)
        ep_states = states[s:e]
        ep_actions = actions[s:e]
        ep_len = e - s
        # 帧表
        tbl = build_frames_parquet(ep_states, ep_actions, ei, ef, base_index, args.fps)
        frame_tables.append(tbl)
        vid_to = vid_from + (ep_len - 1) / args.fps
        # episode 统计行
        st_stats = stats_of(ep_states)
        ac_stats = stats_of(ep_actions)
        im_stats = stats_of(obs[s:e]) if obs is not None else (0, 0, 0, 0, 0)
        ts = np.arange(ep_len, dtype=np.float64) / args.fps
        fi = np.arange(ep_len, dtype=np.float64)
        idx = np.arange(base_index, base_index + ep_len, dtype=np.float64)
        done = np.zeros(ep_len, dtype=bool); done[-1] = True
        rew = np.zeros(ep_len)
        succ = np.zeros(ep_len, dtype=bool)
        ep_index = np.full(ep_len, ei, dtype=np.float64)
        task_index = np.zeros(ep_len)
        row = {
            "episode_index": ei,
            "data/chunk_index": 0,
            "data/file_index": 0,
            "dataset_from_index": base_index,
            "dataset_to_index": base_index + ep_len - 1,
            "videos/observation.image/chunk_index": 0 if obs is not None else None,
            "videos/observation.image/file_index": 0 if obs is not None else None,
            "videos/observation.image/from_timestamp": vid_from if obs is not None else None,
            "videos/observation.image/to_timestamp": vid_to if obs is not None else None,
            "tasks": [args.task],
            "length": ep_len,
            "stats/observation.image/min": im_stats[0], "stats/observation.image/max": im_stats[1],
            "stats/observation.image/mean": im_stats[2], "stats/observation.image/std": im_stats[3],
            "stats/observation.image/count": im_stats[4],
            "stats/observation.state/min": st_stats[0], "stats/observation.state/max": st_stats[1],
            "stats/observation.state/mean": st_stats[2], "stats/observation.state/std": st_stats[3],
            "stats/observation.state/count": st_stats[4],
            "stats/action/min": ac_stats[0], "stats/action/max": ac_stats[1],
            "stats/action/mean": ac_stats[2], "stats/action/std": ac_stats[3],
            "stats/action/count": ac_stats[4],
            "stats/episode_index/min": float(ei), "stats/episode_index/max": float(ei),
            "stats/episode_index/mean": float(ei), "stats/episode_index/std": 0.0,
            "stats/episode_index/count": ep_len,
            "stats/frame_index/min": float(fi.min()), "stats/frame_index/max": float(fi.max()),
            "stats/frame_index/mean": float(fi.mean()), "stats/frame_index/std": float(fi.std()),
            "stats/frame_index/count": ep_len,
            "stats/timestamp/min": float(ts.min()), "stats/timestamp/max": float(ts.max()),
            "stats/timestamp/mean": float(ts.mean()), "stats/timestamp/std": float(ts.std()),
            "stats/timestamp/count": ep_len,
            "stats/next.reward/min": 0.0, "stats/next.reward/max": 0.0,
            "stats/next.reward/mean": 0.0, "stats/next.reward/std": 0.0,
            "stats/next.reward/count": ep_len,
            "stats/next.done/min": False, "stats/next.done/max": bool(done.max()),
            "stats/next.done/mean": float(done.mean()), "stats/next.done/std": float(done.std()),
            "stats/next.done/count": ep_len,
            "stats/next.success/min": False, "stats/next.success/max": False,
            "stats/next.success/mean": 0.0, "stats/next.success/std": 0.0,
            "stats/next.success/count": ep_len,
            "stats/index/min": float(idx.min()), "stats/index/max": float(idx.max()),
            "stats/index/mean": float(idx.mean()), "stats/index/std": float(idx.std()),
            "stats/index/count": ep_len,
            "stats/task_index/min": 0.0, "stats/task_index/max": 0.0,
            "stats/task_index/mean": 0.0, "stats/task_index/std": 0.0,
            "stats/task_index/count": ep_len,
            "meta/episodes/chunk_index": 0,
            "meta/episodes/file_index": 0,
        }
        ep_rows.append(row)
        vid_from = vid_to
        base_index += ep_len

    # ── 帧 parquet 写入 (chunk 切分) ──
    all_frames = pa.concat_tables(frame_tables)
    fi_out = 0
    for off in range(0, all_frames.num_rows, CHUNK):
        part = all_frames.slice(off, min(CHUNK, all_frames.num_rows - off))
        pq.write_table(part, out / "data" / "chunk-000" / f"file-{fi_out:03d}.parquet")
        fi_out += 1

    # ── episodes parquet ──
    fields = []
    for k in ep_rows[0].keys():
        if k == "tasks":
            fields.append((k, pa.list_(pa.string())))
        elif k.startswith("stats/") and k.endswith("/count"):
            fields.append((k, pa.int64()))
        elif k.startswith("stats/") and ("min" in k or "max" in k or "mean" in k or "std" in k):
            fields.append((k, pa.float64()))
        elif k in ("episode_index", "length", "dataset_from_index", "dataset_to_index",
                   "data/chunk_index", "data/file_index",
                   "meta/episodes/chunk_index", "meta/episodes/file_index"):
            fields.append((k, pa.int64()))
        elif k.endswith("/chunk_index") or k.endswith("/file_index"):
            fields.append((k, pa.int64()))
        elif "timestamp" in k:
            fields.append((k, pa.float64()))
        elif "done" in k or "success" in k:
            fields.append((k, pa.bool_()))
        else:
            fields.append((k, pa.float64()))
    ep_schema = pa.schema(fields)
    ep_table = pa.Table.from_pylist(ep_rows, schema=ep_schema)
    pq.write_table(ep_table, out / "meta" / "episodes" / "chunk-000" / "file-000.parquet")

    # ── meta/info.json ──
    features = {
        "observation.state": {"dtype": "float32", "shape": [s_dim], "names": ["state_%d" % i for i in range(s_dim)]},
        "action": {"dtype": "float32", "shape": [a_dim], "names": ["action_%d" % i for i in range(a_dim)]},
        "episode_index": {"dtype": "int64", "shape": [1], "names": ["episode_index"]},
        "frame_index": {"dtype": "int64", "shape": [1], "names": ["frame_index"]},
        "timestamp": {"dtype": "float64", "shape": [1], "names": ["timestamp"]},
        "next.reward": {"dtype": "float64", "shape": [1], "names": ["next.reward"]},
        "next.done": {"dtype": "bool", "shape": [1], "names": ["next.done"]},
        "next.success": {"dtype": "bool", "shape": [1], "names": ["next.success"]},
        "index": {"dtype": "int64", "shape": [1], "names": ["index"]},
        "task_index": {"dtype": "int64", "shape": [1], "names": ["task_index"]},
    }
    if obs is not None:
        features["observation.image"] = {"dtype": "video", "shape": [h, w, 3],
                                         "names": ["image_%d" % i for i in range(3)]}
    info = {
        "codebase_version": "v3.0",
        "robot_type": "unknown",
        "total_episodes": n_eps,
        "total_frames": n,
        "total_tasks": 1,
        "chunks_size": CHUNK,
        "fps": args.fps,
        "splits": {"train": "0:%d" % n_eps},
        "data_path": "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet",
        "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4",
        "features": features,
        "data_files_size_in_mb": 100,
        "video_files_size_in_mb": 500,
    }
    json.dump(info, open(out / "meta" / "info.json", "w"), ensure_ascii=False, indent=2)

    # ── meta/stats.json (帧级全局统计) ──
    st_g = stats_of(states); ac_g = stats_of(actions); im_g = stats_of(obs) if obs is not None else (0, 0, 0, 0, 0)
    ts_g = stats_of(np.arange(n, dtype=np.float64) / args.fps)
    fi_g = stats_of(np.arange(n, dtype=np.float64))
    stats = {
        "observation.state": {"min": [st_g[0]], "max": [st_g[1]], "mean": [st_g[2]], "std": [st_g[3]], "count": [st_g[4]]},
        "action": {"min": [ac_g[0]], "max": [ac_g[1]], "mean": [ac_g[2]], "std": [ac_g[3]], "count": [ac_g[4]]},
        "timestamp": {"min": [ts_g[0]], "max": [ts_g[1]], "mean": [ts_g[2]], "std": [ts_g[3]], "count": [ts_g[4]]},
        "frame_index": {"min": [fi_g[0]], "max": [fi_g[1]], "mean": [fi_g[2]], "std": [fi_g[3]], "count": [fi_g[4]]},
        "index": {"min": [0], "max": [n - 1], "mean": [(n - 1) / 2], "std": [np.std(np.arange(n))], "count": [n]},
        "next.done": {"min": [False], "max": [True], "mean": [n_eps / n], "std": [0.0], "count": [n]},
        "next.success": {"min": [False], "max": [False], "mean": [0.0], "std": [0.0], "count": [n]},
        "next.reward": {"min": [0.0], "max": [0.0], "mean": [0.0], "std": [0.0], "count": [n]},
        "task_index": {"min": [0], "max": [0], "mean": [0.0], "std": [0.0], "count": [n]},
        "episode_index": {"min": [0], "max": [n_eps - 1], "mean": [(n_eps - 1) / 2], "std": [0.0], "count": [n]},
    }
    if obs is not None:
        stats["observation.image"] = {"min": [im_g[0]], "max": [im_g[1]], "mean": [im_g[2]], "std": [im_g[3]], "count": [im_g[4]]}
    json.dump(stats, open(out / "meta" / "stats.json", "w"), ensure_ascii=False, indent=2)

    # ── meta/tasks.parquet ──
    tasks = pa.Table.from_pylist([{"index": 0, "task": args.task}],
                                 schema=pa.schema([("index", pa.int64()), ("task", pa.string())]))
    pq.write_table(tasks, out / "meta" / "tasks.parquet")

    print(f"✅ 转换完成: {out}")
    print(f"   帧数={n} · episodes={n_eps} · state={s_dim}D · action={a_dim}D · 图像={h}x{w} · fps={args.fps}")


if __name__ == "__main__":
    main()
