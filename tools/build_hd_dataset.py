#!/usr/bin/env python3
"""Z-MAX 高清训练数据集构建 · 采集数据(state/action) + 归档高清快照(318x180) 按时间戳融合
原理:
  采集包 meta.time + 帧 timestamp(相对秒) = 帧绝对时间
  → 匹配归档快照 snap_{abs_ts}.jpg (高清图)
  输出: 高清图 + 6D state/action/label → LeRobot 数据集

用法: python3 tools/build_hd_dataset.py
"""
import json, glob, os, sys, base64, io, subprocess, tempfile
import numpy as np
import pandas as pd
from pathlib import Path
from PIL import Image

proj = Path(__file__).parent.parent
OUT = proj / "data" / "orin_hd"
DATA = OUT / "data" / "chunk-000"
META = OUT / "meta" / "episodes" / "chunk-000"
VID = OUT / "videos" / "observation.image" / "chunk-000"
DATA.mkdir(parents=True, exist_ok=True)
META.mkdir(parents=True, exist_ok=True)
VID.mkdir(parents=True, exist_ok=True)

ECS = "root@39.102.211.79"
ARCHIVE = "/root/zmax-relay/archive"


def fetch_snapshot_index():
    """拉取归档快照索引 (文件名→绝对时间戳)"""
    r = subprocess.run(["sshpass", "-p", "Nix19789", "ssh", "-o", "StrictHostKeyChecking=no",
                        ECS, f"ls {ARCHIVE}/snap_*.jpg"], capture_output=True, text=True, timeout=30)
    idx = {}
    for line in r.stdout.strip().split("\n"):
        if not line:
            continue
        name = os.path.basename(line)
        try:
            ts = int(name.split("_")[1])
            idx[ts] = name
        except Exception:
            continue
    return idx


def fetch_snapshot_image(ts):
    """从 ECS 拉取指定快照 (高清)"""
    r = subprocess.run(["sshpass", "-p", "Nix19789", "ssh", "-o", "StrictHostKeyChecking=no",
                        ECS, f"cat {ARCHIVE}/snap_{ts}_*.jpg"], capture_output=True, timeout=30)
    return r.stdout if r.returncode == 0 and r.stdout else None


