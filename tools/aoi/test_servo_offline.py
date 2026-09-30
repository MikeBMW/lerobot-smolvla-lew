"""金手指伺服引导 离线闭环测试 (用合成设备模型, 不接真机):
验证 ① 横向收敛 ② 单步/单轴限幅 ③ 检测不可靠时否决 ④ 对焦退火爬坡到峰值
合成设备: 臂位移 → 图像里区域中心线性移动 + 光轴方向 focus 呈二次曲线(峰在 z=3mm)
"""
import os
import sys
import json
import numpy as np

sys.path.insert(0, "/home/ubuntu/lerobot-smolvla-lew/tools")
import aoi_gold_servo as S

PX_PER_MM = np.array([[-11.5, 0.8], [0.6, -12.2]])   # 图像 px / 臂 mm (带一点交叉耦合, 模拟斜视)
FOCUS_PEAK_Z = 3.0                                    # 光轴最佳位置 mm
FOCUS_MAX = 900.0


class FakePlant:
    """合成设备 + L2 接口替身"""
    def __init__(self, x0=0.0, y0=0.0, z0=0.0, cx0=1198.0, cy0=1173.0, score=0.985, cover=0.72):
        self.x, self.y, self.z = x0, y0, z0
        self.cx0, self.cy0 = cx0, cy0
        self.score, self.cover = score, cover
        self.cmds = []
        self.steps = []

    def region(self, grab=True):
        d = PX_PER_MM @ np.array([self.x, self.y])
        cx, cy = self.cx0 + d[0], self.cy0 + d[1]
        f = FOCUS_MAX - 60.0 * (self.z - FOCUS_PEAK_Z) ** 2
        return {"ok": True, "focus": round(f, 1), "score": self.score,
                "region": {"cx": round(cx, 2), "cy": round(cy, 2), "w": 1455.0, "h": 165.0, "angle": 0.6},
                "quality": {"gold_cover": self.cover}}

    def send(self, skill, **kw):
        """2026-09-20 拆分后: 方向内定在技能名里, d_mm 恒为正(不再有 sign 字段)。
        口径与执行层一致: 前进=+X · 后退=-X · 向左=+Y · 向右=-Y · 抬升=+Z · 下降=-Z。"""
        self.cmds.append((skill, kw))
        d = kw.get("d_mm", 0.0)
        sg = {"L2.forward": 1, "L2.backward": -1, "L2.left": 1, "L2.right": -1,
              "L2.lift": 1, "L2.lower": -1}.get(skill)
        if sg is None:
            raise AssertionError("未知技能 %s (方向技能改名了? 执行层与测试台口径必须同源)" % skill)
        if skill in ("L2.forward", "L2.backward"):
            self.x += sg * d
        elif skill in ("L2.left", "L2.right"):
            self.y += sg * d
        else:
            self.z += sg * d
        self.steps.append((skill, sg * d))


def make_ctl(plant, target=None, **kw):
    if target is None:
        target = {"region": {"cx": plant.cx0, "cy": plant.cy0, "w": 1455.0, "h": 165.0, "angle": 0.6},
                  "focus": FOCUS_MAX}
    jac = {"mm_per_px": np.linalg.inv(PX_PER_MM).round(6).tolist(),
           "px_per_mm": PX_PER_MM.round(3).tolist(), "focus_axis": "L2.lift"}
    return S.ServoController(target, jac=jac, send=plant.send, get_reg=plant.region,
                             verbose=True, **kw)


print("=" * 92)
print("① 横向收敛 (初始偏差 = 臂 x +1.2mm / y -0.9mm → 图像里约 ±13px)")
print("=" * 92)
p = FakePlant(x0=1.2, y0=-0.9)
ctl = make_ctl(p)
reg = p.region()
ctl.target = {"region": {"cx": p.cx0, "cy": p.cy0}, "focus": FOCUS_MAX}
# 基准取"臂在 0 时"的图像位置 = cx0/cy0
ok, why = ctl.run_lateral(dry=False)
final = p.region()["region"]
ex, ey = final["cx"] - p.cx0, final["cy"] - p.cy0
print(f"  → 结果 {ok}({why}) | 终态偏差 ({ex:+.2f},{ey:+.2f})px | 臂位移 x={p.x:+.3f} y={p.y:+.3f}mm | 下发 {len(p.cmds)} 条")
a1 = ok and abs(ex) <= S.TOL_PX and abs(ey) <= S.TOL_PX
print(f"  断言: {'PASS' if a1 else 'FAIL'}  (收敛且误差 ≤ {S.TOL_PX}px)")

