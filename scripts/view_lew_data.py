#!/usr/bin/env python3
"""
LeRobot 数据集可视化 (Standalone - 不依赖 lerobot 框架)
直接用 huggingface_hub 读 Parquet 数据集元信息 + 样本帧

用法:
    python scripts/view_lew_data.py --meta
    python scripts/view_lew_data.py --repo lerobot/pusht
    python scripts/view_lew_data.py --list
    python scripts/view_lew_data.py --steps 50
"""
import argparse
import sys
import os
import json
import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from huggingface_hub import hf_hub_download, HfApi
import pyarrow.parquet as pq
from PIL import Image


# ============================================================
# 1. 加载元信息 (只下载 info.json, 几KB)
# ============================================================
def load_metadata(repo_id):
    print("\n正在加载 %s 的元数据..." % repo_id)
    info_path = hf_hub_download(
        repo_id=repo_id,
        filename="meta/info.json",
        repo_type="dataset",
    )
    with open(info_path, "r", encoding="utf-8") as f:
        info = json.load(f)

    print("✅ 元数据加载成功")
    ep = info.get("total_episodes", "N/A")
    fr = info.get("total_frames", "N/A")
    fps = info.get("fps", "N/A")
    rtype = info.get("robot_type", "N/A")
    print("   Episode: %s | 总帧数: %s | FPS: %s | 机器人: %s" % (ep, fr, fps, rtype))

    print("\n   数据字段:")
    for key, feat in info.get("features", {}).items():
        dtype = feat.get("dtype", "unknown")
        shape = feat.get("shape", "unknown")
        print("     └─ %s: dtype=%s, shape=%s" % (key, dtype, shape))
    return info


# ============================================================
# 2. 下载一个 episode 的 parquet (通常 <1MB)
# ============================================================
def load_sample_parquet(repo_id, episode_idx=0):
    chunk_dir = episode_idx // 1000
    parquet_filename = "data/chunk-%03d/episode_%06d.parquet" % (chunk_dir, episode_idx)
    print("\n下载 %s ..." % parquet_filename)

    try:
        parquet_path = hf_hub_download(
            repo_id=repo_id,
            filename=parquet_filename,
            repo_type="dataset",
        )
        print("✅ 下载到: %s" % parquet_path)
    except Exception as e:
        print("❌ 下载失败: %s" % e)
        return None

    table = pq.read_table(parquet_path)
    print("   行数: %d | 列: %s" % (table.num_rows, table.column_names))
    data = {}
    for col in table.column_names:
        data[col] = table.column(col).to_pylist()
    return data


# ============================================================
# 3. 打印单帧数据
# ============================================================
def print_sample(data, idx=0):
    print("\n--- 第 %d 个时间步 ---" % idx)
    for key, val_list in data.items():
        if idx >= len(val_list):
            continue
        val = val_list[idx]
        if isinstance(val, dict):
            summary = {}
            for k, v in val.items():
                if isinstance(v, (int, float, str)):
                    summary[k] = v
                elif isinstance(v, bytes):
                    summary[k] = "[binary]"
                else:
                    summary[k] = type(v).__name__
            print("  %s: %s" % (key, summary))
        elif isinstance(val, bytes):
            print("  %s: [binary %d bytes]" % (key, len(val)))
        elif hasattr(val, "shape"):
            print("  %s: shape=%s dtype=%s" % (key, val.shape, val.dtype))
        elif isinstance(val, (int, float)):
            print("  %s: %s" % (key, val))
        else:
            print("  %s: %s" % (key, str(val)[:80]))


# ============================================================
# 4. 可视化第一帧图像
# ============================================================
def visualize_first_frame(data, output_dir="/tmp"):
    img_keys = [k for k in data if "image" in k.lower()]
    if not img_keys:
        print("\n⚠️ 未找到图像字段")
        return

    key = img_keys[0]
    first_val = data[key][0]
    print("\n可视化: %s" % key)

    if isinstance(first_val, bytes):
        from io import BytesIO
        img = Image.open(BytesIO(first_val))
    elif isinstance(first_val, np.ndarray):
        img = Image.fromarray(first_val)
    else:
        print("   未知图像格式: %s" % type(first_val))
        return

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.imshow(img)

    task_key = None
    for k in data:
        if "task" in k.lower():
            task_key = k
            break
    task_text = data[task_key][0] if task_key else "N/A"
    ax.set_title("First Frame - Task: %s" % task_text, fontsize=13)
    ax.axis("off")
    plt.tight_layout()
    output_path = os.path.join(output_dir, "first_frame.png")
    plt.savefig(output_path, dpi=150)
    plt.close(fig)
    print("✅ 图像已保存: %s" % output_path)


