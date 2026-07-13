#!/usr/bin/env python3
"""Z-MAX 统一训练管线 — 数据闭环核心

模型清单:
  Sys1  ACT        — 52M, 在4060 (xspace)
  Sys11 SmolVLA    — 450M, 在4060/4090
  Sys12 LeWorld    — 5.5M, 在4060 (xspace)
  Sys11+Sys12 混合 — SmolVLA+LeWorld联合
  Sys21 VTLA       — 450M, 在4090 (web)
  Sys22 GR00T      — 7B, 在4090 (web)

数据闭环:
  Orin(192.168.23.10) → Mac(小芳,订阅rosbag) → 4060(xspace,Sys11/12推理)
  → ECS(39.102.211.79)中转 → 4090(web,训练) → 权重回传ECS
"""

import os, sys, json, time, argparse
from pathlib import Path

MODEL_REGISTRY = {
    "vtla": {"module": "lerobot.policies.smolvla", "class": "SmolVLAPolicy",
             "weights": "/root/models/smolvla_base", "desc": "Sys21 VTLA 450M 触觉VLA"},
    "groot": {"module": "gr00t.policy.gr00t_policy", "class": "Gr00tPolicy",
              "weights": "/root/models/gr00t-n1.7-3b", "desc": "Sys22 GR00T 7B 通用模型"},
}

def train_vtla(rounds=3):
    """Sys21 VTLA 训练 — 随机初始化多轮"""
    print(f"🔧 Sys21 VTLA: {rounds} rounds")
    best_loss = float('inf')
    for r in range(rounds):
        print(f"\n=== Round {r+1}/{rounds} ===")
        # Run zmax_full_pipeline.py
        ret = os.system(f"{sys.executable} zmax_full_pipeline.py 2>&1 | tail -5")
        print(f"  Round {r+1} done")
    return best_loss

def train_groot(dataset_path, output_dir="/root/models/groot-finetuned"):
    """Sys22 GR00T 微调 — 需要MetaWorld等大数据集"""
    if not os.path.exists(dataset_path):
        raise FileNotFoundError(f"数据集不存在: {dataset_path}")
    print(f"🔧 Sys22 GR00T: dataset={dataset_path}")
    cmd = f"bash examples/finetune.sh --base-model-path /root/models/gr00t-n1.7-3b --dataset-path {dataset_path} --embodiment-tag OXE_DROID_RELATIVE_EEF_RELATIVE_JOINT --output-dir {output_dir}"
    return os.system(cmd)

def data_pipeline_check():
    """检查数据闭环各节点连通性"""
    nodes = {
        "Orin": "192.168.23.10",
        "4060": "192.168.23.26", 
        "ECS": "39.102.211.79",
        "4090": "10.23.24.0",
    }
    print("📡 数据闭环节点:")
    for name, ip in nodes.items():
        reachable = os.system(f"ping -c1 -W1 {ip} > /dev/null 2>&1") == 0
        status = "✅" if reachable else "❌"
        print(f"  {status} {name} ({ip})")
    return nodes

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Z-MAX 统一训练管线")
    parser.add_argument("--model", choices=list(MODEL_REGISTRY.keys()) + ["all"], default="vtla")
    parser.add_argument("--rounds", type=int, default=3, help="VTLA训练轮数")
    parser.add_argument("--dataset", help="GR00T数据集路径")
    parser.add_argument("--ping", action="store_true", help="检查数据闭环连通性")
    args = parser.parse_args()
    
    if args.ping:
        data_pipeline_check()
    elif args.model == "vtla":
        train_vtla(args.rounds)
    elif args.model == "groot" and args.dataset:
        train_groot(args.dataset)
    else:
        print("用法: python unified_train.py --model vtla --rounds 3")
        print("     python unified_train.py --model groot --dataset /path/to/metaworld")
        print("     python unified_train.py --ping")
