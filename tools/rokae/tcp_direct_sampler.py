#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tcp_direct_sampler.py — 本机(4060) 不经 Orin/DDS 直连珞石控制器读 TCP 位姿真值, 持续采样落盘。

为什么存在 (2026-09-28):
  Orin 上 /robot/tcp_pose 的发布者 (tactile_force_node, 09-27 20:52 起) 的 DDS 参与者已不再
  对外通告端点 —— `ros2 topic info /robot/tcp_pose --no-daemon` = Publisher count 0,
  `ros2 node list --no-daemon` 里连 robot_driver/motion/tactile_force_node 都没有了。
  ⇒ 任何"新"订阅者在 Orin 本机 / 局域网 / 容器里都收不到 0 帧 (QoS/domain/SHM 全不是原因)。
  唯一还活的口子 = 直接问控制器要编码器真值 (本文件)。

口径 (关键):
  * 与产线 /robot/tcp_pose **同口径**: CoordinateType.endInRef = 工具系在参考系;
    2026-09-21 实测逐位一致 (见 tools/rokae_direct_probe.py 头注 / rokae-direct-control 技能)。
  * 姿态换算与 tactile_force_node 的 euler_to_quaternion 逐行相同 (Euler ZYX → qx,qy,qz,qw),
    所以本文件产出的 (x,y,z,qx..qw) 可直接与 /robot/tcp_pose 对比。
  * 只读: connectToRobot / posture / jointPos / disconnect —— 全程不发任何运动指令。

用法 (SDK 是 cpython-310 → 必须用 python3.10 容器):
  sudo docker run --rm --network host -v ~/zmax_data/rokae_sdk:/sdk -w /sdk \
      ros:humble-ros-base python3 /sdk/tcp_direct_sampler.py --rate 5 --secs 600
产出:
  /sdk/tcp_out/tcp_direct_YYYYMMDD.jsonl  每行一次采样
  /sdk/tcp_out/latest.json                最新一次 (供本地毫秒级读)
