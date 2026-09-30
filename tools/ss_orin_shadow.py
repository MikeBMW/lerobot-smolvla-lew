#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z-MAX 状态空间工程 · Orin 端「旁路(影子)运行器」 — 只读, 绝不发布控制量

老倪 2026-09-16: 「把状态空间工程，旁路运行部署到 orin 上」

旁路铁律 (与产线共存, 不接管):
  · 只订阅, 不发布任何控制话题; 不调用任何服务 (gripper_driver / robot_stop / motion / tower_light 一律不碰)
  · 唯一写入 = ① 本地 jsonl 记录  ② relay 回传(source=orin_shadow)  ③ 遥测话题 /zmax_shadow/status(命名空间隔离)

订阅 (全部只读):
  /robot/joint_states  6 关节位置+速度 (珞石 XMS5-R800, base_link, ~49.5Hz; 可选 --joints-topic /real_joint_states 全速率 100Hz)
  /robot/force_torque  六维力/力矩 (WrenchStamped, ~50Hz)
  /gripper_pos         夹爪开度 (Float32, ~12Hz)
  /robot_status        机器人状态 JSON 串 (power/operation/error, ~2Hz)
  /motion/active_states 产线状态机阶段 (String)

旁路产出 (引擎口径可判定子集, 缺的显式标注不编造):
  · 真实运动学: 关节速度 6 维 / 速度范数 / 单位方向 / 夹爪 / 合力模 / 力矩模
  · 运动分类 (按引擎 STAGE_V_CAP 速度阈值口径): 静止 / 微动 / 运动中 / 力异常(接触疑似)
  · 产线阶段: 原样读 /motion/active_states (不做二次解释)
  · 模型探针: 每 5s 真调本机 8767 /infer/mani(11D) + /infer/yaw(12D), 记 infer_ms 与输出 (证明部署模型链路活着)
  · 诚实缺口: TCP 笛卡尔位姿未接 → 引擎 obs 的 x/_pc/goal 槽位需要 FK + 现场几何标定 (下一阶段)

用法:
  ROS_DOMAIN_ID=0 python3 ss_shadow.py                 # 常驻旁路
  ROS_DOMAIN_ID=0 python3 ss_shadow.py --duration 30 --dry   # 自检 30s, 不回传 relay
