#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
live_trace_publisher.py — 把**真机实测轨迹**(base 系 TCP 折线)持续叠到臂上相机画面上
────────────────────────────────────────────────────────────
老倪 2026-09-29: 「我要开始移动机器人手臂，你要实时显示3D边界框，实时规划轨迹。实时感知和规划结果
                  要叠加到手臂相机的场景。」

数据链(每一环都是真的, 无编造):
  domain0 真机话题(/robot/joint_states + /robot/tcp_pose, BEST_EFFORT)
      → 容器内 live_motion_recorder.py 落 /tmp/live_trace.json(base 系 TCP 点)
      → 本工具每 ~1.5s `docker cp` 出来, 按**空间间隔抽稀**(>2mm 才留)后 merge 进
        data/scene/overlay_spec.json 的 cameras.arm, origin=`trace`(kind=path3d)
      → 8791 推流服务每帧投影 ⇒ 画面上的黄线 = 真机走过的路
注意: 点是 **base 系** ⇒ 用当前 TCP 投影是对的(和静态物体一样, 相机动了它在画面里的位置跟着变),
      这就是"轨迹留在空间里"的视角。

用法: gui-venv311/bin/python tools/live_trace_publisher.py --loop --every 1.5 --max-pts 1500
      (--once 只跑一轮; --clear 清掉 trace 层)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
import scene_overlay as SO                                                      # noqa: E402
import traj_display as TD                                                       # noqa: E402  (显示开关单一真源)

CONTAINER = os.environ.get("TRACE_CONTAINER", "ss-remote-tap")
IN_CONTAINER = os.environ.get("TRACE_PATH", "/tmp/live_trace.json")
LOCAL = os.path.join(_REPO, "reports", "moveit", "live_trace.json")
CAM = os.environ.get("TRACE_CAM", "arm")
ORIGIN = "trace"
LABEL = "实测轨迹·真机TCP"


