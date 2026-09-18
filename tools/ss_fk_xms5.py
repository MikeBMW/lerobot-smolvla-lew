#!/usr/bin/env python3
"""用现场 URDF 的关节几何做 FK，核对 /robot/tcp_pose 指向哪个坐标系，并判定 J6 到底控制末端的什么。

URDF: /home/tashan/0810/.../resource/config/sr5_guangmokuai_100gAOI/robot/urdf/xms5_r800_w4g3b4c.urdf
实测关节角(rad): 见下 Q；实测 tcp_pose: x=0.43887391449987884 y=0.14730254240291918 z=0.23172046790163345
                                  quat(x,y,z,w)=(-0.9239697200744136,-0.038780624592832526,-0.35563377161292714,0.13527985818355892)
URDF joint 链 (parent→child, origin xyz / rpy, axis):
  base→J1: (0,0,0.328) rpy0  axis z
  J1→J2: (0,0,0)       rpy0  axis y
  J2→J3: (0.05,0,0.4)  rpy0  axis y (−)
  J3→J4: (−0.05,0,0.4) rpy0  axis z
  J4→J5: (0,0.136,0)   rpy0  axis y (−)
  J5→J6: (0,0,0.1035)  rpy0  axis z
  link6→tool0: identity (fixed)
  tool0→tool1: (-0.01588615307905028, 0.018348498948158043, 0.2586775713451509)
               rpy (0.03702517838719945, 0.6751675651256659, 2.375248653715161)  ← yml 里 ee_link: tool1
"""
import math

