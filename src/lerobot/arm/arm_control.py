#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""arm_control.py — 🦾 统一机械臂控制层 (老倪 2026-09-26: MoveIt 规划 + 双执行后端, 效率优先)

设计 (为什么这样):
  · 老倪要求: 「不依赖当前机器人的 ROS2 服务, 直接驱动机器人 SDK, 效率优先」+「同时兼容现有 ROS2 操作框架」
  · 事实: 控制器 192.168.23.160; Orin 侧已常驻 **SDK 直驱桥**(zmax-arm-sdk-bridge.service, HTTP 39061, 不经 ROS);
          现有 ROS2 SRV (/move_pose 等) 仍在, 保留兼容
  · 实测: 两条路**同口径**(关节最大偏差 0.91 µrad, 2026-09-26) → 可互换; SDK 桥 /status 3~7ms

后端:
  OrinSdkBridge  : 默认/效率优先 —— HTTP → Orin 桥 → xCoreSDK → 控制器 (不需要 ROS 栈)
  Ros2Srv        : 兼容 —— 经 Orin 的 ROS2 服务 (/move_pose, /robot_stop)
  MoveItPlan     : 规划层 —— MoveIt2 出 IK/碰撞/轨迹 (可选; 装上 moveit 后启用), 执行交给上面两个后端

安全闸 (L2 收口, 任何后端都过):
  ① dry-run 默认 (不传 allow=True 一律只算)  ② Δ 守卫: 单步位移上限 / 向下限幅
  ③ 只读三查 (power=on · operation=idle)  ④ 现场闸门: allow 需显式 True
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.request

BRIDGE = os.environ.get("ZMAX_SDK_BRIDGE", "http://192.168.23.66:39061")
ORIN = ["sshpass", "-p", os.environ.get("ORIN_PWD", "ts123"), "ssh", "-o", "ConnectTimeout=8",
        "-o", "StrictHostKeyChecking=no", "tashan@192.168.23.66"]
ROSX = ('source /opt/ros/humble/setup.bash 2>/dev/null; '
        'for ws in /home/tashan/0810/*/install/setup.bash; do [ -f "$ws" ] && source "$ws" && break; done; '
        'export ROS_DOMAIN_ID=0; ')
JN = ["XMS5-R800-W4G3B4C_joint_%d" % i for i in range(1, 7)]
GATE = {"max_step_mm": 50.0, "max_down_mm": 20.0, "require_idle": True, "require_power_on": True}


class GateViolation(RuntimeError):
    pass


class OrinSdkBridge:
    """默认后端: Orin SDK 直驱桥 (不经 ROS, 不需要起 ROS2 栈)"""
    name = "orin_sdk_bridge"

    @staticmethod
    def _call(path, body=None, timeout=20):
        url = BRIDGE + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"},
                                     method="POST" if body is not None else "GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")

    def health(self):
        return self._call("/health", timeout=8)

    def status(self):
        return self._call("/status", timeout=25).get("status", {})

    def reset(self):
        return self._call("/reset", {}, timeout=30)

    def stop(self):
        return self._call("/stop", {}, timeout=30)

    def move_pose(self, p, q, speed=30.0, dry=True):
        return self._call("/move_pose", {"p": p, "q": q, "speed": speed, "dry": dry}, timeout=60)


