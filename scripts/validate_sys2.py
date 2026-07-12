#!/usr/bin/env python3
"""
Z-MAX Sys2 快速验证脚本

在 4090 上验证 VTLA + GR00T 推理引擎是否正常工作。
"""
import sys
import os
import time
import numpy as np
import torch

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from lerobot.policies.zmax_sys2 import (
    ZmaxSys2Config,
    ZmaxSys2Policy,
    SimFeedback,
    Sys2InferenceResult,
)

print("=" * 60)
print("Z-MAX Sys2 验证 (4090)")
print("=" * 60)

# 1. 检查 GPU
if torch.cuda.is_available():
    gpu_name = torch.cuda.get_device_name(0)
    gpu_mem = torch.cuda.get_device_properties(0).total_mem / 1e9
    print(f"\n✅ GPU: {gpu_name} ({gpu_mem:.1f} GB)")
else:
    print("\n❌ No GPU available!")
    sys.exit(1)

# 2. 创建配置
config = ZmaxSys2Config(
    vtla_model_path="lerobot/smolvla_base",
    grpc_port=50052,
    http_port=8080,
    enable_tactile=True,
)
print(f"\n📋 Config: VTLA={config.vtla_model_path or 'default'}, GR00T={config.groot_model_path or 'not set'}")

# 3. 初始化 Sys2
print("\n🔧 Initializing Sys2...")
sys2 = ZmaxSys2Policy(config)

# 4. 加载模型
print("\n📦 Loading models...")
sys2.load_models("vtla")  # 先只加载 VTLA
loaded = sys2.list_loaded_models()
print(f"   Loaded: {loaded}")

# 5. 构造仿真数据
print("\n🎯 Creating test observation...")
sim = SimFeedback(
    camera_rgb=np.random.rand(3, 480, 640).astype(np.float32),
    force_torque=np.array([0.1, 0.2, -0.5, 0.01, 0.02, 0.03], dtype=np.float32),
    tactile=np.random.rand(16).astype(np.float32),
    joint_states=np.zeros(14, dtype=np.float32),
    gripper_pos=0.5,
    task_text="pick up the red block and place it on the table",
)

# 6. 推理测试
print("\n🚀 Running inference...")

for model_type in ["auto", "vtla", "act"]:
    t0 = time.time()
    result = sys2.predict(sim, model=model_type)
    elapsed = (time.time() - t0) * 1000

    status = "✅" if result.model_used != "none" and "error" not in result.task_type else "❌"
    print(f"\n  {status} model={model_type:6s} → used={result.model_used:20s} "
          f"task={result.task_type:15s} action_shape={result.action.shape} "
          f"time={elapsed:.1f}ms")

# 7. 状态
print(f"\n📊 Status: {json.dumps(sys2.get_status(), indent=2)}")

# 8. 服务测试
print("\n🌐 Testing server startup...")
server = sys2.start_server()
if server:
    print("   ✅ gRPC server started successfully")
    server.stop()
else:
    print("   ⚠️  gRPC server not available (dependencies may be missing)")

print(f"\n{'=' * 60}")
print("✅ Sys2 validation complete!")
print(f"{'=' * 60}")
