#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z-MAX 远程只读采集 (Orin 零程序 · 只转发感知信号)

运行位置: **4060 本机 Docker 容器 (ros:humble-ros-base, --network host, ROS_DOMAIN_ID=0)**
Orin 侧: 不装任何东西、不跑任何自研程序、不接收任何写回 —— 本节点在 DDS 域内
         仅以「订阅者」身份出现, **没有任何 publisher** (下面 publish 调用为零)。

订阅(只读, BEST_EFFORT):
  /robot/tcp_pose      真机 TCP 笛卡尔位姿 50Hz   → 引擎口径 z7 的「手/头」项
  /real_joint_states   真机关节 49Hz              → jvel
  /robot/force_torque  六维力/力矩 49.5Hz         → ft (WrenchStamped, BEST_EFFORT)
                           # 同名双类型话题: 力信号只从 WrenchStamped 来 (JointState 那条无消息)
  /gripper_pos         夹爪位置                   → 夹持判定
  /motion/active_states 产线阶段 (当前空闲, 空)
输出(全部落在 4060 本机):
  $SS_OUT/state_YYYYMMDD.jsonl   原始感知
  $SS_OUT/proposal_YYYYMMDD.jsonl 本机模型建议 (只记录, 不回传)
  $SS_OUT/status.json            计数/频率, 用于取证
