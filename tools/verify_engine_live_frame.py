#!/usr/bin/env python3
"""验证「仿真输入图像 与 ▶运行 同步」修复 (2026-09-17)

老倪问: 点了运行, 仿真渲染的图像不动, 应该实时同步。
根因: 窗口仿真源渲染的是 node_logic._YOLO_ALIGNER.env (只 reset、从不 step) → 永远同一帧。
修法: 引擎 RealStateSpaceSim 每步真渲染的帧挂到进程共享槽 SS_LIVE_FRAME, 窗口优先显示它。

本脚本查 (全部用磁盘上真实代码):
  ① 引擎 _render_frame 真渲染 → 发布到槽 + 落盘 /tmp/ss_live_frame.json (含 step)
  ② env.step 推进后, 发布的帧**逐帧在变** (证明"跟着运行动", 不是同一张)
  ③ 读取端: 帧太旧 (引擎停了) → 返回 None (窗口不许假动)
  ④ 窗口取帧 _SimGrabber._grab_once: 有实况 → 用实况帧并标 engine=True; 无实况且无 node_logic
     → 返回 None (退回静态分支, 由 run() 兜底)

跑法: cd /home/ubuntu/lerobot-smolvla-lew && DISPLAY=:0 gui-venv311/bin/python tools/verify_engine_live_frame.py
"""
import os
import queue
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(HERE, "gui"))

import numpy as np                                       # noqa: E402
import state_space_sim_real as ssr                       # noqa: E402
import yolo_input_viewer as yiv                          # noqa: E402

ok = True


def check(name, cond, extra=""):
    global ok
    ok &= bool(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {extra}")


class EngineStub:
    """只提供 _render_frame 需要的 env/_live_step; 方法体是**磁盘上真实代码**"""
    _render_frame = ssr.RealStateSpaceSim._render_frame

    def __init__(self, env):
        self.env = env
        self._live_step = None
        self._live_tag = "verify"


print("── ① 引擎渲染 → 发布实况帧 ──")
env = ssr._make_env()
env.reset()                                              # _make_env 只建 env, 推进前必须 reset
stub = EngineStub(env)
frames = []
for k in range(4):
    stub._live_step = k
    # 真物理推进 (末端小幅正弦 + 夹爪闭合): 场景**每步都在变** — 正是窗口该跟着动的证据
    act = np.array([0.02 if k % 2 == 0 else -0.02, 0.0,
                    -0.02 if k % 2 == 0 else 0.02, 0.6])
    env.step(act)
    frames.append(stub._render_frame())
    time.sleep(0.05)

S = ssr.SS_LIVE_FRAME
check("渲染帧已挂槽", S.get("rgb") is not None and S.get("step") == 3,
      f"step={S.get('step')} shape={np.asarray(S['rgb']).shape}")
check("落盘 /tmp/ss_live_frame.json 已生成", os.path.isfile(ssr.SS_LIVE_STATUS),
      f"{ssr.SS_LIVE_STATUS}")
import json                                              # noqa: E402
_j0 = json.load(open(ssr.SS_LIVE_STATUS)) if os.path.isfile(ssr.SS_LIVE_STATUS) else {}
check("落盘内容带引擎步号 (1Hz 节流: 首次=step0 属正常)", isinstance(_j0.get("step"), int),
      f"首次落盘 {_j0}")
time.sleep(1.2)                                          # 节流窗口过后再发布一帧 → 文件必须刷新
stub._live_step = 99
stub._render_frame()
_j1 = json.load(open(ssr.SS_LIVE_STATUS))
check("节流窗口外 → 落盘步号刷新到最新", _j1.get("step") == 99, f"刷新后 {_j1}")

print("\n── ② 帧随 env.step 变化 (老倪要的'实时动') ──")
diffs = [float(np.abs(frames[i].astype(np.int16) - frames[i + 1].astype(np.int16)).mean())
         for i in range(len(frames) - 1)]
check("相邻步渲染帧不同", all(d > 0.0 for d in diffs), f"逐帧平均差={[round(d, 3) for d in diffs]}")

print("\n── ③ 读取端新鲜度 (引擎停了不许假动) ──")
_live = ssr.ss_latest_live_frame(max_age=2.0)
check("新鲜帧可取到", _live is not None and _live[1] == 99, f"step={None if _live is None else _live[1]}")
_t_bak = S["t"]
S["t"] = time.time() - 30.0
check("30s 前的旧帧 → None", ssr.ss_latest_live_frame(max_age=2.0) is None)
S["t"] = _t_bak

print("\n── ④ 窗口取帧走实况分支 ──")
g = yiv._SimGrabber(queue.Queue(maxsize=4), False)
img, info = g._grab_once(None)
check("有实况 → 用引擎帧 + engine=True",
      img is not None and info.get("engine") is True and info.get("step") == 99,
      f"src={info.get('src')} / {info.get('device')}")
S["rgb"], S["t"] = None, 0.0                             # 模拟引擎停止
img2, info2 = g._grab_once(None)
check("无实况 且 无 node_logic → 返回 None (run() 走静态兜底)", img2 is None and info2 is None)

print("\n── ⑤ 窗口消费计数 (外部可核对) ──")
c0 = int(S.get("consumed") or 0)
ssr.ss_mark_live_frame_consumed()
ssr.ss_mark_live_frame_consumed()
check("viewer_consumed 递增", int(S.get("consumed") or 0) == c0 + 2, f"{c0} → {S.get('consumed')}")

print("\n── ⑥ R0/非视觉档: 有窗口在看才节流渲染 (没人看=零开销) ──")
ssr.ss_set_viewer_wants(True)
_renders = [s for s in range(12) if ssr.ss_should_render_for_viewer(s, False)]
check("want=True 且非视觉档 → 每 5 步渲染一次", _renders == [0, 5, 10], str(_renders))
check("视觉档 → 不再额外渲染 (引擎每步已渲染)",
      not any(ssr.ss_should_render_for_viewer(s, True) for s in range(12)))
ssr.ss_set_viewer_wants(False)
check("没窗口在看 → 一律不渲染 (老倪不看就不耗)",
      not any(ssr.ss_should_render_for_viewer(s, False) for s in range(12)))
yiv._engine_viewer_wants(True)
check("窗口侧开/关直通引擎槽", ssr.SS_LIVE_FRAME.get("want") is True)
yiv._engine_viewer_wants(False)
check("窗口侧关闭也直通", ssr.SS_LIVE_FRAME.get("want") is False)

print("\n总判定:", "全绿 ✅" if ok else "有失败 ❌")
sys.exit(0 if ok else 1)