"""
import argparse
import json
import math
import os
import sys
import time

SDK_DIR = os.environ.get("ROKAE_SDK_DIR", "/sdk")
ROBOT_IP = os.environ.get("ROKAE_IP", "192.168.23.160")
sys.path.insert(0, SDK_DIR)
import xcoresdk_python as x  # noqa: E402


def euler_to_quaternion(rx, ry, rz):
    """与 tactile_force_node.euler_to_quaternion 逐行相同 (Euler ZYX → qx,qy,qz,qw)"""
    cr, sr = math.cos(rx * 0.5), math.sin(rx * 0.5)
    cp, sp = math.cos(ry * 0.5), math.sin(ry * 0.5)
    cy, sy = math.cos(rz * 0.5), math.sin(rz * 0.5)
    qw = cy * cp * cr + sy * sp * sr
    qx = cy * cp * sr - sy * sp * cr
    qy = sy * cp * sr + cy * sp * cr
    qz = sy * cp * cr - cy * sp * sr
    return qx, qy, qz, qw


def read_tcp6(robot, ct):
    """优先 posture() (与 tactile_force_node 同一个调用); 不行退回 cartPosture()"""
    try:
        p = robot.posture(ct, {})
        if p and len(p) >= 6:
            return [float(v) for v in p[:6]]
    except Exception:
        pass
    cp = robot.cartPosture(ct, {})
    return [float(v) for v in list(cp.trans) + list(cp.rpy)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=float, default=5.0, help="采样率 Hz (默认 5; 控制器 SDK 会话是共享资源, 别开太高)")
    ap.add_argument("--secs", type=float, default=600.0,
                    help="持续秒数 (默认 600 = 10 分钟; **0 = 一直跑** —— 位姿/三查都是真机唯一活口, 别让它到期自停)")
    ap.add_argument("--out", default=os.path.join(SDK_DIR, "tcp_out"))
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    day = time.strftime("%Y%m%d")
    path = os.path.join(args.out, "tcp_direct_%s.jsonl" % day)
    latest = os.path.join(args.out, "latest.json")
    state_f = os.path.join(args.out, "state.json")     # 三查(上电/运行/报警)缓存 —— 与位姿同源同会话
    t_state, n_state = 0.0, 0
    ct = x.CoordinateType.endInRef          # 工具系在参考系 = 产线 /robot/tcp_pose 口径

    robot = None

    def connect():
        r = x.xMateRobot()
        r.connectToRobot(ROBOT_IP)
        return r

    t_conn = time.time()
    robot = connect()
    print("[tcp_direct] 控制器 %s 已连接 (%.3fs) · 口径 endInRef · 输出 %s"
          % (ROBOT_IP, time.time() - t_conn, path), flush=True)

    period = 1.0 / max(args.rate, 0.1)
    n = errs = 0
    t0 = time.time()
    next_t = t0
    f = open(path, "a", buffering=1)
    last6 = None
    try:
        while args.secs <= 0 or time.time() - t0 < args.secs:      # --secs 0 = 一直跑(位姿与三查都是唯一活口)
            next_t += period
            try:
                p6 = read_tcp6(robot, ct)
                if all(abs(float(v)) < 1e-6 for v in p6[:3]):
                    # 🔴 2026-09-29 现场事故: SDK 会话陈旧时 posture() **静默返回全 0**(不抛异常) ⇒
                    #   不判这一点就永远不触发重连, 而 latest.json 会被 0 值覆盖 ⇒
                    #   执行器(l2_daemon._pose_direct)看到"位置全 0"判为无效 → 「位姿读不到」拒发所有技能
                    #   (现象: 点『回到金手指点1』等按钮一律拒绝)。把全 0 当读失败, 走下面的重连逻辑。
                    raise RuntimeError("SDK 返回全 0 位姿(会话疑似陈旧, 需重连)")
                jp = None
                try:
                    jp = [round(float(v), 9) for v in robot.jointPos({})]
                except Exception:
                    pass
                ts = time.time()
                qx, qy, qz, qw = euler_to_quaternion(p6[3], p6[4], p6[5])
                rec = {
                    "ts": round(ts, 4),
                    "t": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) + (".%03d" % int(ts * 1000 % 1000)),
                    "x": round(p6[0], 6), "y": round(p6[1], 6), "z": round(p6[2], 6),
                    "rx": round(p6[3], 6), "ry": round(p6[4], 6), "rz": round(p6[5], 6),
                    "qx": round(qx, 6), "qy": round(qy, 6), "qz": round(qz, 6), "qw": round(qw, 6),
                    "frame": "base_link",
                    "src": "rokae_xcoresdk/endInRef (direct, no DDS)",
                    "joint": jp,
                }
                f.write(json.dumps(rec) + "\n")
                tmp = latest + ".tmp"
                with open(tmp, "w") as g:
                    g.write(json.dumps(rec))
                os.replace(tmp, latest)
                # ── 三查(上电/运行/报警)也走这条直连活路 ──
                # 2026-10-01 老倪: 「我在现场，怎么还是43小时的数据，赶快更新啊」
                # 背景: 页面三查原只读 Orin 的 /robot_status 话题缓存, 而该发布者 09-29 起不再通告端点
                #   ⇒ robot_status.json 停在 09-29 13:46(42h)。本会话一直新鲜, 所以三查改从这里出:
                #   上电/运行 = SDK 原生; 报警 = **控制器日志**(带时间戳, 是真值 —— 不推测"无碰撞")。
                if time.time() - t_state >= 2.0:
                    t_state = time.time()
                    st = {"ts": round(t_state, 4),
                          "t": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t_state)),
                          "src": "rokae_xcoresdk/direct", "ip": ROBOT_IP}
                    for fld, fn in (("power", lambda: str(robot.powerState({}))),
                                    ("mode", lambda: str(robot.operateMode({}))),
                                    ("op", lambda: str(robot.operationState({})))):
                        try:
                            st[fld] = fn().split(".")[-1]
                        except Exception as e:                                # noqa: BLE001
                            st[fld + "_err"] = str(e)[:60]
                    try:
                        _e = robot.queryControllerLog(12, {x.LogInfoLevel.error}, {})
                        st["n_err_recent"] = len(_e)
                        _rows = [{"id": int(getattr(_L, "id", 0) or 0),
                                  "ts": str(getattr(_L, "timestamp", "")),
                                  "content": str(getattr(_L, "content", ""))[:140],
                                  "repair": str(getattr(_L, "repair", ""))[:120]} for _L in _e]
                        st["recent"] = _rows[:6]
                        if _rows:
                            st["last_alarm"] = _rows[0]
                        # 碰撞/急停是单独一类: 就算后面又刷了别的报警, 也要把"上一次撞"留着(老倪: 记住每一次碰撞)
                        for _r in _rows:
                            if _r["id"] in (13036, 30400, 13013):
                                st["last_collision" if _r["id"] != 13013 else "last_estop"] = _r
                                break
                    except Exception as e:                                    # noqa: BLE001
                        st["log_err"] = str(e)[:60]
                    _t = state_f + ".tmp"
                    with open(_t, "w") as g:
                        g.write(json.dumps(st, ensure_ascii=False))
                    os.replace(_t, state_f)
                    n_state += 1
                n += 1
                last6 = p6
                print("%03d %s x=%.6f y=%.6f z=%.6f | rpy=(%.4f,%.4f,%.4f)"
                      % (n, rec["t"], rec["x"], rec["y"], rec["z"], rec["rx"], rec["ry"], rec["rz"]), flush=True)
            except Exception as e:                                             # noqa: BLE001
                errs += 1
                print("[tcp_direct] 读失败 %d 次: %r" % (errs, str(e)[:120]), flush=True)
                if errs % 5 == 0:
                    try:
                        robot.disconnectFromRobot({})
                    except Exception:
                        pass
                    time.sleep(1.0)
                    try:
                        robot = connect()
                        print("[tcp_direct] 已重连", flush=True)
                    except Exception as e2:                                    # noqa: BLE001
                        print("[tcp_direct] 重连失败: %r" % (str(e2)[:120],), flush=True)
            d = next_t - time.time()
            if d > 0:
                time.sleep(d)
            elif d < -2.0:
                next_t = time.time()          # 落后太多就重新对齐节拍(不追积分)
    finally:
        f.close()
        try:
            robot.disconnectFromRobot({})
        except Exception:
            pass
        el = time.time() - t0
        print("[tcp_direct] 结束: %d 样本 / %.1fs = %.2fHz (目标 %.1fHz) · 读失败 %d 次"
              % (n, el, n / max(el, 1e-9), args.rate, errs), flush=True)
        if last6:
            print("[tcp_direct] 最后一位姿 x=%.6f y=%.6f z=%.6f" % (last6[0], last6[1], last6[2]), flush=True)


if __name__ == "__main__":
    main()
