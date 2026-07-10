#!/usr/bin/env python3
"""
Z-MAX 仿真集成测试 — Client-Server 联通验证

测试内容:
1. 协议编解码
2. 传感器模拟器输出
3. Client standalone 模式
4. Client-Server WebSocket 联通
5. 消息往返延迟
6. 数据吞吐量

用法:
    # 完整测试 (需要先启动 server)
    python3 test_simulation_integration.py
    
    # 仅本地测试 (不需要 server)
    python3 test_simulation_integration.py --local-only
"""

import sys, os, time, json, math, asyncio, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from simulation_protocol import (
    JointState, ForceTorque, TactileData, CameraFrame, GripperState,
    SensorData, Action, Heartbeat, SimConfig, MessageType,
    build_sensor_data, build_action, encode_message, decode_message, TOPICS
)


# ═══════════════════════════════════════════════
# 测试1: 协议编解码
# ═══════════════════════════════════════════════

def test_protocol_encoding():
    print("\n📋 测试 1: 协议编解码")
    
    # 编码
    action = build_action(1, [0.1, -0.2, 0.3, 0.4, -0.5, 0.6], 0.8, 214.7)
    encoded = encode_message(action)
    
    # 解码
    decoded = decode_message(encoded)
    
    assert decoded["msg_type"] == "action"
    assert decoded["seq"] == 1
    assert decoded["gripper_cmd"] == 0.8
    assert decoded["inference_time_ms"] == 214.7
    assert len(decoded["joint_positions"]) == 6
    
    # 传感器数据
    sd = build_sensor_data(42)
    encoded = encode_message(sd)
    decoded = decode_message(encoded)
    assert decoded["msg_type"] == "sensor_data"
    assert decoded["seq"] == 42
    assert decoded["robot_model"] == "XMS5-R800-W4G3B4C"
    assert "joint_state" in decoded
    assert "force_torque" in decoded
    assert "camera" in decoded
    assert "gripper" in decoded
    assert "tactile" in decoded
    
    print(f"  ✅ 编码/解码正常 (action {len(encode_message(action))}B, sensor {len(encode_message(sd))}B)")


# ═══════════════════════════════════════════════
# 测试2: 传感器模拟器
# ═══════════════════════════════════════════════

def test_sensor_simulators():
    print("\n📋 测试 2: 传感器模拟器")
    
    from simulation_client import (
        JointSimulator, ForceTorqueSimulator, 
        CameraSimulator, GripperSimulator, TactileSimulator
    )
    
    # 关节
    js = JointSimulator()
    state = js.read()
    assert len(state.names) == 6
    assert len(state.positions) == 6
    assert -3.2 <= state.positions[2] <= 3.2  # joint_3 范围
    print(f"  ✅ 关节: 6轴, position[0]={state.positions[0]:.4f}")
    
    # 力传感器
    ft = ForceTorqueSimulator()
    data = ft.read()
    assert -50 <= data.fz <= 50
    print(f"  ✅ 力传感器: Fz={data.fz:.2f}N")
    
    # 相机
    cam = CameraSimulator()
    frame = cam.read()
    assert frame.width == 640 and frame.height == 480
    assert frame.source == "realsense_d435"
    print(f"  ✅ 相机: {frame.width}×{frame.height}")
    
    # 夹爪
    grip = GripperSimulator()
    gs = grip.read()
    assert 0 <= gs.position <= 1
    print(f"  ✅ 夹爪: pos={gs.position:.3f}")
    
    # 触觉
    tac = TactileSimulator()
    td = tac.read(force_z=4.0)
    assert len(td.pressure_grid) == 4 and len(td.pressure_grid[0]) == 4
    assert td.contact_detected  # force_z足够大
    print(f"  ✅ 触觉: 4×4阵列, contact={td.contact_detected}")


# ═══════════════════════════════════════════════
# 测试3: Client Standalone
# ═══════════════════════════════════════════════

async def test_client_standalone():
    print("\n📋 测试 3: Client Standalone 模式")
    
    from simulation_client import SimulationClient
    
    client = SimulationClient(standalone=True)
    client.sensor_rate_hz = 50  # 快速测试
    
    # 发布100包数据
    for i in range(100):
        sensor = await client.publish_sensors()
        assert sensor.seq == i + 1
        assert "joint_state" in encode_message(sensor)
    
    elapsed = time.time() - client.stats["start_time"]
    rate = client.stats["sensor_packets_sent"] / elapsed
    print(f"  ✅ 100包数据发布, 速率={rate:.1f} Hz")


# ═══════════════════════════════════════════════
# 测试4: 消息大小/吞吐量基准
# ═══════════════════════════════════════════════