# ============================================================
# 5. 绘制时序曲线 state / action / reward
# ============================================================
def plot_time_series(data, max_steps=80, output_dir="/tmp"):
    print("\n绘制前 %d 帧时序曲线..." % max_steps)

    def extract_array(data, candidates):
        for k in candidates:
            if k not in data:
                continue
            vals = data[k][:max_steps]
            if not vals:
                continue
            # 如果是 list of dict (嵌套 state)
            if isinstance(vals[0], dict):
                rows = []
                for v in vals:
                    row = [float(x) for x in v.values()]
                    rows.append(row)
                return np.array(rows), k
            # 如果是 list of bytes → 二进制图像，跳过
            if isinstance(vals[0], bytes):
                continue
            arr = np.array(vals, dtype=np.float64) if isinstance(vals[0], (list, np.ndarray)) else None
            if arr is None:
                try:
                    arr = np.array(vals)
                except (ValueError, TypeError):
                    continue
            if arr.ndim == 1:
                arr = arr[:, np.newaxis]
            return arr, k
        return None, None

    states, s_key = extract_array(data, [
        "observation.state", "observation.state.array", "state",
    ])
    actions, a_key = extract_array(data, [
        "action", "action.array",
    ])
    rewards, r_key = extract_array(data, [
        "next.reward", "reward",
    ])

    items = [(states, s_key, "State"), (actions, a_key, "Action"), (rewards, r_key, "Reward")]
    items = [(a, k, n) for a, k, n in items if a is not None]

    if not items:
        print("⚠️ 未找到 state/action/reward 数据")
        print("   可用字段: %s" % list(data.keys())[:8])
        return

    n_rows = len(items)
    fig, axes = plt.subplots(n_rows, 1, figsize=(10, 3 * n_rows), sharex=True)
    if n_rows == 1:
        axes = [axes]

    for ax_i, (arr, key, name) in enumerate(items):
        ax = axes[ax_i]
        for dim in range(arr.shape[1]):
            ax.plot(arr[:, dim], label="%s[%d]" % (name, dim))
        ax.set_title("%s (%s)" % (name, key))
        ax.set_ylabel("Value")
        ax.legend(fontsize=7, ncol=min(arr.shape[1], 6))
        ax.grid(True, alpha=0.3)

    axes[-1].set_xlabel("Timestep")
    plt.tight_layout()
    out = os.path.join(output_dir, "state_action_reward.png")
    plt.savefig(out, dpi=150)
    plt.close(fig)

    print("✅ 时序曲线已保存: %s" % out)
    for arr, key, name in items:
        print("   %s: shape=%s (key=%s)" % (name, arr.shape, key))


# ============================================================
# 6. 列出 episodes
# ============================================================
def list_episodes(repo_id, max_show=10):
    print("\n列出 %s 的 episodes..." % repo_id)
    api = HfApi()
    try:
        files = api.list_repo_files(repo_id, repo_type="dataset")
        parquets = [f for f in files if f.startswith("data/") and f.endswith(".parquet")]
        print("   找到 %d 个 parquet 文件" % len(parquets))
        for p in parquets[:max_show]:
            print("     %s" % p)
        if len(parquets) > max_show:
            print("     ... 还有 %d 个" % (len(parquets) - max_show))
    except Exception as e:
        print("   ⚠️ %s" % e)


# ============================================================
# main
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="LeRobot 数据集可视化工具 (Standalone)")
    parser.add_argument("--repo", default="lerobot/metaworld_mt50", help="HF dataset repo_id")
    parser.add_argument("--episode", type=int, default=0, help="Episode index")
    parser.add_argument("--steps", type=int, default=80, help="最大时序步数")
    parser.add_argument("--output", default="/tmp", help="输出目录")
    parser.add_argument("--meta", action="store_true", help="仅显示元数据")
    parser.add_argument("--list", action="store_true", help="仅列出 episodes")
    args = parser.parse_args()

    print("=" * 60)
    print("LeRobot 数据集可视化工具 (Standalone)")
    print("数据源: %s" % args.repo)
    print("=" * 60)

    # Step 1
    info = load_metadata(args.repo)

    if args.meta:
        print("\n仅显示元数据，完成。")
        return

    # Step 2
    list_episodes(args.repo, max_show=5)

    if args.list:
        return

    # Step 3
    data = load_sample_parquet(args.repo, episode_idx=args.episode)
    if data is None:
        print("\n❌ 无法加载数据")
        return

    # Step 4
    print_sample(data, idx=0)

    # Step 5
    visualize_first_frame(data, output_dir=args.output)

    # Step 6
    plot_time_series(data, max_steps=args.steps, output_dir=args.output)

    print("\n" + "=" * 60)
    print("✅ 全部完成!")
    print("   %s/first_frame.png" % args.output)
    print("   %s/state_action_reward.png" % args.output)
    print("=" * 60)


if __name__ == "__main__":
    main()
