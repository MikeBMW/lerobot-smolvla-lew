#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_j6_axis.py — 离線证明「沿 J6 轴旋转」的等效笛卡尔公式 = 真正的第 6 轴自转 (零运动)

背景: 8793 手动控制台要加「第 6 轴 (J6) 独立自转 · 逆时针/顺时针」按钮。
现有 A/B/C 三个按钮走 pose_rot (绕**工具**轴旋转, TCP 不动) —— 实测 J6 轴在工具系里
是 (-0.625, +0.029, +0.780), 与工具 X/Y/Z 分别差 51.3°/88.3°/38.7° ⇒ **没有任何一个现有按钮
能转 J6**。而走关节通道 (/target_relative_joint) 动作后驱动会**伺服下电**(老倪已投诉过),
所以改用 /move_pose 下发「绕 J6 轴线旋转」的等效笛卡尔目标 (该通道实测不掉电)。

本脚本用现场 URDF 做 FK, 逐条核对公式 (全程离线, 不碰机器人):
  ① 由 TCP 位姿反算法兰原点 p_flange = p_tcp − R_tool·t_offset   (t_offset = URDF tool0→tool1 平移)
  ② J6 轴在工具系的方向 a_tool = R_offset^T·[0,0,1]              (常数, 与姿态无关)
  ③ 绕轴 (p_flange, R_tool·a_tool) 转 θ → (p_new, q_new)
  ④ 与 FK(q, J6+θ) 逐位对比 (判据: 位置差 <1e-9 m, 姿态夹角 <1e-6°)
用法: python3 tools/test_j6_axis.py [--deg 5]
"""
import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ss_fk_xms5 import fk, mul, mv, quat_from_R, T_tool1          # noqa: E402  现场 URDF 几何

T_OFF = list(T_tool1[0])                       # tool0→tool1 平移 (link6 系)
RPY_OFF = T_tool1[1]                           # tool0→tool1 姿态


def rot_axis(axis, deg):
    """罗德里格斯: 绕单位轴 axis 转 deg 的旋转矩阵 (右手定则, base 系)"""
    x, y, z = axis
    n = math.sqrt(x * x + y * y + z * z)
    x, y, z = x / n, y / n, z / n
    t = math.radians(deg)
    c, s = math.cos(t), math.sin(t)
    C = 1 - c
    return [[c + x * x * C, x * y * C - z * s, x * z * C + y * s],
            [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
            [z * x * C - y * s, z * y * C + x * s, c + z * z * C]]


def quat_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return [aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz]


def axis_quat(axis, deg):
    x, y, z = axis
    n = math.sqrt(x * x + y * y + z * z)
    h = math.radians(deg) / 2.0
    s = math.sin(h)
    return [x / n * s, y / n * s, z / n * s, math.cos(h)]


def R_of_rpy(r, p, y):
    def rx(a):
        c, s = math.cos(a), math.sin(a)
        return [[1, 0, 0], [0, c, -s], [0, s, c]]

    def ry(a):
        c, s = math.cos(a), math.sin(a)
        return [[c, 0, s], [0, 1, 0], [-s, 0, c]]

    def rz(a):
        c, s = math.cos(a), math.sin(a)
        return [[c, -s, 0], [s, c, 0], [0, 0, 1]]
    return mul(rz(y), mul(ry(p), rx(r)))


R_OFF = R_of_rpy(*RPY_OFF)
R_OFF_T = [[R_OFF[j][i] for j in range(3)] for i in range(3)]        # R_off^T
A_TOOL = mv(R_OFF_T, [0.0, 0.0, 1.0])                                # J6 轴在**工具系**的方向
T_OFF_TOOL = mv(R_OFF_T, T_OFF)                                      # tool0→tool1 平移, 换到工具系
J6_AXIS_TOOL = A_TOOL                                                # 常数, 与姿态无关


def j6_target(p, R, deg):
    """由 TCP 位姿算「绕 J6 轴转 deg」的等效笛卡尔目标 (这就是 daemon 里要实现的公式)"""
    a_base = mv(R, J6_AXIS_TOOL)
    p_fl = [p[i] - mv(R, T_OFF_TOOL)[i] for i in range(3)]   # 法兰(link6)原点: p_tcp − R_tool·(t_off in 工具系)
    Rr = rot_axis(a_base, deg)
    d = [p[i] - p_fl[i] for i in range(3)]
    p_new = [p_fl[i] + mv(Rr, d)[i] for i in range(3)]
    q_new = quat_mul(axis_quat(a_base, deg), list(quat_from_R(R)))
    return p_new, q_new, a_base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deg", type=float, default=5.0)
    a = ap.parse_args()
    # 现场实测关节角 (ss_fk_xms5.py 记录的那组, FK 已与 /robot/tcp_pose 对齐到 mm 级)
    Q = [-0.19209894, -0.16929455, -2.34314886, 0.31950399, -0.94447125, 0.24603710]
    R0, p0 = fk(Q, "tool1")
    q0 = quat_from_R(R0)
    print("① J6 轴在工具系的方向 (常数, 与姿态无关) = (%.4f, %.4f, %.4f)" % tuple(J6_AXIS_TOOL))
    for nm, ax in (("工具X(A·俯仰)", (1, 0, 0)), ("工具Y(B·倾侧)", (0, 1, 0)), ("工具Z(C·自转)", (0, 0, 1))):
        d = sum(J6_AXIS_TOOL[i] * ax[i] for i in range(3))
        print("    与 %s 夹角 = %.1f°  ⇒ 现有按钮%s" % (nm, math.degrees(math.acos(max(-1, min(1, abs(d))))),
                                                    "**转不到 J6**" if abs(d) < 0.999 else "可等效"))
    print("\n② 起始: TCP pos=(%.6f, %.6f, %.6f) quat=(%.5f, %.5f, %.5f, %.5f)"
          % (*p0, *q0))
    worst_p = worst_a = 0.0
    for deg in (a.deg, -a.deg, 1.0, 10.0):
        p_new, q_new, a_base = j6_target(p0, R0, deg)
        # 参照真值: FK(同一组关节角, 只把 J6 加 deg)
        q2 = list(Q)
        q2[5] += math.radians(deg)
        R1, p1 = fk(q2, "tool1")
        q1 = quat_from_R(R1)
        dp = math.sqrt(sum((p_new[i] - p1[i]) ** 2 for i in range(3))) * 1000.0
        da = math.degrees(2 * math.acos(max(-1.0, min(1.0, abs(sum(q_new[i] * q1[i] for i in range(4)))))))
        darc = math.sqrt(sum((p_new[i] - p0[i]) ** 2 for i in range(3))) * 1000.0
        worst_p, worst_a = max(worst_p, dp), max(worst_a, da)
        print("   J6 %+6.2f° → 等效目标 vs FK(J6%+.2f°) : 位置差 %.3e mm · 姿态差 %.3e° · TCP 走 %.2f mm"
              % (deg, deg, dp, da, darc))
    print("\n③ 判据: 位置差 <1e-6 mm 且 姿态差 <1e-4° ⇒ 公式 = 纯 J6 自转")
    ok = worst_p < 1e-6 and worst_a < 1e-4
    print("   实测最差: %.3e mm / %.3e° ⇒ %s" % (worst_p, worst_a, "✅ 通过" if ok else "❌ 不通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
