#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""register_j6_skills.py — 第 6 轴 (J6) 独立自转技能 (2026-09-30 老倪手动控制台)

老倪: 「8793 手动控制台，增加让 6 轴独立旋转的按钮，分成逆时针旋转和顺时针旋转」。

「6 轴」= **关节 J6** (末端自转轴), 「独立」= 其他五轴不参与。
现有 A/B/C 三组按钮走 `pose_rot`(绕**工具**轴旋转, TCP 不动), **转不到 J6** ——
实测 J6 轴在工具系里是 (-0.6250, +0.0289, +0.7801), 与工具 X/Y/Z 各差 51.3°/88.3°/38.7°。

本脚本注册 2 个技能 (ros=`j6_rot`, 执行层 `tools/l2_daemon.py run_j6_rot`):
  L2.j6_ccw  「第6轴逆时针自转」 = +J6
  L2.j6_cw   「第6轴顺时针自转」 = −J6

口径 (与方向点动/A-B-C 完全一致, 现场只填正数):
  · 方向由**技能名内定**, `deg` 只填正数 ⇒ 现场不用管负号;
  · 走 /move_pose (等效笛卡尔: 绕 J6 轴轴线 = 法兰原点 + link6 的 z) —— 该通道实测**不掉电**;
    关节通道 /target_relative_joint 动作后会伺服下电, 现场要反复上电 ⇒ 不用。
  · 末端沿 ~24.2mm 半径走小圆弧 (5°≈2.1mm, 10°≈4.2mm) —— **不是原地不动** (那是 A/B/C 的语义)。
  · 执行层守卫: 单次 ≤ max_deg (默认 10°, `build_j6_rot` 收口)。
  · 数学已离线核对(零运动): `python3 tools/test_j6_axis.py` —— 与 FK(q, J6±θ) 位置差 6e-14 mm /
    姿态差 1.7e-06°。

幂等: 同 id 覆盖, 不重复插入; 跑前自动备份注册表。
用法: gui-venv311/bin/python tools/register_j6_skills.py [--max-deg 10]
"""
import argparse
import json
import os
import shutil
import time

REPO = os.environ.get("ZMAX_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(REPO, "data/skills/l2_atomic/registry.json")


def build(sign, max_deg):
    tag = "ccw" if sign > 0 else "cw"
    human = "逆时针" if sign > 0 else "顺时针"
    sid = "L2.j6_%s" % tag
    return {
        "id": sid,
        "name": "第6轴%s自转" % human,
        "icon": "🔩",
        "ros": "j6_rot",
        "param": {"deg": {"default": 5, "unit": "deg", "min": 1, "max": max_deg,
                          "label": "旋转角度(只填正数)"}},
        "guard": {"max_deg": max_deg},
        # 🔝 2026-09-30 老倪: 「转速太慢了，加速。别限制，我在现场，安全」
        #   技能级限速上限提到 1000(相对量) —— 真正物理上限由控制器关节限速兜底。
        #   实测基线: speed=60 → 10° 约 10s(~1°/s); 60→300 约 5 倍。
        "speed_max": 1000,
        "note": ("第6轴(J6)%s自转(**关节自转**, 其余五轴不动) = %sJ6; 度数只填正数(方向内定) · "
                 "单次≤%d° · 末端沿 ~24.2mm 半径走小圆弧(5°≈2.1mm) · 走 /move_pose 不掉电 · "
                 "与 A/B/C(绕工具轴, 位置不动)不是一回事" % (human, "+" if sign > 0 else "−", max_deg)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-deg", type=float, default=10.0, help="单次自转上限(度)")
    a = ap.parse_args()
    with open(REG, encoding="utf-8") as f:
        reg = json.load(f)
    shutil.copy2(REG, "/tmp/registry.json.prej6_%d" % time.time())
    ids = [s["id"] for s in reg["skills"]]
    # 插在 A/B/C 旋转技能之后(同一族), 没有则插在 L2.lower 之后
    anchor = next((i for i, s in enumerate(reg["skills"]) if str(s["id"]).startswith("L2.rot_")), None)
    at = (anchor + 6) if anchor is not None else (ids.index("L2.lower") + 1 if "L2.lower" in ids else len(ids))
    added, updated = [], []
    for sign in (1, -1):
        sk = build(sign, a.max_deg)
        if sk["id"] in ids:
            reg["skills"][ids.index(sk["id"])] = sk
            updated.append(sk["id"])
        else:
            reg["skills"].insert(at, sk)
            ids.insert(at, sk["id"])
            at += 1
            added.append(sk["id"])
    with open(REG, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)
    print("注册表: %s" % REG)
    print("新增 %d: %s" % (len(added), ", ".join(added) or "无"))
    print("覆盖 %d: %s" % (len(updated), ", ".join(updated) or "无"))
    print("总技能数: %d" % len(reg["skills"]))
    print("备份: /tmp/registry.json.prej6_*")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