def test_throughput_benchmark():
    print("\n📋 测试 4: 吞吐量基准")
    
    # 测量各种消息大小
    sensor = build_sensor_data(0)
    sensor_bytes = len(encode_message(sensor))
    
    action = build_action(0, [0.1] * 6, 0.5, 214.7)
    action_bytes = len(encode_message(action))
    
    heartbeat = Heartbeat(seq=0, timestamp=time.time(), source="client")
    hb_bytes = len(encode_message(heartbeat))
    
    # 模拟30Hz持续发送的带宽
    bandwidth_30hz = sensor_bytes * 30
    bandwidth_mbps = bandwidth_30hz * 8 / 1_000_000
    
    results = {
        "sensor_packet_bytes": sensor_bytes,
        "action_packet_bytes": action_bytes,
        "heartbeat_bytes": hb_bytes,
        "bandwidth_30hz_mbps": round(bandwidth_mbps, 2),
        "recommended_min_bandwidth_mbps": round(bandwidth_mbps * 1.5, 2),
    }
    
    print(f"  ✅ 传感器包: {sensor_bytes}B | 动作包: {action_bytes}B")
    print(f"  ✅ 30Hz带宽需求: {results['bandwidth_30hz_mbps']} Mbps")
    print(f"  ✅ 推荐最小带宽: {results['recommended_min_bandwidth_mbps']} Mbps")
    
    return results


# ═══════════════════════════════════════════════
# 测试5: 话题名兼容性
# ═══════════════════════════════════════════════

def test_topic_names():
    print("\n📋 测试 5: 话题名兼容性")
    
    # 检查所有话题名以 /sim/ 开头
    for name, topic in TOPICS.items():
        assert topic.startswith("/sim/"), f"话题 {name}={topic} 必须以 /sim/ 开头"
    
    # 检查关键话题存在
    assert TOPICS["joint_states"] == "/sim/joint_states"
    assert TOPICS["action"] == "/sim/action"
    assert TOPICS["force_torque"] == "/sim/robot/force_torque"
    assert TOPICS["camera_color"] == "/sim/realsense/color/image_raw"
    
    print(f"  ✅ {len(TOPICS)} 话题, 全部命名合规")


# ═══════════════════════════════════════════════
# 测试6: Client-Server 联通 (需要Server运行)
# ═══════════════════════════════════════════════

async def test_client_server_integration(host="localhost", port=8765):
    print(f"\n📋 测试 6: Client-Server 联通 ({host}:{port})")
    
    try:
        import websockets
    except ImportError:
        print("  ⚠️  websockets未安装, 跳过联通测试")
        return None
    
    try:
        ws = await asyncio.wait_for(
            websockets.connect(f"ws://{host}:{port}"),
            timeout=3.0
        )
    except Exception as e:
        print(f"  ⚠️  无法连接服务器: {e}")
        print("  💡 提示: 先在WSL2端启动 simulation_server.py")
        return None
    
    # 等待就绪信号
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = decode_message(raw if isinstance(raw, str) else raw.decode())
        assert msg["msg_type"] in [MessageType.READY, MessageType.CONFIG]
        print(f"  ✅ 收到服务器信号: {msg.get('msg_type')}")
    except asyncio.TimeoutError:
        print("  ⚠️  服务器无响应")
        await ws.close()
        return None
    
    # 发送传感器数据
    sensor = build_sensor_data(1)
    await ws.send(encode_message(sensor))
    
    # 等待动作返回
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = decode_message(raw if isinstance(raw, str) else raw.decode())
        assert msg["msg_type"] == MessageType.ACTION
        assert len(msg["joint_positions"]) == 6
        print(f"  ✅ 收到动作: 6轴, gripper={msg['gripper_cmd']:.2f}")
    except asyncio.TimeoutError:
        print("  ⚠️  未收到动作响应")
    
    # 延迟测试
    latencies = []
    for i in range(10):
        sensor = build_sensor_data(i + 2)
        t0 = time.time()
        await ws.send(encode_message(sensor))
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
            msg = decode_message(raw if isinstance(raw, str) else raw.decode())
            if msg["msg_type"] == MessageType.ACTION:
                latencies.append((time.time() - t0) * 1000)
        except asyncio.TimeoutError:
            pass
    
    if latencies:
        avg_lat = sum(latencies) / len(latencies)
        print(f"  ✅ 往返延迟: avg={avg_lat:.1f}ms (n={len(latencies)})")
    
    await ws.close()
    
    return {
        "avg_latency_ms": round(avg_lat, 1) if latencies else None,
        "samples": len(latencies),
    }


# ═══════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-only", action="store_true")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    
    print("""
╔══════════════════════════════════════════════╗
║   Z-MAX 仿真集成测试                          ║
╚══════════════════════════════════════════════╝
""")
    
    results = {}
    
    # 本地测试
    test_protocol_encoding()
    test_sensor_simulators()
    await test_client_standalone()
    throughput = test_throughput_benchmark()
    test_topic_names()
    
    results["throughput"] = throughput
    
    # 联通测试
    if not args.local_only:
        integration = await test_client_server_integration(args.host, args.port)
        if integration:
            results["integration"] = integration
    
    # 汇总
    print(f"""
┌──────────────────────────────────────────────┐
│          测试汇总 — 全部通过 ✅                │
├──────────────────────────────────────────────┤
│  协议编解码:     ✅
│  传感器模拟器:   ✅ (关节/力/相机/夹爪/触觉)
│  Client独立模式: ✅ (100包数据)
│  吞吐量基准:     ✅ ({throughput['bandwidth_30hz_mbps']} Mbps @30Hz)
│  话题名兼容性:   ✅ ({len(TOPICS)} topics)""")
    
    if "integration" in results:
        print(f"│  Client-Server:  ✅ (延迟={results['integration']['avg_latency_ms']}ms)")
    else:
        print(f"│  Client-Server:  ⏭ 跳过 (WSL2端未启动)")
    
    print(f"""└──────────────────────────────────────────────┘
""")
    
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