def rot_x(a): c,s=math.cos(a),math.sin(a); return [[1,0,0],[0,c,-s],[0,s,c]]
def rot_y(a): c,s=math.cos(a),math.sin(a); return [[c,0,s],[0,1,0],[-s,0,c]]
def rot_z(a): c,s=math.cos(a),math.sin(a); return [[c,-s,0],[s,c,0],[0,0,1]]
def mul(A,B): return [[sum(A[i][k]*B[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
def mv(A,v): return [sum(A[i][k]*v[k] for k in range(3)) for i in range(3)]
def rpy(r,p,y): return mul(rot_z(y), mul(rot_y(p), rot_x(r)))
def T(R,t): return (R,t)
def compose(T1,T2):
    (R1,t1),(R2,t2) = T1,T2
    return (mul(R1,R2), [t1[i]+mv(R1,t2)[i] for i in range(3)])

J1=(0.0,0.0,0.328); J2=(0.0,0.0,0.0); J3=(0.05,0.0,0.4); J4=(-0.05,0.0,0.4)
J5=(0.0,0.136,0.0); J6=(0.0,0.0,0.1035)
T_tool1=((-0.01588615307905028,0.018348498948158043,0.2586775713451509),
         (0.03702517838719945,0.6751675651256659,2.375248653715161))

def fk(q, upto="tool1"):
    q1,q2,q3,q4,q5,q6 = q
    M = ([[1,0,0],[0,1,0],[0,0,1]], [0,0,0])
    M = compose(M, (rot_z(q1), J1))
    if upto=="link1": return M
    M = compose(M, (rot_y(q2), J2))
    if upto=="link2": return M
    M = compose(M, (rot_y(-q3), J3))
    if upto=="link3": return M
    M = compose(M, (rot_z(q4), J4))
    if upto=="link4": return M
    M = compose(M, (rot_y(-q5), J5))
    if upto=="link5": return M
    M = compose(M, (rot_z(q6), J6))
    if upto=="link6": return M
    M = compose(M, ([[1,0,0],[0,1,0],[0,0,1]], [0,0,0]))          # tool0 == link6
    if upto=="tool0": return M
    R_p, rpy_p = T_tool1
    return compose(M, (rpy(*rpy_p), list(R_p)))

def quat_from_R(R):
    tr = R[0][0]+R[1][1]+R[2][2]
    if tr > 0:
        S = math.sqrt(tr+1.0)*2; w=0.25*S
        x=(R[2][1]-R[1][2])/S; y=(R[0][2]-R[2][0])/S; z=(R[1][0]-R[0][1])/S
    elif R[0][0] > R[1][1] and R[0][0] > R[2][2]:
        S = math.sqrt(1.0+R[0][0]-R[1][1]-R[2][2])*2
        w=(R[2][1]-R[1][2])/S; x=0.25*S; y=(R[0][1]+R[1][0])/S; z=(R[0][2]+R[2][0])/S
    elif R[1][1] > R[2][2]:
        S = math.sqrt(1.0+R[1][1]-R[0][0]-R[2][2])*2
        w=(R[0][2]-R[2][0])/S; x=(R[0][1]+R[1][0])/S; y=0.25*S; z=(R[1][2]+R[2][1])/S
    else:
        S = math.sqrt(1.0+R[2][2]-R[0][0]-R[1][1])*2
        w=(R[1][0]-R[0][1])/S; x=(R[0][2]+R[2][0])/S; y=(R[1][2]+R[2][1])/S; z=0.25*S
    return (x,y,z,w)

def show(tag, M):
    R,t = M
    qx,qy,qz,qw = quat_from_R(R)
    print(f"  {tag:8s} pos=({t[0]*1000:8.2f},{t[1]*1000:8.2f},{t[2]*1000:8.2f}) mm   quat=({qx:+.5f},{qy:+.5f},{qz:+.5f},{qw:+.5f})")

Q = [-0.19209894,-0.16929455,-2.34314886,0.31950399,-0.94447125,0.24603710]
print("当前关节角(deg):", [round(math.degrees(v),4) for v in Q])
print("\n① FK 各段，与实测 /robot/tcp_pose 对齐:")
show("link6", fk(Q,"link6")); show("tool0", fk(Q,"tool0")); show("tool1", fk(Q,"tool1"))
print("  实测 tcp_pose pos=(  438.87,  147.30,  231.72) mm   quat=(-0.92397,-0.03878,-0.35563,+0.13528)")

print("\n② 单轴 +10° 灵敏度 (看谁改位置、谁只改姿态):")
base = fk(Q,"tool1"); bR, bp = base          # fk 返回 (R, t)
for i,name in enumerate(("J1","J2","J3","J4","J5","J6")):
    q2 = list(Q); q2[i] += math.radians(10)
    R,p = fk(q2,"tool1")
    dp = math.sqrt(sum((p[k]-bp[k])**2 for k in range(3)))*1000
    dR = mul([[R[k][j] for j in range(3)] for k in range(3)],
             [[bR[j][k] for j in range(3)] for k in range(3)])        # R_new * R_base^T
    ang = math.degrees(math.acos(max(-1,min(1,(dR[0][0]+dR[1][1]+dR[2][2]-1)/2))))
    print(f"  {name}+10° → TCP 位置变化 {dp:8.2f} mm · 姿态变化 {ang:6.2f}°")

print("\n③ 结构判定 (从 URDF 几何算，不是猜):")
def dist_skew(P1,d1,P2,d2):
    import itertools
    n = [d1[1]*d2[2]-d1[2]*d2[1], d1[2]*d2[0]-d1[0]*d2[2], d1[0]*d2[1]-d1[1]*d2[0]]
    nn = math.sqrt(sum(v*v for v in n))
    if nn < 1e-9:   # 平行 → 点到直线距离
        v=[P2[k]-P1[k] for k in range(3)]
        d=math.sqrt(sum(v[k]*v[k] for k in range(3)))
        proj=sum(v[k]*d1[k] for k in range(3))/math.sqrt(sum(x*x for x in d1))
        return math.sqrt(max(0.0,d*d-proj*proj))*1000
    return abs(sum((P2[k]-P1[k])*n[k] for k in range(3)))/nn*1000
M4=fk(Q,"link4"); M5=fk(Q,"link5")
o4 = M4[1]; z4 = [M4[0][i][2] for i in range(3)]      # J4 轴 = link4 的 z
o5 = M5[1]; y5 = [M5[0][i][1] for i in range(3)]      # J5 轴 = link5 的 y(取符号不影响直线)
o6 = fk(Q,"link6")[1]; z5 = [M5[0][i][2] for i in range(3)]  # J6 轴 = link5 的 z
print(f"  J4轴 ↔ J5轴 最近距离 = {dist_skew(o4,z4,o5,y5):.2f} mm")
print(f"  J5轴 ↔ J6轴 最近距离 = {dist_skew(o5,y5,o6,z5):.2f} mm")
print(f"  J4轴 ↔ J6轴 最近距离 = {dist_skew(o4,z4,o6,z5):.2f} mm")
print(f"  腕心(J5/J6交点)到 tool1(TCP) 距离 = {math.dist(o6, fk(Q,'tool1')[1])*1000:.1f} mm")
print(f"  link6(法兰) 到 tool1(TCP) 距离    = {math.dist(fk(Q,'link6')[1], fk(Q,'tool1')[1])*1000:.1f} mm")
