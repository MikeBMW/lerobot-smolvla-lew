#!/usr/bin/env python3
"""
Orin 采集数据 action 修复 (2026-08-02)
根因: Orin 采集端把当前关节状态 (observation.state) 当成了 action 记录 → action == state,
     训练会学到恒等映射 (输出=输入), 无效。

修复策略: 检测 action≈state 的数据包 → action 改为关节速度差分 (delta state),
     与 Stage1 metaworld joint 数据 (关节速度) 定义一致。
     同时输出质量报告 (帧数/维度/动作范围/恒等检测)。

用法:
  .venv/bin/python tools/fix_orin_action.py pkg.json [--out fixed.json]
  .venv/bin/python tools/fix_orin_action.py --check pkg.json   # 只检测不修复
"""
import argparse
import json
import sys

import numpy as np


def detect_identity(actions, states, tol=1e-3):
    """检测 action 是否与 state 恒等 (采集端 bug)"""
    if actions is None or states is None:
        return False
    if actions.shape != states.shape:
        return False
    return bool(np.allclose(actions, states, atol=tol))


def fix_frames(frames, tol=1e-3, inplace=True):
    """修复 frames 列表: action==state → 关节速度差分
    返回 (修复帧数, 是否发生修复)"""
    states = np.array([f.get("observation.state") or f.get("joint") for f in frames],
                      dtype=np.float32)
    actions = np.array([f.get("action") for f in frames], dtype=np.float32)
    if actions.shape != states.shape:
        return 0, False
    if not detect_identity(actions, states, tol):
        return 0, False
    # 关节速度差分: delta = state[t+1] - state[t]; 末帧用前向差
    delta = np.zeros_like(states)
    delta[:-1] = np.diff(states, axis=0)
    if len(states) > 1:
        delta[-1] = states[-1] - states[-2]
    for i, f in enumerate(frames):
        if inplace:
            f["action"] = delta[i].tolist()
            f["action_fixed"] = True
            f["action_orig"] = actions[i].tolist()
        else:
            f = dict(f)
            f["action"] = delta[i].tolist()
            f["action_fixed"] = True
            f["action_orig"] = actions[i].tolist()
            frames[i] = f
    return len(frames), True


def quality_report(frames):
    """数据质量报告"""
    states = np.array([f.get("observation.state") or f.get("joint") for f in frames],
                      dtype=np.float32)
    actions = np.array([f.get("action") for f in frames], dtype=np.float32)
    has_img = any(f.get("camera_b64") for f in frames)
    ident = detect_identity(actions, states)
    rep = {
        "frames": len(frames),
        "state_dim": states.shape[1] if states.ndim > 1 else 0,
        "action_dim": actions.shape[1] if actions.ndim > 1 else 0,
        "action_equals_state": ident,
        "state_range": [float(states.min()), float(states.max())],
        "action_range": [float(actions.min()), float(actions.max())],
        "has_image": has_img,
        "labels": sorted({f.get("label", "?") for f in frames}),
    }
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pkg", help="数据包 json 路径")
    ap.add_argument("--out", default=None, help="修复后输出路径 (默认覆盖写回)")
    ap.add_argument("--check", action="store_true", help="只检测不修复")
    args = ap.parse_args()

    pkg = json.load(open(args.pkg, encoding="utf-8"))
    frames = pkg.get("frames", [])
    if not frames:
        print(f"❌ {args.pkg}: 无 frames")
        sys.exit(1)

    rep = quality_report(frames)
    print(f"📊 质量报告: {rep['frames']}帧 · state{rep['state_dim']}D · action{rep['action_dim']}D"
          f" · 图像{'✓' if rep['has_image'] else '✗'} · 标签={rep['labels']}")
    print(f"   action==state: {rep['action_equals_state']} (采集端恒等bug)"
          if rep["action_equals_state"] else f"   action 正常, 范围 {rep['action_range']}")

    if args.check:
        sys.exit(0)

    n, fixed = fix_frames(frames)
    if not fixed:
        print("✅ 无需修复 (action 非恒等)")
        sys.exit(0)
    print(f"🛠 已修复: {n} 帧 action → 关节速度差分 (delta state)")
    out = args.out or args.pkg
    json.dump(pkg, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"💾 已写回: {out}")


if __name__ == "__main__":
    main()
