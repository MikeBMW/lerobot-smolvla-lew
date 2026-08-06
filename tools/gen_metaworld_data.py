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
    # 官方专家策略 (保证真正抓取-插入, 2026-08-06 v3 修复: 手写 5 阶段夹不住 peg)
    try:
        from metaworld.policies.sawyer_peg_insertion_side_v3_policy import SawyerPegInsertionSideV3Policy
        expert = SawyerPegInsertionSideV3Policy()
        expert_mode = True
        print("🎯 使用官方专家策略 (peg-insert-side-v3)")
    except Exception as ex:
        expert = None
        expert_mode = False
        print(f"⚠️ 官方策略加载失败 ({ex}), 用手写多阶段专家")

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
            # 官方专家策略优先 (保证抓取-插入成功, 2026-08-06)
            if expert_mode and expert is not None:
                obs_vec = np.asarray(obs, dtype=np.float64).ravel()
                try:
                    a4 = np.asarray(expert.get_action(obs_vec), dtype=np.float32).ravel()
                    # 官方策略输出已是 metaworld 兼容动作 (delta_pos 速度 + grab_effort), 直接执行
                    gripper_cmd = a4[3] if a4.size >= 4 else 0.0
                    obs, _, _, _, _ = env.step(a4[:4])  # 更新 obs (官方策略每帧需要新观测)
                    # 🐛 2026-08-06 修复: 直接存专家速度指令 (a4[:4]), 不要用"位移×30" —
                    #   位移×30 把动作压到 0.03 (std=0.0335), 模型学到"不动"→视频拿不起来
                    #   metaworld 是速度控制 (delta_pos ∈ [-1,1]), 专家输出需 clip 到 [-1,1]
                    #   与 env.step 实际执行一致 (否则训练目标与执行不一致)
                    action = np.clip(a4[:4], -1.0, 1.0)
                except Exception:
                    action = np.zeros(4)
                all_frames.append({
                    "observation.state": state.tolist(),
                    "action": action.tolist(),
                    "episode_index": ep,
                    "frame_index": i,   # 轨迹内索引 (LeRobot 标准)
                    "timestamp": i / 30.0,
                })
                total += 1
                continue
            # 专家动作: 完整插销流程 5 阶段 (2026-08-06 v3, 老倪要求"拿起插销")
            # Phase 1: 接近 peg (绿色长条) 上方
            # Phase 2: 下降抓取 peg (夹爪闭合)
            # Phase 3: 抬起 peg (升高到孔高度)
            # Phase 4: 水平移到 hole 上方
            # Phase 5: 下降插入 + 保持
            try:
                hid = env.model.site("hole").id
                hole = env.data.site_xpos[hid]
            except Exception:
                hole = None
            try:
                pid = env.model.site("pegGrasp").id  # 正确抓握点 (peg 中段)
                peg = env.data.site_xpos[pid]
            except Exception:
                try:
                    pid = env.model.site("pegHead").id
                    peg = env.data.site_xpos[pid]
                except Exception:
                    peg = None
            try:
                gid = env.model.site("goal").id
                goal = env.data.site_xpos[gid]
            except Exception:
                goal = None
            target_hole = hole if hole is not None else goal
            # 抓取点: peg 上方 3cm (抓握高度)
            grasp_pt = np.array([peg[0], peg[1], peg[2] + 0.03]) if peg is not None else None
            if grasp_pt is not None and target_hole is not None:
                d_peg = np.linalg.norm(ee - grasp_pt)          # 到抓取点距离
                d_peg_xy = np.linalg.norm((ee - grasp_pt)[:2]) # 水平距离
                d_hole = np.linalg.norm(ee - target_hole)      # 到孔距离
                lifted = ee[2] > target_hole[2] - 0.01         # 是否已抬到孔高度
                if d_peg > 0.06:
                    # Phase 1: 接近 peg 上方 (水平 + 升到抓取高度)
                    dv = grasp_pt - ee
                    horiz = np.array([dv[0], dv[1], dv[2] * 0.5])
                    vel = horiz / max(np.linalg.norm(horiz), 1e-6) * 0.12
                    gripper = 0.0  # 张开
                elif ee[2] < grasp_pt[2] - 0.01:
                    # Phase 2: 下降抓取 (夹爪闭合)
                    dv = grasp_pt - ee
                    vel = dv / max(np.linalg.norm(dv), 1e-6) * 0.05
                    gripper = -0.8  # 闭合抓取
                elif not lifted:
                    # Phase 3: 抬起 peg 到孔高度
                    lift_pt = np.array([ee[0], ee[1], target_hole[2] + 0.02])
                    dv = lift_pt - ee
                    vel = dv / max(np.linalg.norm(dv), 1e-6) * 0.08
                    gripper = -1.0  # 保持闭合
                elif d_hole > 0.06:
                    # Phase 4: 水平移到 hole 上方 (保持高度)
                    dv = np.array([target_hole[0] - ee[0], target_hole[1] - ee[1], 0.0])
                    vel = dv / max(np.linalg.norm(dv), 1e-6) * 0.10
                    gripper = -1.0  # 保持闭合
                else:
                    # Phase 5: 下降插入 + 保持
                    dv = target_hole - ee
                    if np.linalg.norm(dv) > 0.02:
                        vel = dv / max(np.linalg.norm(dv), 1e-6) * 0.04
                    else:
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
