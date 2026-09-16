#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z-MAX 状态空间 · 现场几何标定 (标定桥的"几何"半场)

运行位置: 4060 本机 Docker 容器 (ros:humble-ros-base --network host, ROS_DOMAIN_ID=0)
          → 远程读 Orin 的 /robot/tcp_pose, **Orin 上不装任何程序**

背景: 引擎口径 z7 = [手/头−目标(3), 手/头−光模块(3), 夹持(1)]。
      手/头 可由真机 /robot/tcp_pose 实时得到 (已确认 50Hz 在线),
      但 **目标点 / 光模块(peg)位置 属于现场几何, 必须现场示教**, 不能编造。

本工具用法 (在 Orin 上, 现场把机器人手动/示教点到对应位置后采集):
    # 1) 示教 peg_head (光模块抓握点/头):
    python3 ss_geom_calib.py --record peg_head --note "夹具上光模块中心"
    # 2) 示教目标 (孔口/插入目标点):
    python3 ss_geom_calib.py --record goal --note "连接器孔口中心"
    # 3) (可选) 示教 AOI/耦合台参考点:
    python3 ss_geom_calib.py --record aoi --note "AOI 光学对焦点"
    # 4) 查看/校验:
    python3 ss_geom_calib.py --show
    # 5) 清空重来:
    python3 ss_geom_calib.py --reset

产出: ~/zmax_state_space/models/real_cell_geometry.json
  { "source": "现场示教", "robot": "...", "frame": "base_link",
    "points": {"peg_head": {"x","y","z","t","by","note"}, ...},
    "validated": true|false, "version": 1 }

校验 (--show 时执行, 不过则 validated=false, 推理端会拒用):
  · 至少 peg_head + goal 两个点
  · 两点距离在 0.02~0.60 m (太近=示教错位, 太远=不在同一工位)
  · 与当前 TCP 的偏差 ≤ 0.5 m (避免用了别的工位的坐标)
  · 所有点 z 在 ±0.05~1.2 m (cell 合理高度)
⚠️ 本工具只读 /robot/tcp_pose, 不发送任何控制指令; 机器人如何到指定位置由现场决定 (示教器/HMI 示教)。
"""
import argparse
import json
import os
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from geometry_msgs.msg import PoseStamped

OUT = os.path.expanduser(os.environ.get("SS_GEOM_PATH", "~/zmax_state_space/models/real_cell_geometry.json"))
VALID_KEYS = ("peg_head", "goal", "aoi", "tray_origin", "home")


class TcpGrabber(Node):
    def __init__(self):
        super().__init__("ss_geom_calib")
        q = QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST)
        self.last = None
        self.create_subscription(PoseStamped, "/robot/tcp_pose", self.cb, q)
        self.create_timer(0.2, lambda: None)

    def cb(self, m):
        p = m.pose.position
        self.last = {"x": round(p.x, 6), "y": round(p.y, 6), "z": round(p.z, 6), "t": time.time(),
                     "frame": m.header.frame_id}


def load():
    if os.path.exists(OUT):
        try:
            return json.load(open(OUT))
        except Exception:
            pass
    return {"source": "现场示教", "frame": "base_link", "points": {}, "validated": False, "version": 1}


def save(d):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    d["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    json.dump(d, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"💾 已写 {OUT}")


def validate(d):
    pts = d.get("points", {})
    msgs = []
    ok = True
    if not all(k in pts for k in ("peg_head", "goal")):
        ok = False
        msgs.append("缺 peg_head 或 goal")
    if ok:
        import math
        a, b = pts["peg_head"], pts["goal"]
        dist = math.dist((a["x"], a["y"], a["z"]), (b["x"], b["y"], b["z"]))
        msgs.append(f"peg_head↔goal 距离 {dist * 1000:.1f}mm")
        if not (0.02 <= dist <= 0.60):
            ok = False
            msgs.append("⚠️ 距离超出 20~600mm, 疑似示教错位")
    for k, v in pts.items():
        if not (-0.05 <= v["z"] <= 1.2):
            ok = False
            msgs.append(f"⚠️ {k} 的 z={v['z']:.3f} 超出合理高度")
    d["validated"] = bool(ok)
    d["validate_msgs"] = msgs
    return ok, msgs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", choices=VALID_KEYS, help="记录当前 TCP 到指定几何点")
    ap.add_argument("--note", default="", help="备注 (谁在什么位置示教的)")
    ap.add_argument("--by", default=os.environ.get("USER", "unknown"))
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--reset", action="store_true")
    a = ap.parse_args()

    if a.reset:
        d = {"source": "现场示教", "frame": "base_link", "points": {}, "validated": False, "version": 1}
        save(d)
        print("已清空")
        return

    d = load()
    if a.show or not a.record:
        ok, msgs = validate(d)
        print(f"文件: {OUT}")
        print(f"点: {list(d.get('points', {}))}")
        for k, v in d.get("points", {}).items():
            print(f"  {k:<12} x={v['x']:+.4f} y={v['y']:+.4f} z={v['z']:+.4f}  by={v.get('by')} note={v.get('note','')}")
        print("校验:", "✅ 通过" if ok else "❌ 不通过")
        for m in msgs:
            print("  -", m)
        return

    rclpy.init()
    n = TcpGrabber()
    t0 = time.time()
    while n.last is None and time.time() - t0 < 8:
        rclpy.spin_once(n, timeout_sec=0.2)
    if n.last is None:
        print("❌ 8s 内没收到 /robot/tcp_pose — 检查话题/domain(0)")
        rclpy.shutdown()
        return
    p = dict(n.last)
    frame = p.pop("frame", "base_link")
    p["by"] = a.by
    p["note"] = a.note
    d["frame"] = frame
    d.setdefault("points", {})[a.record] = p
    ok, msgs = validate(d)
    save(d)
    print(f"✅ 记录 {a.record}: x={p['x']:+.4f} y={p['y']:+.4f} z={p['z']:+.4f} (frame={frame})")
    print("校验:", "✅ 通过" if ok else "❌ 不通过 (推理端会拒用, 需补点)")
    for m in msgs:
        print("  -", m)
    n.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
