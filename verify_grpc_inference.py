#!/usr/bin/env python3
"""
Z-MAX gRPC推理验证: PolicyServer + 仿真ROS Client 端到端
"""
import sys, os, time, threading, pickle, json
from concurrent import futures
from dataclasses import dataclass, field
from typing import Any

import grpc
import torch
import numpy as np

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 1: 导入依赖
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
from lerobot.transport import services_pb2, services_pb2_grpc
from lerobot.transport.utils import send_bytes_in_chunks, receive_bytes_in_chunks
from lerobot.async_inference.configs import PolicyServerConfig
from lerobot.async_inference.policy_server import PolicyServer
from lerobot.async_inference.helpers import (
    RemotePolicyConfig, TimedObservation, Observation,
    raw_observation_to_observation
)
from lerobot.datasets import LeRobotDataset, LeRobotDatasetMetadata
from lerobot.utils.feature_utils import dataset_to_policy_features
from lerobot.configs import FeatureType

device_str = "cuda" if torch.cuda.is_available() else "cpu"
CKPT = os.path.abspath("outputs/smolvla_metaworld/checkpoints/000300/pretrained_model")
DATASET = "lerobot/metaworld_mt50"
SERVER_PORT = 50051

print(f"设备: {device_str}")
print(f"模型: {CKPT}")
print(f"数据: {DATASET}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 2: 加载数据集 → 构建 RemotePolicyConfig
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📦 加载数据集...")
meta = LeRobotDatasetMetadata(DATASET)
pfeatures = dataset_to_policy_features(meta.features)
print(f"   Features: {list(pfeatures.keys())}")

# 只传模型需要的特征 (state + image)
from lerobot.configs import FeatureType as FT
lerobot_features = {}
for k, v in pfeatures.items():
    if not (k.startswith("observation.state") or k.startswith("observation.image")):
        continue
    shape = list(v.shape)
    if v.type in (FT.STATE, FT.ENV) and len(shape) == 1:
        names = [f"{k.split('.')[-1]}_{i}" for i in range(shape[0])]
        lerobot_features[k] = {"dtype": "float32", "shape": shape, "names": names}
    elif v.type == FT.VISUAL:
        cam_key = k.replace("observation.image", "observation.images.top")
        lerobot_features[cam_key] = {"dtype": "video", "shape": shape}
    else:
        lerobot_features[k] = {"dtype": "float32", "shape": shape}

# SmolVLA的config用 observation.image (singular), 需要rename_map
rename_map = {}
for k in list(lerobot_features.keys()):
    if k.startswith("observation.images."):
        rename_map[k] = k.replace("observation.images.", "observation.image")

policy_config = RemotePolicyConfig(
    policy_type="smolvla",
    pretrained_name_or_path=CKPT,
    lerobot_features=lerobot_features,
    actions_per_chunk=50,
    device=device_str,
    rename_map=rename_map,
)
print(f"   lerobot_features: {json.dumps({k: {'dtype': v['dtype'], 'shape': v['shape'], 'names': v.get('names', 'N/A')} for k, v in lerobot_features.items()})}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 3: 启动 gRPC 服务端
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print(f"\n🚀 启动gRPC服务端 (端口 {SERVER_PORT})...")
server_config = PolicyServerConfig(
    host="127.0.0.1",
    port=SERVER_PORT,
    fps=30,
    inference_latency=0.033,
    obs_queue_timeout=5,
)

policy_server = PolicyServer(server_config)
grpc_server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
services_pb2_grpc.add_AsyncInferenceServicer_to_server(policy_server, grpc_server)
grpc_server.add_insecure_port(f"{server_config.host}:{server_config.port}")
grpc_server.start()
time.sleep(0.5)
print(f"   ✅ 服务端就绪 @ {server_config.host}:{server_config.port}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 4: 客户端连接 + 发送策略
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print(f"\n🔌 客户端连接...")
channel = grpc.insecure_channel(f"localhost:{SERVER_PORT}")
stub = services_pb2_grpc.AsyncInferenceStub(channel)

# Ready
stub.Ready(services_pb2.Empty())
print(f"   ✅ Ready")

# SendPolicyInstructions
print(f"   📤 发送策略指令...")
t0 = time.time()
stub.SendPolicyInstructions(services_pb2.PolicySetup(
    data=pickle.dumps(policy_config)
))
print(f"   ✅ 模型加载完成 ({time.time()-t0:.1f}s)")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 5: 仿真ROS Client — 推观测流 + 拉动作
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print(f"\n📡 仿真ROS客户端 — 推观测 + 拉动作...")

ds = LeRobotDataset(DATASET, episodes=[0])
n_frames = min(20, len(ds))
actions_received = []

# 在后台线程推观测流
def push_observations():
    """模拟ROS节点持续发送观测数据"""
    for i in range(n_frames):
        frame = ds[i]
        # 原始观测格式：state用标量名，image用缩短的key
        state_arr = np.array(frame["observation.state"])
        obs_dict = {}
        for i, val in enumerate(state_arr):
            obs_dict[f"state_{i}"] = float(val)
        obs_dict["images.top"] = np.array(frame["observation.image"])
        timed_obs = TimedObservation(
            timestamp=time.time(),
            timestep=i,
            observation=obs_dict,
        )
        data = pickle.dumps(timed_obs)
        yield services_pb2.Observation(
            transfer_state=services_pb2.TRANSFER_BEGIN, data=data,
        )
        yield services_pb2.Observation(
            transfer_state=services_pb2.TRANSFER_END, data=b"",
        )
        time.sleep(0.05)

# 推观测（异步）
push_thread = threading.Thread(
    target=lambda: stub.SendObservations(push_observations()),
    daemon=True
)
push_thread.start()
print(f"   开始推送 {n_frames} 帧观测...")

# 拉动作
t0 = time.time()
for i in range(min(n_frames // 3, 5)):  # 拉5次动作
    try:
        response = stub.GetActions(services_pb2.Empty(), timeout=3)
        if response.data:
            action_chunk = pickle.loads(response.data)
            actions_received.append(action_chunk)
            if i == 0:
                print(f"   📥 动作#{i+1}: {type(action_chunk).__name__}")
                if hasattr(action_chunk, 'action') and isinstance(action_chunk.action, torch.Tensor):
                    print(f"     形状: {list(action_chunk.action.shape)}")
                    print(f"     范围: [{action_chunk.action.min():.4f}, {action_chunk.action.max():.4f}]")
    except grpc.RpcError as e:
        if e.code() != grpc.StatusCode.DEADLINE_EXCEEDED:
            print(f"   ⚠️ GetActions error: {e.code()}")

push_thread.join(timeout=5)
elapsed = time.time() - t0
action_count = len(actions_received)
print(f"   ✅ 收到 {action_count} 个动作块 ({elapsed:.2f}s)")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 6: 结果验证
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print(f"\n{'='*60}")
print(f"验证结果")
print(f"{'='*60}")

if actions_received:
    action = actions_received[0]
    print(f"  动作数量: {len(actions_received)} chunks")
    
    # Extract actual actions
    if hasattr(action, 'action'):
        act_tensor = action.action
    elif hasattr(action, 'get_action'):
        act_tensor = action.get_action()
    else:
        act_tensor = None
    
    if act_tensor is not None:
        if isinstance(act_tensor, torch.Tensor):
            print(f"  动作形状: {list(act_tensor.shape)}")
            print(f"  动作范围: [{act_tensor.min().item():.4f}, {act_tensor.max().item():.4f}]")
            print(f"  动作均值: {act_tensor.mean().item():.4f}")
        else:
            print(f"  动作类型: {type(act_tensor)}")
    
    print(f"\n✅ gRPC推理全流程验证通过！")
    print(f"   Server: PolicyServer @ {SERVER_PORT}")
    print(f"   Model:  SmolVLA ({CKPT})")
    print(f"   Data:   {DATASET} ({n_frames} frames)")
    print(f"   往返:   {n_frames} 观测 → {action_count} 动作块 ({elapsed:.2f}s)")
else:
    print("❌ 未收到动作")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 清理
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print(f"\n🧹 清理...")
grpc_server.stop(0)
channel.close()
print(f"   ✅ 完成")