print()
print("=" * 92)
print("② 限幅: 初始偏差巨大 (臂 x=+40mm → 图像 ~460px), 单步必须 ≤2mm, 单轴累计 ≤15mm")
print("=" * 92)
p2 = FakePlant(x0=40.0)
ctl2 = make_ctl(p2, max_iters=60)
ctl2.target = {"region": {"cx": p2.cx0, "cy": p2.cy0}, "focus": FOCUS_MAX}
ok2, why2 = ctl2.run_lateral(dry=False)
mx = max(abs(d) for _, d in p2.steps) if p2.steps else 0
print(f"  → 结果 {ok2}({why2}) | 单步最大 {mx:.3f}mm | 累计 {ctl2.total} | 下发 {len(p2.cmds)} 条")
a2 = mx <= S.MAX_STEP_MM + 1e-9 and abs(ctl2.total["x"]) <= S.MAX_TOTAL_MM + 1e-9
print(f"  断言: {'PASS' if a2 else 'FAIL'}  (单步 ≤{S.MAX_STEP_MM}mm 且 累计 ≤{S.MAX_TOTAL_MM}mm)")

print()
print("=" * 92)
print("③ 否决闸: 检测不可靠(score=0.40) → 一条指令都不许下发")
print("=" * 92)
p3 = FakePlant(x0=3.0, score=0.40)
ctl3 = make_ctl(p3)
ok3, why3 = ctl3.run_lateral(dry=False)
print(f"  → 结果 {ok3}({why3}) | 下发指令数 {len(p3.cmds)}")
a3 = (not ok3) and len(p3.cmds) == 0
print(f"  断言: {'PASS' if a3 else 'FAIL'}  (拒绝下发, 0 条指令)")

print()
print("=" * 92)
print("④ 对焦: 退火爬坡把 focus 拉到峰值 (最佳 z=3.0mm), 且不超过退火步长")
print("=" * 92)
p4 = FakePlant(z0=0.0)
ctl4 = make_ctl(p4)
# 注: run_focus 的直方图里 focus 单调上升才继续; 峰值两侧都下降 → 会退回并反向
ok4, why4 = ctl4.run_focus(dry=False)
print(f"  → 结果 {ok4}({why4}) | 终态 z={p4.z:.3f}mm focus={p4.region()['focus']:.0f}(峰值 {FOCUS_MAX:.0f}) | 下发 {len(p4.cmds)} 条")
a4 = abs(p4.z - FOCUS_PEAK_Z) <= 0.45 and p4.region()["focus"] >= FOCUS_MAX * 0.97
print(f"  断言: {'PASS' if a4 else 'FAIL'}  (z 落在 {FOCUS_PEAK_Z}±0.45mm 且 focus ≥ 峰值 97%)")

print()
print("=" * 92)
print("⑤ dry-run 不出手: 未授权时 0 条指令")
print("=" * 92)
p5 = FakePlant(x0=2.0)
ctl5 = make_ctl(p5)
ok5, why5 = ctl5.run_lateral(dry=True)
print(f"  → 结果 {ok5}({why5}) | 下发指令数 {len(p5.cmds)}")
a5 = (not ok5) and len(p5.cmds) == 0
print(f"  断言: {'PASS' if a5 else 'FAIL'}")

res = {"①收敛": a1, "②限幅": a2, "③否决": a3, "④对焦": a4, "⑤dry-run": a5}
print("\n=== 汇总 ===")
for k, v in res.items():
    print(f"  {k}: {'PASS' if v else 'FAIL'}")
print("RESULT:" + ("PASS" if all(res.values()) else "FAIL"))
