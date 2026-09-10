#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""状态空间引擎 3D 全链演示视频 —— 插入光模块 → 拔出 → AOI 检测 → 回程 → 放下

  真正跑引擎真物理 (RealStateSpaceSim, mode=full = 插拔+AOI 闭环, 13 段),
  每步用 env.render() 取 3D 帧 (corner2 相机) → ffmpeg 合成 mp4。

  用法:
    gui-venv311/bin/python tools/gen_state_space_video.py                    # L2 解析链 (基线)
    gui-venv311/bin/python tools/gen_state_space_video.py --l3               # 叠 L3 新模型 (SS_L3=1)
    gui-venv311/bin/python tools/gen_state_space_video.py --l3 --ck <路径>    # 指定 ckpt
    ... 可选 --seed N --out path.mp4 --every K (每 K 步取一帧, 默认 1)

  L2/L3/L4 联动标注 (视频左上角叠加当前阶段/来源):
    L4 = 世界模型(流形预测器)+ 意图 (阶段/Δz)   L3 = SmolVLA-Lew 出参考   L2 = 六层伺服执行
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("DISPLAY", ":0")
ROOT = "/home/ubuntu/lerobot-smolvla-lew"
for _p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "gui")):
    sys.path.insert(0, _p)
os.chdir(ROOT)

ap = argparse.ArgumentParser()
ap.add_argument("--l3", action="store_true", help="SS_L3=1 (新模型接管执行 — 会降成功率)")
ap.add_argument("--l3-shadow", action="store_true",
                help="SS_L3=1 + SS_L3_SHADOW=1 影子集成: 模型真推理/真记录, 但不接管 (零回退)")
ap.add_argument("--ck", default="outputs/train/smolvla_lew_v10_fast/checkpoints/004000/pretrained_model")
ap.add_argument("--seed", type=int, default=104)
ap.add_argument("--mode", default="full", choices=["full", "insert"])
ap.add_argument("--every", type=int, default=1, help="每 K 步取一帧")
ap.add_argument("--out", default=None)
a = ap.parse_args()

# 环境: 默认解析链 (回归基线), --l3 时开模型执行
os.environ["SS_MODE"] = a.mode
os.environ.setdefault("SS_OBSERVE", "0")
os.environ.setdefault("SS_SHADOW", "0")
if a.l3 or a.l3_shadow:
    os.environ["SS_L3"] = "1"
    os.environ["SS_L3_CK"] = a.ck
    os.environ.setdefault("SS_L3_EVERY", "4")
    if a.l3_shadow:
        os.environ["SS_L3_SHADOW"] = "1"     # 🧠 影子集成: 真推理不接管
else:
    os.environ["SS_L3"] = "0"

from state_space_sim_real import RealStateSpaceSim  # noqa: E402

frames, stamps = [], []
_t0 = time.time()


def _sink(sim, act, o):
    """每步 3D 取帧 + 叠加联动标注 (真渲染, 不造假)"""
    if len(frames) % max(1, a.every) != 0:
        return
    try:
        fr = np.asarray(sim.env.render())
    except Exception as e:
        print(f"  ⚠️ render 失败: {e}", flush=True)
        return
    try:
        import cv2
        _st = sim.sched.stage()
        # L2/L3/L4 联动标签 (左上角, 单色白字不花哨 — 老倪界面偏好)
        _src = "L3模型" if os.environ.get("SS_L3") == "1" else "L2解析"
        _l4 = "L4意图" if getattr(sim, "_mani_pred", None) is not None else "L4-"
        cv2.putText(fr, f"{_l4} | {_src} | 阶段: {_st}", (6, 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    except Exception:
        pass
    frames.append(fr)


print(f"🎬 引擎全链 3D 视频: mode={a.mode} seed={a.seed} L3={'ON' if a.l3 else 'OFF'}"
      f" ck={a.ck if a.l3 else '-'}", flush=True)
sim = RealStateSpaceSim(seed=a.seed, vision=False, mode=a.mode, log=lambda m: print("   ", m, flush=True))
sim._frame_sink = _sink
tr = sim.run(max_steps=2500)
ok = bool(tr["done"][-1]) if tr.get("done") else False
st = [str(x).replace("阶段 ", "").split("·")[0].strip() for x in tr.get("stage", [])]
from collections import Counter  # noqa: E402
print(f"\n✅ 跑完: {len(tr.get('t', []))} 步 · 完成={ok} · {time.time()-_t0:.0f}s")
print(f"   阶段覆盖: {dict(Counter(st))}")
if getattr(sim, "_l3_calls", None):
    print(f"   L3 模型调用: {sim._l3_calls} 次")

# ── 合成 mp4 ──
out = a.out or os.path.join(ROOT, "reports", f"ss_3d_{'l3' if a.l3 else 'l2'}_{a.mode}_{time.strftime('%Y%m%d_%H%M%S')}.mp4")
os.makedirs(os.path.dirname(out), exist_ok=True)
if frames:
    import cv2
    tmp = tempfile.mkdtemp(prefix="ssvid_")
    for i, fr in enumerate(frames):
        cv2.imwrite(os.path.join(tmp, f"f{i:05d}.png"), cv2.cvtColor(np.asarray(fr), cv2.COLOR_RGB2BGR))
    subprocess.run(["ffmpeg", "-y", "-framerate", "20", "-i", os.path.join(tmp, "f%05d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", "-loglevel", "error",
                    out], check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"   🎬 视频: {out} ({len(frames)} 帧)")
    # 关键帧 (每阶段一帧)
    kf = {}
    for i, s in enumerate(st):
        if s not in kf and i // max(1, a.every) < len(frames):
            kf[s] = i
    print(f"   阶段关键帧: {kf}")
else:
    print("   ⚠️ 没有采集到帧")
json.dump({"mode": a.mode, "seed": a.seed, "l3": bool(a.l3), "ck": a.ck if a.l3 else None,
           "steps": len(tr.get("t", [])), "done": ok, "stages": dict(Counter(st)),
           "video": out, "n_frames": len(frames)},
          open(os.path.join(ROOT, "reports", "ss_3d_last.json"), "w"), ensure_ascii=False, indent=1)
