#!/usr/bin/env python3
"""
Hermes Gateway — WSL端SDK
在WSL中导入此模块，通过HTTP操控Mac上的Gateway分身

用法:
    from hermes_gateway_sdk import HermesGatewayClient
    
    gw = HermesGatewayClient("192.168.1.100:8080")  # Mac的IP
    status = gw.get_status()
    joints = gw.get_joints()
    gw.send_cmd("回零")
"""

import json
import asyncio
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError


class HermesGatewayClient:
    """与Mac上的Hermes Gateway通信"""

    def __init__(self, host: str = "localhost:8080"):
        self.base = f"http://{host}"

    def _get(self, path: str) -> dict:
        try:
            req = Request(f"{self.base}{path}")
            with urlopen(req, timeout=5) as resp:
                return json.loads(resp.read())
        except URLError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": str(e)}

    def _post(self, path: str, data: dict) -> dict:
        try:
            body = json.dumps(data).encode()
            req = Request(f"{self.base}{path}", data=body,
                          headers={"Content-Type": "application/json"})
            with urlopen(req, timeout=5) as resp:
                return json.loads(resp.read())
        except URLError as e:
            return {"error": str(e)}

    # ── 查询API ──

    def get_status(self) -> dict:
        """获取完整状态: 关节、夹爪、HMI事件"""
        return self._get("/status")

    def get_joints(self) -> dict:
        """获取关节位置字典"""
        return self._get("/joints")

    def get_gripper(self) -> dict:
        """获取夹爪开度"""
        return self._get("/gripper")

    def ping(self) -> bool:
        """检查Gateway是否在线"""
        r = self._get("/")
        return r.get("status") == "online"

    # ── 指令API ──

    def send_cmd(self, command: str) -> dict:
        """发送HMI指令 (如 "回零", "home")"""
        return self._post("/cmd", {"command": command})

    def send_target_pose(self, joint_names: list, positions: list) -> dict:
        """发送目标关节位姿"""
        return self._post("/target_pose", {
            "names": joint_names,
            "positions": positions,
        })

    def robot_home(self) -> dict:
        """快捷: 机器人回零"""
        return self.send_cmd("回零")

    def gripper_open(self) -> dict:
        """快捷: 夹爪打开"""
        return self.send_cmd("gripper_open")

    def gripper_close(self) -> dict:
        """快捷: 夹爪关闭"""
        return self.send_cmd("gripper_close")


# ── 命令行工具 ──
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python3 hermes_gateway_sdk.py <mac-ip> [cmd]")
        print("  python3 hermes_gateway_sdk.py 192.168.1.100 status")
        print("  python3 hermes_gateway_sdk.py 192.168.1.100 joints")
        print("  python3 hermes_gateway_sdk.py 192.168.1.100 cmd 回零")
        sys.exit(1)

    gw = HermesGatewayClient(sys.argv[1])

    if sys.argv[2] == "status":
        print(json.dumps(gw.get_status(), indent=2, ensure_ascii=False))
    elif sys.argv[2] == "joints":
        print(json.dumps(gw.get_joints(), indent=2, ensure_ascii=False))
    elif sys.argv[2] == "cmd" and len(sys.argv) > 3:
        print(gw.send_cmd(sys.argv[3]))
    elif sys.argv[2] == "ping":
        print("在线" if gw.ping() else "离线")
    else:
        print(f"未知命令: {sys.argv[2]}")
