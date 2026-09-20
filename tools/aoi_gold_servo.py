#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aoi_gold_servo.py — 金手指 AOI「视觉伺服 + 自动对焦」引导 (v1, 2026-09-20)

干什么
    用 10082 相机的**原始图**做金手指区域检测 (/region, 模板法几何; 区域框在原始图坐标系),
    和"示教基准位"比对, 算出偏差 → 用 L2 原子技能小步进把光模块调到最佳视角, 并沿光轴自动对焦。

架构口径 (与状态空间一致)
    上层(状态空间/技能) 只给**意图**: "把金手指调到最佳视角并合焦"
    执行全部走 **L2 收口**: L2.move_x / L2.move_y / L2.lift / L2.lower (FIFO 一行 JSON)
    可行域逐层收窄: 单步限幅 → 单轴总量限幅 → 迭代次数上限 → 检测不可靠即否决
    本脚本不做任何"自研运动学", 只用已注册的 L2 原子技能。

四级安全闸 (缺一不动)
    ① 默认 dry-run: 只算并打印"本想下发什么", 不下发; 要真动必须显式 --authorize
    ② 检测可靠闸: score < MIN_SCORE 或 金覆盖 < MIN_COVER → 判为不可靠 → 拒绝下发(否决步)
    ③ 限幅闸: 单步 ≤ MAX_STEP_MM, 单轴累计 ≤ MAX_TOTAL_MM, 迭代 ≤ MAX_ITERS
    ④ 跳变闸: 一步之后区域位置/尺度跳变超过"按标定雅可比预期"的 3 倍 → 立即停并报错

用法
    # 0) 安全问题: 先看基线有没有过 (全 dry)
    python3 tools/aoi_gold_servo.py check

    # 1) 示教基准位: 人工把光模块摆到"最佳视角", 然后记录基准 (需要真机, 但只读相机)
    python3 tools/aoi_gold_servo.py teach --name aoi_gold_target

    # 2) 一次标定: 量出"图像像素 ↔ 机械臂 mm"的雅可比 (会真动 2 次, 每次 ≤2mm)
    python3 tools/aoi_gold_servo.py calibrate --authorize

    # 3) 伺服闭环 (真动, 需授权):
    python3 tools/aoi_gold_servo.py serve --authorize
