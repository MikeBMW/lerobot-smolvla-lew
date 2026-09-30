#!/usr/bin/env python3
"""
Z-MAX 硬件自检 — 供 GUI 调用
检测: Orin连接 → 控制器 → 传感器 → 机器人状态
返回: JSON 状态报告

用法:
  python3 hardware_healthcheck.py          # 完整检查
  python3 hardware_healthcheck.py --quick  # 快速检查(仅连接)
"""
import subprocess, json, time, argparse, sys, os

ORIN = "192.168.23.10"
CTRL = "192.168.23.160"

def check(name, cmd, timeout=3):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, r.stdout.strip()[:100]
    except:
        return False, "timeout"

def run():
    results = {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "checks": []}

    # L1: 网络
    ok, out = check("Mac→Orin", ["ping","-c1","-W2",ORIN])
    results["checks"].append({"layer":"L1","name":"Mac→Orin","ok":ok,"detail":f"{out}"})

    ok, out = check("Orin→控制器", ["ssh","-o","ConnectTimeout=3",f"nvidia@{ORIN}","ping -c1 -W1 192.168.23.160 2>&1"], timeout=8)
    results["checks"].append({"layer":"L1","name":"控制器","ok":ok,"detail":out[:80]})

    # L2: ROS2
    ok, out = check("ROS2节点", ["ssh","-o","ConnectTimeout=3",f"nvidia@{ORIN}",
        "source /opt/ros/humble/setup.bash && ros2 node list 2>/dev/null | wc -l"], timeout=8)
    count = out.strip() if ok else "0"
    results["checks"].append({"layer":"L2","name":"ROS2节点","ok":ok and int(count)>0,"detail":f"{count} nodes"})

    # L3: 传感器
    ok, out = check("RealSense", ["ssh","-o","ConnectTimeout=3",f"nvidia@{ORIN}",
        "python3 -c 'import pyrealsense2 as rs; print(len(rs.context().devices))' 2>&1"], timeout=8)
    results["checks"].append({"layer":"L3","name":"相机","ok":ok and "1" in out,"detail":out[:20]})

    # L4: 关节
    ok, out = check("关节数据", ["ssh","-o","ConnectTimeout=3",f"nvidia@{ORIN}",
        "source /opt/ros/humble/setup.bash && source ~/0615/tashan_robot_so_20260630_163849_f98c30a_aarch64/install/setup.bash && export ROS_DOMAIN_ID=23 && timeout 3 ros2 topic echo /real_joint_states --once 2>/dev/null | grep -c position:"], timeout=10)
    count = out.strip() if ok else "0"
    results["checks"].append({"layer":"L4","name":"关节","ok":ok and int(count)>0,"detail":f"axes={count}"})

    # L5: 安全
    ok, out = check("急停", ["ssh","-o","ConnectTimeout=3",f"nvidia@{ORIN}",
        "source /opt/ros/humble/setup.bash && source ~/0615/tashan_robot_so_20260630_163849_f98c30a_aarch64/install/setup.bash && export ROS_DOMAIN_ID=23 && timeout 2 ros2 topic echo /emergency_stop --once 2>/dev/null | tail -1"], timeout=8)
    results["checks"].append({"layer":"L5","name":"急停","ok":ok,"detail":out[:30],"warning":"true" in out.lower()})

    # 汇总
    all_ok = all(c["ok"] for c in results["checks"])
    results["status"] = "READY" if all_ok else "DEGRADED"
    results["all_ok"] = all_ok

    return results

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--quick", action="store_true")
    args = p.parse_args()

    if args.quick:
        # 仅L1网络检查
        ok, _ = check("Mac→Orin", ["ping","-c1","-W1",ORIN])
        print(json.dumps({"status":"QUICK","orin_online":ok}))
        return

    results = run()
    print(json.dumps(results, indent=2, ensure_ascii=False))

    # 保存
    path = os.path.expanduser("~/lerobot-smolvla-lew/docs/web/hardware-health.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # 终端状态
    for c in results["checks"]:
        icon = "✅" if c["ok"] else "❌"
        warn = " ⚠️" if c.get("warning") else ""
        print(f"{icon} {c['layer']} {c['name']}: {c['detail']}{warn}")

if __name__ == "__main__":
    main()
