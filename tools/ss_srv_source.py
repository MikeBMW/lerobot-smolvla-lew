#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_srv_source.py — 真机数据源 (ROS2 服务客户端) · 只读, 绝不发控制信号

老倪 2026-09-16: 「真机数据源, 应该是一个 ROS2 的节点, 订阅 orin 上的 ROS2 数据采集服务 srv 的节点, 这样设计」

设计 (4060 侧, Orin 零程序零信号):
  · 本节点是 **服务客户端** → 调 Orin 现场的 **数据采集服务** `/hmi/snapshot`
    (`interfaces/srv/HmiSnapshot`: 响应 = success / message / **snapshot_json**)
  · snapshot_json 里若有图像 (base64) / 位姿 (tcp/pose/joints) → 解码落盘 PNG + 供 L2 YOLO 对齐输入
  · **只调查询类服务**: 绝不调用 /hmi/command, /execute_external_task, /move_*, /gripper_driver 等任何会
    让产线动作或改变状态的接口 (红线: Orin 不能发出实际信号)
  · 需要的 x86_64 类型支持由 tools/ros2_interfaces (从 Orin 只读拷贝的 .srv 源 + colcon 生成) 提供:
       source tools/ros2_interfaces/install/setup.bash

用法:
  python3 tools/ss_srv_source.py --once                 # 调一次, 打印快照结构与字段
  python3 tools/ss_srv_source.py --once --dump 3000     # 多打印一些原始 JSON
  python3 tools/ss_srv_source.py --poll 2.0 --seconds 30  # 2Hz 轮询 30s, 落盘快照 + 图像
"""
import argparse
import base64
import json
import os
import re
import time

OUT = os.environ.get("SS_SRV_OUT", os.path.expanduser("~/zmax_ss_remote"))
SNAP_TOPIC = os.environ.get("SS_SNAPSHOT_SERVICE", "/hmi/snapshot")
IMGB64_KEYS = ("image_base64", "image_b64", "image", "jpeg_base64", "jpg_base64",
               "png_base64", "camera_image", "frame_base64")
POSE_KEYS = ("tcp", "tcp_pose", "pose", "end_effector", "ee_pose", "flange")


try:
    from interfaces.srv import HmiSnapshot            # noqa
    HAVE_IFACE = True
    IFACE_ERR = ""
except Exception as _e:                               # 类型支持没编/没 source → 如实报缺
    HAVE_IFACE = False
    IFACE_ERR = f"{type(_e).__name__}: {_e}"


def _extract_image(snap):
    """从快照 JSON 里找图像: 返回 (png_path, meta) 或 (None, meta)"""
    meta = {"found": False}
    for k in IMGB64_KEYS:
        v = snap.get(k)
        if isinstance(v, str) and len(v) > 200:
            try:
                raw = base64.b64decode(v, validate=False)
            except Exception:
                continue
            ext = "jpg" if raw[:3] == b"\xff\xd8\xff" else ("png" if raw[:4] == b"\x89PNG" else "bin")
            p = os.path.join(OUT, f"srv_cam.{ext}")
            open(p, "wb").write(raw)
            meta.update({"found": True, "key": k, "bytes": len(raw), "ext": ext, "path": p})
            return p, meta
    # 有些实现把图像放在嵌套 dict
    for k, v in snap.items():
        if isinstance(v, dict):
            p, m2 = _extract_image(v)
            if m2.get("found"):
                m2["key"] = f"{k}.{m2.get('key')}"
                return p, m2
    return None, meta


def call_snapshot(timeout=6.0):
    """调一次 /hmi/snapshot (只读查询) → dict"""
    if not HAVE_IFACE:
        return {"ok": False, "reason": f"缺 interfaces 类型支持 ({IFACE_ERR}) — 先 colcon build tools/ros2_interfaces"}
    import rclpy
    from rclpy.node import Node
    rclpy.init()
    n = Node("ss_srv_source", enable_rosout=False, start_parameter_services=False)
    try:
        cli = n.create_client(HmiSnapshot, SNAP_TOPIC)
        if not cli.wait_for_service(timeout_sec=timeout):
            return {"ok": False, "reason": f"服务不可见: {SNAP_TOPIC}"}
        fut = cli.call_async(HmiSnapshot.Request())
        t0 = time.time()
        while not fut.done() and time.time() - t0 < timeout:
            rclpy.spin_once(n, timeout_sec=0.05)
        if not fut.done():
            return {"ok": False, "reason": "调用超时"}
        r = fut.result()
        sj = str(r.snapshot_json or "")
        snap = {}
        try:
            snap = json.loads(sj) if sj else {}
        except Exception as e:
            return {"ok": False, "reason": f"snapshot_json 非 JSON ({type(e).__name__})", "raw_head": sj[:400]}
        p, imeta = _extract_image(snap)
        return {"ok": True, "success": bool(r.success), "message": str(r.message)[:200],
                "keys": sorted(snap.keys()), "snapshot": snap, "image": imeta,
                "png": p, "raw_len": len(sj)}
    finally:
        n.destroy_node()
        rclpy.shutdown()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dump", type=int, default=1200)
    ap.add_argument("--poll", type=float, default=0.0, help="轮询频率 Hz")
    ap.add_argument("--seconds", type=float, default=0.0)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    if a.once or a.poll <= 0:
        r = call_snapshot()
        print(json.dumps({k: v for k, v in r.items() if k != "snapshot"}, ensure_ascii=False, indent=1))
        if r.get("ok"):
            print("快照结构:", json.dumps(r["snapshot"], ensure_ascii=False)[:a.dump])
            json.dump(r["snapshot"], open(os.path.join(OUT, "srv_snapshot.json"), "w"),
                      ensure_ascii=False, indent=1)
        return
    t0 = time.time()
    n = 0
    while True:
        if a.seconds and time.time() - t0 > a.seconds:
            break
        r = call_snapshot()
        n += 1
        rec = {"t": time.time(), "ok": r.get("ok"), "keys": r.get("keys"),
               "image": r.get("image"), "message": r.get("message"), "reason": r.get("reason")}
        with open(os.path.join(OUT, "srv_snapshot.jsonl"), "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if r.get("ok"):
            json.dump(r["snapshot"], open(os.path.join(OUT, "srv_snapshot.json"), "w"),
                      ensure_ascii=False, indent=1)
        print(f"[{n}] ok={r.get('ok')} keys={len(r.get('keys') or [])} image={bool((r.get('image') or {}).get('found'))}"
              f" {r.get('reason', '')[:60]}", flush=True)
        time.sleep(max(0.0, 1.0 / a.poll))
    print(f"完成 {n} 次轮询")


if __name__ == "__main__":
    main()
