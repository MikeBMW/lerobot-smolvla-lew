#!/usr/bin/env python3
"""Z-MAX 数据闭环 · 静静4060端
链路: Orin采集 → Mac(8769) → ECS中转(datadrive.world/api/relay) → 本机训练ACT

用法:
  python3 tools/relay_train.py pull     # 从ECS拉取最新数据包并转LeRobot格式
  python3 tools/relay_train.py train    # 启动 ACT 训练
  python3 tools/relay_train.py loop     # 循环: 拉取→转格式→训练
"""
import json, sys, time, base64, subprocess
from pathlib import Path
import requests
import numpy as np

RELAY = "https://datadrive.world/api/relay"
HOME = Path.home()
DATA_DIR = HOME / "lerobot-smolvla-lew" / "data" / "closed_loop"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def pull():
    """拉取最新数据包 (拉取即删, 中转不留存)"""
    r = requests.get(f"{RELAY}/latest", timeout=30)
    if r.status_code != 200:
        print(f"⚠️  无新数据: {r.json().get('error', r.status_code)}")
        return None
    pkg = r.json()
    ts = time.strftime("%Y%m%d_%H%M%S")
    raw = DATA_DIR / f"pkg_{ts}.json"
    raw.write_text(json.dumps(pkg, ensure_ascii=False, indent=2))
    meta = pkg.get("meta", {})
    frames = pkg.get("frames", [])
    print(f"✅ 拉取: {raw.name} | {meta.get('frames')}帧 | {meta}")
    return raw


def to_lerobot(raw: Path):
    """JSON → LeRobot npz (observations/states/actions)"""
    pkg = json.loads(raw.read_text())
    frames = pkg.get("frames", [])
    if not frames:
        print("⚠️  空数据包")
        return None
    n = len(frames)

    def f(k, dflt):
        v = frames[0].get(k)
        return len(v) if isinstance(v, (list, tuple)) else dflt

    n_joint = f("observation.state", 7) or f("joint", 7) or 7
    n_action = f("action", 6) or f("joint", 7) or 6

    states = np.zeros((n, n_joint), dtype=np.float32)
    actions = np.zeros((n, n_action), dtype=np.float32)
    obs_img = np.zeros((n, 3, 64, 64), dtype=np.float32)

    for i, fr in enumerate(frames):
        states[i] = (fr.get("observation.state") or fr.get("joint") or [0]*n_joint)[:n_joint]
        act = fr.get("action") or [0]*n_action
        actions[i] = act[:n_action]
        cam = fr.get("camera_b64") or fr.get("image_b64")
        if cam:
            try:
                import io, cv2
                arr = cv2.imdecode(np.frombuffer(base64.b64decode(cam), np.uint8), cv2.IMREAD_COLOR)
                if arr is not None:
                    arr = cv2.resize(arr, (64, 64))[..., ::-1] / 255.0
                    obs_img[i] = arr.transpose(2, 0, 1).astype(np.float32)
            except Exception:
                pass
        elif fr.get("obs_img"):
            obs_img[i] = np.asarray(fr["obs_img"], dtype=np.float32)

    npz = raw.with_suffix(".npz")
    np.savez_compressed(npz, observations=obs_img, states=states, actions=actions,
                        task_name="zmax_closed_loop", fps=30)
    print(f"📦 LeRobot格式: {npz.name} | {n}帧 | states{n_joint} actions{n_action}")
    return npz


def train(npz: Path):
    """启动 ACT 训练 (SmolVLA-LEW 框架)"""
    cmd = [
        sys.executable, "-m", "lerobot.scripts.train",
        "--config-path", str(HOME / "lerobot-smolvla-lew" / "config_smolvla_mini.yaml"),
        "--dataset.root", str(npz.parent),
        "--dataset.name", npz.stem,
        "--policy.type", "act",
        "--train.batch_size", "8",
        "--train.num_epochs", "10",
    ]
    print(f"🚀 训练: {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=str(HOME / "lerobot-smolvla-lew"))


def loop():
    """拉取→转格式→训练 (单次)"""
    raw = pull()
    if raw is None:
        return
    npz = to_lerobot(raw)
    if npz is None:
        return
    train(npz)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "loop"
    {"pull": pull, "train": train, "loop": loop}[mode]() if mode == "train" else (
        loop() if mode == "loop" else print(pull()))
