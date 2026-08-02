#!/usr/bin/env python3
"""Z-MAX 数据同步 + 新数据即训练 · 4060端
功能:
  1. 从 ECS 增量拉取快照归档 → 本地 data/orin_archive/
  2. 拉取训练数据队列 (orin 数据包) → 本地 data/orin_live/
  3. 检测到可训练数据 (frames>0) → 触发训练
用法:
  python3 tools/data_sync.py             # 同步一次
  python3 tools/data_sync.py --loop      # 持续同步 (60s间隔)
"""
import json, subprocess, sys, time, os, glob
from pathlib import Path
import requests

ECS = "root@39.102.211.79"
RELAY = "https://datadrive.world/api/relay"
HOME = Path.home() / "lerobot-smolvla-lew"
ARCH_LOCAL = HOME / "data" / "orin_archive"
LIVE_LOCAL = HOME / "data" / "orin_live"
ARCH_LOCAL.mkdir(parents=True, exist_ok=True)
LIVE_LOCAL.mkdir(parents=True, exist_ok=True)


def sync_archive():
    """增量拉取快照归档 (tar 流式)"""
    # 本地已有数量
    local_count = len(list(ARCH_LOCAL.glob("snap_*.jpg")))
    cmd = f"cd /root/zmax-relay && tar cf - archive/ 2>/dev/null"
    r = subprocess.run(["sshpass", "-p", "Nix19789", "ssh", "-o", "StrictHostKeyChecking=no",
                        ECS, cmd], capture_output=True)
    if r.returncode != 0:
        print(f"⚠️ 同步失败: {r.stderr[:100]}")
        return 0
    # 解压到临时目录再合并
    import tarfile, io
    with tarfile.open(fileobj=io.BytesIO(r.stdout), mode="r:") as tf:
        for m in tf.getmembers():
            if m.isfile() and m.name.startswith("archive/"):
                fname = os.path.basename(m.name)
                dest = ARCH_LOCAL / fname
                if not dest.exists():
                    src = tf.extractfile(m)
                    if src:
                        dest.write_bytes(src.read())
    new_count = len(list(ARCH_LOCAL.glob("snap_*.jpg")))
    added = new_count - local_count
    print(f"🖼 快照归档: 本地 {local_count} → {new_count} (+{added})")
    return added


def pull_train_data():
    """拉取训练数据队列 (弹栈)"""
    pulled = 0
    while True:
        r = requests.get(f"{RELAY}/latest", timeout=60)
        if r.status_code != 200:
            break
        pkg = r.json()
        meta = pkg.get("meta", {})
        if meta.get("source") == "orin_snapshot" or pkg.get("snapshot_b64"):
            continue  # 快照不存训练区
        ts = time.strftime("%Y%m%d_%H%M%S")
        fp = LIVE_LOCAL / f"pkg_{ts}_{pulled}.json"
        fp.write_text(json.dumps(pkg, ensure_ascii=False))
        pulled += 1
    if pulled:
        print(f"📥 训练数据: 拉取 {pulled} 包 → {LIVE_LOCAL}")
    return pulled


def check_trainable():
    """检查是否有可训练数据 (frames>0 且非IDLE)"""
    for f in sorted(LIVE_LOCAL.glob("pkg_*.json")):
        try:
            d = json.load(open(f))
            frames = d.get("frames", [])
            labels = d.get("meta", {}).get("labels", {})
            if len(frames) >= 50 and any(k != "IDLE" for k in labels):
                return f
        except Exception:
            pass
    return None


def trigger_train(data_file):
    """触发训练"""
    print(f"🏋️ 检测到可训练数据: {data_file.name} → 触发训练")
    # 备份到训练数据集
    import shutil
    ds_dir = HOME / "data" / "closed_loop"
    ds_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(data_file, ds_dir / data_file.name)
    # 触发训练 (后台)
    subprocess.Popen([
        "bash", "-c",
        f"cd {HOME} && PYTHONPATH=src .venv/bin/python -m lerobot.scripts.lerobot_train "
        f"--config_path config_act_mw_v111.yaml >> outputs/train/live_train.log 2>&1"
    ])
    print(f"  ✅ 训练已触发 (log: outputs/train/live_train.log)")


def main():
    loop = "--loop" in sys.argv
    print("🚀 数据同步服务启动" + (" (持续模式 60s)" if loop else ""))
    while True:
        try:
            sync_archive()
            pull_train_data()
            trainable = check_trainable()
            if trainable:
                trigger_train(trainable)
            else:
                print("⏸ 无达标数据 (需 frames≥50 且非IDLE标签)")
        except Exception as ex:
            print(f"⚠️ 错误: {ex}")
        if not loop:
            break
        time.sleep(60)


if __name__ == "__main__":
    main()