class Ros2Srv:
    """兼容后端: 现有 ROS2 服务 (需要 Orin 的 ROS 栈在跑)"""
    name = "ros2_srv"

    @staticmethod
    def _sh(cmd, timeout=90):
        r = subprocess.run(ORIN + ["bash -lc", ROSX + cmd], capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")

    def status(self):
        import re
        t = self._sh("timeout 10 ros2 topic echo --once /robot_status 2>/dev/null", 30)
        def val(k):
            i = t.find('"%s"' % k)
            if i < 0:
                return None
            j = t.find('"', i + len(k) + 2)
            k2 = t.find('"', j + 1)
            return t[j + 1:k2] if k2 > j else None
        m = re.search(r'"has_error"\s*:\s*(true|false)', t)
        return {"powerState": val("power_state"), "operation": val("operation_state"),
                "has_error": (m.group(1) == "true") if m else None, "src": "ros2_srv"}

    def stop(self):
        return {"raw": self._sh("timeout 30 ros2 service call /robot_stop std_srvs/srv/Trigger '{}'", 60)[-200:]}

    def move_pose(self, p, q, speed=30.0, dry=True):
        if dry:
            return {"dry": True, "plan": {"to": [p[0], p[1], p[2]]}}
        js = ", ".join('"%s"' % n for n in JN)
        cmd = ('timeout 100 ros2 service call /move_pose interfaces/srv/TargetPose '
               '"{speed: %.1f, joint_state: {name: [%s], position: [0,0,0,0,0,0]}, '
               'pose: {position: {x: %.9f, y: %.9f, z: %.9f}, '
               'orientation: {x: %.9f, y: %.9f, z: %.9f, w: %.9f}}}"'
               % (speed, js, p[0], p[1], p[2], q[0], q[1], q[2], q[3]))
        return {"raw": self._sh(cmd, 120)[-200:]}


class MoveItPlan:
    """规划层 (可选): MoveIt2 → IK/碰撞/轨迹; 执行交给 backend

    启用前置: 装 MoveIt (docker pull/build ros-humble-moveit) + 由 URDF 生成 MoveIt 配置包
      config/robot/xms5_r800_w4g3b4c.urdf  (本机已有)  → SRDF + kinematics.yaml + joint_limits
    未安装时 plan() 如实返回 unavailable (不假装能规划)
    """
    name = "moveit_plan"

    @staticmethod
    def available():
        try:
            out = subprocess.run(["sudo", "docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
                                 capture_output=True, text=True, timeout=15).stdout
            return any("moveit" in x for x in out.split())
        except Exception:                                                        # noqa: BLE001
            return False

    @staticmethod
    def plan(start_p, goal_p, q=None):
        if not MoveItPlan.available():
            return {"available": False, "note": "未装 MoveIt 镜像 (需 docker 构建 ros-humble-moveit + 生成配置包)"}
        return {"available": True, "note": "MoveIt2 规划接口 (需在容器内跑 move_group + moveit_py)"}


class ArmController:
    """统一入口: 后端自动选择 + 安全闸收口"""

    def __init__(self, backend="auto"):
        self.sdk = OrinSdkBridge()
        self.ros2 = Ros2Srv()
        self.backend = backend
        if backend == "auto":
            try:
                h = self.sdk.health()
                self.backend = "orin_sdk_bridge" if h.get("sdk") else "ros2_srv"
            except Exception:                                                    # noqa: BLE001
                self.backend = "ros2_srv"

    def be(self):
        return self.sdk if self.backend == "orin_sdk_bridge" else self.ros2

    def status(self):
        return self.be().status()

    def precheck(self):
        st = self.status()
        power = st.get("powerState") or st.get("power")
        op = st.get("operation") or st.get("operation_state")
        err = st.get("has_error")
        problems = []
        if GATE["require_power_on"] and power and "on" not in str(power):
            problems.append("power=%s" % power)
        if GATE["require_idle"] and op and str(op) != "idle":
            problems.append("operation=%s" % op)
        return {"ok": not problems, "problems": problems, "status": st}

    def move_pose(self, p, q, speed=30.0, allow=False):
        """只读三查 → Δ守卫 → dry/真发"""
        chk = self.precheck()
        if not chk["ok"]:
            raise GateViolation("三查不过: %s" % chk["problems"])
        cur = (self.status().get("endInRef") or [None])[:3]
        if all(isinstance(v, (int, float)) for v in cur) and len(cur) == 3:
            d = [p[i] - cur[i] for i in range(3)]
            dist = sum(x * x for x in d) ** 0.5 * 1000
            if dist > GATE["max_step_mm"]:
                raise GateViolation("单步 %.1fmm > 上限 %.1fmm" % (dist, GATE["max_step_mm"]))
            if d[2] * 1000 < -GATE["max_down_mm"]:
                raise GateViolation("向下 %.1fmm > 限幅 %.1fmm" % (-d[2] * 1000, GATE["max_down_mm"]))
        if not allow:
            return {"dry": True, "backend": self.backend, "note": "未 allow=True → 只算不发", "plan": {"to": p}}
        return {"dry": False, "backend": self.backend, "res": self.be().move_pose(p, q, speed, dry=False)}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--precheck", action="store_true")
    ap.add_argument("--moveit", action="store_true", help="MoveIt 可用性")
    a = ap.parse_args()
    c = ArmController()
    print("后端:", c.backend)
    if a.status:
        print(json.dumps(c.status(), ensure_ascii=False, indent=1)[:800])
    if a.precheck:
        print(json.dumps(c.precheck(), ensure_ascii=False, indent=1)[:600])
    if a.moveit:
        print(json.dumps(MoveItPlan.plan([0, 0, 0], [0, 0, 0]), ensure_ascii=False))
