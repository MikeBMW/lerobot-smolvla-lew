#!/usr/bin/env python3
"""Z-MAX 边学边练闭环守护 · 静静端 (v2 — WS 事件驱动 + 轮询兜底)
小芳采集→ECS→本脚本自动拉取→快速训练→推回ECS→小芳部署Orin→循环

循环:
  1. WS 订阅 ECS 广播 (data_arrived 事件) → 数据到达立即处理 (演示零等待)
  2. 每60s HTTP 轮询兜底 (WS 掉线/错过事件时补拉)
  3. 有可训练数据 (frames≥20) → 拉取 → 触发快速训练 (2000步)
  4. 训练完 → 自动推模型回 ECS
  5. 小芳拉取部署 → 采集新数据 → 回到 1

用法:
  python3 tools/auto_loop.py [--once] [--train-only]
"""
import json, subprocess, sys, time, os, glob, threading
from pathlib import Path
import requests

RELAY = "https://datadrive.world/api/relay"
WS_URL = "wss://datadrive.world/ws"
HOME = Path.home() / "lerobot-smolvla-lew"
LIVE = HOME / "data" / "orin_live"
LOCK = HOME / "outputs" / "train" / ".loop_lock"   # 训练锁 (防并发重建数据集)
CFG = "config_act_loop.yaml"   # 闭环训练配置 (真机6D数据)
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
    ckpts = [Path(c) for c in ckpts if "last" not in c]
    if ckpts:
        return ckpts[-1] / "pretrained_model" / "model.safetensors"
    return None


def upload(model_path):
    """推模型回 ECS"""
    r = subprocess.run([sys.executable, str(HOME / "tools/upload_model.py"), str(model_path)],
                       capture_output=True, timeout=300, cwd=str(HOME))
    return r.returncode == 0


def process_new_data():
    """检查并处理队列新数据: 有 frames≥20 且未见过 → 拉取→落地→训练→上传"""
    latest, meta, n = check_new_data()
    if latest and latest not in SEEN:
        frames = meta.get("frames", "?")
        log(f"📥 新数据: {latest} | frames={frames}")
        if isinstance(frames, int) and frames >= 20:
            if LOCK.exists():
                log("🔒 训练进行中, 该包留待下一轮 (防并发破坏数据集)")
                return
            SEEN.add(latest)
            log("⚡ 数据量达标, 拉取+训练...")
            pkg = pull_data()
            if pkg:
                ts = time.strftime("%Y%m%d_%H%M%S")
                fp = LIVE / f"auto_{ts}.json"
                fp.write_text(json.dumps(pkg, ensure_ascii=False))
                log(f"💾 已存 {fp.name} ({len(pkg.get('frames',[]))}帧)")
                # 重建数据集 → 训练 → 上传
                LOCK.touch()
                try:
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
                finally:
                    LOCK.unlink(missing_ok=True)


def ws_listener():
    """WS 订阅线程: 收到 data_arrived 事件 → 立即处理 (演示零等待)"""
    while True:
        try:
            import websocket  # websocket-client
            log(f"🔌 WS 连接 {WS_URL} ...")
            ws = websocket.WebSocketApp(
                WS_URL,
                on_message=lambda w, m: ws_on_message(m),
                on_error=lambda w, e: log(f"⚠️ WS错误: {e}"),
                on_close=lambda w, c, m: log("🔌 WS 断开, 转轮询兜底"),
            )
            ws.run_forever()  # 阻塞直到断开; 断开后重连
        except Exception as ex:
            log(f"⚠️ WS 异常: {ex}")
        time.sleep(5)  # 重连间隔


def ws_on_message(raw):
    """WS 消息处理: data_arrived → 立即触发数据处理"""
    try:
        d = json.loads(raw)
    except Exception:
        return
    if isinstance(d, dict) and d.get("type") == "data_arrived":
        latest = d.get("latest")
        frames = d.get("frames")
        log(f"⚡⚡ [WS事件] 数据到达: {latest} | {frames}帧 → 立即处理")
        # 后台线程处理, 不阻塞 WS 接收
        threading.Thread(target=process_new_data, daemon=True).start()


def main():
    once = "--once" in sys.argv
    log("🔄 边学边练闭环守护 v2 启动 (WS事件驱动 + 60s轮询兜底)")
    # WS 订阅线程 (事件驱动, 零等待)
    if not once:
        threading.Thread(target=ws_listener, daemon=True).start()
    idle = 0
    while True:
        try:
            # 轮询兜底 (WS 掉线/错过事件时补拉)
            process_new_data()
            if idle % 6 == 0 and check_new_data()[0] is None:
                log("⏳ 队列空, 等小芳采集数据...")
            idle += 1
        except Exception as ex:
            import traceback
            log(f"⚠️ 错误: {ex}\n{traceback.format_exc()[-400:]}")
        if once:
            break
        time.sleep(60)


if __name__ == "__main__":
    main()
