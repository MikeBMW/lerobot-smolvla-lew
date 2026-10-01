import json, math, sys
import rclpy
from rclpy.node import Node
from moveit_msgs.srv import GetPositionFK
from moveit_msgs.msg import RobotState

d = json.load(open("/ws/plans/live_plan_latest.json"))
NM=list(d["joint_names"]); JP=list(d["joints_path"]); NP=int(d["n_points"]); GQ=list(d["goal_quat"])
rclpy.init(); n=Node("fk_q"); cli=n.create_client(GetPositionFK,"/compute_fk")
cli.wait_for_service(timeout_sec=15.0)
def fk(q6):
    req=GetPositionFK.Request(); req.header.frame_id=d.get("base_frame") or "base"; req.fk_link_names=["tool0"]
    rs=RobotState(); rs.joint_state.name=NM; rs.joint_state.position=[float(v) for v in q6]; req.robot_state=rs
    f=cli.call_async(req); rclpy.spin_until_future_complete(n,f,timeout_sec=20.0); res=f.result()
    if res is None or res.error_code.val!=1 or not res.pose_stamped: return None
    p=res.pose_stamped[0].pose
    return [p.position.x,p.position.y,p.position.z,p.orientation.x,p.orientation.y,p.orientation.z,p.orientation.w]
e=fk(JP[(NP-1)*6:NP*6])
def ang(q1,q2):                       # 两个四元数之间的旋转角(度) —— 与 RPY 三元组无关, 无歧义
    dot=abs(sum(a*b for a,b in zip(q1,q2)))
    return math.degrees(2.0*math.acos(max(-1.0,min(1.0,dot))))
print("末路点 pos(m)  :", [round(v,5) for v in e[:3]], " 目标:", [round(v,5) for v in d["goal_xyz"]])
print("位置差(mm)     : %.2f   (文件里 end_err_mm=%.3f)" % (1000*math.dist(e[:3], d["goal_xyz"]), d.get("end_err_mm",-1)))
print("末路点 quat    :", [round(v,5) for v in e[3:7]])
print("目标 quat      :", [round(v,5) for v in GQ])
print(">>> 姿态夹角    : %.2f 度   <-- 这才是真差别(位置差 4.9mm 但姿态差这么多 = 规划没满足姿态约束)" % ang(e[3:7], GQ))
n.destroy_node(); rclpy.shutdown()