def main():
    print("📸 构建高清训练数据集 (采集state/action + 归档高清图)")
    print("1/3 拉取归档索引...")
    snap_idx = fetch_snapshot_index()
    print(f"   归档快照: {len(snap_idx)} 帧")

    # 读取所有采集包
    srcs = sorted(glob.glob(str(proj / "data/orin_live/*.json")), key=os.path.getmtime)
    frames_all = []
    eps_all = []
    total = 0
    matched = 0
    print("2/3 融合匹配...")
    for si, src in enumerate(srcs):
        d = json.load(open(src))
        meta = d.get("meta", {})
        base_ts = float(meta.get("time", 0))  # 包绝对时间
        frames = d.get("frames", [])
        ep_frames = 0
        for i, fr in enumerate(frames):
            state = fr.get("observation.state") or fr.get("state")
            action = fr.get("action")
            if state is None or action is None:
                continue
            state = np.asarray(state, dtype=np.float32)
            action = np.asarray(action, dtype=np.float32)
            if state.shape[0] != 6 or action.shape[0] != 6:
                continue
            # 绝对时间 = 包时间 + 帧相对时间
            rel_ts = float(fr.get("timestamp") or i / 30.0)
            abs_ts = int(base_ts + rel_ts)
            # 找最近快照 (±2s)
            best = None
            best_d = 2.0
            for st in snap_idx:
                dd = abs(st - abs_ts)
                if dd < best_d:
                    best_d = dd
                    best = st
            if best is None:
                continue
            # 拉高清图
            img_data = fetch_snapshot_image(best)
            if not img_data:
                continue
            try:
                Image.open(io.BytesIO(img_data)).verify()
            except Exception:
                continue
            img_name = f"ep{si:03d}_f{total:05d}.jpg"
            (VID / img_name).write_bytes(img_data)
            frames_all.append({
                "observation.state": state.tolist(),
                "action": action.tolist(),
                "episode_index": si,
                "frame_index": i,
                "timestamp": rel_ts,
                "next.reward": 0.0,
                "next.done": False,
                "next.success": False,
            })
            ep_frames += 1
            total += 1
            matched += 1
        if ep_frames:
            eps_all.append({"episode_index": si, "length": ep_frames})
        print(f"   包{si}: {ep_frames}帧匹配高清")

    print(f"3/3 写数据集...")
    print(f"   总帧: {total} (匹配高清 {matched})")
    if total == 0:
        print("❌ 无匹配帧")
        return

    import pyarrow as pa
    import pyarrow.parquet as pq
    df = pd.DataFrame(frames_all)
    df["index"] = range(total)
    df["task_index"] = 0
    states = np.stack(df["observation.state"].values).astype(np.float32)
    actions = np.stack(df["action"].values).astype(np.float32)
    schema = pa.schema([
        pa.field("observation.state", pa.list_(pa.float32(), 6)),
        pa.field("action", pa.list_(pa.float32(), 6)),
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
        pa.array([pa.array(s, type=pa.float32()) for s in states], type=pa.list_(pa.float32(), 6)),
        pa.array([pa.array(a, type=pa.float32()) for a in actions], type=pa.list_(pa.float32(), 6)),
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

    # episodes
    eps = pd.DataFrame(eps_all)
    start = 0
    for i, row in eps.iterrows():
        L = int(row["length"])
        eps.at[i, "dataset_from_index"] = start
        eps.at[i, "dataset_to_index"] = start + L - 1
        eps.at[i, "data/chunk_index"] = 0
        eps.at[i, "data/file_index"] = 0
        eps.at[i, "videos/observation.image/chunk_index"] = 0
        eps.at[i, "videos/observation.image/file_index"] = 0
        eps.at[i, "videos/observation.image/from_timestamp"] = 0.0
        eps.at[i, "videos/observation.image/to_timestamp"] = (L - 1) / 30.0
        eps.at[i, "tasks"] = 0
        eps.at[i, "meta/episodes/chunk_index"] = 0
        eps.at[i, "meta/episodes/file_index"] = 0
        start += L
    for c in ["dataset_from_index", "dataset_to_index", "data/chunk_index", "data/file_index",
              "videos/observation.image/chunk_index", "videos/observation.image/file_index",
              "meta/episodes/chunk_index", "meta/episodes/file_index"]:
        eps[c] = eps[c].astype("int64")
    eps.to_parquet(META / "file-000.parquet")

    # info.json
    info = {
        "codebase_version": "v3.0",
        "robot_type": "sr5_6dof",
        "total_episodes": len(eps_all),
        "total_frames": total,
        "total_tasks": 1,
        "chunks_size": 100,
        "fps": 30,
        "splits": {"train": f"0:{total}"},
        "data_path": "data/chunk-000/file-000.parquet",
        "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4",
        "features": {
            "observation.image": {
                "dtype": "video", "shape": [318, 180, 3], "fps": 30,
                "names": ["height", "width", "channel"],
                "video_info": {"video.fps": 30.0, "video.codec": "h264", "video.pix_fmt": "rgb24",
                               "video.is_depth_map": False, "has_audio": False},
            },
            "observation.state": {
                "dtype": "float32", "shape": [6],
                "names": {"motors": [f"joint_{i+1}" for i in range(6)]}, "fps": 30.0,
            },
            "action": {"dtype": "float32", "shape": [6],
                       "names": {"motors": [f"joint_{i+1}" for i in range(6)]}, "fps": 30.0},
            "episode_index": {"dtype": "int64", "shape": [1]},
            "frame_index": {"dtype": "int64", "shape": [1]},
            "timestamp": {"dtype": "float32", "shape": [1], "fps": 30.0},
            "next.reward": {"dtype": "float32", "shape": [1]},
            "next.done": {"dtype": "bool", "shape": [1]},
            "next.success": {"dtype": "bool", "shape": [1]},
            "index": {"dtype": "int64", "shape": [1]},
            "task_index": {"dtype": "int64", "shape": [1]},
        },
    }
    (OUT / "meta" / "info.json").write_text(json.dumps(info, indent=1))
    stats = {
        "observation.state": {"mean": states.mean(axis=0).tolist(), "std": states.std(axis=0).tolist()},
        "action": {"mean": actions.mean(axis=0).tolist(), "std": actions.std(axis=0).tolist()},
    }
    (OUT / "meta" / "stats.json").write_text(json.dumps(stats, indent=1))
    tasks_df = pd.DataFrame([{"task_index": 0, "task": "reach", "language_instruction": "reach target"}])
    tasks_df.to_parquet(OUT / "meta" / "tasks.parquet")

    # 视频合并 (jpg → file-000.mp4)
    jpgs = sorted(glob.glob(str(VID / "ep*.jpg")))
    if jpgs:
        with tempfile.TemporaryDirectory() as td:
            for k, j in enumerate(jpgs):
                import shutil
                shutil.copy(j, f"{td}/{k:06d}.jpg")
            subprocess.run([
                "ffmpeg", "-y", "-framerate", "30", "-i", f"{td}/%06d.jpg",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23",
                "-vsync", "cfr", "-r", "30", "-fps_mode", "cfr",
                "-loglevel", "error", str(VID / "file-000.mp4"),
            ], check=True)
        (VID / "file-000.mp4.metadata").write_text("\n".join(str(i) for i in range(total)))
        for j in jpgs:
            Path(j).unlink(missing_ok=True)
    print(f"✅ 高清数据集: {OUT} ({total}帧/{len(eps_all)}轨迹)")
    print(f"   图像: 318x180 高清 (替代 64x64 缩略图)")


if __name__ == "__main__":
    main()
