#!/usr/bin/env python3
"""Z-MAX 推理服务端到端验证 — 不走GUI，直接脚本测试完整的Server+Client链路"""
import sys, os, time, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from inference_server import ZmaxInferenceServer
from inference_client import ZmaxInferenceClient

def main():
    server = ZmaxInferenceServer()
    client = ZmaxInferenceClient()
    
    # Step 1: 启动服务端
    print("Step 1: 启动服务端...")
    ckpt = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "outputs/smolvla_metaworld/checkpoints/000300/pretrained_model"))
    if not os.path.exists(ckpt):
        print(f"❌ Checkpoint not found: {ckpt}")
        return False
    
    if not server.start_server(ckpt, host="127.0.0.1", port=50055):
        print("❌ 服务端启动失败")
        return False
    print(f"✅ 服务端就绪")
    
    # Step 2: 客户端连接 + 发送策略
    print("\nStep 2: 客户端连接...")
    if not client.connect("127.0.0.1:50055"):
        print("❌ 客户端连接失败")
        server.stop_server()
        return False
    print("✅ 客户端已连接")
    
    print("Step 3: 发送策略...")
    if not client.send_policy(ckpt):
        print("❌ 策略发送失败")
        server.stop_server()
        return False
    print("✅ 策略已发送（等待模型加载...）")
    
    # Step 4: 等待模型加载
    print("\nStep 4: 等待模型加载...")
    for i in range(30):  # 最多等30秒
        time.sleep(1)
        if server.model_loaded:
            print(f"✅ 模型加载完成 ({i+1}s)")
            break
    else:
        print("⚠️ 模型加载超时")
    
    # Step 5: Dummy数据流
    print("\nStep 5: Dummy数据流...")
    client.start_dummy_stream(fps=5, duration_sec=5)
    time.sleep(6)
    client.stop_stream()
    
    # Step 6: 验证结果
    print(f"\nStep 6: 结果")
    status = client.get_status()
    print(f"  帧发送: {status['frames_sent']}")
    print(f"  动作接收: {status['actions']}")
    print(f"  信号源: {status['source']}")
    
    success = status['actions'] > 0
    print(f"\n{'✅ 端到端验证通过！' if success else '❌ 未收到动作'}")
    
    # 清理
    client.disconnect()
    server.stop_server()
    return success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
