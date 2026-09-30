#!/usr/bin/env python3
"""Z-MAX CICD 部署 · MAC端
从 ECS 中转拉取 4060 训练产物 → 部署到 Orin

链路: 4060训练 → ECS中转 → Mac拉取 → Orin部署
⚠️ 中继是弹栈式队列 (拉取即删, 一次成功, 不保存即丢)！
⚠️ 二进制模型必须用本脚本或 curl -o 保存; relay_train.py pull 只用于 JSON 训练数据。
用法:
  python3 cicd_pull_deploy.py       # 拉取最新模型并部署到 Orin
  python3 cicd_pull_deploy.py pull  # 只拉取 (保存到 ~/zmax_deploy/)
  python3 cicd_pull_deploy.py deploy <本地模型路径>  # 只部署
"""
import json, sys, time, subprocess, os
from pathlib import Path
import requests

RELAY = "https://datadrive.world/api/relay"
ORIN, ORIN_PW = "tashan@192.168.23.10", "ts123"
MAC_DIR = Path.home() / "zmax_deploy"
MAC_DIR.mkdir(parents=True, exist_ok=True)


def run_ssh(cmd, timeout=60):
    r = subprocess.run(["sshpass", "-p", ORIN_PW, "ssh", "-o", "StrictHostKeyChecking=no",
                        ORIN, cmd], capture_output=True, text=True, timeout=timeout)
    return r


def pull():
    """拉取最新部署包 (拉取即删)"""
    r = requests.get(f"{RELAY}/latest", timeout=30)
    if r.status_code != 200:
        print(f"⚠️  无部署包: {r.text[:100]}")
        return None
    data = r.content
    name = f"deploy_{time.strftime('%Y%m%d_%H%M%S')}.pt"
    path = MAC_DIR / name
    path.write_bytes(data)
    print(f"✅ 拉取部署包: {name} ({len(data)//1024}KB)")
    return path


def deploy(path):
    """部署模型到 Orin + 启动推理服务 (状态上报 ECS → 控制台可见)"""
    print(f"🤖 部署到 Orin: {path}...")
    # 1. 上传模型到 Orin
    r = subprocess.run(["sshpass", "-p", ORIN_PW, "scp", "-o", "StrictHostKeyChecking=no",
                        str(path), f"{ORIN}:/tmp/zmax_act_model.pt"],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        print(f"❌ scp失败: {r.stderr[:200]}")
        return False
    # 2. 上传推理服务脚本
    script = Path(__file__).parent / "orin_infer_service.py"
    subprocess.run(["sshpass", "-p", ORIN_PW, "scp", "-o", "StrictHostKeyChecking=no",
                    str(script), f"{ORIN}:/tmp/orin_infer_service.py"],
                   capture_output=True, text=True, timeout=60)
    # 3. 启动推理服务 (重启已存在的)
    cmd = ("pkill -f orin_infer_service.py 2>/dev/null; sleep 1; "
           "cd /tmp && setsid nohup python3 orin_infer_service.py --model /tmp/zmax_act_model.pt "
           "> /tmp/orin_infer.log 2>&1 < /dev/null & sleep 3; "
           "curl -s -m 3 http://127.0.0.1:8766/status")
    r = run_ssh(cmd, timeout=30)
    print(f"  推理服务状态: {r.stdout[:200]}")
    if "online" in r.stdout:
        print("✅ 模型已部署并运行 Orin (:8766) · 状态已上报 ECS")
        return True
    print(f"❌ Orin 启动失败: {r.stdout[:200]}{r.stderr[:200]}")
    return False


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "pull":
        pull()
    elif len(sys.argv) > 2 and sys.argv[1] == "deploy":
        deploy(Path(sys.argv[2]))
    else:
        p = pull()
        if p:
            deploy(p)
