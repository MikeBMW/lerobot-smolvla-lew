#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_frame_srv_client.py — 4060 侧 ROS2 服务客户端: 拉 Orin 真机图像帧并落盘

老倪 2026-09-17: 「4060 上的视频流窗口, 要从本地 docker 的 ros2 节点获取图像, 显示原始视频流」

位置: 跑在**本机 Docker 容器** (ros:humble-ros-base --net host, ROS_DOMAIN_ID=0) 里 —— 因为
      gui-venv311 没有 rclpy; 容器是唯一能调 ROS2 服务的运行环境 (与 ss_remote_tap 同一套路)。
链路: 容器 → 调 Orin 的 `/zmax/live_frame` (tools/orin_frame_srv.py, JPEG 压缩在服务端)
      → 解 base64 → 落 `$SS_OUT/live_frame.png` + `$SS_OUT/live_frame.json` (meta)
      → 控制台右键「打开输入图像」窗口轮询这两个文件显示 (GUI 无需 rclpy)。

不冒充新鲜帧: json 里写 ts/age/seq/src/device/fps; 落盘用**原子替换** (tmp→rename), 读端按
age 判定是否过期 (过期显示 "⚠️ 无新帧" 而不是拿旧图当实时)。

用法 (容器内):
  python3 ss_frame_srv_client.py --out /out --rate 10 --seconds 0
  0 = 常驻直到收到 SIGTERM (由控制台窗口关闭时 kill)
"""
import argparse
import base64
import json
import os
import sys
import time

import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--service", default="/zmax/live_frame")
    ap.add_argument("--out", default=os.environ.get("SS_OUT", "/out"))
    ap.add_argument("--rate", type=float, default=10.0)
    ap.add_argument("--seconds", type=float, default=0.0, help="0=常驻")
    ap.add_argument("--stale-s", type=float, default=5.0, help="服务端帧超过这么久没更新 → 记 stale")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    jpg = os.path.join(a.out, "live_frame.jpg")
    png = os.path.join(a.out, "live_frame.png")
    meta_p = os.path.join(a.out, "live_frame.json")

    import rclpy
    from rclpy.node import Node
    from interfaces.srv import HmiSnapshot

    rclpy.init()
    node = Node("ss_frame_srv_client", enable_rosout=False, start_parameter_services=False)
    cli = node.create_client(HmiSnapshot, a.service)
    if not cli.wait_for_service(timeout_sec=8.0):
        print(f"❌ 服务 {a.service} 不存在 (Orin 侧节点没起?) → 退出", flush=True)
        json.dump({"ok": False, "reason": f"服务 {a.service} 不可达", "ts": time.time()},
                  open(meta_p + ".tmp", "w"))
        os.replace(meta_p + ".tmp", meta_p)
        node.destroy_node()
        rclpy.shutdown()
        return 2
    print(f"[srv-client] 已连上 {a.service} · 落盘 {png} / {meta_p} · {a.rate}Hz", flush=True)

    t0 = time.time()
    n_ok = n_fail = 0
    fps_t, fps_n = time.time(), 0
    try:
        while rclpy.ok():
            if a.seconds and time.time() - t0 > a.seconds:
                break
            fut = cli.call_async(HmiSnapshot.Request())
            rclpy.spin_until_future_complete(node, fut, timeout_sec=3.0)
            r = fut.result() if fut.done() else None
            now = time.time()
            if r is None or not bool(r.success):
                n_fail += 1
                reason = (r.message if r is not None else "调用超时 (服务端无响应)")
                if n_fail <= 3 or n_fail % 50 == 0:
                    print(f"⚠️ 取帧失败 #{n_fail}: {reason}", flush=True)
            else:
                try:
                    d = json.loads(str(r.snapshot_json))
                    jb = base64.b64decode(d.get("jpeg_b64") or "")
                    if not jb:
                        raise ValueError("jpeg 为空 (服务端还没采到帧)")
                    # 🐛 2026-09-17: 容器 (ros:humble-ros-base) 没有 cv2 → 不做解码,
                    #   直接把服务端压缩好的 JPEG **原样落盘** (Qt/PIL 都能直接读),
                    #   有 cv2 时额外再落一份 PNG 给别的消费端 (旁路面板等)。
                    # 原子落盘: 先写 tmp 再 rename (读端永不读到半个文件)
                    with open(jpg + ".tmp", "wb") as f:
                        f.write(jb)
                    os.replace(jpg + ".tmp", jpg)
                    n_png = 0
                    try:
                        import cv2                                                      # noqa: PLC0415
                        img = cv2.imdecode(np.frombuffer(jb, np.uint8), cv2.IMREAD_COLOR)
                        if img is not None:
                            cv2.imwrite(png + ".tmp.png", img)
                            os.replace(png + ".tmp.png", png)
                            n_png = 1
                    except Exception:                                                   # noqa: BLE001
                        n_png = 0
                    age = now - float(d.get("ts", now))
                    meta = {"ok": True, "ts": now, "frame_ts": d.get("ts"), "age_s": round(age, 3),
                            "seq": d.get("seq"), "src": d.get("src"), "device": d.get("device"),
                            "w": d.get("w"), "h": d.get("h"), "server": d.get("server"),
                            "encode_ms": d.get("encode_ms"), "quality": d.get("quality"),
                            "server_fps": d.get("fps"), "jpeg_bytes": len(jb), "png": bool(n_png),
                            "jpeg_path": jpg, "stale": bool(age > a.stale_s)}
                    json.dump(meta, open(meta_p + ".tmp", "w"), ensure_ascii=False)
                    os.replace(meta_p + ".tmp", meta_p)
                    n_ok += 1
                    fps_n += 1
                except Exception as e:                                     # noqa: BLE001
                    n_fail += 1
                    if n_fail <= 3:
                        print(f"⚠️ 解帧失败: {type(e).__name__}: {e}", flush=True)
            if time.time() - fps_t >= 2.0:
                if fps_n:
                    print(f"[srv-client] {fps_n/ (time.time()-fps_t):.1f} Hz · 成功 {n_ok} 失败 {n_fail}",
                          flush=True)
                fps_t, fps_n = time.time(), 0
            dt = 1.0 / max(0.5, a.rate) - 0.0
            time.sleep(max(0.0, dt - (time.time() - now)))
    except KeyboardInterrupt:
        pass
    finally:
        json.dump({"ok": False, "reason": "客户端已停止", "ts": time.time()},
                  open(meta_p + ".tmp", "w"), ensure_ascii=False)
        os.replace(meta_p + ".tmp", meta_p)
        try:
            node.destroy_node()
            rclpy.shutdown()
        except Exception:                                                  # noqa: BLE001
            pass
    print(f"[srv-client] 结束: 成功 {n_ok} · 失败 {n_fail}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