"""
import argparse
import json
import resource
import os
import threading
import time
import urllib.request

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.serialization import deserialize_message
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import JointState
from std_msgs.msg import Float32, String
from geometry_msgs.msg import WrenchStamped

RELAY_URL = "http://datadrive.world/api/relay/upload"
INFER_URL = "http://127.0.0.1:8767"
OUT_DIR = os.path.expanduser("~/.zmax/ss_shadow")
STAGE_V = {"接近": 0.30, "对位": 0.10, "下降": 0.06, "抓取": 0.05,
           "转移": 0.35, "插入": 0.05, "拔出": 0.06, "完成": 0.0}   # 引擎 STAGE_V_CAP 口径 (m/s)
JQ = QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST)


class SSShadow(Node):
    JOINTS_TOPIC = os.environ.get("SS_SHADOW_JOINTS_TOPIC", "/robot/joint_states")

    def __init__(self, joints_topic=None):
        super().__init__("ss_shadow")
        self.joints_topic = joints_topic or self.JOINTS_TOPIC
        self.j = self.f = self.g = None      # 解码后的最近消息
        self.st = self.stage = ""            # robot_status / 产线阶段
        self._rj = self._rf = self._rg = self._rst = self._rstage = None   # raw 字节
        self.prev_pos = None
        self.prev_t = None
        self.n_frames = 0
        self.n_upload_ok = 0
        self.n_upload_err = 0
        self.probe = {"ok": 0, "err": 0, "mani_ms": None, "yaw_ms": None, "mani": None, "yaw": None}
        self.buf = []
        self.dry = False      # --dry: 只本地落盘, 不回传 relay
        # ── 订阅 (只读, raw=True: 高频回调只存字节, 反序列化挪到 5Hz tick) ──
        #    实测: 100Hz/50Hz 消息在 Python 里逐条反序列化 ≈21% 单核 → 这条改法降到 ~1%
        self.create_subscription(JointState, self.joints_topic, self.cb_j, JQ, raw=True)
        self.create_subscription(Float32, "/gripper_pos", self.cb_g, 5, raw=True)
        # SS_SHADOW_MIN=1 → 只留 关节+夹爪 (~62 msg/s, 实测 CPU 减半; 六维力/机器人状态两路停订)
        #   阈值红线: 现场要求「我方服务合计 <8% 单核」; 全量(sp_norm+力) 实测 ~14% 单核 (8 核机器 ≈1.8%)
        if os.environ.get("SS_SHADOW_MIN") != "1":
            self.create_subscription(WrenchStamped, "/robot/force_torque", self.cb_f, JQ, raw=True)
            self.create_subscription(String, "/robot_status", self.cb_st, 5, raw=True)
        self.create_subscription(String, "/motion/active_states", self.cb_stage, 5, raw=True)
        # ── 遥测 (唯一下行, 命名空间隔离, 不是控制) ──
        self.pub_status = self.create_publisher(String, "/zmax_shadow/status", 5)
        self.create_timer(0.2, self.tick)            # 5Hz 旁路采样 (降载: 原 10Hz 21% 单核)
        if os.environ.get("SS_SHADOW_NO_PROBE") != "1":
            self.create_timer(5.0, self.probe_models)   # 5s 模型探针 (真调 8767)
        if os.environ.get("SS_SHADOW_NO_UPLOAD") != "1":
            self.create_timer(5.0, self.upload)         # 5s 汇总回传
        if os.environ.get("SS_SHADOW_NO_STATUS") != "1":
            self.create_timer(5.0, self.publish_status) # 遥测

    # ---------- 回调: 只存原始字节 (零反序列化开销, 铁律: 高频回调不做重活) ----------
    def cb_j(self, m):
        self._rj = m

    def cb_f(self, m):
        self._rf = m

    def cb_g(self, m):
        self._rg = m

    def cb_st(self, m):
        self._rst = m

    def cb_stage(self, m):
        self._rstage = m

    def _decode(self):
        """在 tick 里把原始字节解码成消息 (5Hz, 代价可忽略)"""
        try:
            if self._rj is not None:
                self.j = deserialize_message(bytes(self._rj), JointState)
            if self._rf is not None:
                self.f = deserialize_message(bytes(self._rf), WrenchStamped)
            if self._rg is not None:
                self.g = deserialize_message(bytes(self._rg), Float32)
            if self._rst is not None:
                self.st = deserialize_message(bytes(self._rst), String).data
            if self._rstage is not None:
                self.stage = deserialize_message(bytes(self._rstage), String).data
        except Exception:
            pass   # 单帧解码失败不中断旁路

    # ---------- 引擎口径的可判定量 ----------
    def motion_class(self, sp_norm, force_dev):
        """按引擎 STAGE_V_CAP 速度阈值口径做运动分类 (分类, 不是八阶段命名 — 不编造精度)"""
        if force_dev is not None and force_dev > 3.0:
            return "力异常(接触疑似)"
        if sp_norm is None:
            return "无数据"
        if sp_norm < 0.005:
            return "静止"
        if sp_norm < 0.05:
            return "微动"
        return "运动中"

    def tick(self):
        self._decode()
        if self.j is None:
            return
        pos = list(self.j.position)
        vel = list(self.j.velocity) if self.j.velocity else []
        t = time.time()
        if self.prev_pos is not None and self.prev_t and t > self.prev_t and not vel:
            vel = [(a - b) / (t - self.prev_t) for a, b in zip(pos, self.prev_pos)]
        self.prev_pos, self.prev_t = pos, t
        v = np.array(vel[:6], dtype=float) if vel else np.zeros(6)
        sp = float(np.linalg.norm(v))
        ft = None
        if self.f is not None:
            w = self.f.wrench
            ft = [w.force.x, w.force.y, w.force.z, w.torque.x, w.torque.y, w.torque.z]
        fmag = float(np.linalg.norm(ft[:3])) if ft else None
        tmag = float(np.linalg.norm(ft[3:])) if ft else None
        fdev = None
        if fmag is not None:
            self._fhist = getattr(self, "_fhist", [])[-49:] + [fmag]
            if len(self._fhist) >= 10:
                fdev = float(fmag - np.median(self._fhist[:-1]))
        gripper = float(self.g.data) if self.g is not None else None
        rec = {
            "t": round(t, 3),
            "joints": [round(float(x), 5) for x in pos],
            "jvel": [round(float(x), 5) for x in v],
            "sp_norm": round(sp, 5),
            "gripper": gripper,
            "ft": [round(float(x), 4) for x in ft] if ft else None,
            "f_norm": round(fmag, 4) if fmag is not None else None,
            "t_norm": round(tmag, 4) if tmag is not None else None,
            "motion_class": self.motion_class(sp, fdev),
            "prod_stage": self.stage[:60],
            "robot_state": self.st[:120],
            "shadow_scope": "readonly",
            "pending": "TCP位姿→引擎x/_pc/goal 槽位待FK标定",
        }
        self.n_frames += 1
        with threading.Lock():
            self.buf.append(rec)
        if self.n_frames % 100 == 0:
            self.get_logger().info(
                f"旁路采样 {self.n_frames} 帧 | 速度范数={sp:.4f} | 夹爪={gripper} | "
                f"|F|={fmag if fmag is None else round(fmag,2)} | {rec['motion_class']} | 产线阶段={rec['prod_stage'] or '-'}"
            )

    # ---------- 模型探针: 真调本机已部署的推理服务 ----------
    def _post(self, path, payload, timeout=8):
        req = urllib.request.Request(INFER_URL + path, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    def probe_models(self):
        try:
            r = self._post("/infer/mani", {"state": [0.0] * 11})
            self.probe["mani_ms"] = r.get("infer_ms")
            self.probe["mani"] = r.get("action")
            self.probe["ok"] += 1
        except Exception as e:
            self.probe["err"] += 1
            self.probe["mani_ms"] = f"ERR {type(e).__name__}"
        try:
            r = self._post("/infer/yaw", {"obs": [0.0] * 12})
            self.probe["yaw_ms"] = r.get("infer_ms")
            self.probe["yaw"] = {k: r.get(k) for k in ("dz", "ok")}
        except Exception as e:
            self.probe["yaw_ms"] = f"ERR {type(e).__name__}"

    # ---------- 遥测 / 回传 ----------
    def publish_status(self):
        m = String()
        m.data = json.dumps({"frames": self.n_frames, "probe": self.probe,
                             "upload_ok": self.n_upload_ok, "scope": "readonly"}, ensure_ascii=False)
        self.pub_status.publish(m)

    def upload(self, dry=None):
        dry = self.dry if dry is None else dry
        with threading.Lock():
            if not self.buf:
                return
            batch = self.buf[-50:]
            self.buf = []
        arr = np.array([s["sp_norm"] for s in batch])
        f = np.array([s["f_norm"] for s in batch if s["f_norm"] is not None])
        rep = {
            "meta": {"source": "orin_shadow", "type": "ss_shadow_report", "time": time.time(),
                     "project": "zmax_state_space", "mode": "bypass"},
            "shadow": {
                "count": len(batch),
                "sp_norm_mean": round(float(arr.mean()), 5),
                "sp_norm_max": round(float(arr.max()), 5),
                "f_norm_mean": round(float(f.mean()), 3) if f.size else None,
                "f_norm_max": round(float(f.max()), 3) if f.size else None,
                "motion_classes": {c: sum(1 for s in batch if s["motion_class"] == c)
                                   for c in set(s["motion_class"] for s in batch)},
                "prod_stage_last": batch[-1]["prod_stage"],
                "probe": self.probe,
                "scope": "readonly (不发布控制)",
                "pending": "TCP位姿→引擎 x/_pc/goal 槽位待 FK 标定",
            },
            "samples": batch[-10:],
        }
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(os.path.join(OUT_DIR, f"ss_shadow_{int(time.time())}.json"), "w") as fp:
            json.dump(rep, fp, ensure_ascii=False)
        if dry:
            return
        try:
            req = urllib.request.Request(RELAY_URL, data=json.dumps(rep).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=10) as r:
                r.read()
            self.n_upload_ok += 1
            self.get_logger().info(f"📤 旁路汇总回传 relay #{self.n_upload_ok} ({len(batch)} 样本)")
        except Exception as e:
            self.n_upload_err += 1
            self.get_logger().warn(f"⚠️ 回传失败({self.n_upload_err}): {type(e).__name__}: {str(e)[:60]}")

    def dump_jsonl(self):
        os.makedirs(OUT_DIR, exist_ok=True)
        p = os.path.join(OUT_DIR, f"ss_shadow_{time.strftime('%Y%m%d_%H%M%S')}.jsonl")
        with open(p, "w") as f:
            for s in getattr(self, "_all", []):
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
        return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=float, default=0, help="运行秒数 (0=常驻)")
    ap.add_argument("--dry", action="store_true", help="不回传 relay (自检用)")
    ap.add_argument("--joints-topic", default=None,
                    help="关节话题 (默认 /robot/joint_states 49.5Hz; 全速率用 /real_joint_states 100Hz, 实测 Python 订阅开销 x2)")
    args = ap.parse_args()

    os.environ.setdefault("ROS_DOMAIN_ID", "0")
    rclpy.init()
    node = SSShadow(joints_topic=args.joints_topic)
    node._all = []
    node.dry = bool(args.dry)
    _spin = threading.Thread(target=rclpy.spin, args=(node,), daemon=True)
    _spin.start()
    node.get_logger().info(f"👻 状态空间旁路(影子)运行器启动 — 只读, 绝不发布控制 | OUT={OUT_DIR}")
    t0 = time.time()
    try:
        while rclpy.ok():
            time.sleep(1.0)
            if args.duration and time.time() - t0 >= args.duration:
                break
    except KeyboardInterrupt:
        pass
    # 收尾: 落 jsonl + 最后一次回传
    with threading.Lock():
        node._all = list(node.buf)
    node.upload(dry=args.dry)
    p = node.dump_jsonl()
    _ru = resource.getrusage(resource.RUSAGE_SELF)
    _cpu = (_ru.ru_utime + _ru.ru_stime) / max(1e-6, time.time() - t0) * 100
    node.get_logger().info(
        f"停止: 采样 {node.n_frames} 帧 · 回传 ok={node.n_upload_ok} err={node.n_upload_err} · "
        f"CPU={_cpu:.1f}% 单核 (user+sys) · jsonl={p}")
    rclpy.shutdown()                      # 先让 spin 线程退出 (否则 destroy_node 与 spin_once 竞态抛 handler.exception)
    try:
        _spin.join(timeout=3)
    except Exception:
        pass
    node.destroy_node()


if __name__ == "__main__":
    main()
