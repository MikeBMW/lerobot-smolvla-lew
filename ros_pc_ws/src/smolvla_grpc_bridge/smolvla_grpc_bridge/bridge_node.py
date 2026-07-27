#!/usr/bin/env python3
"""
ROS2-gRPC Bridge Node for SmolVLA Async Inference.

Subscribes to Orin camera/joint topics via ROS2 DDS,
relays observations to local gRPC policy_server,
and publishes received action chunks back to Orin.

Self-contained: only needs grpcio, protobuf, rclpy — no heavy lerobot imports.

Data flow:
  Orin ROS topics → bridge → gRPC policy_server → bridge → Orin ROS action topic

Usage (after colcon build and sourcing ROS2 + install):
  ros2 run smolvla_grpc_bridge bridge_node
"""

import pickle
import sys as _sys
import time
from dataclasses import dataclass, field
from types import ModuleType as _ModuleType
from typing import Any

import grpc

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import Float32MultiArray

# Lightweight gRPC stubs — no pandas dependency
from lerobot.transport import services_pb2, services_pb2_grpc


# ── Cross-environment pickle compatibility ──
# The bridge runs in Python 3.10 (system), policy_server in conda Python 3.12.
# pickle records the module path of serialized objects. We inject a fake
# lerobot.async_inference.helpers module and use __reduce__ on our dataclasses
# so pickle writes GLOBAL 'lerobot.async_inference.helpers' — which the server CAN import.
#
# Tested: conda Python 3.12 successfully unpickles bytes from system Python 3.10.

# Inject fake module for pickle's import verification
_fake_helpers = _ModuleType("lerobot.async_inference.helpers")

def _stub_timed_obs(*a, **kw):
    raise NotImplementedError("pickle stub only")

_stub_timed_obs.__module__ = "lerobot.async_inference.helpers"
_stub_timed_obs.__qualname__ = "TimedObservation"
_fake_helpers.TimedObservation = _stub_timed_obs

def _stub_remote_cfg(*a, **kw):
    raise NotImplementedError("pickle stub only")

_stub_remote_cfg.__module__ = "lerobot.async_inference.helpers"
_stub_remote_cfg.__qualname__ = "RemotePolicyConfig"
_fake_helpers.RemotePolicyConfig = _stub_remote_cfg

# Create a proper class stub for TimedAction (needed for NEWOBJ pickle opcode)
class _StubTimedAction:
    __module__ = "lerobot.async_inference.helpers"
    __qualname__ = "TimedAction"
    def get_action(self): return self.action
    def get_timestamp(self): return self.timestamp
    def get_timestep(self): return self.timestep

class _StubTimedData:
    __module__ = "lerobot.async_inference.helpers"
    __qualname__ = "TimedData"
    def get_timestamp(self): return self.timestamp
    def get_timestep(self): return self.timestep

_fake_helpers.TimedAction = _StubTimedAction
_fake_helpers.TimedData = _StubTimedData

# Install fake packages so pickle.whichmodule() finds stubs, not __main__ classes
_sys.modules.setdefault("lerobot", _ModuleType("lerobot"))
_sys.modules.setdefault("lerobot.async_inference", _ModuleType("lerobot.async_inference"))
_sys.modules["lerobot.async_inference.helpers"] = _fake_helpers


# ── Local dataclass mirrors (with __reduce__ for cross-env pickle) ──

@dataclass
class TimedObservation:
    """Observation with timestamp metadata."""
    timestamp: float
    timestep: int
    observation: dict[str, Any]
    must_go: bool = False

    def get_timestamp(self) -> float:
        return self.timestamp

    def get_timestep(self) -> int:
        return self.timestep

    def get_observation(self) -> dict[str, Any]:
        return self.observation

    def __reduce__(self):
        return (_fake_helpers.TimedObservation,
                (self.timestamp, self.timestep, self.observation, self.must_go))


