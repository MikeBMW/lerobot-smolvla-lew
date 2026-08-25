#!/usr/bin/env python3
"""🔍 状态空间算法全局审计 (逐状态: 证据/阈值/余量/限速/风险)

用法: gui-venv311/bin/python tools/audit_state_machine.py
读同源 episode trace, 对八阶段逐个检查:
  1. 持续时长、触发下一阶段的证据值 vs 阈值、余量 (margin)
  2. 证据在阈值附近是否震荡 (误触发风险)
  3. 阶段限速 cap 是否生效/是否过度限制
  4. 夹持稳定性、插销高度回退 (滑落风险)
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# ⚠️ 直接按文件加载 cognition.py — 走 lerobot 包会触发 __init__ 链导入 huggingface_hub
#   (gui-venv311 里没装), 审计脚本不需要整个 lerobot
import importlib.util as _ilu  # noqa: E402
_cg_path = os.path.join(ROOT, "src", "lerobot", "policies", "left_right",
                        "state_space", "cognition.py")
_spec = _ilu.spec_from_file_location("_cognition_audit", _cg_path)
_cg = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_cg)
ActionModulator = _cg.ActionModulator

NPZ = os.path.join(ROOT, "reports", "ss_episode_latest.npz")
d = np.load(NPZ, allow_pickle=True)
meta = dict(d["meta"][0])
st = [str(s).replace("阶段 ", "").split(" · ")[0] for s in d["stage"]]
x = d["x"].astype(float)
peg = d["peg"].astype(float)
head = d["peg_head"].astype(float)
grip = d["gripper"].astype(float)
fe = d["force"].astype(float)
fg = d["force_grasp"].astype(float)
cp = d["contact_p"].astype(float)
uff = d["u_ff_vec"].astype(float)[:, :3]
ufu = d["u_fuse_vec"].astype(float)[:, :3]
usat = d["u_limit_vec"].astype(float)[:, :3]
dt = float(meta["ctrl_dt"])
hole_mouth = np.asarray(meta["hole_mouth"], dtype=float)
goal = np.asarray(meta["goal"], dtype=float)
peg0 = np.asarray(meta["peg0"], dtype=float)

# ⚠️ 必须与生成器同参数 (metaworld 夹爪夹住 0.03m 销后开度饱和 0.70 → grasp_th=0.6)
am = ActionModulator(grasp_th=0.6)
STAGES = am.STAGES
CAP = am.STAGE_V_CAP
n = len(st)

# 阶段区间
segs = []
cur, start = st[0], 0
for i in range(1, n):
    if st[i] != cur:
        segs.append((cur, start, i - 1))
        cur, start = st[i], i
segs.append((cur, start, n - 1))

print(f"═══ 状态空间算法审计 · {meta.get('episode_tag')} ({n} 步 / {n * dt:.1f}s) ═══")
print(f"状态机 = 动作调制器 ActionModulator 八阶段: {' → '.join(STAGES)}")
print(f"终态 {meta['stage_final']}  success={meta['success']}\n")

# 各阶段证据定义 (与 cognition.advance 一一对应)
d_xy = np.linalg.norm(x[:, :2] - peg[:, :2], axis=1)
hand_above = x[:, 2] - peg[:, 2]
lifted = peg[:, 2] - peg0[2]
dist_h = np.linalg.norm(head[:, :2] - hole_mouth[:2], axis=1)
depth = np.linalg.norm(head - goal, axis=1)

EV = {
    "接近": ("d_xy(手-销水平)", d_xy, am.align_xy_coarse, "<"),
    "对位": ("d_xy(精对位)", d_xy, am.align_xy_fine, "<"),
    "下降": ("接触概率|到位", cp, am.contact_th, ">"),
    "抓取": ("gripper(夹持度)", grip, am.grasp_th, ">"),
    "抬起": ("lifted(提升高度)", lifted, am.lift_h, ">"),
    "转移": ("dist_h(销头-孔口)", dist_h, am.align_th, "<"),
    "插入": ("depth(销头-终点)", depth, am.insert_depth, "<"),
}

print("① 逐状态: 时长 / 触发证据 / 阈值 / 余量 / 限速生效情况")
print(f"{'阶段':<4} {'帧数':>5} {'时长s':>6} {'证据':<16} {'触发值':>9} {'阈值':>8} "
      f"{'余量%':>7} {'限速':>6} {'实速':>7} {'触顶%':>6}")
issues = []
for name, a, b in segs:
    dur = b - a + 1
    ev = EV.get(name)
    cap = CAP.get(name, 0)
    spd = np.linalg.norm(ufu[a:b + 1], axis=1)
    hit = 100.0 * float((spd > cap * 0.98).mean()) if cap else 0.0
    if ev:
        lbl, arr, th, op = ev
        val = float(arr[min(b + 1, n - 1)])
        margin = (100.0 * (th - val) / max(abs(th), 1e-9) if op == "<"
                  else 100.0 * (val - th) / max(abs(th), 1e-9))
        print(f"{name:<4} {dur:>5} {dur * dt:>6.2f} {lbl:<16} {val:>9.4f} {th:>8.4f} "
              f"{margin:>6.0f}% {cap:>6.2f} {spd.mean():>7.4f} {hit:>5.0f}%")
        if dur <= 3:
            issues.append(f"⚠️ 「{name}」只持续 {dur} 帧 ({dur * dt:.2f}s) — 阶段几乎无意义, 阈值可能过松")
        # 🐛 触发瞬间的"余量"必然≈0 (状态机就是在证据刚跨过阈值那帧切换) → 不是风险指标。
        #   真正的风险 = 证据在阈值带内**滞留**多久 (滞留久 = 噪声可能来回把它推过阈值)
        band = 0.10 * abs(th)
        dwell = int(np.sum(np.abs(arr[a:b + 2] - th) < band))
        if dwell > 25:
            issues.append(f"⚠️ 「{name}」证据在阈值±10% 带内滞留 {dwell} 帧 "
                          f"({dwell * dt:.2f}s) — 建议加滞回/连续确认")
        if hit > 85:
            issues.append(f"⚠️ 「{name}」{hit:.0f}% 时间贴着限速上限 {cap} m/s — cap 是当前瓶颈, 可评估放宽")
    else:
        print(f"{name:<4} {dur:>5} {dur * dt:>6.2f} {'(终态)':<16} {'-':>9} {'-':>8} "
              f"{'-':>7} {cap:>6.2f} {spd.mean():>7.4f} {hit:>5.0f}%")

# ② 证据震荡检测: 触发前 30 帧内是否多次越过阈值
print("\n② 误触发风险 (触发前 30 帧内证据越过阈值次数)")
for name, a, b in segs:
    ev = EV.get(name)
    if not ev:
        continue
    lbl, arr, th, op = ev
    w = arr[max(0, b - 29):b + 2]
    cross = int(np.sum(np.diff((w < th).astype(int) if op == "<" else (w > th).astype(int)) != 0))
    flag = "✅" if cross <= 1 else f"⚠️ 越界 {cross} 次"
    print(f"  {name:<4} {lbl:<16} {flag}")
    if cross > 1:
        issues.append(f"⚠️ 「{name}」证据在触发前越界 {cross} 次 — 需要滞回 (hysteresis) 或连续 N 帧确认")

# ③ 夹持稳定性 / 滑落检测
print("\n③ 夹持与插销状态")
gi = st.index("抓取") if "抓取" in st else 0
after = slice(gi, n)
# 🐛 原来从"抓取阶段起点"统计, 会把夹爪还没合上的那十几帧算成"夹持丢失", 把销还在台面
#   的高度算成"回退" → 假警报。正确起点 = **夹持真正建立之后** (进入抬起阶段)
_lift_i = st.index("抬起") if "抬起" in st else gi
after = slice(_lift_i, n)
_lost = int((fg[after] < 0.05).sum())
_pz = peg[_lift_i:, 2]
_drawdown = 1000 * float(np.max(np.maximum.accumulate(_pz) - _pz))   # 最大回撤 (峰值→之后最低)
print(f"  夹持建立后(抬起起) 夹持力 均值 {fg[after].mean():.3f}  最小 {fg[after].min():.3f}  "
      f"丢失帧数 {_lost}")
print(f"  插销高度 峰值 {peg[:, 2].max():.4f}m   最大回撤 {_drawdown:.1f}mm (>15mm 视为滑落)")
print(f"  最终插入残距 {1000 * depth[-1]:.2f}mm (阈值 {1000 * am.insert_depth:.1f}mm)")
# 🐛 回撤>15mm 单独不构成滑落: 插入阶段本身就要把插销压进孔里 (实测回撤 21mm 而夹持力
#   从未丢失 0 帧) → 必须**夹持丢失 且 回撤**同时成立才算滑落
if _lost > 5 and _drawdown > 15:
    issues.append(f"⚠️ 夹持建立后丢失 {_lost} 帧 / 插销回撤 {_drawdown:.1f}mm — 需要 "
                  f"「夹持丢失 → 回退重抓」状态机分支")

# ④ 安全层是否介入
print("\n④ 安全执行边界 (饱和限幅) 介入情况")
diff = np.linalg.norm(ufu - usat, axis=1)
print(f"  |u_fuse − u_sat| 均值 {diff.mean():.6f}  最大 {diff.max():.6f}  "
      f"介入帧数 {int((diff > 1e-6).sum())}/{n}")
print(f"  指令最大速度 {np.linalg.norm(ufu, axis=1).max():.4f} m/s (安全上限 0.6)")

# ⑤ 性能
print("\n⑤ 性能")
print(f"  总时长 {n * dt:.2f}s ({n} 步)   最慢阶段: "
      f"{max(segs, key=lambda s: s[2] - s[1])[0]} "
      f"{(max(segs, key=lambda s: s[2] - s[1])[2] - max(segs, key=lambda s: s[2] - s[1])[1] + 1) * dt:.2f}s")
for name, a, b in segs:
    print(f"    {name:<4} {(b - a + 1) * dt:>6.2f}s  ({100.0 * (b - a + 1) / n:>4.1f}%)")

print("\n═══ 审计结论 ═══")
if issues:
    for k, s in enumerate(dict.fromkeys(issues), 1):
        print(f"  {k}. {s}")
else:
    print("  ✅ 未发现阈值/震荡/滑落/限速类问题")