"""
import argparse
import json
import os
import sys
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIFO = os.path.expanduser("~/zmax_data/l2_cmd.fifo")
TARGET_PATH = os.path.join(REPO, "data/skills/l2_atomic/aoi_gold_target.json")
AOI_BASE = os.environ.get("AOI_BASE", "http://192.168.23.23:10082")

# ---- 安全参数 (可被 CLI 覆盖) ----
MIN_SCORE = 0.85          # 模板匹配分下限
MIN_COVER = 0.45          # 金覆盖率下限(裁剪内金像素/全图金像素)
MAX_STEP_MM = 2.0         # 单步限幅
MAX_TOTAL_MM = 15.0       # 单轴累计限幅
MAX_ITERS = 25            # 迭代上限
TOL_PX = 12.0             # 收敛判据: 区域中心偏差(像素)
FOCUS_STEPS = (0.8, 0.4, 0.2)   # 对焦退火步长(mm)
JUMP_TOL = 3.0            # 跳变闸倍数


# ---------------------------------------------------------------- IO 层 (可注入, 便于离线测试)
def http_json(path, timeout=20):
    with urllib.request.urlopen(f"{AOI_BASE}{path}", timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def get_region(grab=True):
    """区域检测: 从 10082 拿原始图上的金手指区域 + 对焦清晰度"""
    return http_json("/region?grab=1" if grab else "/region")


def send_l2(skill, **kw):
    """下发 L2 原子技能 (一行 JSON 进 FIFO)"""
    payload = {"skill": skill, **kw}
    with open(FIFO, "w", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return payload


# ---------------------------------------------------------------- 纯逻辑 (离线可测)
class ServoController:
    """误差 → L2 步进 的全部数学与闸门都在这; 通过注入 plant 做离线闭环测试"""

    def __init__(self, target, jac=None, send=None, get_reg=None, log=print,
                 max_step=MAX_STEP_MM, max_total=MAX_TOTAL_MM, max_iters=MAX_ITERS,
                 tol_px=TOL_PX, min_score=MIN_SCORE, min_cover=MIN_COVER, verbose=True):
        self.target = target                 # {"region":{cx,cy,w,h,angle}, "focus":..}
        self.jac = jac                       # {"mm_per_px": [[a,b],[c,d]], "focus_axis":"L2.lift"}
        self.send = send or (lambda *a, **k: None)
        self.get_reg = get_reg or get_region
        self.log = log
        self.max_step, self.max_total, self.max_iters, self.tol_px = max_step, max_total, max_iters, tol_px
        self.min_score, self.min_cover = min_score, min_cover
        self.verbose = verbose
        self.total = {"x": 0.0, "y": 0.0, "z": 0.0}


    # -- 闸门 --
    def reliable(self, reg):
        """检测可靠闸: 不可靠 → 拒绝下发(否决步)"""
        if not reg or not reg.get("ok"):
            return False, "区域检测失败"
        q = reg.get("quality") or {}
        sc = reg.get("score")
        cov = q.get("gold_cover")
        if sc is not None and sc < self.min_score:
            return False, f"匹配分 {sc} < {self.min_score}"
        if cov is not None and cov < self.min_cover:
            return False, f"金覆盖 {cov} < {self.min_cover}"
        if (reg.get("region") or {}).get("w", 0) < 200:
            return False, "区域尺度异常(过小)"
        return True, "ok"

    def clamp_step(self, mm, axis):
        """限幅闸: 单步 + 单轴累计"""
        mm = float(max(-self.max_step, min(self.max_step, mm)))
        room = self.max_total - abs(self.total[axis])
        if abs(mm) > room:
            mm = room if mm > 0 else -room
            if self.verbose:
                self.log(f"    [限幅] {axis} 轴累计已到 {self.total[axis]:+.2f}mm, 本步压到 {mm:+.3f}mm")
        self.total[axis] += mm
        return mm

    @staticmethod
    def jump_ok(prev, now, jac, sent_mm, factor=JUMP_TOL):
        """跳变闸: 实测位移 vs 按雅可比预期位移, 超 factor 倍判异常"""
        if jac is None or prev is None:
            return True, "未标定/无历史, 跳过跳变闸"
        # 用标定矩阵把 mm 换算成像素预期位移
        import numpy as _np
        Jinv = _np.linalg.inv(_np.array(jac["mm_per_px"], dtype=float))  # px per mm
        exp_px = Jinv @ _np.array([[sent_mm[0]], [sent_mm[1]]])
        act_px = _np.array([[now["cx"] - prev["cx"]], [now["cy"] - prev["cy"]]])
        exp_len = float(_np.linalg.norm(exp_px))
        act_len = float(_np.linalg.norm(act_px))
        if exp_len < 1e-6:
            return True, "本步未运动"
        ratio = act_len / exp_len
        if act_len > 1.0 and (ratio > factor or ratio < 1.0 / max(factor, 1e-6)):
            return False, f"区域位移跳变 {act_len:.1f}px vs 预期 {exp_len:.1f}px (比值 {ratio:.2f})"
        return True, "ok"

    # -- 主环 --
    def step_lateral(self, reg):
        """横向前馈: 区域中心偏差 → 机械臂 mm 步进"""
        r, t = reg["region"], self.target["region"]
        ex = r["cx"] - t["cx"]
        ey = r["cy"] - t["cy"]
        if self.jac is None:
            return None, ex, ey, "未标定(先跑 calibrate)"
        a, b = self.jac["mm_per_px"][0]
        c, d = self.jac["mm_per_px"][1]
        # 注意符号: mm_per_px 描述"臂动 1mm → 图像动多少像素"的逆; 要**消掉**偏差 e=区域-基准,
        # 必须让图像反向移动 e, 所以步进取负: darm = -M · e
        mx = -(a * ex + b * ey)
        my = -(c * ex + d * ey)
        return (mx, my), ex, ey, "ok"

    def focus_axis(self):
        return (self.jac or {}).get("focus_axis", "L2.lift")

    def run_lateral(self, dry=True):
        """横向闭环: 反复 检测→限幅→下发 直到 |误差| < tol_px"""
        it = 0
        prev = None
        while it < self.max_iters:
            it += 1
            reg = self.get_reg()
            ok, why = self.reliable(reg)
            if not ok:
                self.log(f"[{it}] ⛔ 否决: {why} (不下发)")
                return False, f"否决: {why}"
            r = reg["region"]
            step, ex, ey, why = self.step_lateral(reg)
            if step is None:
                self.log(f"[{it}] 区域中心偏差 ({ex:+.1f},{ey:+.1f})px — {why}")
                return False, why
            self.log(f"[{it}] 偏差 ({ex:+.1f},{ey:+.1f})px  期望步进 ({step[0]:+.3f},{step[1]:+.3f})mm")
            if abs(ex) <= self.tol_px and abs(ey) <= self.tol_px:
                self.log(f"✅ 横向收敛: 偏差 ({ex:+.1f},{ey:+.1f})px ≤ {self.tol_px}px")
                return True, "converged"
            mx = self.clamp_step(step[0], "x")
            my = self.clamp_step(step[1], "y")
            sent = (mx, my)
            if dry:
                self.log(f"    [dry] 本想下发: L2.move_x {mx:+.3f}mm / L2.move_y {my:+.3f}mm")
                return False, "dry-run (未授权不动)"
            if abs(mx) > 0.02:
                self.send("L2.move_x", d_mm=round(abs(mx), 3), sign=1 if mx > 0 else -1)
            if abs(my) > 0.02:
                self.send("L2.move_y", d_mm=round(abs(my), 3), sign=1 if my > 0 else -1)
            time.sleep(0.4)
            now = self.get_reg()
            okj, whyj = self.jump_ok(prev or r, now["region"], self.jac, sent)
            if not okj:
                self.log(f"    ⛔ 跳变闸拦下: {whyj} → 停止")
                return False, whyj
            prev = now["region"]
        return False, f"超过迭代上限 {self.max_iters}"

    def run_focus(self, dry=True):
        """对焦闭环: 沿光轴退火爬坡, focus(Laplacian方差) 到峰值即停"""
        ax = self.focus_axis()
        reg = self.get_reg()
        ok, why = self.reliable(reg)
        if not ok:
            return False, f"否决: {why}"
        best = reg.get("focus")
        if best is None:
            return False, "无 focus 指标"
        sign = 1
        for mm in FOCUS_STEPS:
            for attempt in range(2):
                if dry:
                    self.log(f"    [dry] 本想下发: {ax} {sign*mm:+.2f}mm (当前 focus={best:.0f})")
                    return False, "dry-run (未授权不动)"
                d = self.clamp_step(sign * mm, "z")
                self.send(ax, d_mm=round(abs(d), 3), sign=1 if d > 0 else -1)
                time.sleep(0.5)
                reg = self.get_reg()
                ok, why = self.reliable(reg)
                if not ok:
                    self.log(f"    ⛔ 否决: {why} → 退回本步")
                    self.send(ax, d_mm=round(abs(d), 3), sign=-1 if d > 0 else 1)
                    break
                f = reg.get("focus")
                self.log(f"    {ax} {d:+.2f}mm → focus={f:.0f} (原 {best:.0f})")
                if f is not None and f > best * 1.01:
                    best = f
                    continue
                # 变差 → 退回并反向
                self.send(ax, d_mm=round(abs(d), 3), sign=-1 if d > 0 else 1)
                sign = -sign
                break
        self.log(f"✅ 对焦完成: focus={best:.0f}")
        return True, "focused"


# ---------------------------------------------------------------- CLI
def cmd_check(args):
    reg = get_region(grab=True)
    print(json.dumps(reg, ensure_ascii=False, indent=1)[:1200])
    print(f"\n检测可靠闸: {'PASS' if reg.get('ok') and (reg.get('score') or 0) >= MIN_SCORE else 'FAIL/不可靠'}")
    tgt = load_target() if os.path.exists(TARGET_PATH) else None
    if tgt:
        ctl = ServoController(tgt, jac=tgt.get("jac"), send=send_l2, get_reg=lambda: reg)
        step, ex, ey, why = ctl.step_lateral(reg)
        print(f"与示教基准偏差: ({ex:+.1f},{ey:+.1f})px · 角度差 {reg['region']['angle']-tgt['region']['angle']:+.2f}° · "
              f"focus {reg.get('focus')} vs 基准 {tgt.get('focus')}")
        if step:
            print(f"若授权, 本步会下发: L2.move_x {step[0]:+.3f}mm / L2.move_y {step[1]:+.3f}mm")
    else:
        print(f"未找到示教基准 {TARGET_PATH} → 先 teach")
    return 0


def load_target():
    return json.load(open(TARGET_PATH, encoding="utf-8"))


def cmd_teach(args):
    reg = get_region(grab=True)
    if not reg.get("ok"):
        print("区域检测失败, 不记基准:", reg.get("reason"))
        return 1
    out = {"name": args.name, "ts": time.time(), "region": reg["region"], "focus": reg.get("focus"),
           "score": reg.get("score"), "quality": reg.get("quality"), "note": "金手指最佳视角基准(示教)"}
    if os.path.exists(TARGET_PATH):
        bak = TARGET_PATH + f".bak_{int(time.time())}"
        os.replace(TARGET_PATH, bak)
        print(f"旧基准已备份: {os.path.basename(bak)}")
    json.dump(out, open(TARGET_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"✅ 基准已写入 {TARGET_PATH}\n   region={out['region']}\n   focus={out['focus']} score={out['score']}")
    return 0


def cmd_calibrate(args):
    """量雅可比: 沿臂 X/Y 各推 +dmm, 看区域中心在图像里移动多少像素 → mm_per_px"""
    if not args.authorize:
        print("⛔ 标定会真动机械臂(每轴 ≤2mm)。确认安全后加 --authorize 重跑。")
        return 2
    dmm = args.probe_mm
    pts = {}
    base = get_region(grab=True)
    if not base.get("ok"):
        print("区域检测失败, 无法标定"); return 1
    pts["base"] = base["region"]
    for axis, skill in (("x", "L2.move_x"), ("y", "L2.move_y")):
        send_l2(skill, d_mm=dmm, sign=1)
        time.sleep(args.settle)
        reg = get_region(grab=True)
        if not reg.get("ok"):
            print(f"{axis} 探测后区域检测失败 → 中止"); return 1
        pts[axis] = reg["region"]
        send_l2(skill, d_mm=dmm, sign=-1)      # 回原位
        time.sleep(args.settle)
    dx = [(pts["x"]["cx"] - pts["base"]["cx"]) / dmm, (pts["x"]["cy"] - pts["base"]["cy"]) / dmm]
    dy = [(pts["y"]["cx"] - pts["base"]["cx"]) / dmm, (pts["y"]["cy"] - pts["base"]["cy"]) / dmm]
    # 图像位移(px/mm) → 臂位移/像素 = 2x2 逆矩阵
    import numpy as _np
    Jinv = _np.array([[dx[0], dy[0]], [dx[1], dy[1]]])     # px per mm
    if abs(_np.linalg.det(Jinv)) < 1e-6:
        print("⛔ 标定矩阵退化(两轴在图像里方向几乎相同), 换探测方向重测"); return 1
    M = _np.linalg.inv(Jinv)                               # mm per px
    tgt = load_target() if os.path.exists(TARGET_PATH) else {"region": get_region()["region"]}
    tgt["jac"] = {"mm_per_px": [[round(float(M[0, 0]), 6), round(float(M[0, 1]), 6)],
                                [round(float(M[1, 0]), 6), round(float(M[1, 1]), 6)]],
                  "px_per_mm": [[round(v, 3) for v in dx], [round(v, 3) for v in dy]],
                  "probe_mm": dmm, "focus_axis": args.focus_axis, "ts": time.time()}
    json.dump(tgt, open(TARGET_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"✅ 雅可比已写入 {TARGET_PATH}\n   图像位移 px/mm: x轴 {dx} · y轴 {dy}\n   mm/px: {tgt['jac']['mm_per_px']}")
    return 0


def cmd_serve(args):
    tgt = load_target() if os.path.exists(TARGET_PATH) else None
    if not tgt:
        print(f"⛔ 没有示教基准 {TARGET_PATH}: 先 `teach`"); return 1
    ctl = ServoController(tgt, jac=tgt.get("jac"), send=send_l2, log=print,
                          max_step=args.max_step, max_total=args.max_total, max_iters=args.max_iters)
    if ctl.jac is None:
        print("⛔ 还没标定雅可比: 先 `calibrate` (需要一次真机动 2 次)"); return 1
    dry = not args.authorize
    if dry:
        print("=== DRY-RUN (未授权, 不会真动; 要真动加 --authorize) ===")
    ok1, why1 = ctl.run_lateral(dry=dry)
    if not dry and ok1:
        ok2, why2 = ctl.run_focus(dry=dry)
    else:
        ok2, why2 = (None, "skipped") if not dry else (None, "dry")
    print(f"\n结果: 横向={ok1}({why1}) 对焦={ok2}({why2}) 累计位移 {ctl.total}")
    return 0 if ok1 else 1


def main():
    ap = argparse.ArgumentParser(description="金手指 AOI 视觉伺服 + 自动对焦引导")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check", help="只读自检: 区域检测 + 与基准偏差 + 本步会下发什么 (不动)")
    p.set_defaults(func=cmd_check)
    p = sub.add_parser("teach", help="记录「最佳视角」基准 (只读相机, 不动)")
    p.add_argument("--name", default="aoi_gold_target")
    p.set_defaults(func=cmd_teach)
    p = sub.add_parser("calibrate", help="量图像↔机械臂 雅可比 (会真动 2 次, 每次 ≤2mm)")
    p.add_argument("--authorize", action="store_true")
    p.add_argument("--probe-mm", type=float, default=1.0)
    p.add_argument("--settle", type=float, default=1.0)
    p.add_argument("--focus-axis", default="L2.lift", choices=["L2.lift", "L2.lower"])
    p.set_defaults(func=cmd_calibrate)
    p = sub.add_parser("serve", help="伺服闭环: 横向对准 + 自动对焦")
    p.add_argument("--authorize", action="store_true", help="允许真机上电动作(默认 dry-run)")
    p.add_argument("--max-step", type=float, default=MAX_STEP_MM)
    p.add_argument("--max-total", type=float, default=MAX_TOTAL_MM)
    p.add_argument("--max-iters", type=int, default=MAX_ITERS)
    p.set_defaults(func=cmd_serve)
    a = ap.parse_args()
    sys.exit(a.func(a))


if __name__ == "__main__":
    main()
