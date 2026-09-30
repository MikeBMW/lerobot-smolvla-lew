#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rokae_direct_probe.py — 4060 **不经 Orin** 直连珞石控制器的只读探针 (2026-09-21 实测通)

背景 / 结论 (2026-09-21):
  老倪问「能不能不启动 Orin 上的工程, 由本机从头控制机械臂」。第一步(读)已实证:
  4060 用厂家 xCoreSDK 的 **x86_64** 版直连控制器 192.168.23.160, 0.09s 连通,
  读到的关节角与 Orin 上 /real_joint_states **最大偏差 0.96 µrad**(同一真值源),
  TCP 位姿与 /robot/tcp_pose **逐位一致**(endInRef = 工具系在参考系, 即产线口径)。

怎么跑 (SDK 是 cpython-310, 本机 3.12 不行 → 用 python3.10 容器):
  # SDK 从 Orin 拷一份 (含 arm 与 x86_64 两套 .so):
  #   ssh tashan@192.168.23.66 "cd .../robot_driver/lib/python3.10/site-packages/robot_driver/rokae && tar -cf - xcoresdk_python" | tar -C ~/zmax_data/rokae_sdk -xf -
  sudo docker run --rm --network host -v ~/zmax_data/rokae_sdk:/sdk -w /sdk ros:humble-ros-base \
      python3 /sdk/rokae_direct_probe.py

零运动: 只 connectToRobot / jointPos / cartPosture / jointVel / jointTorque / operateMode / disconnect。
⚠️ 尚未实动。接管产线运动前必须先 moveReset(清空已发指令) —— SDK 文档: "RL程序和SDK运动指令切换控制,
   需要先运动重置"; 且直连绕开产线安全层(MES/HMI/急停互锁), 守卫得由本机链路自兜。
"""
import json
import sys

SDK_DIR = "/sdk"
ROBOT_IP = "192.168.23.160"
sys.path.insert(0, SDK_DIR)
import xcoresdk_python as x  # noqa: E402


def main():
    out = {"ip": ROBOT_IP}
    r = x.xMateRobot()                       # XMS5-R800-W4G3B4C → xMateRobot (实测: 其它类会报机型不匹配)
    r.connectToRobot(ROBOT_IP)
    out["robot_model_class"] = "xMateRobot"
    try:
        ec = {}
        out["jointPos_rad"] = [round(float(v), 9) for v in r.jointPos(ec)]
        out["jointVel_rad_s"] = [round(float(v), 9) for v in r.jointVel({})]
        out["jointTorque_Nm"] = [round(float(v), 6) for v in r.jointTorque({})]
        cp = r.cartPosture(x.CoordinateType.endInRef, {})     # 工具系在参考系 = 产线 /robot/tcp_pose 同口径
        out["tcp_endInRef_m"] = [round(float(v), 9) for v in cp.trans]
        out["tcp_endInRef_rpy_rad"] = [round(float(v), 9) for v in cp.rpy]
        out["flangeInBase_m"] = [round(float(v), 9)
                                 for v in r.cartPosture(x.CoordinateType.flangeInBase, {}).trans]
        out["operateMode"] = str(r.operateMode({}))
    finally:
        try:
            r.disconnectFromRobot({})
            out["disconnect"] = "ok"
        except Exception as e:                                            # noqa: BLE001
            out["disconnect_err"] = str(e)[:120]
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
