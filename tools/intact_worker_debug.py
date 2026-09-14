# -*- coding: utf-8 -*-
"""🔬 INTACT 模型侧单步调试驱动器 (跑在 INTACT-JEPA 自己的 venv 里, 供 VSCode 断点用)。

为什么需要它: 正式路径是「跨 venv 子进程桥」——GUI venv 起 worker, worker 跑在 INTACT venv 里。
debugpy 只调停它 **launch 的那个进程**, 所以在 GUI 侧调试会话里, `/home/ubuntu/INTACT-JEPA/**` 的
模型代码断点永远不命中。要单步模型侧, 就必须在 **INTACT venv 里 in-process 起同一个 Runtime 类**。

真输入从哪来 (不造假数据): 正式跑一次时设 `INTACT_KEEP_INPUT=1` → 桥会把 worker 收到的**真实输入**
(真渲染帧 224² + 真 goal + 真动作历史) 存到 `reports/intact_last_input.npz` → 本驱动器重放它。
没有该文件时只做 `load()` (单步模型构建/权重加载路径), 并如实说明"没跑 forward"。

用法 (VSCode 选「🔬 INTACT L4 · 模型侧单步」即可):
  INTACT_DEVICE=cpu INTACT_POLICY=intact_goal_optical_insert_v4_s3072/weights_epoch_2.pt \\
  /home/ubuntu/INTACT-JEPA/.venv/bin/python tools/intact_worker_debug.py [输入npz] [输出npz]

断点位置: /home/ubuntu/INTACT-JEPA/** (模型内部) + tools/intact_worker.py::Runtime.act / load
"""
import json
import os
import sys
import time

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
os.environ.setdefault("LOCAL_DATASET_DIR", os.environ["STABLEWM_HOME"])
os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("INTACT_REPO", "/home/ubuntu/INTACT-JEPA")

import numpy as np                                  # noqa: E402
import intact_worker as W                           # noqa: E402  (同 venv 里的 worker 实现)

inp = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "reports", "intact_last_input.npz")
out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/intact_worker_debug_out.npz"
policy = os.environ.get("INTACT_POLICY") or "intact_goal_optical_insert_v4_s3072/weights_epoch_2.pt"
runtime_kind = os.environ.get("INTACT_RUNTIME") or "root"      # 本域微调权重 = 根运行时
device = os.environ.get("INTACT_DEVICE", "cpu")

print("=" * 78)
print(f"🔬 INTACT 模型侧调试 · repo={os.environ['INTACT_REPO']}")
print(f"   policy={policy} · runtime={runtime_kind} · device={device}")
print(f"   输入={inp} ({'存在' if os.path.isfile(inp) else '缺 → 只单步 load()'})")
print(f"   STABLEWM_HOME={os.environ['STABLEWM_HOME']}")
print("=" * 78)

rt = W.Runtime(repo=os.environ["INTACT_REPO"], ckpt=None, task="pusht",
               hf_repo="INTACT-JEPA/INTACT", hf_rev="paper-e5-goal-v1",
               device=device, policy="direct", policy_name=policy, runtime_kind=runtime_kind)

t0 = time.time()
rt.load()                                            # ← 断点: 模型构建 / 权重加载 / 官方 load_pretrained
print(f"\n加载完成 {time.time() - t0:.1f}s · trained={rt.trained} · dims={rt.dims}")
if rt.reason:
    print(f"reason: {rt.reason}")

if not os.path.isfile(inp):
    print("\n⚠️ 没有 reports/intact_last_input.npz → 本次只单步了 load() 路径, **没有跑 forward**。")
    print("   要跑 forward: 先 `INTACT_KEEP_INPUT=1 INTACT_POLICY=<name> gui-venv311/bin/python "
          "tools/intact_service_e2e.py` 正式跑一次, 再回来重放。")
    sys.exit(0)

print(f"\n▶ 重放真输入 → rt.act(horizon=8)   (断点: intact_worker.Runtime.act / 模型 forward)")
t1 = time.time()
r = rt.act(inp, out, 8)                              # ← 断点: 真前向 (整条模型链)
print(f"act 完成 {time.time() - t1:.1f}s · " +
      json.dumps({k: v for k, v in r.items() if isinstance(v, (int, float, str, bool, type(None)))},
                 ensure_ascii=False)[:300])
a = np.load(out)["actions"]
print(f"actions{a.shape} std={float(a.std()):.4f} 第一拍前4维={np.round(a[0][:4], 4).tolist()}")
with np.load(out) as z:
    print("潜空间键:", [k for k in ("z_t", "z_goal", "delta") if k in z.files])
print("\n✅ 模型侧单步完成 (真输入 + 真前向; 无任何写死/合成替代)")
