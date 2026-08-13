#!/usr/bin/env python3
"""Z700 整体部署包生成器 — YOLO + 双脑模型 + 状态机 + meta (2026-08-10)
打包 → ECS relay 中转 → Mac docker 拉取部署

用法:
  python tools/z700_build_package.py              # 生成 z700_<ts>.tar.gz
  python tools/z700_build_package.py --push       # 生成 + 推 ECS relay
"""
import argparse, hashlib, json, os, shutil, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "outputs", "z700_packages")

# 资产清单
ASSETS = {
    "model/yolo_peg_best.pt": os.path.join(ROOT, "runs/detect/outputs/yolo_peg/peg_full/weights/best.pt"),
    "model/left_right_model.pt": os.path.join(ROOT, "outputs/rl_peg/full_pipeline.pt"),
    "state_machines/orin_main_flow.yaml": os.path.join(ROOT, "config/state_machines/orin_main_flow.yaml"),
    "state_machines/orin_production_flow.yaml": os.path.join(ROOT, "config/state_machines/orin_production_flow.yaml"),
    "state_machines/插拔工序.yaml": os.path.join(ROOT, "config/state_machines/插拔工序.yaml"),
}

RELAY_UPLOAD = "https://datadrive.world/api/relay/upload"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(push=False):
    os.makedirs(OUT_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    pkg_name = f"z700_{ts}.tar.gz"
    staging = os.path.join(OUT_DIR, f"z700_{ts}")
    os.makedirs(staging, exist_ok=True)

    # 拷贝资产 + 算 sha256
    manifest = {"version": "z700-v1.0", "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "models": [], "files": {}}
    for rel, src in ASSETS.items():
        if not os.path.exists(src):
            print(f"⚠️ 缺失: {src}")
            continue
        dst = os.path.join(staging, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        manifest["files"][rel] = {"size": os.path.getsize(src), "sha256": sha256(src)}
        print(f"  📦 {rel} ({os.path.getsize(src)//1024}KB)")

    # meta.json
    with open(os.path.join(staging, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # Dockerfile (Mac arm64 部署)
    dockerfile = """# Z700 left_right 推理容器 (arm64) — 2026-08-10
FROM arm64v8/python:3.11-slim
WORKDIR /app
COPY model/ /app/model/
COPY state_machines/ /app/state_machines/
COPY meta.json /app/
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \\
    && pip install --no-cache-dir numpy pyyaml ultralytics websockets
# 推理入口 (eval_lr.py 部署时由 cicd 脚本挂载)
CMD ["python", "-c", "import torch,numpy,yaml;print('Z700 推理容器就绪')"]
"""
    with open(os.path.join(staging, "Dockerfile"), "w") as f:
        f.write(dockerfile)

    # 打包
    pkg_path = os.path.join(OUT_DIR, pkg_name)
    subprocess.run(["tar", "czf", pkg_path, "-C", OUT_DIR, f"z700_{ts}"], check=True)
    size = os.path.getsize(pkg_path)
    print(f"\n✅ 打包完成: {pkg_path} ({size//1024//1024}MB)")
    print(f"   sha256: {sha256(pkg_path)}")

    if push:
        # 推 ECS relay
        print(f"\n🚀 推 ECS relay...")
        r = subprocess.run(["curl", "-s", "-m", "120", "-X", "POST", RELAY_UPLOAD,
                            "-F", f"file=@{pkg_path}"], capture_output=True, text=True)
        print(f"   relay 响应: {r.stdout[:200]}")
    return pkg_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true", help="打包后推送 ECS relay")
    args = ap.parse_args()
    build(push=args.push)
