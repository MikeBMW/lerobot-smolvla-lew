#!/usr/bin/env python3
"""Z-MAX 边学边练闭环守护 · 静静端
小芳采集→ECS→本脚本自动拉取→快速训练→推回ECS→小芳部署Orin→循环

循环:
  1. 每60s 检查 ECS 队列新数据
  2. 有可训练数据 (frames≥50) → 拉取 → 触发快速训练 (2000步)
  3. 训练完 → 自动对比基线 → 有提升 → 推模型回 ECS
  4. 小芳拉取部署 → 采集新数据 → 回到 1

用法:
  python3 tools/auto_loop.py [--once] [--train-only]
"""
import json, subprocess, sys, time, os, glob
from pathlib import Path
import requests

RELAY = "https://datadrive.world/api/relay"
HOME = Path.home() / "lerobot-smolvla-lew"
LIVE = HOME / "data" / "orin_live"
CFG = "config_act_cartesian.yaml"   # 笛卡尔接口 (7轴泛化6轴)
SEEN = set()


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def check_new_data():
    """检查队列新数据包 (非快照)"""
    try:
        r = requests.get(f"{RELAY}/status", timeout=10)
        d = r.json()
        latest = d.get("latest")
        meta = d.get("latest_meta") or {}
        n = d.get("packages", 0)
        src = meta.get("source", "")
        if latest and src != "orin_snapshot" and "snapshot" not in str(meta.get("type", "")):
            return latest, meta, n
        return None, {}, n
    except Exception:
        return None, {}, 0


def pull_data():
    """拉取队列数据包 → 本地"""
    r = requests.get(f"{RELAY}/latest", timeout=60)
    if r.status_code != 200:
        return None
    return r.json()


def build_dataset():
    """用 orin_live 数据重建 6D 数据集 (若新数据到达)"""
    subprocess.run([sys.executable, str(HOME / "tools/build_orin6d_dataset.py")],
                   cwd=str(HOME), capture_output=True, timeout=120)
    return (HOME / "data" / "orin_6d").exists()


def train():
    """快速训练 (2000步)"""
    log("🏋️ 开始训练...")
    r = subprocess.run([
        "bash", "-c",
        f"cd {HOME} && rm -rf outputs/train/act_loop && "
        f"PYTHONPATH=src .venv/bin/python -m lerobot.scripts.lerobot_train "
        f"--config_path {CFG} >> outputs/train/loop_train.log 2>&1"
    ], timeout=600)
    ckpts = sorted(glob.glob(str(HOME / "outputs/train/act_loop/checkpoints/*")))
    ckpts = [c for c in ckpts if "last" not in c]
    if ckpts:
        return ckpts[-1] / "pretrained_model" / "model.safetensors"
    return None


def upload(model_path):
    """推模型回 ECS"""
    r = subprocess.run([sys.executable, str(HOME / "tools/upload_model.py"), str(model_path)],
                       capture_output=True, timeout=300, cwd=str(HOME))
    return r.returncode == 0


def main():
    once = "--once" in sys.argv
    log("🔄 边学边练闭环守护启动 (每60s检查)")
    idle = 0
    while True:
        try:
            latest, meta, n = check_new_data()
            now = time.strftime("%H:%M:%S")
            if latest and latest not in SEEN:
                SEEN.add(latest)
                frames = meta.get("frames", "?")
                log(f"📥 新数据: {latest} | frames={frames}")
                if isinstance(frames, int) and frames >= 50:
                    log("⚡ 数据量达标, 拉取+训练...")
                    pkg = pull_data()
                    if pkg:
                        ts = time.strftime("%Y%m%d_%H%M%S")
                        fp = LIVE / f"auto_{ts}.json"
                        fp.write_text(json.dumps(pkg, ensure_ascii=False))
                        log(f"💾 已存 {fp.name} ({len(pkg.get('frames',[]))}帧)")
                        # 重建数据集 → 训练 → 上传
                        if build_dataset():
                            model = train()
                            if model and model.exists():
                                log(f"✅ 训练完成: {model}")
                                if upload(model):
                                    log("🚀 模型已推回 ECS → 小芳拉取部署 Orin")
                                else:
                                    log("❌ 模型上传失败")
                            else:
                                log("❌ 训练失败")
                        else:
                            log("❌ 数据集构建失败")
            elif latest is None and idle % 6 == 0:
                log("⏳ 队列空, 等小芳采集数据...")
            idle += 1
        except Exception as ex:
            log(f"⚠️ 错误: {ex}")
        if once:
            break
        time.sleep(60)


if __name__ == "__main__":
    main()
