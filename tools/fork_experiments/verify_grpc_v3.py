#!/usr/bin/env python3
"""
Z-MAX gRPC推理验证 v3 — 定制预处理器
直接注入自定义preprocessor，绕过checkpoint的训练预处理器
"""
import sys, os, time, threading, pickle
from concurrent import futures
import grpc, torch, numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lerobot.transport import services_pb2, services_pb2_grpc
from lerobot.async_inference.configs import PolicyServerConfig
from lerobot.async_inference.policy_server import PolicyServer
from lerobot.async_inference.helpers import RemotePolicyConfig, TimedObservation
from lerobot.policies.smolvla import SmolVLAPolicy
from lerobot.datasets import LeRobotDataset, LeRobotDatasetMetadata
from lerobot.utils.feature_utils import dataset_to_policy_features
from lerobot.utils.constants import OBS_LANGUAGE_TOKENS, OBS_LANGUAGE_ATTENTION_MASK
from lerobot.configs import FeatureType

device = torch.device("cuda")
CKPT = os.path.abspath("outputs/smolvla_metaworld/checkpoints/000300/pretrained_model")
PORT = 50053
print(f"设备: {device}  模型: {CKPT}")

# ━━ 加载数据集/特征 ━━
meta = LeRobotDatasetMetadata("lerobot/metaworld_mt50")
pf = dataset_to_policy_features(meta.features)
ds = LeRobotDataset("lerobot/metaworld_mt50", episodes=[0])

# ━━ 构建features ━━
from lerobot.configs import FeatureType as FT
lf = {}
for k, v in pf.items():
    if k == "observation.state":
        lf[k] = {"dtype": "float32", "shape": list(v.shape), 
                 "names": [f"s{i}" for i in range(v.shape[0])]}
    elif k == "observation.image":
        lf[k] = {"dtype": "video", "shape": list(v.shape)}
print(f"Features: {list(lf.keys())}")

# ━━ 启动Server ━━
print(f"\n🚀 gRPC服务 @ :{PORT}")
cfg = PolicyServerConfig(host="127.0.0.1", port=PORT)
ps = PolicyServer(cfg)
srv = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
services_pb2_grpc.add_AsyncInferenceServicer_to_server(ps, srv)
srv.add_insecure_port(f"127.0.0.1:{PORT}")
srv.start(); time.sleep(0.3)
print(f"   ✅ 就绪")

# ━━ Client: Ready + SendPolicy ━━
ch = grpc.insecure_channel(f"localhost:{PORT}")
stub = services_pb2_grpc.AsyncInferenceStub(ch)
stub.Ready(services_pb2.Empty())

pcfg = RemotePolicyConfig(
    policy_type="smolvla", pretrained_name_or_path=CKPT,
    lerobot_features=lf, actions_per_chunk=50, device="cuda", rename_map={},
)

t0 = time.time()
stub.SendPolicyInstructions(services_pb2.PolicySetup(data=pickle.dumps(pcfg)))
print(f"   ✅ 模型加载 ({time.time()-t0:.1f}s)")

# ━━ 定制预处理器 — 注入到Server ━━
from transformers import AutoTokenizer
tokenizer = AutoTokenizer.from_pretrained(ps.policy.config.vlm_model_name)

def custom_preprocessor(obs_dict):
    """手动构建SmolVLA需要的输入格式，跳过checkpoint的训练预处理器"""
    import torch
    device = ps.device
    B = 1
    
    # 处理图像
    img = obs_dict.get("observation.image")
    if img is not None:
        if isinstance(img, np.ndarray):
            img = torch.from_numpy(img).float() / 255.0
        if img.ndim == 3:
            img = img.unsqueeze(0)  # (1, C, H, W)
        img = img.to(device)
    else:
        img = torch.zeros(B, 3, 480, 480, device=device)
    
    # 处理状态
    state = obs_dict.get("observation.state")
    if state is not None:
        if isinstance(state, np.ndarray):
            state = torch.from_numpy(state).float()
        state = state.to(device)
        if state.ndim == 1:
            state = state.unsqueeze(0)
    else:
        state = torch.zeros(B, 4, device=device)
    
    # 语言token
    task = obs_dict.get("task", "complete the task")
    if isinstance(task, list):
        task = task[0] if task else "complete the task"
    encoded = tokenizer(str(task), return_tensors="pt", padding="max_length",
                        max_length=ps.policy.config.tokenizer_max_length, truncation=True)
    
    result = {
        "observation.image": img,
        "observation.state": state,
        OBS_LANGUAGE_TOKENS: encoded["input_ids"].to(device),
        OBS_LANGUAGE_ATTENTION_MASK: encoded["attention_mask"].to(torch.bool).to(device),
    }
    return result

# 替换preprocessor
ps.preprocessor = custom_preprocessor
ps.postprocessor = lambda x: x  # 不做后处理
print(f"   ✅ 定制预处理器已注入")

from torch.utils.data import DataLoader

# ━━ 发送观测 → 获取动作 ━━
loader = DataLoader(ds, batch_size=1, shuffle=True)
batch = next(iter(loader))
batch = {k: v.to(device) if isinstance(v, torch.Tensor) else v for k, v in batch.items()}

state_arr = batch["observation.state"].cpu().numpy().flatten()
obs_dict = {}
for i, val in enumerate(state_arr):
    obs_dict[f"s{i}"] = float(val)
obs_dict["observation.image"] = batch["observation.image"].cpu().numpy()
obs_dict["task"] = "complete the manipulation task"

timed_obs = TimedObservation(timestamp=time.time(), timestep=0, observation=obs_dict)
data = pickle.dumps(timed_obs)

def obs_gen():
    yield services_pb2.Observation(transfer_state=services_pb2.TRANSFER_BEGIN, data=data)
    yield services_pb2.Observation(transfer_state=services_pb2.TRANSFER_END, data=b"")

t = threading.Thread(target=lambda: stub.SendObservations(obs_gen()), daemon=True)
t.start(); time.sleep(0.5)
print(f"   📤 观测推送: state={list(state_arr[:2])}... img={batch['observation.image'].shape}")

try:
    resp = stub.GetActions(services_pb2.Empty(), timeout=8)
    if resp.data:
        a = pickle.loads(resp.data)
        print(f"\n✅✅✅ gRPC推理成功！")
        print(f"   动作: {a.action.shape if hasattr(a,'action') else type(a)}")
        if hasattr(a, 'action'):
            print(f"   形状: {list(a.action.shape)}")
            print(f"   范围: [{a.action.min():.3f}, {a.action.max():.3f}]")
    else:
        print(f"\n⚠️ 空响应")
except grpc.RpcError as e:
    print(f"\n⚠️ {e.code()}: {e.details()}")

t.join(timeout=2)
srv.stop(0); ch.close()
print(f"\n🧹 完成")
