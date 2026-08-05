#!/usr/bin/env python3
"""Z-MAX metaworld 7电机数据生成器 · 真实渲染
生成: metaworld reach-v3 专家轨迹 → 7关节state + 4D action + 真实图像
输出: LeRobotDataset 格式 (data/metaworld_joint_real/)
用法:
  DISPLAY=:0 MUJOCO_GL=glfw python3 tools/gen_metaworld_data.py --eps 10 --steps 180
"""
import os, sys, json, argparse
import numpy as np
from pathlib import Path

os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")

proj = Path(__file__).parent.parent
sys.path.insert(0, str(proj))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eps", type=int, default=10, help="轨迹数")
    ap.add_argument("--steps", type=int, default=180, help="每条轨迹帧数")
    ap.add_argument("--task", default="reach-v3")
    ap.add_argument("--out", default="data/metaworld_cartesian")
    args = ap.parse_args()

    import metaworld
    from PIL import Image

    mt = metaworld.MT1(args.task)
    env = mt.train_classes[args.task](render_mode="rgb_array")
    task = mt.train_tasks[0]
    env.set_task(task)

    out = proj / args.out
    data_dir = out / "data" / "chunk-000"
    img_dir = out / "videos" / "observation.image" / "chunk-000"
    meta_dir = out / "meta" / "episodes" / "chunk-000"
    data_dir.mkdir(parents=True, exist_ok=True)
    img_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    all_frames = []   # 所有帧 (parquet)
    all_eps = []      # 轨迹索引 (episodes)
    ep_imgs_all = {}  # 每轨迹图像列表 → mp4
    total = 0
    print(f"🎯 生成 {args.task} · {args.eps} 条轨迹 × {args.steps} 帧")
    for ep in range(args.eps):
        obs, _ = env.reset()
        ep_imgs = []
        for i in range(args.steps):
            # 渲染真实图像 (480x480 → 128x128)
            img = np.asarray(env.render())
            pil = Image.fromarray(img).resize((128, 128), Image.LANCZOS)
            ep_imgs.append(np.asarray(pil))
            # 关节状态: 用末端笛卡尔位姿 (跨机器人泛化, 非Sawyer关节角)
            ee = env.data.site_xpos[env.model.site("endEffector").id]
            state = ee.astype(np.float32).copy()  # 3D 末端位置 (x,y,z)
            # 专家动作: 多阶段决策 (2026-08-06, 老倪要求"预测中决策"场景)
            # Phase 1: 快速接近 hole 上方 (水平面)
            # Phase 2: 缓慢对准+下降插入 (预测接触)
            # Phase 3: 完成保持
            try:
                hid = env.model.site("hole").id
                hole = env.data.site_xpos[hid]
            except Exception:
                hole = None
            # 目标点: 先用 hole (peg 任务), 回退 goal
            try:
                gid = env.model.site("goal").id
                goal = env.data.site_xpos[gid]
            except Exception:
                goal = None
            target = hole if hole is not None else goal
            if target is not None:
                delta = target - ee
                dist_xy = np.linalg.norm(delta[:2])
                dist_z = abs(delta[2])
                if dist_xy > 0.05:
                    # Phase 1: 水平快速接近 (上方 5cm 处)
                    horiz = np.array([delta[0], delta[1], max(delta[2] - 0.05, -0.05)])
                    vel = horiz / max(np.linalg.norm(horiz), 1e-6) * 0.12
                    gripper = 0.0
                elif dist_z > 0.03:
                    # Phase 2: 垂直缓慢插入 (预测接触, 减速)
                    vert = np.array([delta[0] * 0.2, delta[1] * 0.2, delta[2]])
                    vel = vert / max(np.linalg.norm(vert), 1e-6) * 0.05
                    gripper = -0.5  # 夹爪闭合
                else:
                    # Phase 3: 完成保持
                    vel = np.zeros(3)
                    gripper = -1.0
                action = np.concatenate([vel, [gripper]])
            else:
                action = np.zeros(4)
            env.step(action)
            all_frames.append({
                "observation.state": state.tolist(),
                "action": action.tolist(),
                "episode_index": ep,
                "frame_index": i,   # 轨迹内索引 (LeRobot 标准)
                "timestamp": i / 30.0,
            })
            total += 1
        ep_imgs_all[ep] = ep_imgs
        all_eps.append({"episode_index": ep, "length": args.steps})
        print(f"  轨迹{ep}: 完成")

    # 写视频 (每轨迹 mp4 + metadata) — 用 ffmpeg 命令行 (imageio PyAV 参数不兼容)
    import subprocess, tempfile
    for ep, imgs in ep_imgs_all.items():
        mp4_name = f"episode_{ep:06d}.mp4"
        # 图像存临时目录 → ffmpeg 编码
        with tempfile.TemporaryDirectory() as td:
            for i, im in enumerate(imgs):
                Image.fromarray(im).save(f"{td}/{i:06d}.png")
            subprocess.run([
                "ffmpeg", "-y", "-framerate", "30", "-i", f"{td}/%06d.png",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23",
                "-loglevel", "error", str(img_dir / mp4_name),
            ], check=True)
        (img_dir / f"{mp4_name}.metadata").write_text(
            "\n".join(str(i) for i in range(len(imgs))))
    print(f"  🎬 视频: {len(ep_imgs_all)} 个 mp4")

    # 写 parquet (float32 匹配 info)
    import pandas as pd
    df = pd.DataFrame(all_frames)
    df["observation.state"] = df["observation.state"].apply(lambda v: np.asarray(v, dtype=np.float32))
    df["action"] = df["action"].apply(lambda v: np.asarray(v, dtype=np.float32))
    df["timestamp"] = df["timestamp"].astype(np.float32)
    df["index"] = df["frame_index"]
    df["task_index"] = 0
    df["next.reward"] = 0.0
    df["next.done"] = False
    df["next.success"] = False
    df.to_parquet(data_dir / "file-000.parquet")
    pd.DataFrame(all_eps).to_parquet(meta_dir / "file-000.parquet")
    # 补视频索引列 (LeRobotDataset 需要)
    eps_df = pd.read_parquet(meta_dir / "file-000.parquet")
    eps_df["videos/observation.image/chunk_index"] = 0
    eps_df["videos/observation.image/frame_index"] = eps_df["length"] - 1
    eps_df["videos/observation.image/file_index"] = 0
    # v3.0 标准: from/to_timestamp + dataset 索引 (2026-08-06 修复, 否则 LeRobot 解码 KeyError)
    from_idx = eps_df["dataset_from_index"] if "dataset_from_index" in eps_df.columns else eps_df["episode_index"] * args.steps
    eps_df["dataset_from_index"] = from_idx
    eps_df["dataset_to_index"] = eps_df["dataset_from_index"] + eps_df["length"] - 1
    eps_df["videos/observation.image/from_timestamp"] = 0.0
    eps_df["videos/observation.image/to_timestamp"] = (eps_df["length"] - 1) / 30.0
    eps_df["data/chunk_index"] = 0
    eps_df["data/file_index"] = 0
    eps_df["tasks"] = 0
    eps_df["meta/episodes/chunk_index"] = 0
    eps_df["meta/episodes/file_index"] = 0
    eps_df.to_parquet(meta_dir / "file-000.parquet")
    # tasks.parquet (LeRobotDataset 需要)
    import pandas as _pd
    _pd.DataFrame({"task_index": [0], "task": [args.task]}).to_parquet(out / "meta" / "tasks.parquet")

    # 写 meta/info.json (v3.0 标准)
    states = np.stack([f["observation.state"] for f in all_frames])
    actions = np.stack([f["action"] for f in all_frames])
    info = {
        "codebase_version": "v3.0",
        "robot_type": "metaworld_sawyer",
        "total_episodes": args.eps,
        "total_frames": total,
        "total_tasks": 1,
        "chunks_size": 100,
        "fps": 30,
        "splits": {"train": f"0:{total}"},
        "data_path": "data/chunk-000/file-000.parquet",
        "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4",
        "repo_id": "MikeBMW/metaworld-joint-real",
        "features": {
            "observation.image": {
                "dtype": "video", "shape": [128, 128, 3], "fps": 30,
                "video.codec": "h264", "video.pix_fmt": "rgb24",
                "video.is_depth_map": False, "has_audio": False,
            },
            "observation.state": {
                "dtype": "float32", "shape": [3],
                "names": {"motors": ["x", "y", "z"]}, "fps": 30.0,
            },
            "action": {"dtype": "float32", "shape": [4],
                       "names": {"motors": ["dx", "dy", "dz", "gripper"]}, "fps": 30.0},
            "episode_index": {"dtype": "int64", "shape": [1]},
            "frame_index": {"dtype": "int64", "shape": [1]},
            "timestamp": {"dtype": "float32", "shape": [1], "fps": 30.0},
            "next.reward": {"dtype": "float32", "shape": [1]},
            "next.done": {"dtype": "bool", "shape": [1]},
            "next.success": {"dtype": "bool", "shape": [1]},
        },
        "data_files_size_in_mb": 0.1,
        "video_files_size_in_mb": 12.0,
    }
    (out / "meta" / "info.json").write_text(json.dumps(info, indent=1))
    stats = {
        "observation.state": {"mean": states.mean(axis=0).tolist(), "std": states.std(axis=0).tolist(),
                              "min": states.min(axis=0).tolist(), "max": states.max(axis=0).tolist()},
        "action": {"mean": actions.mean(axis=0).tolist(), "std": actions.std(axis=0).tolist(),
                   "min": actions.min(axis=0).tolist(), "max": actions.max(axis=0).tolist()},
        "observation.image": {  # ImageNet 归一化 (SmolVLM 视觉需要, 2026-08-06 修复)
            "mean": [0.485, 0.456, 0.406], "std": [0.229, 0.224, 0.225],
            "min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 1.0],
        },
    }
    (out / "meta" / "stats.json").write_text(json.dumps(stats, indent=1))

    print(f"\n✅ 生成完成: {total} 帧 / {args.eps} 轨迹")
    print(f"   state: {states.shape} range=[{states.min():.2f},{states.max():.2f}]")
    print(f"   action: {actions.shape} range=[{actions.min():.4f},{actions.max():.4f}]")
    print(f"   非零动作帧: {(np.abs(actions).max(axis=1) > 1e-4).sum()}/{total}")
    print(f"   保存: {out}")


if __name__ == "__main__":
    main()
