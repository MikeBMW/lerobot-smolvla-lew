#!/usr/bin/env python3
"""🧪 状态机新增逻辑实测 (连续确认防抖 + 夹持丢失回退重抓)

用法: gui-venv311/bin/python tools/test_fsm_logic.py
不依赖 trace — 直接驱动 ActionModulator 造场景, 验证:
  1. 单帧证据成立**不应**切换 (confirm_n=2 连续确认)
  2. 证据抖动 (成立→不成立→成立) 不应切换
  3. 连续 2 帧成立才切换
  4. 抬起阶段夹持力连续 5 帧丢失 + 光模块落回台面 → 回退「接近」重抓
  5. 夹持力正常时不误触发回退
"""
import importlib.util as ilu
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_p = os.path.join(ROOT, "src", "lerobot", "policies", "left_right", "state_space", "cognition.py")
_s = ilu.spec_from_file_location("_cg_test", _p)
_m = ilu.module_from_spec(_s)
_s.loader.exec_module(_m)
ActionModulator = _m.ActionModulator

ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and cond
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  {detail}" if detail else ""))


print("═══ ① 连续确认防抖 (confirm_n=2) ═══")
am = ActionModulator(grasp_th=0.6)
am.advance(d_xy=0.05)                       # 第1帧证据成立
check("单帧证据成立不切换", am.stage() == "接近", f"当前 {am.stage()}")
am.advance(d_xy=0.09)                       # 证据不成立 → 计数清零
am.advance(d_xy=0.05)                       # 又成立 (第1帧)
check("抖动一次后仍不切换", am.stage() == "接近", f"当前 {am.stage()}")
am.advance(d_xy=0.05)                       # 连续第2帧 → 切换
check("连续2帧成立才切换", am.stage() == "对位", f"当前 {am.stage()}")

print("\n═══ ② 夹持丢失 → 回退重抓 ═══")
am2 = ActionModulator(grasp_th=0.6)
for _ in range(2):
    am2.advance(d_xy=0.05)
for _ in range(2):
    am2.advance(d_xy=0.01)
for _ in range(2):
    am2.advance(at_grasp_pose=True)
for _ in range(2):
    am2.advance(gripper=0.8)
check("已推进到抬起阶段", am2.stage() == "抬起", f"当前 {am2.stage()}")
# 夹持正常 → 不该回退
for _ in range(8):
    am2.advance(grasp_force=1.0, peg_z=0.14, peg_z_grasp=0.03, lifted=0.05)
check("夹持正常不误触发回退", am2.stage() == "抬起", f"当前 {am2.stage()}")
# 夹持丢失但光模块还在高处 (被别的东西托住?) → 不该回退
for _ in range(8):
    am2.advance(grasp_force=0.0, peg_z=0.14, peg_z_grasp=0.03, lifted=0.05)
check("仅夹持丢失但光模块未落回 → 不回退", am2.stage() == "抬起", f"当前 {am2.stage()}")
# 夹持丢失 + 光模块落回台面 → 回退
for _ in range(5):
    am2.advance(grasp_force=0.0, peg_z=0.032, peg_z_grasp=0.03, lifted=0.0)
check("夹持丢失且光模块落回 → 回退接近重抓", am2.stage() == "接近", f"当前 {am2.stage()}")
_last = am2.history[-1][1] if am2.history else ""
check("回退原因已记录", "夹持丢失" in _last, _last)

print("\n═══ ③ 阶段限速 / 最小趋近速度 ═══")
import numpy as np  # noqa: E402
am3 = ActionModulator(grasp_th=0.6)
u_big = np.array([1.0, 0.0, 0.0, 0.0])
u_out, _ = am3.decide(u_big, np.zeros(4), 0.0, 0.0)
check("接近阶段限速 0.35 生效", abs(np.linalg.norm(u_out[:3]) - 0.35) < 1e-6,
      f"|u|={np.linalg.norm(u_out[:3]):.4f}")
u_tiny = np.array([0.001, 0.0, 0.0, 0.0])
u_out2, _ = am3.decide(u_tiny, np.zeros(4), 0.0, 0.0)
check("接近阶段最小趋近速度 0.12 生效", abs(np.linalg.norm(u_out2[:3]) - 0.12) < 1e-6,
      f"|u|={np.linalg.norm(u_out2[:3]):.4f}")
check("限速只削幅不改方向",
      abs(u_out[0] / max(np.linalg.norm(u_out[:3]), 1e-9) - 1.0) < 1e-6)
u_veto, tag = am3.decide(u_big, np.zeros(4), 0.0, 99.0)
check("否决返回同形零向量 (不是标量)", hasattr(u_veto, "shape") and u_veto.shape == (4,),
      f"shape={getattr(u_veto, 'shape', None)} tag={tag}")

print(f"\n═══ 总判定: {'✅ 全部通过' if ok else '❌ 有失败项'} ═══")
sys.exit(0 if ok else 1)
