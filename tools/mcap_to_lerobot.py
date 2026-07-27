#!/usr/bin/env python3
"""MCAP rosbag → LeRobot 数据集转换器 · GUI可调用"""
import rosbag2_py, os, json, cv2, numpy as np, argparse, time
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message
from sensor_msgs.msg import Image, JointState
from geometry_msgs.msg import WrenchStamped, PoseStamped
from pathlib import Path

def convert_mcap_to_lerobot(mcap_path, output_dir, max_frames=100):
    """MCAP → LeRobot 格式"""
    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=mcap_path, storage_id='sqlite3'), rosbag2_py.ConverterOptions())
    
    img_type = get_message('sensor_msgs/msg/Image')
    joint_type = get_message('sensor_msgs/msg/JointState')
    wrench_type = get_message('geometry_msgs/msg/WrenchStamped')
    
    frames = []
    count = 0
    
    print(f"读取MCAP: {mcap_path}")
    while reader.has_next() and count < max_frames:
        topic, data, t = reader.read_next()
        if topic == '/realsense/color/image_raw':
            img_msg = deserialize_message(data, img_type)
            h, w = img_msg.height, img_msg.width
            arr = list(img_msg.data)[:w*h*3]
            frame = np.array(arr, dtype=np.uint8).reshape(h, w, 3)
            _, buf = cv2.imencode('.jpg', cv2.cvtColor(frame, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 70])
            frames.append({"image": base64.b64encode(buf).decode(), "timestamp": t})
            count += 1
            if count % 10 == 0: print(f"  提取 {count}/{max_frames} 帧...")
    
    # 关联关节/力数据
    reader.open(rosbag2_py.StorageOptions(uri=mcap_path, storage_id='sqlite3'), rosbag2_py.ConverterOptions())
    joints, forces = [], []
    while reader.has_next():
        topic, data, t = reader.read_next()
        if 'joint' in topic or topic == '/real_joint_states' or topic == '/robot/joint_states':
            msg = deserialize_message(data, joint_type)
            joints.append({"t": t, "pos": list(msg.position)})
        elif topic == '/robot/force_torque':
            msg = deserialize_message(data, wrench_type)
            forces.append({"t": t, "f": [msg.wrench.force.x, msg.wrench.force.y, msg.wrench.force.z],
                           "tau": [msg.wrench.torque.x, msg.wrench.torque.y, msg.wrench.torque.z]})
    
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    dataset = {"frames": frames, "joints": joints[:100], "forces": forces[:100], "total_frames": len(frames)}
    json.dump(dataset, open(out / "dataset.json", "w"), indent=2)
    print(f"✅ 转换完成: {out}/dataset.json ({len(frames)}帧, {len(joints)}关节, {len(forces)}力)")

if __name__ == "__main__":
    import sys, base64
    convert_mcap_to_lerobot(sys.argv[1], sys.argv[2] if len(sys.argv)>2 else "data/mcap_import")
