#!/usr/bin/env python3
"""Orin 真机数据 → LeRobot 数据集 (6D state / 6D action)
从 data/orin_live/*.json (小芳采集) 构建标准数据集
"""
import json, glob, sys
import numpy as np
import pandas as pd
from pathlib import Path
from PIL import Image

proj = Path(__file__).parent.parent
OUT = proj / "data" / "orin_6d"
DATA = OUT / "data" / "chunk-000"
META = OUT / "meta" / "episodes" / "chunk-000"
VID = OUT / "videos" / "observation.image" / "chunk-000"
DATA.mkdir(parents=True, exist_ok=True)
META.mkdir(parents=True, exist_ok=True)
VID.mkdir(parents=True, exist_ok=True)


def main():
    srcs = sorted(glob.glob(str(proj / "data/orin_live/*.json")))
    frames_all = []
    eps_all = []
    total = 0
    print(f"📥 读取 {len(srcs)} 个真机数据包")
    for si, src in enumerate(srcs):
        d = json.load(open(src))
        frames = d.get("frames", [])
        if not frames:
            continue
        ep_frames = []
        ep_imgs = []
        for i, fr in enumerate(frames):
            st = fr.get("observation.state") or fr.get("state")
            act = fr.get("action")
            cam = fr.get("camera_b64") or fr.get("camera")
            if st is None or act is None:
                continue
            state = np.asarray(st, dtype=np.float32)
            action = np.asarray(act, dtype=np.float32)
            if state.shape[0] != 6 or action.shape[0] != 6:
                print(f"  ⚠️ {src} 帧{i} 维度异常: state{state.shape} action{action.shape}, 跳过")
                continue
            # 图像: base64 → 暂存 (按包分目录, 每包独立视频)
            img_name = None
            if cam:
                import base64, io
                try:
                    img_bytes = base64.b64decode(cam)
                    # 验证是有效 JPEG
                    pil_check = Image.open(io.BytesIO(img_bytes))
                    pil_check.verify()
                    img_name = f"ep{si:03d}_f{total:05d}.jpg"
                    (VID / img_name).write_bytes(img_bytes)
                except Exception:
                    img_name = None
            if img_name is None:
                continue  # 无有效图像 → 跳过该帧 (避免视频/parquet 帧数不一致)
            frames_all.append({
                "observation.state": state.tolist(),
                "action": action.tolist(),
                "episode_index": si,   # 每包一个 episode (方案2, LeRobot 标准)
                "frame_index": total,  # 全局索引 (视频合并顺序, 与 index 一致)
                "timestamp": float(i / 30.0),  # episode 内相对时间戳 (reader 会加 from_timestamp)
                "next.reward": 0.0,
                "next.done": False,
                "next.success": False,
            })
            ep_frames.append(i)
            total += 1
        if ep_frames:
            eps_all.append({"episode_index": si, "length": len(ep_frames)})
            print(f"  包{si}: {len(ep_frames)}帧")

    print(f"\n✅ 总帧: {total}")
    if total == 0:
        print("❌ 无有效帧")
        return

    # parquet (float32 fixed-list 匹配 info)
    import pandas as pd
    df = pd.DataFrame(frames_all)
    df["index"] = range(total)
    df["task_index"] = 0
    df["next.reward"] = df["next.reward"].astype("float32")
    df["next.done"] = df["next.done"].astype("bool")
    df["next.success"] = df["next.success"].astype("bool")
    import pyarrow as pa
    import pyarrow.parquet as pq
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
    print(f"✅ parquet float32 重写完成")

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
        eps.at[i, "videos/observation.image/from_timestamp"] = float(start) / 30.0   # 全局视频时间
        eps.at[i, "videos/observation.image/to_timestamp"] = float(start + L - 1) / 30.0
        eps.at[i, "tasks"] = 0
        eps.at[i, "meta/episodes/chunk_index"] = 0
        eps.at[i, "meta/episodes/file_index"] = 0
        start += L
    # Z-MAX 修复: 索引列转 int64 (format 需要)
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
                "dtype": "video", "shape": [480, 640, 3], "fps": 30,
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
        },
    }
    (OUT / "meta" / "info.json").write_text(json.dumps(info, indent=1))
    # Z-MAX 修复: 补 index/task_index features (parquet 列匹配)
    info["features"]["index"] = {"dtype": "int64", "shape": [1]}
    info["features"]["task_index"] = {"dtype": "int64", "shape": [1]}
    (OUT / "meta" / "info.json").write_text(json.dumps(info, indent=1))
    states = np.stack([f["observation.state"] for f in frames_all])
    actions = np.stack([f["action"] for f in frames_all])
    stats = {
        "observation.state": {"mean": states.mean(axis=0).tolist(), "std": states.std(axis=0).tolist()},
        "action": {"mean": actions.mean(axis=0).tolist(), "std": actions.std(axis=0).tolist()},
    }
    (OUT / "meta" / "stats.json").write_text(json.dumps(stats, indent=1))
    # tasks.parquet (LeRobot 必需)
    tasks_df = pd.DataFrame([{"task_index": 0, "task": "reach",
                              "language_instruction": "reach target"}])
    tasks_df.to_parquet(OUT / "meta" / "tasks.parquet")
    # 图像 jpg → file-000.mp4 (LeRobot 视频格式)
    import subprocess, tempfile, glob as _glob
    jpgs = sorted(_glob.glob(str(VID / "ep*.jpg")))
    if jpgs:
        with tempfile.TemporaryDirectory() as td:
            # 重命名连续序号
            for k, j in enumerate(jpgs):
                import shutil
                shutil.copy(j, f"{td}/{k:06d}.jpg")
            subprocess.run([
                "ffmpeg", "-y", "-framerate", "30", "-i", f"{td}/%06d.jpg",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23",
                "-vsync", "0", "-fps_mode", "passthrough",
                "-loglevel", "error", str(VID / "file-000.mp4"),
            ], check=True)
        (VID / "file-000.mp4.metadata").write_text(
            "\n".join(str(i) for i in range(total)))
        # 删除 jpg
        for j in jpgs:
            Path(j).unlink(missing_ok=True)
        print(f"🎬 视频合并: {len(jpgs)} 帧 → file-000.mp4")
    print(f"✅ 数据集: {OUT} ({total}帧/{len(eps_all)}轨迹)")
    print(f"   state {states.shape} action {actions.shape}")
    print(f"   action range: [{actions.min():.4f}, {actions.max():.4f}]")


if __name__ == "__main__":
    main()
