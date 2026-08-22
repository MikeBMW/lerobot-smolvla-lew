#!/usr/bin/env python3
"""Z-MAX 联调自动监控 · 轮询 ECS 队列 → 新数据即拉取训练
检测到 stage_act 打标数据(非IDLE) → 立即 pull → 训练 → 推送模型
"""
import json, time, subprocess, sys, requests
from pathlib import Path

RELAY = "https://datadrive.world/api/relay"
HOME = Path.home() / "lerobot-smolvla-lew"
SEEN = set()  # 已处理的包名


def check():
    """检查队列最新包"""
    try:
        r = requests.get(f"{RELAY}/status", timeout=10)
        d = r.json()
        latest = d.get("latest")
        meta = d.get("latest_meta") or {}
        return latest, meta, d.get("packages", 0)
    except Exception:
        return None, {}, 0


def pull_latest():
    """拉取最新数据包"""
    r = requests.get(f"{RELAY}/latest", timeout=60)
    if r.status_code != 200:
        return None
    return r.json()


def has_action(meta):
    """判断是否有真实动作标签 (非纯 IDLE)"""
    labels = meta.get("labels") or {}
    if not labels:
        return False
    return any(k != "IDLE" for k in labels)


def main():
    print("🚀 联调监控启动 (每30秒检查队列)")
    idle_wait = 0
    while True:
        latest, meta, n = check()
        now = time.strftime("%H:%M:%S")
        if latest and latest not in SEEN and n > 0:
            SEEN.add(latest)
            src = meta.get("source", "?")
            frames = meta.get("frames", "?")
            labels = meta.get("labels", {})
            # 过滤快照包 (只处理 orin 真实数据)
            if src == "orin_snapshot":
                if idle_wait % 6 == 0:
                    print(f"[{now}] 🖼 快照包跳过 (src={src})")
                idle_wait += 1
                time.sleep(30)
                continue
            print(f"[{now}] 📥 新包: {latest} | src={src} frames={frames} labels={labels}")
            if has_action(meta):
                print(f"  ⚡ 检测到动作标签! 拉取训练...")
                pkg = pull_latest()
                if pkg:
                    # 保存并触发训练
                    out = HOME / "data" / "orin_live"
                    out.mkdir(parents=True, exist_ok=True)
                    fp = out / f"live_{time.strftime('%Y%m%d_%H%M%S')}.json"
                    fp.write_text(json.dumps(pkg, ensure_ascii=False))
                    print(f"  💾 已保存: {fp}")
                    # 触发训练 (后台)
                    subprocess.Popen([
                        "bash", "-c",
                        f"cd {HOME} && PYTHONPATH=src .venv/bin/python -m lerobot.scripts.lerobot_train --config_path configs/policies/act/config_act_mw_v111.yaml >> outputs/train/live_train.log 2>&1"
                    ])
                    print(f"  🏋️ 训练已触发 (log: outputs/train/live_train.log)")
            else:
                print(f"  ⏸ IDLE数据 (跳过训练, 等真实动作)")
        elif not latest:
            if idle_wait % 6 == 0:
                print(f"[{now}] ⏳ 队列空, 等待小芳上传...")
            idle_wait += 1
        time.sleep(30)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⏹ 监控停止")
