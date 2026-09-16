#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z-MAX 跨机闭环 · Orin 侧采集 + 执行闸门节点 (Step 2)

严格不新增 Orin 软件依赖: 只用已装的 rclpy/numpy, 不需要 rclcpp/编译工具链。
(2026-09-16 老倪: 「不要在 orin 上安装新软件」→ 原 rclcpp 重写方案取消, 改 Python 降载 + 闸门)

拓扑: Orin(本节点) --/zmax_ss/state--> 4060(Docker ROS 桥 → venv 推理) --/zmax_ss/action--> Orin
      ↑ Step 2 起: 收到提案先过闸门 (阶段白名单 / 方向一致度 / 幅值上限 / 超时), 通过且 armed 才放行

CPU 降载 (实测依据, 60s 稳态, 单核口径):
  全量 5 路(关节49.5Hz+力50Hz+夹爪12Hz+状态2Hz+阶段1Hz) ≈ 13~14%
  默认 MIN(关节49.5+夹爪12 ≈ 62 msg/s)            ≈ 7~8%   ← 满足「我方服务 <8% 单核」红线
  Python rclpy 的开销主要在"DDS 逐条派发", 与反序列化/我的计算无关(实测两者差 ~0.3%);
  想全量又低载需 rclcpp(C++), 但 Orin 无 rclcpp 头且不装新包 → 现方案: 默认 MIN, 需要力/阶段时 SS_EDGE_FULL=1 临时开。

执行闸门 (Step 2, 老倪: 逐层收窄 + L2 收口):
  · SS_GATE_ARM=0 (默认) → 只判决、只记录, 不下发 (旁路; 放权需显式开)
  · 阶段白名单 SS_GATE_STAGES (默认 "接近,对位,转移") —— 下降/抓取/插入/拔出/AOI 交回执行层
  · 方向一致度 SS_GATE_COS_MIN (默认 0.9): 提案方向 vs 真机当前运动方向
  · 幅值上限 SS_GATE_MAX_MAG (默认 1.5×): 提案幅值 / 真机速度幅值
  · 超时 SS_GATE_STALE_MS (默认 300): 提案比现场旧太多 → 否决
  每条判决写 jsonl + 计数, 可复核; 否决原因分类统计。
