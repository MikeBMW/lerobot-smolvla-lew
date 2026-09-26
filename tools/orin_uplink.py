#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""orin_uplink.py — Orin 侧只读遥测上行 (A1 授权 2026-09-26)

作用: 每 5s 把 **Orin 本机真实状态** 发到 https://datadrive.world/api/relay/orin/heartbeat
      → 云端 `/api/relay/orin/status` 变 online:true, 网页/APP 能看到机器人侧状态。

=== 红线 (orins 零自研零自启的例外: 老倪 2026-09-26 明确授权 A1) ===
  · **只读**: 读 /proc /sys / uptime / 静态进程表; 另用 `ros2 topic echo --once` **只订阅** /robot_status
  · **零动作**: 不调任何 service、不发任何 topic、不碰 robot_driver/motion
  · **可回滚**: 停了 unit 删了文件即无残留; 不注册任何开机依赖 (systemd unit 可 disable)

字段口径 (如实, 拿不到就给 null, 绝不编造):
  online / uptime_s / cpu_temp_c / mem_used_mb / mem_total_mb / load1
  robot_stack: robot_driver + motion 是否在跑 (静态进程表判定)
  robot: /robot_status 的 power_state / operation_state / has_error / error_code (只读订阅, 失败则 null)
  infer_count / model = null  ← **Orin 上没有推理服务** (生产栈=robot_driver+motion), 如实标 null
用法: python3 orin_uplink.py [--once|--watch] [--interval 5] [--robot-interval 30]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

URL = os.environ.get("ZMAX_RELAY_ORIN", "https://datadrive.world/api/relay/orin/heartbeat")
HOST = os.environ.get("ZMAX_HOST_NAME", "orin-192.168.23.66")


def _read(path, cast=float):
    try:
        with open(path, encoding="utf-8") as f:
            return cast(f.read().strip())
    except Exception:                                                          # noqa: BLE001
        return None


def _ps_grep(names):
    try:
        out = subprocess.run(["ps", "-eo", "cmd"], capture_output=True, text=True, timeout=6).stdout
    except Exception:                                                          # noqa: BLE001
        return {n: None for n in names}
    return {n: any(n in l and "grep" not in l for l in out.splitlines()) for n in names}


def _robot_state():
    """只读订阅 /robot_status --once → 正则直取关键字段

    ⚠️ 该消息很长 (含 controller_error_logs), 实测会被截断 → **不能用 json.loads**, 用正则直取
    """
    import re as _re
    try:
        r = subprocess.run(["bash", "-lc",
                            "source /opt/ros/humble/setup.bash 2>/dev/null; "
                            "for ws in /home/tashan/0810/*/install/setup.bash; do [ -f \"$ws\" ] && source \"$ws\" && break; done; "
                            "export ROS_DOMAIN_ID=0; timeout 20 ros2 topic echo --once --no-daemon /robot_status 2>/dev/null"],
                           capture_output=True, text=True, timeout=26)
        txt = r.stdout or ""
        if "power_state" not in txt:
            # 如实记因: 服务上下文 DDS 发现慢/话题未就绪 时到此 (不静默)
            print("[%s] ⚠ robot 状态未取到 (rc=%s, 收到 %dB, stderr=%s)" %
                  (time.strftime("%H:%M:%S"), r.returncode, len(txt), (r.stderr or "")[:80]), flush=True)
            return None

        def _val(field):
            """纯字符串查找: 找 "field": 之后第一个引号内的值 (对消息截断免疫)"""
            i = txt.find('"%s"' % field)
            if i < 0:
                return None
            j = txt.find('"', i + len(field) + 2)
            if j < 0:
                return None
            k = txt.find('"', j + 1)
            return txt[j + 1:k] if k > j else None

        out = {}
        for f in ("power_state", "operation_state", "error_code"):
            v = _val(f)
            if v is not None:
                out[f] = v
        m = _re.search(r'"has_error"\s*:\s*(true|false)', txt)
        if m:
            out["has_error"] = (m.group(1) == "true")
        return out or None
    except Exception:                                                          # noqa: BLE001
        return None


def snap(robot=None, robot_ts=None):
    mem = {}
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for ln in f:
                k, v = ln.split(":", 1)
                mem[k.strip()] = int(v.strip().split()[0]) // 1024
    except Exception:                                                          # noqa: BLE001
        pass
    t = _read("/sys/class/thermal/thermal_zone0/temp")
    procs = _ps_grep(["robot_driver", "motion"])
    d = {
        "online": True, "source": "orin", "host": HOST, "ts": time.strftime("%F %T"),
        "uptime_s": round(_read("/proc/uptime", lambda s: float(s.split()[0])) or 0, 0),
        "cpu_temp_c": round(t / 1000.0, 1) if isinstance(t, (int, float)) else None,
        "mem_used_mb": (mem.get("MemTotal", 0) - mem.get("MemAvailable", 0)) or None,
        "mem_total_mb": mem.get("MemTotal") or None,
        "load1": _read("/proc/loadavg", lambda s: float(s.split()[0])),
        "robot_stack": procs,
        "ros_domain": os.environ.get("ROS_DOMAIN_ID", "0"),
        # ⚠️ 如实: Orin 上没有推理服务 → 这两项就是 null (云端能区分"没读到"与"读到 0")
        "infer_count": None, "model": None,
        "note": "只读遥测 · 生产栈=robot_driver+motion · 本脚本不参与任何动作",
    }
    # 🐛 2026-09-26: 原实现 robot 只在采样那一次带上, 之后 5 次都发 None → **把云端好数据覆盖成 null**。
    #    改为"记住上次采样, 每次心跳都带上"(附带 robot_ts 标明采样时刻, 不谎称是实时)
    d["robot"] = robot
    d["robot_ts"] = robot_ts
    return d


def post(d):
    req = urllib.request.Request(URL, data=json.dumps(d).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read().decode() or "{}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--robot-interval", type=float, default=30.0)
    ap.add_argument("--dry", action="store_true", help="只打印不上传")
    a = ap.parse_args()
    if not (a.once or a.watch):
        a.once = True
    last_robot = 0.0
    robot_cache, robot_ts = None, None
    while True:
        now = time.time()
        if (now - last_robot) >= a.robot_interval:
            last_robot = now
            robot_cache = _robot_state()
            robot_ts = time.strftime("%F %T")
        d = snap(robot=robot_cache, robot_ts=robot_ts)
        if a.dry:
            print(json.dumps(d, ensure_ascii=False))
        else:
            try:
                r = post(d)
                print("[%s] ⬆ ok=%s %s | 温度 %s°C · 内存 %s/%sMB · robot %s" %
                      (time.strftime("%H:%M:%S"), r.get("ok"), r.get("seq", ""), d["cpu_temp_c"],
                       d["mem_used_mb"], d["mem_total_mb"], json.dumps(d.get("robot"), ensure_ascii=False)), flush=True)
            except Exception as e:                                              # noqa: BLE001
                print("[%s] ⬆ 失败: %s: %s" % (time.strftime("%H:%M:%S"), type(e).__name__, str(e)[:100]), flush=True)
        if not a.watch:
            return 0
        time.sleep(a.interval)


if __name__ == "__main__":
    raise SystemExit(main())
