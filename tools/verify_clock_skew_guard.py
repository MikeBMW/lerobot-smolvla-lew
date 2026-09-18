#!/usr/bin/env python3
"""验证「时钟回拨 (NTP 把系统钟回拨 8h) 不再让真机画面冒充实时」的守门逻辑 (2026-09-18 事故回归测试)

事故: 12:15 本机 NTP 把系统钟回拨 8h →
  ① Docker tap 采样/解码节拍用 time.time() 差值 → 恒假/恒真 → 图像冻在最后一帧 (13 分钟)
  ② GUI 判新鲜度 = now - mtime, mtime 在未来 → age 为负 ≤ 阈值 → **旧帧被判成新鲜帧**
     (老倪红线: 绝不拿旧图冒充实时)

本脚本只测**守门判据** (不启 GUI 窗口, offscreen):
  ① 未来 mtime (age<0) → 必须**拒用** (返回 None) 且状态里如实标"时钟异常"
  ② 正常新鲜帧 (age≈1s) → 必须入选
  ③ 旧帧 (age≈60s > 阈值 10s) → 必须拒用
  ④ 真实现场 SHARED 里的 cam_rs.png → 现在应是新鲜的 (链路健康自证)

跑法: cd /home/ubuntu/lerobot-smolvla-lew && gui-venv311/bin/python tools/verify_clock_skew_guard.py
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "gui"))

import yolo_input_viewer as yiv  # noqa: E402

ok = True


class Stub:
    """只带 _pick_real_file 需要的字段 (不建 QWidget)"""

    def __init__(self):
        self._real_cand_status = []


def run_pick(shared, name="cam_rs.png", fresh_s=10.0):
    yiv.SHARED = shared
    yiv.REAL_FILE_CANDS = ((name, "测试源"),)
    st = Stub()
    got = yiv.YoloInputViewer._pick_real_file(st, fresh_s)
    return got, st._real_cand_status


def case(title, mtime_delta, want_selected, want_note=None):
    global ok
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "cam_rs.png")
        with open(p, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
        os.utime(p, (time.time() + mtime_delta, time.time() + mtime_delta))
        got, status = run_pick(d)
        sel = got is not None
        good = (sel == want_selected) and (want_note is None or any(want_note in s for s in status))
        ok &= good
        print(f"  [{'PASS' if good else 'FAIL'}] {title} → 选中={sel} (期望={want_selected}) 状态={status}")


print("── ①/③ 守门判据 (临时目录) ──")
case("未来 8h 的 mtime (时钟回拨场景) → 拒用", 8 * 3600, False, "时钟异常")
case("未来 30s 的 mtime (轻微超前一秒级) → 拒用", 30, False, "时钟异常")
case("新鲜帧 age≈1s → 入选", -1, True)
case("旧帧 age≈60s → 拒用", -60, False, "旧帧")

print("── ④ 现场链路自证 (真 SHARED 目录) ──")
yiv.SHARED = yiv.SHARED  # 恢复 (上面 case 里已改回? 下面显式复原)
import importlib  # noqa: E402
importlib.reload(yiv)   # 复原模块级常量 = 出厂值
st = Stub()
got = yiv.YoloInputViewer._pick_real_file(st, 10.0)
if got is None:
    ok = False
    print(f"  [FAIL] 现场无新鲜真机帧 (链路未恢复?) 状态={st._real_cand_status}")
else:
    p, label, age = got
    print(f"  [PASS] 现场真机帧 {os.path.basename(p)} · {label} · 帧龄 {age:.1f}s (阈值 10s) 状态={st._real_cand_status}")

print("\n结果:", "全绿 ✅" if ok else "有 FAIL ❌")
sys.exit(0 if ok else 1)
