#!/usr/bin/env python3
"""
实时机器人状态采集 → JSON → Git推送
每5秒采集一次 Orin 状态，更新 docs/web/robot-status.json
xspace 的 web 页面读取此JSON进行实时渲染

用法:
  python3 update_robot_status.py              # 单次采集
  python3 update_robot_status.py --watch 5    # 每5秒自动采集
"""
import time, json, os, sys, argparse

def collect_status():
    """采集当前机器人状态"""
    ts = time.time()
    # 尝试从 Orin 读取实时数据
    try:
        import subprocess
        r = subprocess.run([
            "ssh", "-o", "ConnectTimeout=3", "nvidia@192.168.23.10",
            "source /opt/ros/humble/setup.bash && "
            "source ~/0615/tashan_robot_so_20260630_163849_f98c30a_aarch64/install/setup.bash && "
            "export ROS_DOMAIN_ID=23 && "
            "timeout 3 ros2 topic echo /real_joint_states --once 2>/dev/null | grep position: -A6 | tail -6"
        ], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            lines = r.stdout.strip().split('\n')
            positions = [float(l.strip().lstrip('- ').split()[-1]) for l in lines if l.strip()]
            online = True
        else:
            positions = None
            online = False
    except:
        positions = None
        online = False

    # 回退到上次已知数据
    if not positions:
        positions = [0.1602, -0.0615, -2.5455, 1.4469, 0.4350, -0.8225]

    # 构建状态包
    status = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "timestamp_unix": ts,
        "source": "orin_live" if online else "last_known",
        "robot": {
            "model": "XMS5-R800-W4G3B4C",
            "controller_ip": "192.168.23.160",
            "online": online,
            "estop": True,
        },
        "joints": {
            "names": [f"XMS5-R800-W4G3B4C_joint_{i}" for i in range(1,7)],
            "positions_rad": [round(p, 4) for p in positions],
            "velocities": [0]*6,
            "efforts": [0]*6,
        },
        "safety": {"sys0_loaded": True, "estop_active": True},
        "alerts": [
            {"level": "critical", "msg": "急停激活", "code": "ESTOP"}
        ] if not online else []
    }

    path = os.path.expanduser("~/lerobot-smolvla-lew/docs/web/robot-status.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(status, f, indent=2, ensure_ascii=False)
    return status

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", type=int, default=0, help="监控间隔(秒)")
    args = parser.parse_args()

    if args.watch > 0:
        print(f"🔄 每{args.watch}秒采集一次...")
        while True:
            s = collect_status()
            j6 = s["joints"]["positions_rad"][5]
            print(f"  [{s['timestamp']}] J6={j6:.4f} rad  source={s['source']}")
            time.sleep(args.watch)
    else:
        s = collect_status()
        print(json.dumps(s, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
