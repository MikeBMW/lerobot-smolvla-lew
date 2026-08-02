#!/usr/bin/env python3
"""Orin 真机数据 → LeRobot 数据集 (6D state / 6D action)
从 data/orin_live/*.json (小芳采集) 构建标准数据集
"""
import json, glob, sys
import numpy as np
import pandas as pd
from pathlib import Path

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
            # 图像: base64 → jpg
            img_name = None
            if cam:
                import base64, io
                try:
                    img_bytes = base64.b64decode(cam)
                    img_name = f"ep{si:03d}_f{total:05d}.jpg"
                    (VID / img_name).write_bytes(img_bytes)
                except Exception:
                    img_name = None
            frames_all.append({
                "observation.state": state.tolist(),
                "action": action.tolist(),
                "episode_index": si,
                "frame_index": i,
                "timestamp": i / 30.0,
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

    # parquet
    df = pd.DataFrame(frames_all)
    df["index"] = range(total)
    df["task_index"] = 0
    df["next.reward"] = 0.0
    df["next.done"] = False
    df["next.success"] = False
    df.to_parquet(DATA / "file-000.parquet")

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
    states = np.stack([f["observation.state"] for f in frames_all])
    actions = np.stack([f["action"] for f in frames_all])
    stats = {
        "observation.state": {"mean": states.mean(axis=0).tolist(), "std": states.std(axis=0).tolist()},
        "action": {"mean": actions.mean(axis=0).tolist(), "std": actions.std(axis=0).tolist()},
    }
    (OUT / "meta" / "stats.json").write_text(json.dumps(stats, indent=1))
    print(f"✅ 数据集: {OUT} ({total}帧/{len(eps_all)}轨迹)")
    print(f"   state {states.shape} action {actions.shape}")
    print(f"   action range: [{actions.min():.4f}, {actions.max():.4f}]")


if __name__ == "__main__":
    main()
