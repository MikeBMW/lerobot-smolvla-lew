#!/usr/bin/env python3
"""Z700 部署包拉取 + docker 部署 (Mac 侧, 2026-08-10 静静 → 小芳)
用法:
  python3 cicd_pull_z700.py                 # 下载最新包 + 校验 sha256 + 解包
  python3 cicd_pull_z700.py --build         # 下载 + 构建 docker 镜像
  python3 cicd_pull_z700.py --run           # 下载 + 构建 + 启动推理容器
"""
import argparse, hashlib, json, os, subprocess, sys, tarfile, urllib.request

DEPLOY_DIR = os.path.expanduser("~/zmax_deploy/z700")
RELEASE_URL = "https://github.com/MikeBMW/lerobot-smolvla-lew/releases/download/z700-deploy-v1.0"
API = "https://api.github.com/repos/MikeBMW/lerobot-smolvla-lew/releases/tags/z700-deploy-v1.0"


def latest_asset():
    """从 GitHub API 找最新 asset"""
    req = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        rel = json.load(r)
    assets = rel.get("assets", [])
    if not assets:
        print("❌ Release 无 asset")
        sys.exit(1)
    a = assets[0]
    return a["name"], a["browser_download_url"], a.get("size", 0)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pull():
    os.makedirs(DEPLOY_DIR, exist_ok=True)
    name, url, size = latest_asset()
    pkg = os.path.join(DEPLOY_DIR, name)
    if os.path.exists(pkg) and os.path.getsize(pkg) == size:
        print(f"✅ 已存在: {name} ({size//1024//1024}MB)")
    else:
        print(f"⬇️ 下载 {name} ({size//1024//1024}MB)...")
        urllib.request.urlretrieve(url, pkg)
        print(f"✅ 下载完成 ({os.path.getsize(pkg)} bytes)")
    # 解包
    with tarfile.open(pkg, "r:gz") as t:
        t.extractall(DEPLOY_DIR)
    # 找解包目录 (z700_<ts>)
    subdirs = [d for d in os.listdir(DEPLOY_DIR) if d.startswith("z700_") and os.path.isdir(os.path.join(DEPLOY_DIR, d))]
    if not subdirs:
        print("❌ 解包失败: 无 z700_* 目录")
        sys.exit(1)
    latest = os.path.join(DEPLOY_DIR, sorted(subdirs)[-1])
    # 校验 meta.json
    meta_p = os.path.join(latest, "meta.json")
    if os.path.exists(meta_p):
        meta = json.load(open(meta_p))
        ok = True
        for rel, info in meta.get("files", {}).items():
            f = os.path.join(latest, rel)
            if os.path.exists(f):
                if sha256(f) != info["sha256"]:
                    print(f"  ⚠️ sha256 不匹配: {rel}")
                    ok = False
        print(f"{'✅' if ok else '⚠️'} 校验: {meta.get('version')} ({len(meta.get('files', {}))} 文件)")
    print(f"📂 部署目录: {latest}")
    return latest


def docker_build(deploy_dir):
    print("🐳 构建 docker 镜像 z700-infer:arm64 ...")
    r = subprocess.run(["docker", "build", "-t", "z700-infer:arm64", deploy_dir],
                       capture_output=True, text=True)
    if r.returncode == 0:
        print("✅ 镜像构建成功: z700-infer:arm64")
    else:
        print(f"❌ 构建失败:\n{r.stderr[-500:]}")
    return r.returncode == 0


def docker_run():
    print("🚀 启动推理容器 (挂载部署目录)...")
    r = subprocess.run(["docker", "run", "-d", "--name", "z700-infer",
                        "-v", f"{DEPLOY_DIR}:/app",
                        "-p", "8890:8890",
                        "z700-infer:arm64",
                        "python", "-c",
                        "import torch,numpy,yaml;print('Z700 推理容器就绪');"
                        "import time;time.sleep(3600)"],
                       capture_output=True, text=True)
    if r.returncode == 0:
        print("✅ 容器已启动: z700-infer (端口 8890)")
    else:
        print(f"❌ 启动失败:\n{r.stderr[-400:]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true", help="构建 docker 镜像")
    ap.add_argument("--run", action="store_true", help="构建 + 启动容器")
    args = ap.parse_args()
    d = pull()
    if args.build or args.run:
        if docker_build(d):
            if args.run:
                docker_run()
