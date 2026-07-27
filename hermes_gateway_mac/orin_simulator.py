#!/usr/bin/env python3
"""Orin Simulator — 当Orin离线时，用真实缓存数据模拟机器人状态"""
import json, time, threading, argparse, sys
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
import uvicorn

# ═══════════════════════════════════════════════
# 真实 Orin 快照数据 (2025-07-08 22:00+)
# ═══════════════════════════════════════════════

JOINT_NAMES = [
    "XMS5-R800-W4G3B4C_joint_1",
    "XMS5-R800-W4G3B4C_joint_2",
    "XMS5-R800-W4G3B4C_joint_3",
    "XMS5-R800-W4G3B4C_joint_4",
    "XMS5-R800-W4G3B4C_joint_5",
    "XMS5-R800-W4G3B4C_joint_6",
]

JOINT_POSITIONS = [
    0.16020332090107084,
    -0.06144651662015299,
    -2.5454611543855594,
    1.4468808793804981,
    0.4349413173296231,
    -0.6976726783522458,
]

ROBOT_MODEL = "XMS5-R800-W4G3B4C"
ORIN_IP = "192.168.23.10"
ORIN_HOSTNAME = "nvidia-desktop"
ORIN_KERNEL = "Linux 5.15.148-tegra aarch64"

ALL_TOPICS = [
    "/CloudToRobotManageMapArea", "/CloudToRobotMapInfo", "/ControlMove", "/CurRealPose",
    "/RobotChassisLogLevel", "/RobotEvent", "/RobotPower", "/RobotState",
    "/RobotToCloudManageMapArea", "/RobotToCloudMapInfoReq", "/RobotToCloudPosture",
    "/barcode_scanner/status", "/brake_ctrl", "/cancel_action", "/chassis_status",
    "/chassis_velocity", "/clicked_point", "/client_count", "/connected_clients",
    "/ee_target", "/emergency_stop", "/emergency_stop/event", "/execution_mode_real",
    "/foundationpose/tray_reference/debug_image", "/goal_pose", "/gripper_pos",
    "/hmi/events", "/initialpose", "/joint_states", "/mapping_progress",
    "/motion/active_states", "/motion/active_transition", "/motion/execution_result",
    "/motion/initialization_complete", "/motion/node_runtime", "/nav_system_state",
    "/obstacle_box_state", "/obstacle_boxes", "/obstacle_boxes_array",
    "/obstacle_marker_server/feedback", "/obstacle_marker_server/update",
    "/parameter_events", "/physical_estop", "/physical_estop/event",
    "/ply_pointcloud", "/points_raw", "/real_joint_states",
    "/realsense/color/camera_info", "/realsense/color/image_raw",
    "/realsense/depth/image_rect_raw", "/realsense/points",
    "/robot/force_torque", "/robot/joint_states", "/robot/tcp_pose",
    "/robot_description", "/robot_status", "/rosout", "/scan",
    "/scene_mesh_delete", "/scene_mesh_import",
    "/scene_mesh_marker_server/feedback", "/scene_mesh_marker_server/update",
    "/sim_joint_states", "/sim_joint_trajectory", "/slam_status", "/stop_move",
    "/tactile_sensor", "/tf", "/tf_static", "/tower_light/command",
    "/tower_light/status", "/usb_estop", "/usb_estop/event",
    "/visualization_marker_array",
]

ALL_NODES = [
    "/chassis_node", "/external_comm", "/gripper_driver", "/hmi_v1_tashan_bridge",
    "/honeywell_scanner", "/motion", "/obstacle_marker", "/pointcloud_receiver",
    "/realsense_source", "/robot_state_publisher", "/rosapi", "/rosapi_params",
    "/rosbridge_websocket", "/rviz2", "/scene_mesh_marker", "/sim_joint_state_publisher",
    "/tactile_force_node", "/tower_light",
    "/transform_listener_impl_aaaab772ecd0", "/transform_listener_impl_aaaab78ec270",
    "/transform_listener_impl_aaaab81447a0", "/vision", "/vision_pointcloud", "/vision_tag",
]

# ═══════════════════════════════════════════════
# 模拟器
# ═══════════════════════════════════════════════

class OrinSimulator:
    def __init__(self):
        self.state = {
            "joint_names": JOINT_NAMES,
            "joint_positions": JOINT_POSITIONS,
            "gripper_pos": None,
            "sim_joints": None,
            "last_update": time.time(),
            "mode": "simulation",
            "note": "Orin offline — using cached snapshot",
        }

    def get_state(self):
        self.state["last_update"] = time.time()
        return dict(self.state)

    def get_joints(self):
        return dict(zip(JOINT_NAMES, JOINT_POSITIONS))

    def get_gripper(self):
        return None

    def list_topics(self):
        return ALL_TOPICS

    def list_nodes(self):
        return ALL_NODES

    def send_cmd(self, command: str):
        return {"command": command, "result": "simulated", "note": "Orin offline"}


def run_simulator(host="0.0.0.0", port=8080):
    sim = OrinSimulator()
    app = FastAPI(title="Hermes Gateway (Orin Simulator)")
    ws_clients = []

    @app.get("/")
    async def root():
        return {"service": "Hermes Gateway (Sim)", "orin": ORIN_IP, "status": "simulated"}

    @app.get("/status")
    async def status():
        return sim.get_state()

    @app.get("/joints")
    async def joints():
        j = sim.get_joints()
        return {"joints": j, "count": len(j)}

    @app.get("/gripper")
    async def gripper():
        return {"gripper_pos": sim.get_gripper()}

    @app.get("/topics")
    async def topics():
        return {"topics": sim.list_topics(), "count": len(ALL_TOPICS)}

    @app.get("/nodes")
    async def nodes():
        return {"nodes": sim.list_nodes(), "count": len(ALL_NODES)}

    @app.post("/cmd")
    async def cmd(data: dict):
        command = data.get("command", "")
        if not command:
            return JSONResponse({"error": "command required"}, status_code=400)
        return sim.send_cmd(command)

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        ws_clients.append(ws)
        await ws.send_json({"type": "connected", "mode": "simulation"})
        try:
            while True:
                import asyncio
                await asyncio.sleep(1.0)
                try:
                    await ws.send_json({
                        "type": "state",
                        "joints": sim.get_joints(),
                        "gripper": sim.get_gripper(),
                        "ts": time.time(),
                        "mode": "simulation",
                    })
                except Exception:
                    break
        except WebSocketDisconnect:
            pass
        finally:
            if ws in ws_clients:
                ws_clients.remove(ws)

    print(f"\n{'='*50}")
    print(f"🎭 Orin Simulator @ http://{host}:{port}")
    print(f"   模式: 仿真 (Orin离线)")
    print(f"   机器人: {ROBOT_MODEL} (6轴)")
    print(f"   话题数: {len(ALL_TOPICS)}")
    print(f"   节点数: {len(ALL_NODES)}")
    print(f"{'='*50}\n")

    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Orin Simulator")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    run_simulator(port=args.port)