"""
import argparse
import json
import os
import threading
import time

import numpy as np
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from rclpy.serialization import deserialize_message
from geometry_msgs.msg import PoseStamped
from sensor_msgs.msg import JointState
from std_msgs.msg import Float32, String
from geometry_msgs.msg import WrenchStamped

OUT_DIR = os.path.expanduser("~/.zmax/ss_link")
JQ = QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST)
AQ = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_LAST)


class EdgeNode(Node):
    JOINTS_TOPIC = os.environ.get("SS_EDGE_JOINTS_TOPIC", "/robot/joint_states")
    FULL = os.environ.get("SS_EDGE_FULL", "0") == "1"
    TCP = os.environ.get("SS_EDGE_TCP", "0") == "1"      # 订阅 /robot/tcp_pose 并算 z7 (标定桥)
    GEOM_PATH = os.environ.get("SS_GEOM_PATH", os.path.expanduser("~/zmax_state_space/models/real_cell_geometry.json"))
    ARM = os.environ.get("SS_GATE_ARM", "0") == "1"
    STAGES = [s.strip() for s in os.environ.get("SS_GATE_STAGES", "接近,对位,转移").split(",") if s.strip()]
    COS_MIN = float(os.environ.get("SS_GATE_COS_MIN", "0.9"))
    MAX_MAG = float(os.environ.get("SS_GATE_MAX_MAG", "1.5"))
    STALE_MS = float(os.environ.get("SS_GATE_STALE_MS", "300"))
    # 仅测试用: 参考速度注入 (现场静止时让方向/幅值判据可被确定性验证)
    _REF = os.environ.get("SS_GATE_REF_VEL", "")
    REF_VEL = np.array([float(x) for x in _REF.split(",") if x.strip()]) if _REF.strip() else None

    def __init__(self, state_topic, action_topic, rate_hz):
        super().__init__("ss_edge")
        os.makedirs(OUT_DIR, exist_ok=True)
        day = time.strftime("%Y%m%d")
        self.f_state = open(os.path.join(OUT_DIR, f"state_{day}.jsonl"), "a")
        self.f_action = open(os.path.join(OUT_DIR, f"action_{day}.jsonl"), "a")
        self.f_gate = open(os.path.join(OUT_DIR, f"gate_{day}.jsonl"), "a")
        self._lock = threading.Lock()
        self._rj = self._rf = self._rg = self._rst = self._rstage = None
        self._rtcp = None
        self.tcp = None
        self.geom, self.geom_note = self._load_geom()
        self.j = self.f = self.g = None
        self.st = self.stage = ""
        self.prev_pos = self.prev_t = None
        self.seq = self.n_pub = self.n_act = 0
        self.vel = np.zeros(6)
        self.verdicts = {}
        self.gate_armed = self.ARM

        # ── 订阅 (只读) ──
        self.create_subscription(JointState, self.JOINTS_TOPIC, self.cb_j, JQ, raw=True)
        self.create_subscription(Float32, "/gripper_pos", self.cb_g, 5, raw=True)
        if self.TCP:    # 标定桥: 真机 TCP 位姿 (50Hz, 用于引擎口径 z7)
            self.create_subscription(PoseStamped, "/robot/tcp_pose", self.cb_tcp, JQ, raw=True)
        if self.FULL:   # 全量模式: 力/机器人状态/产线阶段 (CPU ~13%, 仅在需要时开)
            self.create_subscription(WrenchStamped, "/robot/force_torque", self.cb_f, JQ, raw=True)
            self.create_subscription(String, "/robot_status", self.cb_st, 5, raw=True)
            self.create_subscription(String, "/motion/active_states", self.cb_stage, 5, raw=True)

        self.pub = self.create_publisher(String, state_topic, AQ)
        self.create_subscription(String, action_topic, self.on_action, AQ)
        self.create_timer(1.0 / max(1.0, rate_hz), self.tick)
        self.create_timer(10.0, self.report)
        self.get_logger().info(
            f"🛰️ Orin 采集+闸门节点启动 | 订阅 {'全量5路' if self.FULL else 'MIN(关节+夹爪)'} + {self.JOINTS_TOPIC} | "
            f"发布 {state_topic} @{rate_hz}Hz | 闸门 {'ARMED(会放行)' if self.ARM else 'disarmed(只判不下发)'} | "
            f"阶段白名单={self.STAGES} cos≥{self.COS_MIN} |mag|≤{self.MAX_MAG}× | 超时>{self.STALE_MS}ms | 记录 {OUT_DIR}")

    # ── 回调: 只存原始字节 ──
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

    def cb_tcp(self, m):
        self._rtcp = m

    def _load_geom(self):
        """加载现场示教几何; 缺失/未通过校验 → 返回 None (推理端必须拒算 z7, 不许编造)"""
        try:
            import json as _json
            d = _json.load(open(self.GEOM_PATH))
            if not d.get("validated"):
                return None, f"几何未通过校验 ({self.GEOM_PATH})"
            pts = d.get("points", {})
            if not all(k in pts for k in ("peg_head", "goal")):
                return None, "几何缺 peg_head/goal"
            return {"peg_head": [pts["peg_head"][k] for k in "xyz"],
                    "goal": [pts["goal"][k] for k in "xyz"]}, f"示教几何 {d.get('updated_at')}"
        except Exception as e:
            return None, f"无示教几何文件 ({type(e).__name__})"

    def _z7(self):
        """引擎口径 z7 = [手/头−目标(3), 手/头−光模块(3), 夹持(1)] (与 _fiber_z7_geo 同公式)"""
        if self.tcp is None or self.geom is None:
            return None
        hx = np.array(self.tcp, dtype=float)
        tg = np.array(self.geom["goal"], dtype=float)
        pg = np.array(self.geom["peg_head"], dtype=float)
        grasp = 1.0 if (self.g is not None and float(self.g.data) < 500.0) else 0.0
        return np.concatenate([hx - tg, hx - pg, [grasp]])

    def _decode(self):
        try:
            if self._rj is not None:
                self.j = deserialize_message(bytes(self._rj), JointState)
            if self._rg is not None:
                self.g = deserialize_message(bytes(self._rg), Float32)
            if self.TCP and self._rtcp is not None:
                _p = deserialize_message(bytes(self._rtcp), PoseStamped).pose.position
                self.tcp = [round(_p.x, 6), round(_p.y, 6), round(_p.z, 6)]
            if self.FULL:
                if self._rf is not None:
                    self.f = deserialize_message(bytes(self._rf), WrenchStamped)
                if self._rst is not None:
                    self.st = deserialize_message(bytes(self._rst), String).data
                if self._rstage is not None:
                    self.stage = deserialize_message(bytes(self._rstage), String).data
        except Exception:
            pass

    def tick(self):
        self._decode()
        if self.j is None:
            return
        pos = [float(x) for x in self.j.position]
        vel = [float(x) for x in self.j.velocity] if self.j.velocity else []
        t = time.time()
        if not vel and self.prev_pos is not None and self.prev_t:
            dt = max(1e-4, t - self.prev_t)
            vel = [(a - b) / dt for a, b in zip(pos, self.prev_pos)]
        self.prev_pos, self.prev_t = pos, t
        self.vel = np.array(vel[:6], dtype=float) if vel else np.zeros(6)
        ft = None
        if self.f is not None:
            w = self.f.wrench
            ft = [round(w.force.x, 4), round(w.force.y, 4), round(w.force.z, 4),
                  round(w.torque.x, 4), round(w.torque.y, 4), round(w.torque.z, 4)]
        self.seq += 1
        st = {
            "t": round(t, 4), "seq": self.seq, "src": "orin_edge",
            "joints": [round(x, 5) for x in pos],
            "jvel": [round(float(x), 5) for x in self.vel],
            "sp_norm": round(float(np.linalg.norm(self.vel)), 5),
            "gripper": round(float(self.g.data), 3) if self.g is not None else None,
            "ft": ft,
            "robot_state": self.st[:160],
            "prod_stage": self.stage[:60],
            "tcp": self.tcp,
            "z7": ([round(float(x), 6) for x in self._z7().tolist()] if self._z7() is not None else None),
            "geom": (self.geom_note if self.geom else f"缺失: {self.geom_note}"),
            "scope": "readonly",
        }
        m = String()
        m.data = json.dumps(st, ensure_ascii=False)
        self.pub.publish(m)
        self.n_pub += 1
        with self._lock:
            self.f_state.write(json.dumps(st, ensure_ascii=False) + "\n")
        if self.n_pub % 100 == 0:
            self.f_state.flush()

    # ═══ 执行闸门 (Step 2) ═══
    def gate(self, prop: dict, real_vel: np.ndarray, now: float):
        """返回 (verdict, detail)。绝不执行任何动作, 只判决。

        SS_GATE_REF_VEL: **仅测试用** 参考速度注入 (逗号分隔 6 维)。现场机械臂静止时,
        方向/幅值判据没有参考 → 无法验证; 该钩子让判据可被确定性测试, 默认不设 = 用真机速度。
        """
        ref = self.REF_VEL if self.REF_VEL is not None else (real_vel if real_vel is not None else np.zeros(6))
        if not self.gate_armed:
            return "disarmed", "闸门未武装(SS_GATE_ARM=0) — 只判不下发"
        age_ms = (now - float(prop.get("t", 0))) * 1000.0
        if age_ms > self.STALE_MS:
            return "veto_stale", f"提案过旧 {age_ms:.0f}ms > {self.STALE_MS:.0f}ms"
        stage = (prop.get("stage") or self.stage or "").strip()
        if stage and self.STAGES and not any(s in stage for s in self.STAGES):
            return "veto_stage", f"阶段 '{stage}' 不在白名单 {self.STAGES}"
        a = np.array(prop.get("action") or [], dtype=float)
        if a.size < 3:
            return "veto_shape", f"动作维度异常 {a.size}"
        a3 = a[:3]
        na = float(np.linalg.norm(a3))
        nv = float(np.linalg.norm(ref[:3])) if ref.size >= 3 else 0.0
        if nv > 1e-6:
            cos = float(np.dot(a3, ref[:3]) / (na * nv + 1e-9))
            if cos < self.COS_MIN:
                return "veto_dir", f"方向不一致 cos={cos:.3f} < {self.COS_MIN} (提案 {na:.3f} vs 参考 {nv:.3f})"
            if self.MAX_MAG > 0 and na > self.MAX_MAG * nv:
                return "veto_mag", f"幅值过大 {na:.3f} > {self.MAX_MAG}×参考 {nv:.3f}"
            return "pass_no_exec", f"过闸 (cos={cos:.3f}) — 执行钩子未接线, 仅记录"
        # 真机静止: 无参考方向 → 只允许极小动作
        if na > 1e-3:
            return "veto_noref", f"真机静止(|v|<1e-6) 但提案幅值 {na:.3f} → 无可信参考, 否决"
        return "pass_no_exec", "真机静止 + 提案近零 — 过闸, 仅记录"

    def on_action(self, msg):
        """收到 4060 的动作提案 → 过闸 → 只记录 (Step 2 不加执行钩子)"""
        self.n_act += 1
        now = time.time()
        try:
            prop = json.loads(msg.data)
        except Exception:
            prop = {"raw": msg.data[:200]}
        verdict, detail = self.gate(prop, self.vel, now)
        self.verdicts[verdict] = self.verdicts.get(verdict, 0) + 1
        rec = {"t": round(now, 4), "seq": prop.get("seq"), "case": prop.get("case"),
               "verdict": verdict, "detail": detail,
               "action": prop.get("action"), "yaw": prop.get("yaw"),
               "model_ms": prop.get("model_ms"), "e2e_ms": prop.get("e2e_ms"),
               "real_jvel": [round(float(x), 5) for x in self.vel],
               "prod_stage": self.stage[:40], "armed": self.gate_armed, "executed": False}
        with self._lock:
            self.f_gate.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self.f_action.write(json.dumps(prop, ensure_ascii=False) + "\n")
        if self.n_act % 20 == 0:
            self.f_gate.flush()
            self.f_action.flush()
            self.get_logger().info(f"🚧 闸门 #{self.n_act}: {verdict} · {detail} · 统计={self.verdicts}")

    def report(self):
        self.get_logger().info(
            f"🛰️ 上行 {self.n_pub} 帧 · 提案 {self.n_act} 条 · 闸门={self.verdicts} · "
            f"速度范数={float(np.linalg.norm(self.vel)):.4f} · 阶段={self.stage[:20] or '-'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-topic", default="/zmax_ss/state")
    ap.add_argument("--action-topic", default="/zmax_ss/action")
    ap.add_argument("--rate", type=float, default=20.0)
    a = ap.parse_args()
    os.environ.setdefault("ROS_DOMAIN_ID", "0")
    os.environ.setdefault("ZMAX_REPO_ROOT", "/home/tashan/zmax_state_space")
    rclpy.init()
    n = EdgeNode(a.state_topic, a.action_topic, a.rate)
    try:
        rclpy.spin(n)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass          # SIGTERM/kill 时 rclpy 抛 ExternalShutdownException — 属正常退出路径
    finally:
        try:
            n.get_logger().info(f"停止: 上行 {n.n_pub} · 提案 {n.n_act} · 闸门={n.verdicts}")
        except Exception:
            pass
        try:
            n.destroy_node()
        except Exception:
            pass
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
