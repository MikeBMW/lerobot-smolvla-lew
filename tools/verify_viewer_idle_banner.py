#!/usr/bin/env python3
"""验证: 引擎未运行时的"静态初始帧"必须被压上横幅提示 (老倪两次误读成"光模块没插进槽")

① 无引擎 + 仿真源 → 落到 idle 渲染帧, 画面顶部要有横幅 (压暗 + 橙字), info.engine=False
② 有引擎实况帧 → 原样显示, **不许**加横幅, info.engine=True
跑法: gui-venv311/bin/python tools/verify_viewer_idle_banner.py
"""
import os
import queue
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("DISPLAY", ":0")
sys.path.insert(0, os.path.join(HERE, "gui"))

import numpy as np                                       # noqa: E402
import state_space_sim_real as ssr                       # noqa: E402
import yolo_input_viewer as yiv                          # noqa: E402

ok = True


def check(name, cond, extra=""):
    global ok
    ok &= bool(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {extra}")


class FakeEnv:
    def render(self):
        return np.full((480, 480, 3), 190, np.uint8)     # 纯灰, 便于判横幅


class FakeNL:
    def _yolo_ensure_aligner(self, log):
        class _Al:
            env = FakeEnv()
            model = None
        return _Al()


ssr.SS_LIVE_FRAME.update({"rgb": None, "t": 0.0, "step": None})   # 模拟引擎没在跑
g = yiv._SimGrabber(queue.Queue(maxsize=2), False)

print("── ① 无引擎 → idle 帧必须带横幅 ──")
img, info = g._grab_once(FakeNL())
band = int(img.shape[0] * 0.075)
top, mid = float(img[:band].mean()), float(img[band + 20:].mean())
check("走了 idle 分支", info is not None and info.get("engine") is False, f"src={info.get('src')}")
check("顶部横幅把画面压暗了", top < mid * 0.6, f"顶部均值={top:.1f} vs 其余={mid:.1f}")
check("画面里有橙色字像素", int(((img[:band, :, 0].astype(int) - img[:band, :, 2].astype(int)) > 60).sum()) > 30)

print("\n── ② 有引擎实况帧 → 原样显示, 不加横幅 ──")
live = np.full((480, 480, 3), 77, np.uint8)
ssr.ss_publish_live_frame(live, step=123, tag="verify")
img2, info2 = g._grab_once(FakeNL())
check("走了引擎实况分支", info2.get("engine") is True and info2.get("step") == 123, f"step={info2.get('step')}")
check("实况帧原样上屏 (无横幅, 字节一致)",
      img2.shape == live.shape and np.array_equal(np.asarray(img2), live),
      f"顶部均值={float(img2[:band].mean()):.1f}")

print("\n── ③ 引擎停了 (帧过期) → 回到横幅状态 ──")
ssr.SS_LIVE_FRAME["t"] = 0.0
img3, info3 = g._grab_once(FakeNL())
check("过期实况帧不算数", info3.get("engine") is False)
check("回到带横幅的 idle 帧", float(img3[:band].mean()) < float(img3[band + 20:].mean()) * 0.6)

print("\n总判定:", "全绿 ✅" if ok else "有失败 ❌")
sys.exit(0 if ok else 1)