@dataclass
class RemotePolicyConfig:
    """Policy configuration sent to gRPC server."""
    policy_type: str
    pretrained_name_or_path: str
    lerobot_features: dict = field(default_factory=dict)
    actions_per_chunk: int = 50
    device: str = "cpu"
    rename_map: dict = field(default_factory=dict)

    def __reduce__(self):
        return (_fake_helpers.RemotePolicyConfig,
                (self.policy_type, self.pretrained_name_or_path,
                 self.lerobot_features, self.actions_per_chunk,
                 self.device, self.rename_map))


SUPPORTED_POLICIES = ["act", "smolvla", "diffusion", "tdmpc", "vqbet", "pi0", "pi05", "groot"]


class SmolVLAGrpcBridge(Node):
    """ROS2 node that bridges Orin hardware topics to gRPC policy_server."""

    def __init__(self):
        super().__init__("smolvla_grpc_bridge")

        # ── Parameters ──
        self.declare_parameter("grpc_host", "127.0.0.1")
        self.declare_parameter("grpc_port", 8080)
        self.declare_parameter("policy_type", "smolvla")
        self.declare_parameter("pretrained_name_or_path", "")
        self.declare_parameter("actions_per_chunk", 50)
        self.declare_parameter("infer_hz", 20.0)

        grpc_host = self.get_parameter("grpc_host").value
        grpc_port = self.get_parameter("grpc_port").value
        self.policy_type = self.get_parameter("policy_type").value
        self.pretrained_path = self.get_parameter("pretrained_name_or_path").value
        self.actions_per_chunk = self.get_parameter("actions_per_chunk").value
        infer_hz = self.get_parameter("infer_hz").value

        # ── State ──
        self.latest_rgb: bytes | None = None
        self.latest_joint: list[float] | None = None
        self.timestep_counter = 0
        self.policy_initialized = False

        # ── gRPC channel ──
        server_addr = f"{grpc_host}:{grpc_port}"
        self.get_logger().info(f"Connecting to gRPC policy_server at {server_addr}...")
        self.channel = grpc.insecure_channel(server_addr)
        self.stub = services_pb2_grpc.AsyncInferenceStub(self.channel)

        # ── ROS subscriptions (from Orin) ──
        self.create_subscription(
            CompressedImage,
            "/camera/rgb/compressed",
            self._rgb_callback,
            5,
        )
        self.create_subscription(
            Float32MultiArray,
            "/arm/joint_state",
            self._joint_callback,
            5,
        )

        # ── ROS publisher (to Orin) ──
        self.action_pub = self.create_publisher(
            Float32MultiArray, "/arm/target_action", 5
        )

        # ── Inference timer ──
        self.timer = self.create_timer(1.0 / infer_hz, self._infer_loop)

        self.get_logger().info("SmolVLA gRPC Bridge node started")

    def set_model_path(self, path: str):
        """Override pretrained model path (for programmatic use)."""
        self.pretrained_path = path
        self.get_logger().info(f"Model path set: {path}")

    def _rgb_callback(self, msg: CompressedImage):
        self.latest_rgb = msg.data  # bytes, JPEG compressed

    def _joint_callback(self, msg: Float32MultiArray):
        self.latest_joint = list(msg.data)

    def _ensure_policy_initialized(self) -> bool:
        """Send policy instructions to gRPC server on first inference."""
        if self.policy_initialized:
            return True

        if not self.pretrained_path:
            self.get_logger().error(
                "pretrained_name_or_path not set — cannot initialize policy"
            )
            return False

        if self.policy_type not in SUPPORTED_POLICIES:
            self.get_logger().error(
                f"Unsupported policy type: {self.policy_type}. "
                f"Supported: {SUPPORTED_POLICIES}"
            )
            return False

        try:
            # Send Ready
            self.stub.Ready(services_pb2.Empty())

            # Build policy config with feature descriptors matching the model
            policy_config = RemotePolicyConfig(
                policy_type=self.policy_type,
                pretrained_name_or_path=self.pretrained_path,
                lerobot_features={
                    "observation.images.top": {
                        "dtype": "video",
                        "shape": [3, 96, 96],
                        "names": ["top"],
                    },
                    "observation.state": {
                        "dtype": "float32",
                        "shape": [2],
                        "names": ["pos_0", "pos_1"],
                    },
                },
                actions_per_chunk=self.actions_per_chunk,
                device="cuda" if self._cuda_available() else "cpu",
                rename_map={
                    "observation.images.top": "observation.image",
                    "observation.state": "observation.state",
                },
            )

            setup = services_pb2.PolicySetup(data=pickle.dumps(policy_config))
            self.stub.SendPolicyInstructions(setup)

            self.policy_initialized = True
            self.get_logger().info(
                f"Policy initialized: {self.policy_type} @ {self.pretrained_path}"
            )
            return True

        except grpc.RpcError as e:
            self.get_logger().error(f"gRPC error during policy init: {e}")
            return False

    @staticmethod
    def _cuda_available() -> bool:
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False

    def _send_observation(self, obs: TimedObservation) -> bool:
        """Send a single observation to the gRPC server via client-streaming RPC."""

        def observation_generator():
            data = pickle.dumps(obs)
            # Server expects TRANSFER_END to complete the stream
            yield services_pb2.Observation(
                transfer_state=services_pb2.TRANSFER_BEGIN,
                data=data,
            )
            yield services_pb2.Observation(
                transfer_state=services_pb2.TRANSFER_END,
                data=b"",
            )

        try:
            self.stub.SendObservations(observation_generator())
            return True
        except grpc.RpcError as e:
            self.get_logger().error(f"gRPC SendObservations error: {e}")
            return False

    def _get_actions(self) -> list | None:
        """Request action chunk from gRPC server."""
        try:
            response = self.stub.GetActions(services_pb2.Empty())
            if response.data:
                timed_actions = pickle.loads(response.data)
                return timed_actions
            return None
        except grpc.RpcError as e:
            self.get_logger().error(f"gRPC GetActions error: {e}")
            return None

    def _infer_loop(self):
        """Main inference loop triggered by ROS timer."""
        if self.latest_rgb is None or self.latest_joint is None:
            return

        if not self._ensure_policy_initialized():
            return

        # Build observation dict (keys must match model's input_features)
        # Decode JPEG image bytes → numpy array for the policy server
        import numpy as np
        try:
            import cv2
            img_array = cv2.imdecode(
                np.frombuffer(self.latest_rgb, np.uint8), cv2.IMREAD_COLOR
            )
            if img_array is None:
                return  # skip corrupt frame
        except ImportError:
            img_array = np.zeros((96, 96, 3), dtype=np.uint8)

        obs_dict = {
            "top": img_array,
            "pos_0": float(self.latest_joint[0]),
            "pos_1": float(self.latest_joint[1]),
            "task": "push the T block to the goal",
        }

        timed_obs = TimedObservation(
            timestamp=time.time(),
            timestep=self.timestep_counter,
            observation=obs_dict,
            must_go=False,
        )
        self.timestep_counter += 1

        # Send to gRPC server
        if not self._send_observation(timed_obs):
            return

        # Request actions
        timed_actions = self._get_actions()
        if timed_actions is None:
            return

        # Publish first action from the chunk to ROS
        if timed_actions:
            first_action = timed_actions[0]  # TimedAction from server
            action_data = first_action.get_action()
            if hasattr(action_data, "numpy"):
                action_arr = action_data.numpy()
            elif hasattr(action_data, "tolist"):
                action_arr = action_data
            else:
                import numpy as np
                action_arr = np.array(action_data)

            # Publish as Float32MultiArray (flattened)
            action_msg = Float32MultiArray()
            if hasattr(action_arr, "flatten"):
                action_msg.data = action_arr.flatten().tolist()
            else:
                action_msg.data = list(action_arr)
            self.action_pub.publish(action_msg)

            self.get_logger().debug(
                f"Inference #{timed_obs.get_timestep()}: "
                f"action dims={len(action_msg.data)}"
            )


def main(args=None):
    rclpy.init(args=args)
    node = SmolVLAGrpcBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
