#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""orin_frame_srv.py — Orin 侧「真机图像 → ROS2 服务」转发节点 (视频压缩在服务端做)

老倪 2026-09-17: 「4060 上的视频流窗口, 要从本地 docker 的 ros2 节点获取图像, 显示原始视频流。
orin 上传的视频流, 你来在 ROS2 srv 节点做视频压缩处理」

为什么必须有这个节点 (现场核查结论, 别绕):
  · `/realsense/*` **Publisher=0** (Orin 未装 realsense2_camera 驱动) → ROS 话题拿不到相机帧;
  · 全部现场 srv 里**没有任何一个返回图像** (实测: /hmi/snapshot 的 snapshot_json image=found:false;
    VisionServer 只返回 grasp_pose; grep "image|uint8[]" 在 18 个 .srv 里 0 命中);
  · D405 唯一能拿像素的路 = **UVC 直读** (`/dev/video2|4`, 内核驱动, 零安装) —— 实测 8/10 帧 sha 不同。
  ⇒ 于是本节点: 取帧(UVC 优先, 若 ROS 话题真有发布者则优先用话题) → **JPEG 压缩** → 用 ROS2 服务对外提供。
    压缩在服务端做 (老倪要求), 客户端只拿 JPEG 字节。

服务接口 (类型复用现场 `interfaces/srv/HmiSnapshot`, 免在 Orin 上编译自定义 .srv):
  服务名: /zmax/live_frame   (与现场 /hmi/* 无冲突; 只读提供图像, 不发布任何话题/不碰控制接口)
  响应: success=True · message="jpeg" · snapshot_json = JSON:
        {seq, ts, ts_iso, src, device, w, h, jpeg_b64, encode_ms, fps, quality}

纪律 (Orin 生产设备红线):
  · **临时进程**: 由 4060 控制台按需拉起; 无客户端调用超过 --idle-seconds (默认 20s) 或超过
    --max-seconds (默认 900s) 自动退出; **绝不自启/不常驻/不写 systemd**。
  · 只读相机与只读话题; 不创建任何 publisher; 不动 /hmi/command 等会动作的接口。
  · 启动打印设备身份 (sysfs VID:PID/序列号) → 客户端界面能显示"这确实是那台 D405"。

用法 (在 Orin 上, 由 4060 侧 ssh 拉起):
  python3 orin_frame_srv.py --device 2 --quality 70 --fps 10
"""
import argparse
import base64
import glob
import json
import os
import subprocess
import sys
import threading
import time

import numpy as np

INTERFACES_HINT = "/home/tashan/0810/*/install/interfaces/local/lib/python3.10/dist-packages"


def _ensure_interfaces_importable():
    """现场 `interfaces` 包可能没进 PYTHONPATH (未 source 工作区) → 直接补路径"""
    try:
        import interfaces  # noqa: F401
        return True
    except Exception:                                                      # noqa: BLE001
        pass
    for p in glob.glob(INTERFACES_HINT):
        if os.path.isdir(p) and p not in sys.path:
            sys.path.append(p)
    try:
        import interfaces  # noqa: F401
        return True
    except Exception as e:                                                 # noqa: BLE001
        print(f"❌ 无法 import interfaces (现场接口包): {type(e).__name__}: {e}", file=sys.stderr)
        print(f"   提示: source /home/tashan/0810/<项目>/install/setup.bash 后再跑; 或检查 {INTERFACES_HINT}",
              file=sys.stderr)
        return False


def device_identity(dev: int) -> dict:
    info = {}
    try:
        info["kernel_name"] = open(f"/sys/class/video4linux/video{dev}/name").read().strip()
    except Exception:                                                      # noqa: BLE001
        info["kernel_name"] = "?"
    cur = os.path.realpath(f"/sys/class/video4linux/video{dev}")
    for _ in range(12):
        up = os.path.dirname(cur)
        if up in ("", "/"):
            break
        cur = up
        if os.path.isfile(os.path.join(cur, "idVendor")):
            for k in ("idVendor", "idProduct", "serial", "product"):
                f = os.path.join(cur, k)
                if os.path.isfile(f):
                    try:
                        info[k] = open(f).read().strip()
                    except Exception:                                      # noqa: BLE001
                        pass
            break
    return info


class Grabber:
    """取帧 + JPEG 压缩 (压缩在服务端做)。优先 ROS 图像话题 (真有发布者时), 否则 UVC 直读。"""

    def __init__(self, device: int, w: int, h: int, fps: float, quality: int, topic: str):
        self.quality = quality
        self.period = 1.0 / max(1.0, fps)
        self.lock = threading.Lock()
        self.jpeg = None
        self.meta = {}
        self.n = 0
        self._stop = False
        self.mode = "uvc"
        self.cap = None
        self.ros_img = None
        self.topic = topic
        # ① 先看 ROS 话题有没有真发布者 (驱动装好 + 产线在跑时优先走它, 口径与生产一致)
        if topic and self._topic_has_publisher(topic):
            try:
                self._start_ros_sub(topic)
                self.mode = f"ros:{topic}"
            except Exception as e:                                         # noqa: BLE001
                print(f"⚠️ ROS 话题 {topic} 订阅失败 ({type(e).__name__}: {e}) → 退回 UVC", flush=True)
        if self.mode == "uvc":
            import cv2
            self.cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
            if not self.cap.isOpened():
                raise RuntimeError(f"/dev/video{device} 打不开 (被占用?)")
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            self.cap.set(cv2.CAP_PROP_FPS, fps)
            for _ in range(3):
                self.cap.read()

    @staticmethod
    def _topic_has_publisher(topic: str) -> bool:
        try:
            import rclpy
            from rclpy.node import Node
            if not rclpy.ok():
                rclpy.init()
            n = Node("zmax_topic_probe", enable_rosout=False, start_parameter_services=False)
            ok = n.count_publishers(topic) > 0
            n.destroy_node()
            return ok
        except Exception:                                                  # noqa: BLE001
            return False

    def _start_ros_sub(self, topic):
        import rclpy
        from rclpy.node import Node
        from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
        from sensor_msgs.msg import Image
        if not rclpy.ok():
            rclpy.init()
        self.node = Node("zmax_frame_srv", enable_rosout=False, start_parameter_services=False)
        q = QoSProfile(depth=2, history=HistoryPolicy.KEEP_LAST, reliability=ReliabilityPolicy.BEST_EFFORT)

        def cb(m):
            it = {"rgb8": np.uint8, "bgr8": np.uint8, "mono8": np.uint8,
                  "16UC1": np.uint16, "32FC1": np.float32}.get(m.encoding, np.uint8)
            ch = 3 if m.encoding in ("rgb8", "bgr8") else 1
            raw = np.frombuffer(bytes(m.data), dtype=it)
            raw = raw.reshape(m.height, m.step // raw.dtype.itemsize)[:, : m.width * ch]
            a = raw.reshape(m.height, m.width, ch)
            if ch == 3:
                a = a[:, :, ::-1] if m.encoding == "bgr8" else a[:, :, ::-1]   # 统一成 BGR (cv2 编码用)
                self.ros_img = np.ascontiguousarray(a)
            else:
                self.ros_img = np.ascontiguousarray(np.repeat(a[:, :, 0][:, :, None], 3, axis=2))

        self.node.create_subscription(Image, topic, cb, q)

    def loop(self):
        import cv2
        t_prev, n = time.time(), 0
        while not self._stop:
            t0 = time.time()
            fr = None
            if self.mode.startswith("ros"):
                import rclpy
                rclpy.spin_once(self.node, timeout_sec=0.05)
                fr = self.ros_img if self.ros_img is not None else None
            else:
                ok, f = self.cap.read()
                fr = f if ok else None
            if fr is not None:
                t_enc = time.time()
                ok_j, buf = cv2.imencode(".jpg", fr, [int(cv2.IMWRITE_JPEG_QUALITY), self.quality])
                enc_ms = (time.time() - t_enc) * 1000
                if ok_j:
                    with self.lock:
                        self.jpeg = buf.tobytes()
                        self.n += 1
                        self.meta = {"seq": self.n, "src": self.mode, "w": int(fr.shape[1]),
                                     "h": int(fr.shape[0]), "encode_ms": round(enc_ms, 2),
                                     "quality": self.quality}
                    n += 1
            if n and time.time() - t_prev >= 1.0:
                with self.lock:
                    self.meta["fps"] = round(n / (time.time() - t_prev), 1)
                n, t_prev = 0, time.time()
            dt = self.period - (time.time() - t0)
            if dt > 0:
                time.sleep(dt)
        try:
            if self.cap is not None:
                self.cap.release()
        except Exception:                                                      # noqa: BLE001
            pass

    def snapshot(self):
        with self.lock:
            return self.jpeg, dict(self.meta)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", type=int, default=2)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--fps", type=float, default=10.0, help="服务端取帧+压缩频率")
    ap.add_argument("--quality", type=int, default=70, help="JPEG 质量 (服务端压缩)")
    ap.add_argument("--topic", default="/realsense/color/image_raw",
                    help="有发布者时优先用的话题; 无发布者自动退回 UVC")
    ap.add_argument("--service", default="/zmax/live_frame")
    ap.add_argument("--idle-seconds", type=float, default=20.0)
    ap.add_argument("--max-seconds", type=float, default=900.0)
    ap.add_argument("--marker", default="orin_frame_srv.py")
    a = ap.parse_args()

    # 单实例守卫 (避免双击/重连时堆多个进程)
    try:
        r = subprocess.run(["pgrep", "-f", a.marker], capture_output=True, text=True)
        others = [p for p in r.stdout.split() if p.isdigit() and int(p) != os.getpid()]
        if len(others) > 0:
            print(f"[frame-srv] 已有实例在跑 (pid={others}) → 本进程退出", flush=True)
            return 0
    except Exception:                                                      # noqa: BLE001
        pass

    if not _ensure_interfaces_importable():
        return 3
    import rclpy
    from rclpy.node import Node
    from interfaces.srv import HmiSnapshot

    ident = device_identity(a.device)
    dev_desc = (f"/dev/video{a.device} {ident.get('kernel_name','?')} "
                f"{ident.get('idVendor','?')}:{ident.get('idProduct','?')} sn={ident.get('serial','?')}")
    grab = Grabber(a.device, a.width, a.height, a.fps, a.quality, a.topic)
    threading.Thread(target=grab.loop, daemon=True).start()
    if not rclpy.ok():
        rclpy.init()
    node = Node("zmax_frame_srv", enable_rosout=False, start_parameter_services=False)
    state = {"calls": 0, "last": time.time(), "t0": time.time()}

    def srv_cb(_req, resp):
        jpeg, meta = grab.snapshot()
        state["calls"] += 1
        state["last"] = time.time()
        resp.success = jpeg is not None
        resp.message = "jpeg" if jpeg is not None else "no_frame_yet"
        payload = dict(meta)
        payload.update({"ts": time.time(), "ts_iso": time.strftime("%F %T"),
                        "device": dev_desc, "server": os.uname().nodename,
                        "jpeg_b64": base64.b64encode(jpeg).decode() if jpeg is not None else ""})
        resp.snapshot_json = json.dumps(payload)
        return resp

    node.create_service(HmiSnapshot, a.service, srv_cb)
    print(f"[frame-srv] 就绪 · 服务={a.service} · 源={grab.mode} · {dev_desc} · "
          f"JPEG q={a.quality} @ {a.fps}Hz (压缩在服务端, 老倪要求)", flush=True)
    srv = None
    try:
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.1)
            if time.time() - state["last"] > a.idle_seconds and state["calls"] > 0:
                print(f"[frame-srv] 无调用 {a.idle_seconds:.0f}s → 退出 (临时进程不常驻)", flush=True)
                break
            if time.time() - state["t0"] > a.max_seconds:
                print(f"[frame-srv] 到达兜底时限 {a.max_seconds:.0f}s → 退出", flush=True)
                break
    except KeyboardInterrupt:
        pass
    finally:
        grab._stop = True
        try:
            node.destroy_node()
            rclpy.shutdown()
        except Exception:                                                  # noqa: BLE001
            pass
    print(f"[frame-srv] 结束 · 共服务调用 {state['calls']} 次", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
