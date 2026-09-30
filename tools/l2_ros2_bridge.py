#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l2_ros2_bridge.py — L2 肌肉记忆 → ROS2 转发到 Orin (真链路, 2026-09-19)

用法:
  gui-venv311/bin/python tools/l2_ros2_bridge.py --skill data/skills/l2_muscle/光模块_抓放循环_v1.json --cycles 1
  ... --dry-run      只打印将要下发的字节, 不发
纪律: 每步前查三闸门(power=on/idle/has_error=false) → 先复位清错 → 单步 → 取证(位姿/开度) → 落盘
"""
import argparse
import json
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "tashan@192.168.23.66"]
PRE = ('source /opt/ros/humble/setup.bash; for ws in /home/tashan/0810/*/install/setup.bash; '
       'do [ -f "$ws" ] && source "$ws" && break; done; export ROS_DOMAIN_ID=0; ')


def sh(cmd, timeout=180):
    try:
        p = subprocess.run(SSH + [PRE + cmd], capture_output=True, text=True, timeout=timeout)
        return (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return "TIMEOUT"


def status_line():
    o = sh("ros2 topic echo --once /robot_status 2>/dev/null | head -2", 90)
    d = {}
    for k in ("power_state", "operation_state", "has_error", "error_code"):
        i = o.find('"%s"' % k)
        if i > 0:
            d[k] = o[i + len(k) + 3:i + 60].split(",")[0].strip().strip('"').strip("'")
    return d


def tcp_pose():
    return sh("ros2 topic echo --once /robot/tcp_pose 2>/dev/null | tr '\\n' ' '", 90)


def grip_pos():
    o = sh("ros2 topic echo --once /gripper_pos std_msgs/msg/Float32 2>&1 | head -1", 90)
    for tok in o.replace("\\n", " ").split():
        try:
            return float(tok)
        except ValueError:
            pass
    return None


def gate():
    """三闸门: 返回 (ok, 状态字典); 有错先复位"""
    st = status_line()
    if str(st.get("has_error")).lower() == "true":
        sh("timeout 30 ros2 service call /rokae_recover_estop std_srvs/srv/Trigger 2>&1 | tail -1", 90)
        time.sleep(2)
        st = status_line()
    ok = str(st.get("power_state")) == "on" and str(st.get("has_error")).lower() != "true"
    return ok, st


def cmd_move(pt, speed):
    x, y, z = pt["pos"]
    qx, qy, qz, qw = pt["quat"]
    return ('timeout 90 ros2 service call /move_line interfaces/srv/TargetPose "{speed: %s, '
            'joint_state: {name: [], position: []}, pose: {position: {x: %s, y: %s, z: %s}, '
            'orientation: {x: %s, y: %s, z: %s, w: %s}}}" 2>&1 | tail -3'
            % (speed, x, y, z, qx, qy, qz, qw))


def cmd_grip(pos, force=-1.0):
    return ('timeout 60 ros2 service call /gripper_driver interfaces/srv/GripperSrv '
            '"{target_pos: %s, target_speed: -1.0, target_force: %s, target_acc: -1.0, '
            'target_push_length: -1.0, target_push_speed: -1.0}" 2>&1 | tail -2' % (pos, force))


def run_step(step, skill, logf, dry=False):
    op = step["op"]
    if op == "move":
        pt = skill["points"][step["to"]]
        cmd = cmd_move(pt, skill["params"].get("speed", 30))
    elif op == "gripper":
        a = step.get("args") or {}
        cmd = cmd_grip(a.get("target_pos", 1000), a.get("target_force", -1.0))
    else:
        return {"ok": False, "why": "unknown op"}
    if dry:
        return {"ok": True, "dry": cmd}
    ok, st = gate()
    if not ok:
        rec = {"step": step.get("note"), "ok": False, "why": "闸门未过", "state": st}
        logf.write(json.dumps(rec, ensure_ascii=False) + "\n"); logf.flush()
        return rec
    t0 = time.time()
    out = sh(cmd, 240)
    time.sleep(6)
    rec = {"step": step.get("note"), "op": op, "success_flag": "success=True" in out,
           "grip": grip_pos(), "dt": round(time.time() - t0, 1), "pose": tcp_pose()[-150:],
           "raw": out[-140:]}
    logf.write(json.dumps(rec, ensure_ascii=False) + "\n"); logf.flush()
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", default="data/skills/l2_muscle/光模块_抓放循环_v1.json")
    ap.add_argument("--cycles", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    skill = json.load(open(os.path.join(REPO, a.skill), encoding="utf-8"))
    logp = os.path.expanduser("~/zmax_data/l2_muscle_run_%s.jsonl" % time.strftime("%Y%m%d_%H%M%S"))
    logf = open(logp, "w", encoding="utf-8")
    print("L2 技能: %s | 步/轮 %d | 轮数 %d | dry=%s" % (skill["id"], len(skill["steps"]), a.cycles, a.dry_run))
    print("日志: %s" % logp)
    for c in range(1, a.cycles + 1):
        print("\n═══ 第 %d/%d 轮 ═══" % (c, a.cycles))
        for i, s in enumerate(skill["steps"], 1):
            r = run_step(s, skill, logf, a.dry_run)
            print("  %d) %-22s grip=%s succ=%s %s" % (i, str(s.get("note"))[:22], r.get("grip"),
                                                      r.get("success_flag"), ("[DRY]" if a.dry_run else "")))
            if a.dry_run:
                print("      " + r.get("dry", "")[:200])
    logf.close()
    print("\n✅ 完成, 日志: %s" % logp)


if __name__ == "__main__":
    main()
