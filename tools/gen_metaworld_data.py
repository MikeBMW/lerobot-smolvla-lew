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
    ap.add_argument("--yolo", action="store_true", help="用 YOLO 检测替换 39D (模拟真机感知)")
    ap.add_argument("--steps", type=int, default=180, help="每条轨迹帧数")
    ap.add_argument("--grab-only", action="store_true", help="只到抓起(不含插入), 2026-08-08 老倪: 方向一致防平均化")
    ap.add_argument("--stop-after-grab", action="store_true", help="抓起后即停(分段数据), 2026-08-08 老倪: 防方向反转")
    ap.add_argument("--rel-vec", action="store_true", help="state加相对向量(hand→peg,peg→hole), 2026-08-08 ③目标条件化")
    ap.add_argument("--far", action="store_true", help="远起点模式 (2026-08-07 老倪: 让模型学会更长接近轨迹)")
    ap.add_argument("--task", default="reach-v3")
    ap.add_argument("--out", default="data/metaworld_cartesian")
    args = ap.parse_args()
    yolo_mode = getattr(args, "yolo", False)
    yolo_aligner = None
    if yolo_mode:
        from tools.yolo_state_aligner import YoloStateAligner
        WEIGHTS = "runs/detect/outputs/yolo_peg/peg_full/weights/best.pt"
        import metaworld as _mt
        _mt_env = _mt.MT1("peg-insert-side-v3")
        _env0 = _mt_env.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
        _env0._freeze_rand_vec = False
        _env0.set_task(_mt_env.train_tasks[0])
        _env0.reset(seed=0)
        yolo_aligner = YoloStateAligner(WEIGHTS, _env0)

    import metaworld
    from PIL import Image
    # 官方专家策略 (保证真正抓取-插入, 2026-08-06 v3 修复: 手写 5 阶段夹不住 peg)
    # 2026-08-07: --far 远起点用多阶段专家 (官方专家假设标准起点, 远移后状态机失效)
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
    env = mt.train_classes[args.task](render_mode="rgb_array", camera_name="corner2")
    env.set_task(mt.train_tasks[0])
    env._freeze_rand_vec = False  # 允许随机初始化 (多 seed 探索)

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
        # 远起点模式 (2026-08-07 老倪: 长接近轨迹) — 先移手到远处再记录
        if getattr(args, "far", False):
            ee_site = env.model.site("endEffector").id
            tgt = np.array([-0.05, 0.3, 0.25])  # 远处起点 (远离 peg)
            for _ in range(40):
                cur = env.data.site_xpos[ee_site]
                delta = (tgt - cur) * 0.3
                env.step(np.concatenate([delta, [0.0]]))
            # 远移后重新获取 obs (专家要用最新状态)
            obs, _, _, _, _ = env.step(np.zeros(4))
        # 记录轨迹开始时 peg 高度 (成功判定基准, 2026-08-06)
        try:
            peg_z0 = env.data.site_xpos[env.model.site("pegGrasp").id][2]
        except Exception:
            peg_z0 = 0.02
        ep_imgs = []
        grabbed_frames = 0  # 2026-08-08: 分段数据 — 抓起后保持 N 帧即停 (方向一致, 无转移反转)
        for i in range(args.steps):
            # 2026-08-08: 分段数据 — 官方专家抓起 peg 后保持 30 帧即停止记录
            if getattr(args, "stop_after_grab", False) and grabbed_frames >= 30:
                break
            # 渲染真实图像 (480x480 → 128x128)
            img = np.asarray(env.render())
            pil = Image.fromarray(img).resize((128, 128), Image.LANCZOS)
            ep_imgs.append(np.asarray(pil))
            # YOLO 检测必须用 480 原图 (128 分辨率检测不准)
            yolo_img = img
            # 关节状态: 用末端笛卡尔位姿 (跨机器人泛化, 非Sawyer关节角)
            ee = env.data.site_xpos[env.model.site("endEffector").id]
            # 关节状态: 39 维完整观测 (2026-08-07: --yolo 模式用 YOLO 检测替换, 模拟真机感知)
            # 默认用模拟器直给 (完美观测); --yolo 时 YOLO 2D 检测 → 3D → 替换对应段
            if yolo_mode and yolo_aligner is not None:
                try:
                    det3d = yolo_aligner.detect_3d(yolo_img)
                    state = yolo_aligner.align(np.asarray(env._get_obs(), dtype=np.float32).ravel(), det3d).astype(np.float32)
                except Exception:
                    state = np.asarray(env._get_obs(), dtype=np.float32).ravel()
            else:
                try:
                    state = np.asarray(env._get_obs(), dtype=np.float32).ravel()  # 39D
                except Exception:
                    state = ee.astype(np.float32).copy()  # 兜底 3D
            # 2026-08-08 ③目标条件化: state 加相对向量 (hand→peg, peg→hole) — MLP 成功的核心
            if getattr(args, "rel_vec", False) and state.size >= 39:
                try:
                    hand_pos = env.data.site_xpos[env.model.site("endEffector").id].astype(np.float32)
                    peg_pos = env.data.site_xpos[env.model.site("pegGrasp").id].astype(np.float32)
                    hole_pos = env.data.site_xpos[env.model.site("hole").id].astype(np.float32)
                    rel_vec = np.concatenate([peg_pos - hand_pos, hole_pos - peg_pos]).astype(np.float32)
                    state = np.concatenate([state, rel_vec]).astype(np.float32)  # 39+6=45D
                except Exception:
                    pass
            # 官方专家策略优先 (保证抓取-插入成功, 2026-08-06)
            # 2026-08-07: --far 用多阶段专家 (官方专家远起点状态机失效)
            # 2026-08-08: --grab-only 也用多阶段专家 (官方专家夹爪离散, 学不到闭合)
            use_official = expert_mode and expert is not None and not getattr(args, "far", False) and not getattr(args, "grab_only", False)
            if use_official:
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
                # 2026-08-08: 分段数据 — 官方专家路径同样截断 (抓起后 30 帧即停)
                if getattr(args, "stop_after_grab", False):
                    try:
                        peg_z_now = env.data.site_xpos[env.model.site("pegGrasp").id][2]
                        if peg_z_now > peg_z0 + 0.03:
                            grabbed_frames = max(grabbed_frames, 1)
                        if grabbed_frames >= 1:
                            grabbed_frames += 1
                    except Exception:
                        pass
                all_frames.append({
                    "observation.state": state.tolist(),
                    "action": action.tolist(),
                    "episode_index": ep,
                    "frame_index": i,   # 轨迹内索引 (LeRobot 标准)
                    "timestamp": i / 30.0,
                })
                total += 1
                # 2026-08-08: 分段数据 — 官方专家路径: 截断条件满足即 break (continue 前检查)
                if getattr(args, "stop_after_grab", False) and grabbed_frames >= 30:
                    break
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
            # 抓取点: peg 上方 3cm (抓握高度) — 2026-08-08 修复: 每步重新获取 peg 位置 (循环内 peg 会动)
            pid_use = pid if 'pid' in dir() else env.model.site("pegGrasp").id
            peg_cur = env.data.site_xpos[pid_use]
            grasp_pt = np.array([peg_cur[0], peg_cur[1], peg_cur[2] + 0.03]) if peg_cur is not None else None
            if grasp_pt is not None and target_hole is not None:
                d_peg = np.linalg.norm(ee - grasp_pt)          # 到抓取点距离
                d_peg_xy = np.linalg.norm((ee - grasp_pt)[:2]) # 水平距离
                d_hole = np.linalg.norm(ee - target_hole)      # 到孔距离
                # 2026-08-08 修复: lifted 用 peg 是否被抓起 (手初始 z 就高, 用手的 z 判断永远 True → 跳过抓取)
                pid_use = pid if 'pid' in dir() else env.model.site("pegGrasp").id
                peg_now = env.data.site_xpos[pid_use]
                lifted = peg_now[2] > peg_z0 + 0.04            # peg 相对初始升高 4cm = 已抓起
                if d_peg > 0.06:
                    # Phase 1: 接近 peg 上方 (水平 + 升到抓取高度)
                    dv = grasp_pt - ee
                    horiz = np.array([dv[0], dv[1], dv[2] * 0.5])
                    # 2026-08-08 grab-only: 接近加速 (防轨迹全在接近段), 0.3太快抓取失误→0.18
                    spd = 0.18 if getattr(args, "grab_only", False) else 0.12
                    vel = horiz / max(np.linalg.norm(horiz), 1e-6) * spd
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
                    # 2026-08-08 grab-only: 只到抓起, 不转移 (防方向反转平均化)
                    if getattr(args, "grab_only", False):
                        vel = np.zeros(3)
                        gripper = -1.0  # 保持抓住, 原地不动
                    else:
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
            # 2026-08-08: 分段数据 — 检测 peg 是否被抓起 (升高 3cm, 锁存后每帧+1)
            if getattr(args, "stop_after_grab", False):
                try:
                    peg_z_now = env.data.site_xpos[env.model.site("pegGrasp").id][2]
                    if peg_z_now > peg_z0 + 0.03:
                        grabbed_frames = max(grabbed_frames, 1)  # 锁存
                    if grabbed_frames >= 1:
                        grabbed_frames += 1  # 锁存后每帧累加 (无论 peg 是否保持)
                except Exception:
                    pass
            all_frames.append({
                "observation.state": state.tolist(),
                "action": action.tolist(),
                "episode_index": ep,
                "frame_index": i,   # 轨迹内索引 (LeRobot 标准)
                "timestamp": i / 30.0,
            })
            total += 1
        # 成功过滤 (2026-08-06: 只保留抓起 peg 的轨迹, 失败轨迹污染训练)
        try:
            peg_z1 = env.data.site_xpos[env.model.site("pegGrasp").id][2]
        except Exception:
            peg_z1 = 0.02
        if peg_z1 - peg_z0 > 0.05:
            ep_imgs_all[ep] = ep_imgs
            # 2026-08-08 修复: length 用实际帧数 (stop_after_grab 截断后 < args.steps)
            actual_len = len([f for f in all_frames if f["episode_index"] == ep])
            all_eps.append({"episode_index": ep, "length": actual_len if actual_len > 0 else args.steps})
            print(f"  轨迹{ep}: 完成 (抓取成功 +{peg_z1-peg_z0:.3f}m, {actual_len}帧)")
        else:
            # 丢弃失败轨迹: 从 all_frames 移除该 episode
            all_frames[:] = [f for f in all_frames if f["episode_index"] != ep]
            print(f"  轨迹{ep}: 丢弃 (未抓起 peg, 升高{peg_z1-peg_z0:+.3f}m)")

    # 写视频 (单文件 file-000.mp4, LeRobot 标准 — 所有 episode 帧按序合成一个 mp4,
    #   episodes meta 用 from/to_frame 定位; 2026-08-06 修复: 原来每 episode 一个
    #   episode_XXX.mp4 与 info.video_path (file-{file_index}.mp4) 不一致 → 读取失败)
    import subprocess, tempfile
    all_frames_flat = []
    for ep in range(args.eps):
        all_frames_flat.extend(ep_imgs_all.get(ep, []))
    with tempfile.TemporaryDirectory() as td:
        for i, im in enumerate(all_frames_flat):
            Image.fromarray(im).save(f"{td}/{i:06d}.png")
        subprocess.run([
            "ffmpeg", "-y", "-framerate", "30", "-i", f"{td}/%06d.png",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23",
            "-loglevel", "error", str(img_dir / "file-000.mp4"),
        ], check=True)
    (img_dir / "file-000.mp4.metadata").write_text(
        "\n".join(str(i) for i in range(len(all_frames_flat))))
    print(f"  🎬 视频: 1 个 file-000.mp4 ({len(all_frames_flat)} 帧)")

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
                # 🐛 2026-08-06 修复: 缺 names → feature_utils.py L153 ft["names"] KeyError
                #   (metaworld_act 有 ['height','width','channel'], 对齐)
                "names": ["height", "width", "channel"],
            },
            "observation.state": {
                "dtype": "float32", "shape": [39],
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
            # 🐛 2026-08-06 修复: 补 index/task_index 声明 + names 键 (feature_utils.py
            #   dataset_to_policy_features 读 ft["names"], 缺键 → KeyError)
            "index": {"dtype": "int64", "shape": [1], "names": None},
            "task_index": {"dtype": "int64", "shape": [1], "names": None},
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
