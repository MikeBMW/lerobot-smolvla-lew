#!/usr/bin/env python3
"""
Z-MAX 推理客户端 — gRPC Stub + 本地Dummy数据源
支持: 本地Dummy / 数据集回放 / 远端真机(Orin)预留
"""
import os, sys, time, pickle, threading
from dataclasses import dataclass, field
from typing import Optional, Callable, Any
from enum import Enum

import numpy as np
import grpc

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from lerobot.transport import services_pb2, services_pb2_grpc
from lerobot.async_inference.helpers import RemotePolicyConfig, TimedObservation
from lerobot.utils.feature_utils import dataset_to_policy_features
from lerobot.configs import FeatureType


class DataSource(Enum):
    """数据源类型"""
    DUMMY = "dummy"           # 本地随机数据
    PUSHT = "pusht"           # PushT数据集回放
    METAWORLD = "metaworld"   # MetaWorld数据集回放
    REMOTE = "remote"         # 远端真机(Orin) — 预留


@dataclass
class ClientState:
    """客户端状态"""
    connected: bool = False
    policy_sent: bool = False
    server_address: str = "127.0.0.1:50051"
    data_source: DataSource = DataSource.DUMMY
    fps: int = 20
    actions_received: int = 0
    frames_sent: int = 0
    last_action: Optional[Any] = None
    error_message: str = ""