def fetch(retries: int = 3) -> dict | None:
    """从容器里拷出轨迹文件(docker cp 到仓库 reports/moveit/ 下, 便于事后取证)。

    实测坑: 生产者写盘与 docker cp 撞上时会拷到**半截文件** ⇒ json 解析报
    `Expecting value: line 1 column 1 (char 0)`。这里重试 + 生产者已改原子落盘, 两头都堵。
    """
    os.makedirs(os.path.dirname(LOCAL), exist_ok=True)
    last = ""
    for i in range(max(1, retries)):
        r = subprocess.run(["sudo", "docker", "cp", "%s:%s" % (CONTAINER, IN_CONTAINER), LOCAL],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            last = (r.stderr or "").strip()[:200]
        else:
            try:
                return json.load(open(LOCAL, encoding="utf-8"))
            except Exception as e:                                             # noqa: BLE001
                last = str(e)
        if i < retries - 1:
            time.sleep(0.25)
    print("  fetch 失败(重试 %d 次): %s" % (retries, last), flush=True)
    return None


def decimate(pts, min_gap_mm=2.0, max_pts=1500):
    """按空间间隔抽稀: 相邻点 < min_gap 就丢(去掉抖动), 超过 max_pts 再等距抽。"""
    out = []
    for p in pts:
        if len(p) < 3:
            continue
        q = [float(p[0]), float(p[1]), float(p[2])]
        if out:
            d = math.dist(q, out[-1]) * 1000.0
            if d < min_gap_mm:
                continue
        out.append(q)
    if len(out) > max_pts:
        step = len(out) / float(max_pts)
        out = [out[int(i * step)] for i in range(max_pts)]
    return out


def publish(pts, clear=False):
    spec = SO.load_spec()
    cam = spec.setdefault("cameras", {}).setdefault(CAM, {})
    if clear or not pts:
        # 清层: 过滤 boxes + 清 by_origin + 落 deleted(见技能: merge_origin([]) 是空操作)
        # 只清"轨迹路径"这一条, **保留**同 origin 的参考点标记(P1/P2/... —— marker 写的),
        # 否则每 2s 重发布一次就会把参考点刷掉/来回闪(实测踩到)
        def _is_path(b):
            return str(b.get("origin")) == ORIGIN and str(b.get("label") or "").startswith("实测轨迹")
        cam["boxes"] = [b for b in cam.get("boxes", []) if not _is_path(b)]
        cam.get("by_origin", {}).pop(ORIGIN, None)
        SO.save_spec(spec)
        return 0
    el = {"origin": ORIGIN, "label": "%s(%d点)" % (LABEL, len(pts)),
          "kind": "path3d", "pts3d": pts, "width": 4, "no_label": True, "conf": 1.0}
    SO.merge_origin(spec, CAM, ORIGIN, [el])
    SO.save_spec(spec)
    return len(pts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--every", type=float, default=1.5)
    ap.add_argument("--max-pts", type=int, default=1500)
    ap.add_argument("--gap-mm", type=float, default=2.0)
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--seconds", type=float, default=5400)
    ap.add_argument("--stale-s", type=float, default=120.0,
                    help="轨迹源(容器内 /tmp/live_trace.json)超过这么多秒没更新 ⇒ 判为停摆, "
                         "把画面上的轨迹撤掉(不然会一直画着一条冻结的旧轨迹, 看着像实时的)")
    a = ap.parse_args()

    if a.clear:
        publish([], clear=True)
        print("已清 trace 层")
        return 0

    t0 = time.time()
    said_off = False
    while True:
        st = TD.get_state()
        # 🔴 默认不显示: 人工开启前一律把 trace/plan 折线撤掉(规格里不留, 画面干净)
        if not st["show"]:
            if not said_off:
                publish([], clear=True)
                print("[%s] 轨迹显示=关 (默认) ⇒ 已撤掉画面上的轨迹线; 需要时点页面的『显示轨迹』" % (
                    time.strftime("%H:%M:%S")), flush=True)
                said_off = True
            else:
                publish([], clear=True)
        else:
            said_off = False
            if st["plan_hidden"]:                       # 自愈: 开关开着但航路还没恢复 ⇒ 恢复
                TD.restore_origins(["plan"])
                TD.set_state(plan_hidden=False)
            # 🔴 停摆守卫: 录制器死了但主机上留着旧副本时, fetch 照样"成功" ⇒ 画面会一直重画那条
            #    冻结的旧轨迹(老倪现场: 链停了 8 小时, 页面上还写着"已录 26479 点")。这里按**文件龄**判停摆。
            _age = None
            try:
                _age = time.time() - os.path.getmtime(LOCAL)
            except Exception:                                                      # noqa: BLE001
                pass
            if _age is not None and _age > a.stale_s:
                publish([], clear=True)
                if int(time.time()) % 30 < 3:                 # 别刷屏
                    print("[%s] ⚠️ 轨迹源已停 %.1f 分钟 ⇒ 已撤掉画面上的轨迹(等录制器回来)" % (
                        time.strftime("%H:%M:%S"), _age / 60.0), flush=True)
                if a.once or not a.loop or time.time() - t0 > a.seconds:
                    break
                time.sleep(a.every)
                continue
            d = fetch()
            if d and d.get("pts"):
                base = int(st["baseline_n"] or 0)
                raw = d["pts"]
                if base > 0:
                    raw = raw[base:] if base < len(raw) else raw[-1:]
                pts = decimate(raw, a.gap_mm, a.max_pts)
                n = publish(pts)
                print("[%s] 轨迹 %d 点(原始 %d, 清除线 %d, 抽稀后 %d) → cameras.%s origin=%s" % (
                    time.strftime("%H:%M:%S"), n, len(d["pts"]), base, n, CAM, ORIGIN), flush=True)
            else:
                print("[%s] 还没有轨迹数据(录制器起了吗? /tmp/live_trace.json)" % time.strftime("%H:%M:%S"),
                      flush=True)
        if a.once or not a.loop or time.time() - t0 > a.seconds:
            break
        time.sleep(a.every)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
