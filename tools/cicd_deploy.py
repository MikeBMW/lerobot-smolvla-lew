#!/usr/bin/env python3
"""Z-MAX CICD 部署脚本 · 4060端
链路: 4060训练产物 → ECS中转 → 小芳Mac拉取 → 部署Orin

用法:
  python3 tools/cicd_deploy.py push   # 上传最新模型产物到ECS
  python3 tools/cicd_deploy.py status # 查看部署状态
"""
import json, sys, time, glob, os
from pathlib import Path
import requests

RELAY = "https://datadrive.world/api/relay"
HOME = Path.home()
OUT = HOME / "lerobot-smolvla-lew" / "outputs" / "train"


def find_latest_model():
    """找最新训练产物 (checkpoint)"""
    cands = []
    for d in sorted(glob.glob(str(OUT / "*"))):
        # 找 policy 权重目录
        for pat in ("**/model.safetensors", "**/policy/*.pt", "**/checkpoint*.pt"):
            for f in glob.glob(os.path.join(d, pat), recursive=True):
                if os.path.isfile(f):
                    cands.append((os.path.getmtime(f), f))
    if not cands:
        print("⚠️  未找到训练产物")
        return None
    cands.sort(reverse=True)
    path = cands[0][1]
    print(f"📦 最新产物: {path} ({os.path.getsize(path)//1024}KB)")
    return path


def push():
    """上传模型产物到 ECS 中转 (供小芳拉取部署)"""
    path = find_latest_model()
    if not path:
        return
    name = f"model_{time.strftime('%Y%m%d_%H%M%S')}_{os.path.basename(path)}"
    with open(path, "rb") as f:
        data = f.read()
    r = requests.post(f"{RELAY}/upload", data=data, timeout=60)
    print(f"📤 推送结果: {r.json()}")
    # 记录部署元信息
    meta = {"name": name, "size": len(data), "source": "4060", "time": time.time(),
            "model": "act", "target": "orin"}
    requests.post(f"{RELAY}/upload", json={"name": f"deploy_meta_{name}.json", "meta": meta},
                  timeout=10)
    print("✅ 部署包已就绪, 通知小芳拉取 → Orin")


def status():
    r = requests.get(f"{RELAY}/status", timeout=10)
    print(json.dumps(r.json(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "status"
    {"push": push, "status": status}[mode]()