"""
import argparse
import json
import os
import threading
import time
import urllib.request

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from geometry_msgs.msg import PoseStamped, WrenchStamped
from sensor_msgs.msg import Image, JointState
from std_msgs.msg import Float64, String

OUT = os.environ.get("SS_OUT", "/out")
GEOM_PATH = os.environ.get("SS_GEOM_PATH", os.path.join(OUT, "real_cell_geometry.json"))
INFER_URL = os.environ.get("SS_INFER_URL", "http://127.0.0.1:8790/infer")


def _q(depth=1):
    return QoSProfile(depth=depth, reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST)


class RemoteTap(Node):
    def __init__(self):
        # enable_rosout=False: 连 rclpy 自带的 /rosout 发布者都不要 → 域内零 publisher, 绝对只读
        super().__init__("ss_remote_tap", enable_rosout=False, start_parameter_services=False)
        self.lock = threading.Lock()
        self.n = {k: 0 for k in ("tcp", "joint", "ft", "grip", "stage", "rstat", "img")}
        self.tcp = None
        self.jpos = self.jvel = None
        self.ft = None
        self.grip = None
        self.stage = ""
        self.tcp_quat = None
        self.tcp_frame = None
        self.jnames = []
        self.rstat = None
        self._rimgs = {}            # topic → 最近原始 Image 字节 (raw 订阅, 1Hz 解码)
        self.img = None             # 选定帧 (RealSense 彩色优先)
        self.imgs = {}             # topic → 最近解码结果 (分话题如实报状态)
        self.geom, self.geom_note = self._load_geom()
        self.create_subscription(PoseStamped, "/robot/tcp_pose", self.cb_tcp, _q(1))
        self.create_subscription(JointState, "/real_joint_states", self.cb_joint, _q(1))
        # ⚠️ 现场 /robot/force_torque 是**同名双类型**话题 (JointState + WrenchStamped)。
        #    实测 (2026-09-18 容器内直订取证): 真实的力/力矩以 **WrenchStamped @ BEST_EFFORT**
        #    在发 (~49.5Hz, Fx/Fy/Fz+Tx/Ty/Tz 真实变化); JointState 那条**一条也没有** (ft 计数长期为 0)。
        #    ⛔ 同一个 node 里**不能**对同一话题名建两个不同类型的订阅 —— 会直接抛
        #      "create_subscription() called for existing topic name … with incompatible type"
        #      → "invalid allocator" (这就是旧注释里那条坑的真因, 曾把 tap 打成 crash-loop)。
        #    故本节点**只订 WrenchStamped**; 若将来力信号改回 JointState 发布, 这里会显示
        #    "缺(无发布者)", 需按新类型改这一行 (不会假报)。
        self.create_subscription(WrenchStamped, "/robot/force_torque", self.cb_wrench, _q(1))
        self.create_subscription(Float64, "/gripper_pos", self.cb_grip, _q(1))
        self.create_subscription(String, "/motion/active_states", self.cb_stage, _q(1))
        self.create_subscription(String, "/robot_status", self.cb_rstat, _q(1))   # 真机状态 JSON
        # 📷 真机图像 (现场唯一有发布者的图像话题: FoundationPose 托盘参考 debug_image;
        #    RealSense 驱动未装 ⇒ /realsense/* 无发布者, 已实测)
        self.topics_watch = ["/robot/tcp_pose", "/real_joint_states", "/robot/force_torque", "/gripper_pos",
                             "/motion/active_states", "/robot_status", "/tactile_sensor", "/realsense/color/image_raw",
                             "/foundationpose/tray_reference/debug_image"]
        self.pub_counts = {}
        # 🛠 2026-09-23 修复 (老倪问"摄像头连接失败"): 原先这里用 rclpy 定时器驱动
        #   发布者计数/图像解码 —— **rclpy 定时器按墙钟调度**, 本机 NTP 把钟回拨 7.14h 后,
        #   定时器的"下次触发时刻"被推到未来 7h → **永久停摆** (实测: cam_rs.png 冻在
        #   回拨前那一刻 01:14:34, 而 img 计数照涨 = 假采集; 同容器的独立探针立刻能出图)。
        #   纪律与 09-18 同名事故一致: **节拍一律用单调钟** → 改为由主循环按 monotonic 驱动
        #   (见 main(): n._tick_img() / n._count_pubs())。
        self._tick_dt = {"img": 0.0, "pub": 0.0}
        # 📷 图像: RealSense 彩色 (现场期望的"实时 realsense 图像") 优先, FoundationPose 调试图兜底
        self.cam_topics = ["/realsense/color/image_raw",
                           "/foundationpose/tray_reference/debug_image"]
        for _t in self.cam_topics:
            self.create_subscription(Image, _t, lambda m, _tt=_t: self.cb_img(m, _tt), _q(1), raw=True)

    def _load_geom(self):
        try:
            d = json.load(open(GEOM_PATH))
            if not d.get("validated"):
                return None, f"几何未通过校验({GEOM_PATH})"
            p = d["points"]
            return {"peg_head": [p["peg_head"][k] for k in "xyz"], "goal": [p["goal"][k] for k in "xyz"]}, \
                   f"示教几何 {d.get('updated_at')}"
        except Exception as e:
            return None, f"无示教几何({type(e).__name__}) — z7 拒算, 不编造"

    def cb_tcp(self, m):
        p, o = m.pose.position, m.pose.orientation
        with self.lock:
            self.tcp = [p.x, p.y, p.z]
            self.tcp_quat = [o.x, o.y, o.z, o.w]      # 姿态 (真机 TCP 四元数)
            self.tcp_frame = m.header.frame_id        # 坐标系 (base_link)
            self.n["tcp"] += 1

    def cb_joint(self, m):
        with self.lock:
            self.jpos = list(m.position)
            self.jvel = list(m.velocity) if len(m.velocity) else None
            if m.name and not self.jnames:
                self.jnames = list(m.name)            # 关节名 (只记一次)
            self.n["joint"] += 1

    def cb_ft(self, m):
        """⚠️ 现场该话题的 JointState 类型**无发布者**(实测计数恒 0), 当前未建订阅 —— 保留供切类型时复用"""
        with self.lock:
            self.ft = list(m.effort)[:6] if len(m.effort) else None
            self.n["ft"] += 1

    def cb_wrench(self, m):
        w = m.wrench
        with self.lock:
            self.ft = [w.force.x, w.force.y, w.force.z, w.torque.x, w.torque.y, w.torque.z]
            self.n["ft"] += 1

    def cb_grip(self, m):
        with self.lock:
            self.grip = float(m.data)
            self.n["grip"] += 1

    def cb_stage(self, m):
        with self.lock:
            self.stage = str(m.data)[:60]
            self.n["stage"] += 1

    def _count_pubs(self):
        """每话题发布者数 → 区分"无发布者"(设备/驱动缺) 与 "有发布者但当前空闲无帧" """
        try:
            for t in self.topics_watch:
                self.pub_counts[t] = int(self.count_publishers(t))
        except Exception:
            pass

    def cb_img(self, m, topic=None):
        """raw=True 订阅 → 回调只存字节 (高频不做重活), 解码在 1Hz 定时器里"""
        with self.lock:
            self._rimgs[topic or "?"] = m
            self.n["img"] += 1

    @staticmethod
    def _png_write(arr, path, gray=False):
        """纯 Python PNG 编码 (容器只有 numpy, 无 cv2/PIL): arr=uint8 HxW(x3)"""
        import struct
        import zlib
        h, w = arr.shape[:2]
        raw = b"".join(b"\x00" + arr[y].tobytes() for y in range(h))

        def chunk(tag, data):
            c = tag + data
            return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

        png = b"\x89PNG\r\n\x1a\n"
        png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0 if gray else 2, 0, 0, 0))
        png += chunk(b"IDAT", zlib.compress(raw, 6))
        png += chunk(b"IEND", b"")
        # 🛠 2026-09-18: 原实现 = open(path,"wb").write(png) **非原子** (先截断再写) ——
        #   读者 (输入图像窗口 / L2 旁路, 10Hz 轮询) 可能读到**半张 PNG** (截断帧):
        #   解码失败 → 最轻是无图, 最坏是解码器原生崩 (06:53:40 控制台 SIGSEGV 的可疑向量之一)。
        #   改为 写临时文件 + os.replace 原子替换 (同目录同文件系统 → 读者永远看到完整帧)。
        tmp = f"{path}.tmp{os.getpid()}"
        with open(tmp, "wb") as f:
            f.write(png)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def _decode_img(self, m, topic=None):
        """Image → 元数据 + PNG 落盘 (真图判据 std>5, 与引擎同口径); 不支持的编码只记元数据"""
        import numpy as _np
        enc = (m.encoding or "").lower()
        h, w = int(m.height), int(m.width)
        tp = topic or getattr(m, "_ss_topic", None) or "?"
        meta = {"topic": tp, "encoding": enc, "w": w, "h": h, "step": int(m.step),
                "t": time.time(), "tm": time.monotonic(), "std": None, "saved": False,
                "path": os.path.join(OUT, "cam_rs.png" if "realsense" in tp else "cam_fp.png")}
        try:
            buf = _np.frombuffer(bytes(m.data), dtype=_np.uint8)
            if enc in ("rgb8", "bgr8") and buf.size >= h * w * 3:
                a = buf[: h * w * 3].reshape(h, w, 3)
                if enc == "bgr8":
                    a = a[:, :, ::-1]
                meta["std"] = round(float(a.std()), 2)
                self._png_write(_np.ascontiguousarray(a), meta["path"])
                meta["saved"] = True
            elif enc in ("mono8", "8uc1") and buf.size >= h * w:
                a = buf[: h * w].reshape(h, w)
                meta["std"] = round(float(a.std()), 2)
                self._png_write(a, meta["path"], gray=True)
                meta["saved"] = True
            elif enc in ("mono16", "16uc1", "32fc1") and buf.size >= h * w * 2:
                a16 = buf[: h * w * 2].view(_np.uint16).reshape(h, w)
                a = (a16.astype(_np.float32) / max(1.0, float(a16.max())) * 255).astype(_np.uint8)
                meta["std"] = round(float(a.std()), 2)
                self._png_write(a, meta["path"], gray=True)
                meta["saved"] = True
        except Exception as e:
            meta["err"] = f"{type(e).__name__}: {e}"
        return meta

    def _tick_img(self):
        """1Hz: 反序列化各话题最新帧 → 解码落盘; RealSense 有帧则优先作为 self.img

        🩹 2026-09-18 时钟回拨事故 (真机画面冻在 12:15 不再实时): 本机 NTP 把系统钟
        回拨 8h 后, 所有 `time.time()` 差值变负 → ① 本函数 `time.time()-上次解码 <= 1.0`
        恒真 → 永久 continue, 图像再也不解码; ② 主循环采样判据同样恒假 → 停止落盘。
        纪律: **节拍/新鲜度一律用单调钟 time.monotonic()**, time.time() 只用于落盘时间戳。
        """
        try:
            from rclpy.serialization import deserialize_message
            tm = getattr(self, "_dec_tm", None)
            if tm is None:
                tm = self._dec_tm = {}
            for t, raw in list(self._rimgs.items()):
                if time.monotonic() - tm.get(t, 0.0) <= 1.0:
                    continue
                try:
                    msg = deserialize_message(bytes(raw), Image)
                    meta = self._decode_img(msg, topic=t)
                    self.imgs[t] = meta
                    if meta.get("saved") and ("realsense" in t or not (self.img or {}).get("saved")):
                        self.img = meta
                except Exception as e:
                    self.imgs[t] = {"topic": t, "err": f"{type(e).__name__}: {e}", "t": time.time(),
                                    "tm": time.monotonic()}
                tm[t] = time.monotonic()
        except Exception:
            pass

    def tick_monotonic(self):
        """🛠 2026-09-23: **单调钟节拍** (替代 rclpy 墙钟定时器, 免疫时钟回拨/跳变)。

        图像解码 1Hz · 发布者计数 5s。由 main() 主循环每轮调用 (主循环本身用 monotonic 计时)。
        为什么不用 create_timer: rclpy Timer 以墙钟算"下次触发时刻", NTP 回拨后该时刻落到
        未来 (实测 7.14h) → 回调永久不再触发, 而订阅回调照跑 ⇒ "假采集"(计数涨、图不更新)。
        """
        now = time.monotonic()
        if now - self._tick_dt["img"] >= 1.0:
            self._tick_dt["img"] = now
            self._tick_img()
        if now - self._tick_dt["pub"] >= 5.0:
            self._tick_dt["pub"] = now
            self._count_pubs()

    def cb_rstat(self, m):
        with self.lock:
            self.rstat = str(m.data)[:1200]     # 截断会破坏 JSON → 面板解析失败 (300 截过)
            self.n["rstat"] = self.n.get("rstat", 0) + 1

    def z7(self):
        with self.lock:
            if self.tcp is None or self.geom is None:
                return None
            hx = np.array(self.tcp, float)
            grasp = 1.0 if (self.grip is not None and self.grip < 500.0) else 0.0
            return np.concatenate([hx - np.array(self.geom["goal"]), hx - np.array(self.geom["peg_head"]), [grasp]])

    def snapshot(self):
        z = self.z7()
        with self.lock:
            return {"t": round(time.time(), 3), "tcp": self.tcp,
                    "tcp_quat": self.tcp_quat, "tcp_frame": self.tcp_frame,
                    "jnames": self.jnames, "robot_status": self.rstat,
                    "image": (dict(self.img, age=_age_m(self.img)) if self.img else None),
                    "images_by_topic": {t: dict(v, age=_age_m(v))
                                        for t, v in self.imgs.items()},
                    "pubs": dict(self.pub_counts),
                    "jpos": [round(float(x), 6) for x in self.jpos[:6]] if self.jpos else None,
                    "jvel": [round(float(x), 6) for x in self.jvel[:6]] if self.jvel else None,
                    "ft": [round(float(x), 4) for x in self.ft] if self.ft else None,
                    "gripper": self.grip, "prod_stage": self.stage,
                    "z7": [round(float(x), 6) for x in z] if z is not None else None,
                    "geom": self.geom_note if self.geom else f"缺失: {self.geom_note}",
                    "scope": "readonly-remote"}


def _age_m(meta):
    """帧龄 (秒): 优先单调钟 (时钟回拨/跳变安全), 老记录退化 wall-clock 差值且**钳到非负**。
    🩹 2026-09-18: 旧实现 age=time.time()-t, NTP 回拨 8h 后 age≈-28800 → 任何
    `age <= 阈值` 的新鲜度判据都恒真, 旧帧被当成实时帧 (老倪红线: 绝不拿旧图冒充实时)。"""
    if not meta:
        return None
    if "tm" in meta:
        return round(max(0.0, time.monotonic() - float(meta["tm"])), 2)
    return round(max(0.0, time.time() - float(meta.get("t", time.time()))), 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=float, default=10.0)
    ap.add_argument("--no-infer", action="store_true", help="只记感知, 不调本机模型")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    rclpy.init()
    n = RemoteTap()
    day = time.strftime("%Y%m%d")
    fs = open(os.path.join(OUT, f"state_{day}.jsonl"), "a", buffering=1)
    fp = open(os.path.join(OUT, f"proposal_{day}.jsonl"), "a", buffering=1)
    print(f"[tap] 远程只读采集启动 rate={a.rate}Hz out={OUT} geom={n.geom_note} 本节点 publisher 数=0", flush=True)
    t0, cnt = time.monotonic(), 0
    while True:
        rclpy.spin_once(n, timeout_sec=0.02)
        n.tick_monotonic()          # 🛠 2026-09-23: 图像解码/发布者计数 (单调钟节拍, 免疫回拨)
        if time.monotonic() - t0 >= 1.0 / a.rate:
            t0 = time.monotonic()
            st = n.snapshot()
            fs.write(json.dumps(st, ensure_ascii=False) + "\n")
            cnt += 1
            if not a.no_infer and st["tcp"] is not None:
                try:
                    body = json.dumps({"state": {k: st[k] for k in ("jpos", "jvel", "ft", "gripper", "prod_stage", "z7")}}).encode()
                    rq = urllib.request.Request(INFER_URL, data=body, headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(rq, timeout=3) as r:
                        pr = json.loads(r.read())
                    fp.write(json.dumps({"t": st["t"], "input_map": pr.get("input_map"), "action": pr.get("action"),
                                         "yaw": pr.get("yaw"), "model_ms": pr.get("model_ms")}, ensure_ascii=False) + "\n")
                except Exception as e:
                    fp.write(json.dumps({"t": st["t"], "error": f"{type(e).__name__}: {e}"}) + "\n")
            if cnt % int(max(1, a.rate * 5)) == 0:
                # 自证: 本节点自己建了几个发布者 (rclpy 未暴露公开列表, 用运行时实体表)
                _pubs = [getattr(x, "topic_name", "?") for x in getattr(n, "_publishers", [])]
                _ext = {t: n.count_publishers(t) for t in
                        ("/robot/tcp_pose", "/real_joint_states", "/robot/force_torque", "/gripper_pos", "/motion/active_states")}
                json.dump({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "samples": cnt, "recv": dict(n.n),
                           "self_publishers": _pubs,   # 预期 [] = 域内零发布
                           "self_pub_count": len(_pubs), "self_subscriptions": len(getattr(n, "_subscriptions", [])),
                           "外部队列发布者(Orin侧)": _ext,
                           "geom": n.geom_note, "z7_ok": st["z7"] is not None,
                           "tcp": st["tcp"], "stage": st["prod_stage"]},
                          open(os.path.join(OUT, "status.json"), "w"), ensure_ascii=False, indent=1)
                print(f"[tap] {cnt} 样本 收包={n.n} z7={'ok' if st['z7'] is not None else 'null(几何未示教)'}", flush=True)
    n.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
