#!/usr/bin/env python3
"""collect_simreal_vla_data.py — sim_real 解析教师 → SmolVLA 图像数据集 (2026-09-08 静静)

背景: 官方 peg-insert 专家只抓不插 (700 步验证), gen_metaworld_data --far EGL 渲染崩;
smolvla_lew 需要 图像+state+action lerobot 集 → 用状态空间真实引擎 (R0 解析伺服,
插装 100% 可靠, mode=insert 8 段) 的帧钩子采 图像(480→128) + obs39 + 实际执行动作。

用法: MUJOCO_GL=egl gui-venv311/bin/python tools/collect_simreal_vla_data.py [--target 30] [--out data/smolvla_peg_v1]
"""
import argparse, json, os, subprocess, sys, tempfile, time
import numpy as np
from pathlib import Path

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("MUJOCO_EGL_DEVICE", "0")

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "tools" / "gui"))

from PIL import Image  # noqa: E402
from state_space_sim_real import RealStateSpaceSim  # noqa: E402

GOOD_SEEDS = [101, 102, 103, 104, 108]   # R0 实测成功布局 (回归基线)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=30, help="目标成功轨迹数")
    ap.add_argument("--out", default=str(ROOT / "data" / "smolvla_peg_v1"))
    ap.add_argument("--max-seeds", type=int, default=60)
    # 🗣 C2 多任务数据 (2026-09-10): mode=insert(插装) / full(插拔+AOI 全链) —— 语义不同的
    #   任务 × 不同指令 → 语言才有"区分力", 模型才学得会"听懂要干什么"(L4 指挥 L3 的前提)。
    ap.add_argument("--mode", default="insert", choices=["insert", "full"], help="引擎任务模式")
    ap.add_argument("--task", default="metaworld 光模块插拔",
                    help="任务指令串 (写进 tasks.parquet, 必须与训练/推理保持一致; 禁硬编码旧串)")
    ap.add_argument("--max-steps", type=int, default=0, help="单轮步数上限 (0=自动: insert 1200 / full 3000)")
    args = ap.parse_args()
    out = Path(args.out)
    (out / "data" / "chunk-000").mkdir(parents=True, exist_ok=True)
    (out / "meta" / "episodes" / "chunk-000").mkdir(parents=True, exist_ok=True)
    (out / "videos" / "observation.image" / "chunk-000").mkdir(parents=True, exist_ok=True)
    img_dir = out / "videos" / "observation.image" / "chunk-000"

    seeds = list(GOOD_SEEDS)
    s = 110
    while len(seeds) < args.max_seeds:
        seeds.append(s); s += 1

    ep_frames = {}       # ep -> 帧 dict 列表
    ep_imgs = {}         # ep -> 图像列表
    n_ok = 0
    t0 = time.time()
    for seed in seeds:
        if n_ok >= args.target:
            break
        frames, imgs = [], []
        sink_called = [False]

        def _sink(sim, act, o, _fr=frames, _im=imgs):
            try:
                _im.append(np.asarray(Image.fromarray(np.asarray(sim.env.render()))
                                     .resize((128, 128), Image.LANCZOS)))
                _fr.append({"observation.state": np.asarray(o[:39], dtype=np.float32),
                            "action": np.asarray(act, dtype=np.float32)})
                sink_called[0] = True
            except Exception:
                pass

        sim = RealStateSpaceSim(seed=seed, vision=False, mode=args.mode,
                                log=lambda *a: None)
        sim._frame_sink = _sink
        _mst = args.max_steps or (3000 if args.mode == "full" else 1200)
        tr = sim.run(max_steps=_mst)
        done = bool(tr["done"][-1]) if tr.get("done") else False
        if not done or not sink_called[0]:
            print(f"  seed{seed}: 未完成, 跳过 ({time.time()-t0:.0f}s)", flush=True)
            continue
        # 插到底校验: 引擎 done 已保证 (插入段 advance 判据 = 光模块头到孔底 <6mm);
        #   原生 hole site 是 metaworld 随机销位, 与本场景带孔盒无关 — 不用它校验 (09-08 实锤)
        d = 0.0
        ep = n_ok
        # 帧序号+时间戳
        n = len(frames)
        for i, f in enumerate(frames):
            f["episode_index"] = ep
            f["frame_index"] = i
            f["timestamp"] = float(i) / 30.0
        ep_frames[ep] = frames
        ep_imgs[ep] = imgs
        n_ok += 1
        print(f"  seed{seed}: ✅ 轨迹{ep} 采得 {n} 帧 (插深 {d*1000:.1f}mm) "
              f"[{n_ok}/{args.target} · {time.time()-t0:.0f}s]", flush=True)

    if n_ok == 0:
        print("❌ 无成功轨迹"); return
    # ── 写 lerobot v3.0 ──
    flat_imgs = []
    all_frames, all_eps = [], []
    cum = 0
    for ep in sorted(ep_frames):
        fr = ep_frames[ep]
        all_frames.extend(fr)
        n = len(fr)
        all_eps.append({"episode_index": ep, "length": n,
                        "dataset_from_index": cum, "dataset_to_index": cum + n - 1,
                        "videos/observation.image/chunk_index": 0,
                        "videos/observation.image/frame_index": n - 1,
                        "videos/observation.image/file_index": 0,
                        "videos/observation.image/from_timestamp": cum / 30.0,
                        "videos/observation.image/to_timestamp": (cum + n - 1) / 30.0,
                        "data/chunk_index": 0, "data/file_index": 0,
                        "tasks": 0, "meta/episodes/chunk_index": 0,
                        "meta/episodes/file_index": 0})
        flat_imgs.extend(ep_imgs[ep])
        cum += n
    print("写入视频/parquet ...", flush=True)
    with tempfile.TemporaryDirectory() as td:
        for i, im in enumerate(flat_imgs):
            Image.fromarray(im).save(f"{td}/{i:06d}.png")
        subprocess.run(["ffmpeg", "-y", "-framerate", "30", "-i", f"{td}/%06d.png",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23",
                        "-loglevel", "error", str(img_dir / "file-000.mp4")], check=True)
    (img_dir / "file-000.mp4.metadata").write_text(
        "\n".join(str(i) for i in range(len(flat_imgs))))
    import pandas as pd
    df = pd.DataFrame(all_frames)
    df["index"] = df["frame_index"]
    df["task_index"] = 0
    df["next.reward"] = 0.0
    df["next.done"] = False
    df["next.success"] = False
    df.to_parquet(out / "data" / "chunk-000" / "file-000.parquet")
    pd.DataFrame(all_eps).to_parquet(out / "meta" / "episodes" / "chunk-000" / "file-000.parquet")
    pd.DataFrame({"task_index": [0], "task": [args.task]}).to_parquet(
        out / "meta" / "tasks.parquet")
    states = np.stack([f["observation.state"] for f in all_frames])
    actions = np.stack([f["action"] for f in all_frames])
    info = {
        "codebase_version": "v3.0", "robot_type": "metaworld_sawyer",
        "total_episodes": n_ok, "total_frames": len(all_frames), "total_tasks": 1,
        "chunks_size": 100, "fps": 30, "splits": {"train": f"0:{len(all_frames)}"},
        "data_path": "data/chunk-000/file-000.parquet",
        "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4",
        "repo_id": "MikeBMW/metaworld-peg-simreal",
        "features": {
            "observation.image": {"dtype": "video", "shape": [128, 128, 3], "fps": 30,
                                  "video.codec": "h264", "video.pix_fmt": "rgb24",
                                  "video.is_depth_map": False, "has_audio": False,
                                  "names": ["height", "width", "channel"]},
            "observation.state": {"dtype": "float32", "shape": [39],
                                  "names": {"motors": ["x", "y", "z"]}, "fps": 30.0},
            "action": {"dtype": "float32", "shape": [4],
                       "names": {"motors": ["dx", "dy", "dz", "gripper"]}, "fps": 30.0},
            "episode_index": {"dtype": "int64", "shape": [1]},
            "frame_index": {"dtype": "int64", "shape": [1]},
            "timestamp": {"dtype": "float32", "shape": [1], "fps": 30.0},
            "next.reward": {"dtype": "float32", "shape": [1]},
            "next.done": {"dtype": "bool", "shape": [1]},
            "next.success": {"dtype": "bool", "shape": [1]},
            "index": {"dtype": "int64", "shape": [1], "names": None},
            "task_index": {"dtype": "int64", "shape": [1], "names": None},
        },
        "data_files_size_in_mb": round(len(all_frames) * 39 * 4 / 1e6, 1),
        "video_files_size_in_mb": round(sum(os.path.getsize(img_dir / f)
                                            for f in os.listdir(img_dir)) / 1e6, 1),
    }
    (out / "meta" / "info.json").write_text(json.dumps(info, indent=1))
    stats = {
        "observation.state": {"mean": states.mean(0).tolist(), "std": states.std(0).tolist(),
                              "min": states.min(0).tolist(), "max": states.max(0).tolist()},
        "action": {"mean": actions.mean(0).tolist(), "std": actions.std(0).tolist(),
                   "min": actions.min(0).tolist(), "max": actions.max(0).tolist()},
        "observation.image": {"mean": [0.485, 0.456, 0.406], "std": [0.229, 0.224, 0.225],
                              "min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 1.0]},
    }
    (out / "meta" / "stats.json").write_text(json.dumps(stats, indent=1))
    print(f"\n✅ 完成: {n_ok} 轨迹 / {len(all_frames)} 帧 → {out} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
