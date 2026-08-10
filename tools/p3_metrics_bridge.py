#!/usr/bin/env python3
"""P3 指标上报 bridge — left_right metrics → HTTP API (大屏监督用)
2026-08-10 静静 · 大屏监督方案 P3

用法:
  python tools/p3_metrics_bridge.py              # 跑 8 seed 评估, 每 N 帧上报 metrics
  python tools/p3_metrics_bridge.py --api URL    # 指定上报端点 (默认 datadrive.world/api/robot-action)
  python tools/p3_metrics_bridge.py --local      # 本地回环测试 (不起真 API, 打印 JSON)
"""
import argparse, json, os, sys, time, urllib.request
import numpy as np, torch

os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

from lerobot.policies.left_right import LeftRightPolicy
from importlib import util
_spec = util.spec_from_file_location("tfp", os.path.join(ROOT, "tools", "train_full_pipeline.py"))
_tfp = util.module_from_spec(_spec); _spec.loader.exec_module(_tfp)

DEFAULT_API = "https://datadrive.world/api/robot-action"
ROBOTS = ["R1", "R3", "R4", "R5", "R6", "R7"]  # 模拟机器人分配 (场景1-6)


def _jfloat(v):
    """float32/tensor → python float (JSON 可序列化)
    json.dumps(default=...) 会对每个无法序列化的值调用, 返回可序列化替换"""
    if isinstance(v, (np.floating, np.integer)):
        return float(v)
    if isinstance(v, np.ndarray):
        return v.tolist()
    if isinstance(v, torch.Tensor):
        return v.detach().cpu().item() if v.ndim == 0 else v.detach().cpu().tolist()
    return v


def post_metrics(api, payload, local):
    """上报 metrics (大屏 GET /api/robot-action 轮询或 POST /api/action-log)"""
    if local:
        print("  📤", json.dumps(payload, ensure_ascii=False, default=_jfloat)[:160], flush=True)
        return True
    try:
        req = urllib.request.Request(api, data=json.dumps(payload, default=_jfloat).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status == 200
    except Exception as e:
        if local:
            return True
        print(f"  ⚠️ 上报失败: {e}", flush=True)
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=DEFAULT_API)
    ap.add_argument("--local", action="store_true", help="本地回环测试 (打印 JSON)")
    ap.add_argument("--every", type=int, default=10, help="每 N 帧上报一次")
    ap.add_argument("--seeds", type=int, default=4, help="评估 seed 数 (默认4, 快)")
    args = ap.parse_args()

    p = LeftRightPolicy()
    p.load_trained_weights(os.path.join(ROOT, "outputs", "rl_peg", "full_pipeline.pt"))
    p.eval()

    lifts = ins = 0
    n_report = 0
    for seed in range(args.seeds):
        env = _tfp.make_env(seed)
        o = _tfp.get_obs(env)
        peg_z0 = env.data.site_xpos[env.model.site("pegGrasp").id][2]
        hole = env.data.site_xpos[env.model.site("hole").id]
        p.reset(); p.set_peg_z0(peg_z0); p.set_env(env)
        robot = ROBOTS[seed % len(ROBOTS)]
        for step in range(500):
            batch = {"observation.state": torch.from_numpy(o).float().unsqueeze(0).unsqueeze(0)}
            act = p.select_action(batch).squeeze(0).cpu().numpy()
            env.step(np.clip(act, -1, 1))
            o = _tfp.get_obs(env)
            # 每 N 帧上报当前阶段指标
            if step % args.every == 0 and p.metrics:
                payload = {
                    "robot": robot, "zone": "oe", "ts": time.time(),
                    "stage": p.metrics.get("stage"), "stageIdx": p.metrics.get("stageIdx"),
                    "metrics": p.metrics.get("metrics", []), "pass": p.metrics.get("pass", True),
                }
                ok = post_metrics(args.api, payload, args.local)
                n_report += 1 if ok else 0
            if p.state == 7:
                ins += 1
                # 动作完成留痕
                for log in p.action_log:
                    payload = {"robot": robot, "zone": "oe", "ts": log["ts"],
                               "stage": log["stage"], "stageIdx": log["stageIdx"],
                               "metrics": log["metrics"], "pass": log["pass"], "done": True}
                    post_metrics(args.api, payload, args.local)
                break
        peg = env.data.site_xpos[env.model.site("pegGrasp").id]
        if peg[2] - peg_z0 > 0.05:
            lifts += 1
        env.close()
        print(f"  seed{seed} ({robot}): 抓起={'✅' if peg[2]-peg_z0 > 0.05 else '❌'} 插入={'✅' if ins > 0 else '❌'}", flush=True)
    print(f"== P3 上报 bridge: 抓起={lifts}/{args.seeds} 插入={ins}/{args.seeds} · 上报 {n_report} 帧", flush=True)


if __name__ == "__main__":
    main()
