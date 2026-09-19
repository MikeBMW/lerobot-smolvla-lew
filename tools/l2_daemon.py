#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l2_daemon.py — L2 原子技能常驻执行器 (立即动作, 不再每条指令重连)

架构: 两条常驻 ssh 通道
  A) 命令通道: bash 循环读 stdin -> 直接 eval ROS2 服务调用 (环境只 source 一次)
  B) 状态通道: 循环读 /robot/tcp_pose -> 维护当前位姿缓存 (供相对技能算目标)
接口: FIFO ~/zmax_data/l2_cmd.fifo  (一行一条 JSON: {"skill":"L2.lift","d_mm":100})
"""
import json, os, re, subprocess, sys, threading, time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = "tashan@192.168.23.66"
FIFO = os.path.expanduser("~/zmax_data/l2_cmd.fifo")
LOG = os.path.expanduser("~/zmax_data/l2_daemon.log")
PRE = ("source /opt/ros/humble/setup.bash; for ws in /home/tashan/0810/*/install/setup.bash; "
       "do [ -f \"$ws\" ] && source \"$ws\" && break; done; export ROS_DOMAIN_ID=0; ")

_pose = {"p": None, "q": None, "t": 0.0}

def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def state_thread():
    cmd = PRE + "while true; do ros2 topic echo --once /robot/tcp_pose --field pose 2>/dev/null; sleep 0.5; done"
    p = subprocess.Popen(["ssh", "-o", "BatchMode=yes", HOST, cmd], stdout=subprocess.PIPE, text=True, bufsize=1)
    buf = []
    for ln in p.stdout:
        s = ln.strip()
        if s.startswith("---"):
            continue
        if ":" in s:
            try:
                buf.append(float(s.split(":", 1)[1]))
            except ValueError:
                continue
        if len(buf) >= 7:
            _pose["p"] = buf[:3]
            _pose["q"] = buf[3:7]
            _pose["t"] = time.time()
            buf = []


def build_move(sk, spec, pts):
    p, q = _pose["p"], _pose["q"]
    if not p or not q:
        return None
    t = list(p)
    if sk["ros"] == "line_rel":
        d = float(spec.get("d_mm", sk["param"]["d_mm"].get("default", 50))) / 1000.0
        a = sk["axis"]
        if a == "z_pos":
            t[2] = p[2] + abs(d)
        elif a == "z_neg":
            t[2] = p[2] - abs(d)
        elif a == "x":
            t[0] = p[0] + d
        elif a == "y":
            t[1] = p[1] + d
    elif sk["ros"] == "line_abs":
        name = spec.get("point", sk["param"]["point"].get("default", "home"))
        if name not in pts:
            return None
        t = list(pts[name]["pos"])
    return (t, q)


def dispatch(reg, spec, chan):
    sid = spec.get("skill", "")
    sk = {s["id"]: s for s in reg["skills"]}.get(sid)
    if not sk:
        log("拒绝: 未知技能 %s" % sid)
        return "未知技能: %s" % sid
    if sk.get("ros") == "http":
        url = sk.get("url", "")
        method = sk.get("method", "POST")
        try:
            req = urllib.request.Request(url, data=(b"" if method == "POST" else None), method=method)
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8", "ignore")
                code = r.status
            dt = (time.time() - t0) * 1000
            log("HTTP %s → %s (%.0fms) %s" % (url, code, dt, body[:400]))
            return "HTTP %s → %s (%.0fms) 返回: %s" % (url, code, dt, body[:300].replace("\n", " "))
        except Exception as e:
            log("HTTP 失败 %s: %s" % (url, e))
            return "HTTP 失败: %s" % e
    if sk["ros"] == "gripper":
        if "close" in sid:
            fo = float(spec.get("force", sk["param"]["force"].get("default", 40)))
            call = ('ros2 service call /gripper_driver interfaces/srv/GripperSrv "{target_pos: 0.0, '
                    'target_speed: -1.0, target_force: %s, target_acc: -1.0, target_push_length: -1.0, '
                    'target_push_speed: -1.0}"' % fo)
        else:
            call = ('ros2 service call /gripper_driver interfaces/srv/GripperSrv "{target_pos: 1000.0, '
                    'target_speed: -1.0, target_force: -1.0, target_acc: -1.0, target_push_length: -1.0, '
                    'target_push_speed: -1.0}"')
    else:
        pts = {}
        try:
            pts = json.load(open(os.path.join(REPO, "data/skills/l2_muscle/光模块_抓放_演示学习_v1.json"), encoding="utf-8"))["points"]
        except Exception:
            pts = {}
        r = build_move(sk, spec, pts)
        if not r:
            log("拒绝: 位姿缓存未就绪或点位不存在")
            return "位姿缓存未就绪"
        (x, y, z), (qx, qy, qz, qw) = r[0], r[1]
        sp = float(spec.get("speed", 60))
        call = ('ros2 service call /move_line interfaces/srv/TargetPose "{speed: %s, joint_state: {name: [], '
                'position: []}, pose: {position: {x: %s, y: %s, z: %s}, orientation: {x: %s, y: %s, z: %s, w: %s}}}"'
                % (sp, x, y, z, qx, qy, qz, qw))
    chan.stdin.write(call + "\n")
    chan.stdin.flush()
    log("已下发 %s -> %s" % (sid, (spec.get("d_mm", spec.get("force", spec.get("point", ""))))))
    return "已下发"


def out_thread(chan):
    for ln in chan.stdout:
        ln = ln.strip()
        if ln:
            log("ROS: " + ln[:200])


def main():
    if os.path.exists(FIFO):
        os.unlink(FIFO)
    os.mkfifo(FIFO)
    reg = json.load(open(os.path.join(REPO, "data/skills/l2_atomic/registry.json"), encoding="utf-8"))
    threading.Thread(target=state_thread, daemon=True).start()
    loop = PRE + 'while read -r c; do eval "$c"; done'
    chan = subprocess.Popen(["ssh", "-o", "BatchMode=yes", HOST, loop],
                            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)
    threading.Thread(target=out_thread, args=(chan,), daemon=True).start()
    log("L2 常驻执行器启动 · FIFO=%s · 原子技能 %d 个" % (FIFO, len(reg["skills"])))
    while True:
        with open(FIFO, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    spec = json.loads(line)
                except Exception:
                    log("无效指令: %s" % line[:80])
                    continue
                try:
                    log("受理: " + dispatch(reg, spec, chan))
                except Exception as e:
                    log("执行异常: %s" % e)


if __name__ == "__main__":
    main()