class ZmaxInferenceClient:
    """
    Z-MAX推理客户端
    支持多种数据源，通过gRPC向服务端发送观测、接收动作
    
    远端真机(Orin)预留:
    - 数据源设为 DataSource.REMOTE 时，通过SSH从Orin获取实时相机+状态数据
    - 当前版本先实现本地dummy + 数据集回放
    """
    
    def __init__(self, log_callback: Optional[Callable] = None):
        self.state = ClientState()
        self._log = log_callback or (lambda msg: print(f"[Client] {msg}"))
        self._channel: Optional[grpc.Channel] = None
        self._stub = None
        self._running = False
        self._push_thread: Optional[threading.Thread] = None
        self._dataset = None  # 数据集回放用
        
    def _log_info(self, msg: str):
        self._log(f"ℹ️ {msg}")
    
    def _log_ok(self, msg: str):
        self._log(f"✅ {msg}")
    
    def _log_err(self, msg: str):
        self._log(f"❌ {msg}")
        self.state.error_message = msg
    
    def _log_action(self, msg: str):
        self._log(f"🤖 {msg}")
    
    def connect(self, server_address: str = "127.0.0.1:50051") -> bool:
        """连接推理服务器"""
        if self.state.connected:
            self._log_info("已连接")
            return True
        
        try:
            self._log_info(f"连接 {server_address}...")
            self.state.server_address = server_address
            self._channel = grpc.insecure_channel(
                server_address,
                options=[('grpc.max_receive_message_length', 100*1024*1024)]
            )
            self._stub = services_pb2_grpc.AsyncInferenceStub(self._channel)
            
            # Ready握手
            self._stub.Ready(services_pb2.Empty(), timeout=5)
            self.state.connected = True
            self._log_ok(f"已连接 {server_address}")
            return True
        except Exception as e:
            self._log_err(f"连接失败: {e}")
            self.state.connected = False
            return False
    
    def send_policy(self, checkpoint_path: str, dataset_repo: str = "lerobot/metaworld_mt50") -> bool:
        """发送策略配置到服务端"""
        if not self.state.connected:
            self._log_err("未连接")
            return False
        
        try:
            self._log_info("构建策略配置...")
            
            # 加载数据集特征
            from lerobot.datasets import LeRobotDatasetMetadata
            meta = LeRobotDatasetMetadata(dataset_repo)
            pf = dataset_to_policy_features(meta.features)
            
            # 构建lerobot_features
            lf = {}
            for k, v in pf.items():
                if k == "observation.state":
                    lf[k] = {"dtype": "float32", "shape": list(v.shape),
                             "names": [f"s{i}" for i in range(v.shape[0])]}
                elif k == "observation.image":
                    lf[k] = {"dtype": "video", "shape": list(v.shape)}
            
            pcfg = RemotePolicyConfig(
                policy_type="smolvla",
                pretrained_name_or_path=os.path.abspath(checkpoint_path),
                lerobot_features=lf,
                actions_per_chunk=50,
                device="cuda",
                rename_map={},
            )
            
            data = pickle.dumps(pcfg)
            self._stub.SendPolicyInstructions(
                services_pb2.PolicySetup(data=data), timeout=60
            )
            self.state.policy_sent = True
            self._log_ok("策略已发送，等待模型加载...")
            return True
        except Exception as e:
            self._log_err(f"发送策略失败: {e}")
            return False
    
    def start_dummy_stream(self, fps: int = 20, duration_sec: float = 10.0):
        """启动本地Dummy数据流 — 随机生成观测"""
        self.state.data_source = DataSource.DUMMY
        self.state.fps = fps
        self._running = True
        self._log_info(f"Dummy数据源: {fps}FPS × {duration_sec}s")
        
        self._push_thread = threading.Thread(
            target=self._dummy_loop, args=(fps, duration_sec), daemon=True
        )
        self._push_thread.start()
    
    def start_dataset_stream(self, dataset_repo: str, fps: int = 10, n_frames: int = 50):
        """启动数据集回放数据流"""
        self.state.data_source = (
            DataSource.PUSHT if "pusht" in dataset_repo else DataSource.METAWORLD
        )
        self.state.fps = fps
        self._running = True
        
        try:
            from lerobot.datasets import LeRobotDataset
            self._dataset = LeRobotDataset(dataset_repo, episodes=[0])
            n = min(n_frames, len(self._dataset))
            self._log_info(f"数据集回放: {dataset_repo} × {n}帧 @ {fps}FPS")
        except Exception as e:
            self._log_err(f"加载数据集失败: {e}，回退到Dummy")
            self.start_dummy_stream(fps)
            return
        
        self._push_thread = threading.Thread(
            target=self._dataset_loop, args=(fps, n), daemon=True
        )
        self._push_thread.start()
    
    def _dummy_loop(self, fps: int, duration: float):
        """Dummy数据生成循环"""
        interval = 1.0 / fps
        n_frames = int(fps * duration)
        
        for i in range(n_frames):
            if not self._running:
                break
            
            # 生成随机观测（模拟4D state + 480×480图像）
            obs = {
                "s0": float(np.random.randn()),
                "s1": float(np.random.randn()),
                "s2": float(np.random.randn()),
                "s3": float(np.random.randn()),
                "observation.image": np.random.rand(3, 480, 480).astype(np.float32),
                "task": "dummy task",
            }
            
            try:
                self._send_observation(obs, i)
                self.state.frames_sent += 1
            except Exception as e:
                self._log_err(f"发送观测 #{i} 失败: {e}")
                break
            
            time.sleep(interval)
        
        self._running = False
        self._log_info(f"Dummy流结束: {self.state.frames_sent}帧, {self.state.actions_received}动作")
    
    def _dataset_loop(self, fps: int, n_frames: int):
        """数据集回放循环"""
        interval = 1.0 / fps
        
        for i in range(n_frames):
            if not self._running or self._dataset is None:
                break
            
            frame = self._dataset[i]
            state_arr = np.array(frame["observation.state"]).flatten()
            
            obs = {}
            for j, val in enumerate(state_arr):
                obs[f"s{j}"] = float(val)
            
            img = np.array(frame["observation.image"])
            if hasattr(frame["observation.image"], 'numpy'):
                img = frame["observation.image"].numpy()
            obs["observation.image"] = img.astype(np.float32) if img.dtype != np.float32 else img
            
            task = frame.get("task", ["complete task"])
            obs["task"] = task[0] if isinstance(task, (list, tuple)) else str(task)
            
            try:
                self._send_observation(obs, i)
                self.state.frames_sent += 1
            except Exception as e:
                self._log_err(f"发送帧 #{i} 失败: {e}")
                break
            
            time.sleep(interval)
        
        self._running = False
        self._log_info(f"回放结束: {self.state.frames_sent}帧, {self.state.actions_received}动作")
    
    def _send_observation(self, obs_dict: dict, timestep: int):
        """发送单帧观测"""
        timed_obs = TimedObservation(
            timestamp=time.time(), timestep=timestep, observation=obs_dict
        )
        data = pickle.dumps(timed_obs)
        
        # 推送到服务端观测队列
        obs_gen = self._observation_generator(data)
        self._stub.SendObservations(obs_gen, timeout=5)
        
        # 尝试获取动作 (非阻塞)
        try:
            resp = self._stub.GetActions(services_pb2.Empty(), timeout=2)
            if resp.data:
                action = pickle.loads(resp.data)
                self.state.last_action = action
                self.state.actions_received += 1
        except grpc.RpcError:
            pass  # 可能还没准备好
    
    @staticmethod
    def _observation_generator(data: bytes):
        yield services_pb2.Observation(transfer_state=services_pb2.TRANSFER_BEGIN, data=data)
        yield services_pb2.Observation(transfer_state=services_pb2.TRANSFER_END, data=b"")
    
    def stop_stream(self):
        """停止数据流"""
        self._running = False
        if self._push_thread and self._push_thread.is_alive():
            self._push_thread.join(timeout=3)
        self._log_info("数据流已停止")
    
    def disconnect(self):
        """断开连接"""
        self.stop_stream()
        if self._channel:
            self._channel.close()
        self.state.connected = False
        self.state.policy_sent = False
    
    def get_status(self) -> dict:
        return {
            "connected": self.state.connected,
            "policy_sent": self.state.policy_sent,
            "server": self.state.server_address,
            "source": self.state.data_source.value,
            "frames_sent": self.state.frames_sent,
            "actions": self.state.actions_received,
            "error": self.state.error_message,
        }
