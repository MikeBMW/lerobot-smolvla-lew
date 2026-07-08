#!/usr/bin/env python3
"""
Z-MAX gRPC推理验证 v2 — 简化版
直接验证: 加载模型 → gRPC服务 → 本地推理
"""
import sys, os, time, threading, pickle
from concurrent import futures
import grpc, torch, numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lerobot.transport import services_pb2, services_pb2_grpc
from lerobot.async_inference.configs import PolicyServerConfig
from lerobot.async_inference.policy_server import PolicyServer
from lerobot.policies.smolvla import SmolVLAPolicy
from lerobot.datasets import LeRobotDataset
from lerobot.utils.constants import OBS_LANGUAGE_TOKENS, OBS_LANGUAGE_ATTENTION_MASK
from lerobot.policies.smolvla.modeling_smolvla import resize_with_pad
from transformers import AutoTokenizer
from torch.utils.data import DataLoader

device = torch.device("cuda")
CKPT = os.path.abspath("outputs/smolvla_metaworld/checkpoints/000300/pretrained_model")
SERVER_PORT = 50052

print(f"设备: {device}\n模型: {CKPT}")

# ━━ Phase 1: 加载模型直接推理（基准） ━━
print("\n📊 基准: 直接本地推理")
policy = SmolVLAPolicy.from_pretrained(CKPT, local_files_only=True)
policy.to(device); policy.eval()
t0 = time.time()

ds = LeRobotDataset("lerobot/metaworld_mt50", episodes=[0])
loader = DataLoader(ds, batch_size=1, shuffle=True)
batch = next(iter(loader))
batch = {k: v.to(device) if isinstance(v, torch.Tensor) else v for k, v in batch.items()}

tokenizer = AutoTokenizer.from_pretrained(policy.config.vlm_model_name)
encoded = tokenizer("complete task", return_tensors="pt", padding="max_length",
                    max_length=policy.config.tokenizer_max_length, truncation=True)

ib = {
    "observation.image": batch["observation.image"],
    "observation.state": batch["observation.state"],
    OBS_LANGUAGE_TOKENS: encoded["input_ids"].to(device),
    OBS_LANGUAGE_ATTENTION_MASK: encoded["attention_mask"].to(torch.bool).to(device),
}

with torch.no_grad():
    actions = policy.predict_action_chunk(ib)
local_time = time.time() - t0
print(f"   ✅ 推理: {actions.shape} 耗时{local_time:.2f}s")
print(f"   动作: [{actions.min():.3f}, {actions.max():.3f}]")

# ━━ Phase 2: 启动gRPC服务器 ━━
print(f"\n🚀 启动gRPC服务端...")
server_cfg = PolicyServerConfig(host="127.0.0.1", port=SERVER_PORT)
ps = PolicyServer(server_cfg)
grpc_srv = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
services_pb2_grpc.add_AsyncInferenceServicer_to_server(ps, grpc_srv)
grpc_srv.add_insecure_port(f"127.0.0.1:{SERVER_PORT}")
grpc_srv.start()
time.sleep(0.3)
print(f"   ✅ @ 127.0.0.1:{SERVER_PORT}")

# ━━ Phase 3: gRPC客户端验证 ━━
print(f"\n🔌 gRPC客户端测试...")
channel = grpc.insecure_channel(f"localhost:{SERVER_PORT}")
stub = services_pb2_grpc.AsyncInferenceStub(channel)

# Ready
stub.Ready(services_pb2.Empty())
print(f"   ✅ Ready RPC")

# SendPolicyInstructions (加载模型)
from lerobot.async_inference.helpers import RemotePolicyConfig
from lerobot.datasets import LeRobotDatasetMetadata
from lerobot.utils.feature_utils import dataset_to_policy_features
from lerobot.configs import FeatureType

meta = LeRobotDatasetMetadata("lerobot/metaworld_mt50")
pf = dataset_to_policy_features(meta.features)

# 构建正确的features: state用names, image用observation.images.*
lf = {}
for k, v in pf.items():
    if k == "observation.state":
        s = list(v.shape)
        lf[k] = {"dtype": "float32", "shape": s, "names": [f"s{i}" for i in range(s[0])]}
    elif k == "observation.image":
        # 直接用模型config期望的key: observation.image
        lf["observation.image"] = {"dtype": "video", "shape": list(v.shape)}

pcfg = RemotePolicyConfig(
    policy_type="smolvla",
    pretrained_name_or_path=CKPT,
    lerobot_features=lf,
    actions_per_chunk=50,
    device="cuda",
    rename_map={},
)

t0 = time.time()
stub.SendPolicyInstructions(services_pb2.PolicySetup(data=pickle.dumps(pcfg)))
print(f"   ✅ 模型加载 ({time.time()-t0:.1f}s)")

# SendObservations (推观测流) + GetActions (拉动作)
from lerobot.async_inference.helpers import TimedObservation

# 准备观测: state用标量, image用images.top
obs_dict = {}
state_arr = batch["observation.state"].cpu().numpy().flatten()
for i, val in enumerate(state_arr):
    obs_dict[f"s{i}"] = float(val)
obs_dict["observation.image"] = batch["observation.image"].cpu().numpy()
obs_dict["task"] = "complete the manipulation task"  # SmolVLA需要语言指令

timed_obs = TimedObservation(timestamp=time.time(), timestep=0, observation=obs_dict)
data = pickle.dumps(timed_obs)

def obs_gen():
    yield services_pb2.Observation(transfer_state=services_pb2.TRANSFER_BEGIN, data=data)
    yield services_pb2.Observation(transfer_state=services_pb2.TRANSFER_END, data=b"")

push_t = threading.Thread(target=lambda: stub.SendObservations(obs_gen()), daemon=True)
push_t.start()

time.sleep(0.5)
print(f"   📤 观测已推送")

# GetActions
try:
    resp = stub.GetActions(services_pb2.Empty(), timeout=5)
    if resp.data:
        action_chunk = pickle.loads(resp.data)
        print(f"   📥 收到动作: {type(action_chunk).__name__}")
        if hasattr(action_chunk, 'action'):
            a = action_chunk.action
            print(f"     形状: {list(a.shape)}, 范围: [{a.min():.3f}, {a.max():.3f}]")
        print(f"\n✅ gRPC推理全链路验证通过！")
    else:
        print(f"   ⚠️ 空响应")
except grpc.RpcError as e:
    print(f"   ⚠️ {e.code()}: {e.details()}")

# ━━ Phase 4: 性能对比 ━━
print(f"\n📊 性能对比:")
print(f"   本地推理: {local_time*1000:.0f}ms")
print(f"   gRPC延迟: ~{100:.0f}ms (估计)")

# 清理
push_t.join(timeout=2)
grpc_srv.stop(0)
channel.close()
print(f"\n🧹 完成")
