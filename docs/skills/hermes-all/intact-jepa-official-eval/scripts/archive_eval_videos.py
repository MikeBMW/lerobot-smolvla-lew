#!/usr/bin/env python3
"""把一次 INTACT paper_runtime 评测的逐局视频归档成独立证据目录。

为什么必须做: eval.py/world.py 把视频写成 $STABLEWM_HOME/env_<i>.mp4 —— 文件名跨运行复用,
后一次跑会静默覆盖前一次的 env_0..env_N。跑完不拷走, 证据就没了。
(save_panel_videos: 一局一个 mp4, 3 面板并排 agent|dataset|goal, 实测 736x288/50帧/15fps)

用法:
  python archive_eval_videos.py --task pusht --tag debug_0913 \
      --successes T,T,T,F,T,T,F,T,T,T,T,T,T,T,T,T,T,T,T,T
  # successes 就是 eval 输出里 episode_successes 的顺序; 第 i 个 = env_<i>.mp4
  # 也可 --metrics-json <结果>.json 自动读 episode_successes (list[bool])
"""
import argparse
import json
import os
import shutil
import subprocess


def parse_successes(s):
    return [t.strip().upper() in ("T", "TRUE", "1", "O") for t in s.split(",")]


def probe(path):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,nb_frames,duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, check=True).stdout.strip()
        return out
    except Exception as e:      # ffprobe 缺失时不阻塞归档
        return f"(ffprobe 失败: {e})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.environ.get("STABLEWM_HOME",
                                                     "/home/ubuntu/stable-wm-cache"))
    ap.add_argument("--out-root", default="/home/ubuntu/l4_ab/intact_results")
    ap.add_argument("--task", required=True)
    ap.add_argument("--tag", required=True, help="本次运行标识, 如 debug_0913")
    ap.add_argument("--successes", help="逗号分隔 T/F, 顺序 = episode_successes")
    ap.add_argument("--metrics-json", help="含 episode_successes 的 json (与 --successes 二选一)")
    ap.add_argument("--frame-check", action="store_true",
                    help="额外抽第 25 帧算 std (判黑帧, 老倪红线 std>5)")
    a = ap.parse_args()

    if a.metrics_json:
        with open(a.metrics_json) as f:
            m = json.load(f)
        succ = [bool(x) for x in m["episode_successes"]]
    elif a.successes:
        succ = parse_successes(a.successes)
    else:
        ap.error("需要 --successes 或 --metrics-json")

    out = os.path.join(a.out_root, f"{a.task}_{a.tag}_videos")
    os.makedirs(out, exist_ok=True)
    ok = bad = 0
    for i, s in enumerate(succ):
        src = os.path.join(a.cache, f"env_{i}.mp4")
        if not os.path.exists(src):
            print(f"⚠️  缺 env_{i}.mp4 (局数对不上? 拿错 cache 目录?)")
            continue
        dst = os.path.join(out, f"env{i:02d}_{'success' if s else 'FAIL'}.mp4")
        shutil.copy2(src, dst)
        ok += s
        bad += (not s)
        if a.frame_check:
            tmp = f"/tmp/_fr_{a.task}_{i}.png"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src,
                            "-vf", r"select=eq(n\,25)", "-vframes", "1", tmp], check=True)
            try:
                import numpy as np
                from PIL import Image
                arr = np.asarray(Image.open(tmp).convert("RGB")).astype("float32")
                flag = "OK" if arr.std() > 5 else "🚨可能是黑帧"
                print(f"  env_{i}: std={arr.std():.1f} {flag}")
            except ImportError:
                print("  (装 numpy+Pillow 才能做帧自检)")

    with open(os.path.join(out, "README.txt"), "w") as f:
        f.write("由 archive_eval_videos.py 生成 —— 一轮评测的逐局视频证据\n")
        f.write(f"cache={a.cache}  task={a.task}  tag={a.tag}\n")
        f.write(f"成功 {ok} / 失败 {bad} (共 {len(succ)} 局)\n")
        f.write("成败序列: " + "".join("O" if s else "X" for s in succ) + "\n")
        f.write("失败局: " + ", ".join(f"env{i} (env{i:02d}_FAIL.mp4)"
                                      for i, s in enumerate(succ) if not s) + "\n")
        f.write("帧布局: 3 面板并排 224x224 = agent(模型rollout) | dataset(数据真值) | goal(目标)\n")
        f.write(f"规格样例: {probe(os.path.join(out, os.listdir(out)[0])) if ok + bad else '-'}\n")
    print(f"已归档 {ok + bad} 局 → {out}")


if __name__ == "__main__":
    main()
