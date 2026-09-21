#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gravity_torque_check.py — 用现场 URDF 算「当前姿态下各轴的重力力矩」, 与控制器实测对照

目的: 判定 J5 实测 -21.96 Nm (限值 22) 到底是
  (A) 姿态本身的真实重力负载 (⇒ 换姿态就能救) 还是
  (B) 传感器零点/负载模型不符 (⇒ 控制器报警 #41447「力矩传感器与模型偏差较大」那条)

输入: URDF (连杆质量/质心/关节轴) + 实测关节角 + 控制器 toolset 负载(质量/质心)
输出: 各轴重力力矩 (N·m) 与实测并列 + 残差
"""
import math
import numpy as np

# ---- 实测 (2026-09-22, 控制器 SDK 只读) ----
Q = [0.566044304, 0.036935781, -2.400618614, 1.831983161, 0.624965584, -0.719388573]
MEASURED = [28.982556, -15.877123, -25.014848, -11.369649, -21.959517, 0.827337]
RATED = [113, 113, 70, 25, 25, 19]          # URDF joint <limit effort>
FIELD_LIMIT = 22.0                          # 现场 J5 报警线 (2026-09-21 实测 22.013951)

# ---- URDF: 关节 (parent→child origin xyz, axis) 与连杆惯量 ----
JOINTS = [  # name, xyz, axis(unit, in parent frame), link(child) mass, com
    ("J1", (0.0, 0.0, 0.328), (0, 0, 1), 3.167, (1.1e-05, -0.007992, 0.235842)),
    ("J2", (0.0, 0.0, 0.0), (0, 1, 0), 4.291, (0.016666, -0.069301, 0.184671)),
    ("J3", (0.05, 0.0, 0.4), (0, -1, 0), 2.018, (0.0249, 0.009986, 0.083739)),
    ("J4", (-0.05, 0.0, 0.4), (0, 0, 1), 2.005, (6.6e-05, -0.008515, -0.068865)),
    ("J5", (0.0, 0.136, 0.0), (0, -1, 0), 1.507, (3e-06, 0.029173, 0.007019)),
    ("J6", (0.0, 0.0, 0.1035), (0, 0, 1), 0.634, (7.3e-05, 7.9e-05, -0.044853)),
]
TOOL_XYZ = (-0.01588615307905028, 0.018348498948158043, 0.2586775713451509)
TOOL_RPY = (0.03702517838719945, 0.6751675651256659, 2.375248653715161)
# 控制器 toolset 里的负载 (只读到的那一份)
LOAD_MASS = 1.51
LOAD_COG = (0.01617, 0.01289, 0.031170000000000003)
G = np.array([0.0, 0.0, -9.81])


def rpy_to_R(r, p, y):
    cr, sr = math.cos(r), math.sin(r)
    cp, sp = math.cos(p), math.sin(p)
    cy, sy = math.cos(y), math.sin(y)
    Rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
    Ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
    Rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def fk(q):
    """返回每轴 (原点位置, 轴方向(基座系)), 以及末端 tool1 系; 以及各连杆 COG 的世界位置与质量."""
    T = np.eye(4)
    origins, axes, coms = [], [], []
    for i, (name, xyz, ax, m, com) in enumerate(JOINTS):
        # 先平移到关节原点 (子系 = 父系 R 不变, t += xyz) —— 关节旋转前的静态偏移
        Tn = T.copy()
        Tn[:3, 3] = T[:3, 3] + T[:3, :3] @ np.array(xyz, float)
        p_axis = Tn[:3, :3] @ np.array(ax, float)
        origins.append(Tn[:3, 3].copy())
        axes.append(p_axis / np.linalg.norm(p_axis))
        # 关节旋转
        c, s = math.cos(q[i]), math.sin(q[i])
        a = np.array(ax, float); a = a / np.linalg.norm(a)
        K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
        Rj = np.eye(3) + s * K + (1 - c) * (K @ K)
        T = Tn.copy()
        T[:3, :3] = T[:3, :3] @ Rj
        # 该 child link 的 COG (在旋转后的子系里)
        coms.append((T[:3, 3] + T[:3, :3] @ np.array(com, float), m))
    # 末端 tool1
    Tt = T.copy()
    Tt[:3, 3] = T[:3, 3] + T[:3, :3] @ np.array(TOOL_XYZ, float)
    Tt[:3, :3] = T[:3, :3] @ rpy_to_R(*TOOL_RPY)
    p_load = Tt[:3, 3] + Tt[:3, :3] @ np.array(LOAD_COG, float)
    coms.append((p_load, LOAD_MASS))
    return origins, axes, coms, Tt


def main():
    origins, axes, coms, Tt = fk(Q)
    print("姿态 (rad):", [round(v, 4) for v in Q])
    print(f"末端 tool1 位置: {np.round(Tt[:3,3], 4)}  (控制器 endInRef 实测 [0.6623, 0.1262, 0.2928])")
    print(f"负载 COG 世界位置: {np.round(coms[-1][0], 4)}  质量 {LOAD_MASS} kg")
    print()
    print(f"{'轴':>3} {'重力力矩(Nm)':>13} {'实测(Nm)':>11} {'残差':>10} {'额定':>5} {'占额定':>7}")
    for i in range(6):
        tau = 0.0
        for (pc, m) in coms[i:]:                      # 该轴之后的所有连杆 (含末端负载)
            r = pc - origins[i]
            tau += float(np.dot(np.cross(r, m * G), axes[i]))
        resid = MEASURED[i] - tau
        print(f"{i+1:>3} {tau:>13.3f} {MEASURED[i]:>11.3f} {resid:>10.3f} {RATED[i]:>5} "
              f"{abs(MEASURED[i])/RATED[i]*100:>6.1f}%")
    print()
    print(f"现场 J5 报警线 {FIELD_LIMIT} Nm → 实测 |J5| = {abs(MEASURED[4]):.3f} Nm "
          f"= {abs(MEASURED[4])/FIELD_LIMIT*100:.1f}% of 报警线")
    print("判读: 若 残差 与实测同量级而 重力力矩≈0~几 Nm ⇒ 传感器零点/负载模型不符 (控制器 #41447 那条);")
    print("      若 重力力矩 本身就接近实测 ⇒ 是这个姿态的真实重力负载, 换姿态即可降下来。")


if __name__ == "__main__":
    main()
