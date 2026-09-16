#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z-MAX 远程只读采集 (Orin 零程序 · 只转发感知信号)

运行位置: **4060 本机 Docker 容器 (ros:humble-ros-base, --network host, ROS_DOMAIN_ID=0)**
Orin 侧: 不装任何东西、不跑任何自研程序、不接收任何写回 —— 本节点在 DDS 域内
         仅以「订阅者」身份出现, **没有任何 publisher** (下面 publish 调用为零)。

订阅(只读, BEST_EFFORT):
  /robot/tcp_pose      真机 TCP 笛卡尔位姿 50Hz   → 引擎口径 z7 的「手/头」项
  /real_joint_states   真机关节 49Hz              → jvel
  /robot/force_torque  力/力矩                    → ft
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
from geometry_msgs.msg import PoseStamped
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
        self._rimg = None
        self.img = None            # {topic,encoding,w,h,std,t}
        self.img_path = os.path.join(OUT, "cam_latest.png")
        self.geom, self.geom_note = self._load_geom()
        self.create_subscription(PoseStamped, "/robot/tcp_pose", self.cb_tcp, _q(1))
        self.create_subscription(JointState, "/real_joint_states", self.cb_joint, _q(1))
        # ⚠️ 现场 /robot/force_torque 是同名双类型话题(JointState + WrenchStamped)。
        #    本镜像的 WrenchStamped python typesupport 建订阅即报 "invalid allocator"(已实测),
        #    故只订 JointState; 若将来力信号以 WrenchStamped 发布 → 计数为 0, 需换桥接方式。
        self.create_subscription(JointState, "/robot/force_torque", self.cb_ft, _q(1))
        self.create_subscription(Float64, "/gripper_pos", self.cb_grip, _q(1))
        self.create_subscription(String, "/motion/active_states", self.cb_stage, _q(1))
        self.create_subscription(String, "/robot_status", self.cb_rstat, _q(1))   # 真机状态 JSON
        # 📷 真机图像 (现场唯一有发布者的图像话题: FoundationPose 托盘参考 debug_image;
        #    RealSense 驱动未装 ⇒ /realsense/* 无发布者, 已实测)
        self.topics_watch = ["/robot/tcp_pose", "/real_joint_states", "/robot/force_torque", "/gripper_pos",
                             "/motion/active_states", "/robot_status", "/tactile_sensor", "/realsense/color/image_raw",
                             "/foundationpose/tray_reference/debug_image"]
        self.pub_counts = {}
        self.create_timer(5.0, self._count_pubs)      # 发布者计数 (只读查询)
        self.create_subscription(Image, os.environ.get("SS_CAM_TOPIC",
                                                       "/foundationpose/tray_reference/debug_image"),
                                 self.cb_img, _q(1), raw=True)

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

    def cb_img(self, m):
        with self.lock:
            self._rimg = m
            self.n["img"] += 1

    def cb_rstat(self, m):
        with self.lock:
            self.rstat = str(m.data)[:300]
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
                    "image": (dict(self.img, age=round(time.time() - self.img["t"], 2)) if self.img else None),
                    "pubs": dict(self.pub_counts),
                    "jpos": [round(float(x), 6) for x in self.jpos[:6]] if self.jpos else None,
                    "jvel": [round(float(x), 6) for x in self.jvel[:6]] if self.jvel else None,
                    "ft": [round(float(x), 4) for x in self.ft] if self.ft else None,
                    "gripper": self.grip, "prod_stage": self.stage,
                    "z7": [round(float(x), 6) for x in z] if z is not None else None,
                    "geom": self.geom_note if self.geom else f"缺失: {self.geom_note}",
                    "scope": "readonly-remote"}


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
    t0, cnt = time.time(), 0
    while True:
        rclpy.spin_once(n, timeout_sec=0.02)
        if time.time() - t0 >= 1.0 / a.rate:
            t0 = time.time()
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
