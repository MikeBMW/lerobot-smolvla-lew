#!/usr/bin/env python3
"""Z-MAX 触觉数据生成 — metaworld_peg (39D) → metaworld_peg_tac (43D)
2026-08-12 老倪: Marker 触觉跟踪需要输入数据 — metaworld 无 GelSight, 从 39D state 改造合成触觉 4D:

  tactile[0] 夹持力   = 1 - gripper  (夹爪闭合=1, 张开=0)
  tactile[1] 接触力   = 1/(1+5d)     (d=|光模块−hole| 距离, 越近力越大)
  tactile[2] 接触方向x = (peg_x−hole_x)/d
  tactile[3] 接触方向z = (peg_z−hole_z)/d

输出: LeRobot 格式 data/metaworld_peg_tac/ (parquet 加列 + meta 更新 + videos 软链, 磁盘铁律)
用法: .venv/bin/python src/lerobot/policies/yolo_3d/gen_tactile.py [--src data/metaworld_peg] [--out data/metaworld_peg_tac]
"""
import argparse, json, os, shutil, sys
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))


def synth_tactile(states):
    """39D state 批量 → 4D 触觉 (N,39) → (N,4)"""
    states = np.asarray(states, dtype=np.float32)
    grip = states[:, 3]                      # 夹爪开度 0闭合 1张开
    peg = states[:, 4:7]
    hole = states[:, 36:39]
    d = np.linalg.norm(peg - hole, axis=1) + 1e-6
    t0 = 1.0 - grip                          # 夹持力
    t1 = 1.0 / (1.0 + 5.0 * d)               # 接触力 (近→大)
    t2 = (peg[:, 0] - hole[:, 0]) / d        # 接触方向 x
    t3 = (peg[:, 2] - hole[:, 2]) / d        # 接触方向 z
    return np.stack([t0, t1, t2, t3], axis=1).astype(np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(ROOT, "data", "metaworld_peg"))
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "metaworld_peg_tac"))
    args = ap.parse_args()
    src, out = args.src, args.out
    assert os.path.isdir(src), f"源数据集不存在: {src}"
    if os.path.exists(out):
        shutil.rmtree(out)

    # 1) 读全部 parquet
    import glob
    files = sorted(glob.glob(os.path.join(src, "data", "chunk-*", "*.parquet")))
    assert files, f"无 parquet: {src}/data/chunk-*/"
    n_eps = n_rows = 0
    for f in files:
        t = pq.read_table(f)
        states = np.asarray(t.column("observation.state").to_pylist(), dtype=np.float32)
        tac = synth_tactile(states)
        t = t.append_column("observation.tactile", pa.array(tac.tolist(), type=pa.list_(pa.float32())))
        rel = os.path.relpath(f, src)
        dst = os.path.join(out, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        pq.write_table(t, dst)
        n_eps = max(n_eps, int(np.max(t.column("episode_index").to_pylist())) + 1)
        n_rows += t.num_rows
    print(f"✓ 已写 {len(files)} parquet, {n_eps} 集 {n_rows} 帧 → {out}")

    # 2) meta 复制 + info.json features 加 observation.tactile
    shutil.copytree(os.path.join(src, "meta"), os.path.join(out, "meta"))
    ip = os.path.join(out, "meta", "info.json")
    info = json.load(open(ip, encoding="utf-8"))
    info["features"]["observation.tactile"] = {"dtype": "float32", "shape": [4]}
    json.dump(info, open(ip, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # 3) stats.json 补触觉统计 (训练归一化需要) — 读输出 parquet (含 tactile)
    sp = os.path.join(out, "meta", "stats.json")
    if os.path.exists(sp):
        stats = json.load(open(sp, encoding="utf-8"))
        tac_all = []
        for f in sorted(glob.glob(os.path.join(out, "data", "chunk-*", "*.parquet"))):
            t = pq.read_table(f, columns=["observation.tactile"])
            tac_all.extend(t.column("observation.tactile").to_pylist())
        a = np.asarray(tac_all, dtype=np.float32)
        stats["observation.tactile"] = {
            "mean": a.mean(axis=0).tolist(), "std": a.std(axis=0).tolist(),
            "min": a.min(axis=0).tolist(), "max": a.max(axis=0).tolist(),
        }
        json.dump(stats, open(sp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # 4) videos 软链 (磁盘铁律: 不复制)
    os.symlink(os.path.abspath(os.path.join(src, "videos")), os.path.join(out, "videos"))
    print("✓ meta 更新 (tactile 4D) + videos 软链")
    print(f"✅ 完成: {out}  (state 39D+4D=43D, 双击训练节点前把 dataset.root 指到此处)")


if __name__ == "__main__":
    main()
