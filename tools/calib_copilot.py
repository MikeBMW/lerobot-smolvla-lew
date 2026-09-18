#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""calib_copilot.py — 🎯 真机标定向导 (视觉大模型 + 机器人自身位姿, 人工零测量)

老倪 2026-09-19: 「我现在缺少人工标定的工具, 你需要设计一个方法, 利用大语言模型的视觉和
理解能力, 推进真实场景的标定。」

要标的东西 (真机光模块插拔 3D 感知链):
  ① 相机内参 K      — 已从 D405 camera_info 白拿 (models/real_cam_calib.json)
  ② 手眼外参 T_base_cam + 夹持偏移 off + 夹持歪斜 R_rel — 本工具标的: 用「YOLO 框 + 编码器位姿」
     自监督拟合 (不需要棋盘格、不需要量尺寸、不需要深度)
  ③ 台面高度 plane_z — 量一次 (本工具会提示该量哪)

本工具怎么用 VLM (它只做"看图说话/判质量/给下一步", 数字一律来自几何):
  · **采集准入**: 每帧问 VLM "这帧能不能用" (模糊/太远/出画/遮挡/目标不在夹爪上) → 拒绝坏帧
    (自监督拟合最怕脏帧; 人工筛帧正是"缺少的工具"那一环)
  · **人机指令**: 每步给操作员一句具体动作 + 验收判据 (做什么 → 图里该看到什么)
  · **场景核对**: 目标可见性/朝向/背景线索与几何结果交叉核对, 不一致就报出来 (不掩盖)

纪律 (老倪红线): 没有 VLM 时照样能标 (规则判据全在), 只是少了"看懂画面"那层;
                 每帧的"可用/不可用"都带**具体原因**, 拟合结果带**留出残差 + 前提自证 IoU**。

用法:
  gui-venv311/bin/python tools/calib_copilot.py                 # 单帧体检 + 下一步指令 (现场点一下)
  ... --loop                                                    # 常驻向导: 每 3s 判一次, 边采集边提示
  ... --collect                                                 # 采集模式: 合格帧进解算器, 攒够自动拟合+落盘
  ... --report                                                  # 出标定报告 (JSON+文本, 含 VLM 逐帧判定)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_REPO, "src"))
sys.path.insert(0, os.path.join(_REPO, "src", "lerobot", "policies", "yolo_3d"))

import box3d_live_box as LB                                                    # noqa: E402
from box3d_solver import Box3DSolver                                           # noqa: E402

OUT = os.path.expanduser("~/zmax_data/calib_copilot")
STATE = os.path.join(_REPO, "models", "box3d_state.json")


def vlm():
    """懒载 VLM (拿不到就返回 None, 规则路径继续跑)"""
    try:
        from lerobot.policies.left_right.state_space.scene_vlm import SceneVLM
        return SceneVLM.get()
    except Exception:                                                          # noqa: BLE001
        try:
            sys.path.insert(0, os.path.join(_REPO, "src", "lerobot", "policies", "left_right", "state_space"))
            from scene_vlm import SceneVLM
            return SceneVLM.get()
        except Exception as e:                                                 # noqa: BLE001
            print(f"⚠️ 场景大模型不可用 ({type(e).__name__}: {e}) — 本次只用规则判据 (诚实降级)")
            return None


class Copilot:
    def __init__(self, use_vlm=True, min_conf=0.4, imgsz=640, log_dir=None):
        self.dir = log_dir or os.path.join(OUT, time.strftime("%Y%m%d_%H%M%S"))
        os.makedirs(self.dir, exist_ok=True)
        self.logf = open(os.path.join(self.dir, "session.jsonl"), "a", encoding="utf-8")
        self.vlm = vlm() if use_vlm else None
        self.min_conf, self.imgsz = float(min_conf), int(imgsz)
        self.solver = LB.ensure_solver(log=True)
        self.n_seen = self.n_cand = self.n_acc = 0
        self.hist = []

    # ── 一帧完整体检: 几何配对 + YOLO + VLM 准入 ──
    def observe(self, want_collect=False):
        rec = {"t": time.time(), "step": self.n_seen}
        line, info = LB.newest_state_line()
        if line is None:
            rec.update({"ok": False, "why": f"位姿真值不可用: {info}"})
            return rec
        rec["pose_age_s"] = round(float(info), 2)
        fp, fage, note = LB.frame_for(line)
        if fp is None:
            rec.update({"ok": False, "why": note})
            return rec
        rec.update({"frame": os.path.basename(fp),
                    "frame_age_s": (None if fage is None else round(float(fage), 2)),
                    "frame_note": note})
        box, conf, cls, shp = LB.detect(fp, self.min_conf, self.imgsz)
        tcp = [float(v) for v in line["tcp"]]
        quat = [float(v) for v in line["tcp_quat"]]
        rec.update({"tcp": [round(v, 5) for v in tcp], "box": box, "conf": conf, "cls": cls})
        if box is None:
            rec.update({"ok": False, "why": f"YOLO 未检出光模块 (conf<{self.min_conf})",
                        "next": "把光模块放到相机视野内 (画面中上部); 检查光照/是否被手挡住"})
            return rec
        # 几何自检: 夹持假设 (已标定时才有效)
        sc = self.solver.held_selfcheck(box, tcp, quat) if self.solver.fitted else None
        rec["held_selfcheck"] = sc
        # VLM 准入 (看得懂画面那层)
        v = None
        if self.vlm is not None:
            try:
                v = self.vlm.quality(fp, {"box": box, "conf": conf, "tcp": tcp})
            except Exception as e:                                             # noqa: BLE001
                v = {"ok": False, "why": f"{type(e).__name__}: {e}"}
        rec["vlm_quality"] = v
        vok = None if not v or not v.get("ok") else bool((v.get("json") or {}).get("合格", True))
        rec["vlm_ok"] = vok
        if vok is False:
            rec.update({"ok": False, "why": "VLM 判定该帧不合格: "
                        + str((v.get("json") or {}).get("问题")),
                        "next": "按 VLM 指出的问题调整 (靠近/别挡/对光/对焦) 再采一次"})
            return rec
        # 规则准入 (几何门槛, 与解算器 add() 同一套)
        add = self.solver.add(box, tcp, quat, meta={"frame": os.path.basename(fp), "conf": conf,
                                                   "vlm_ok": vok, "src": "calib_copilot"})
        rec["solver_add"] = add
        rec["ok"] = bool(add.get("ok"))
        if not add.get("ok"):
            rec["why"] = add.get("why")
        else:
            rec["diversity"] = self.solver.diversity()
        return rec

    def next_instruction(self, rec):
        """给操作员的下一步 (VLM 有话说就用它, 否则规则)"""
        if rec.get("ok") and self.solver.fitted is False:
            d = rec.get("diversity") or {}
            n, need = d.get("n", len(self.solver.obs)), 10
            if n < need:
                return (f"继续走位姿: 已收 {n}/{need} 帧 → 拖动模式下把模块在画面里换位置/换朝向 "
                        f"(进来一点、转个手腕、抬高一点)")
            if not d.get("ok"):
                return f"位姿还不够有区分度: {d.get('why')} → 重点做『深度变化』(让模块离相机远近变化) + 转手腕"
            return "位姿够了 → 按 Enter 触发自监督拟合 (或加 --collect 自动拟合)"
        if rec.get("ok"):
            return "本帧已收下 (可用于验证/复核)"
        return rec.get("next") or "按提示调整"

    # ── 拟合 + 落盘 (含前提自证) ──
    def fit(self):
        if self.solver.fitted:
            return {"ok": True, "already": True, "status": self.solver.status()}
        r = LB.try_fit(self.solver, log=True)
        return r

    def close(self):
        try:
            self.logf.close()
        except Exception:                                                      # noqa: BLE001
            pass

    def log_rec(self, rec):
        try:
            self.logf.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            self.logf.flush()
        except Exception:                                                      # noqa: BLE001
            pass


def print_rec(c, rec, tag=""):
    print(f"\n───── 🎯 标定向导 {tag} (t={time.strftime('%H:%M:%S')}) ─────")
    if rec.get("frame"):
        print(f"  图: {rec['frame']} (帧龄 {rec.get('frame_age_s')}s) · TCP {rec.get('tcp')}")
    if rec.get("box"):
        b = rec["box"]
        print(f"  YOLO: {rec.get('cls')} conf={rec.get('conf')} 框={[round(v,1) for v in b]} "
              f"({b[2]-b[0]:.0f}x{b[3]-b[1]:.0f}px)")
    v = rec.get("vlm_quality")
    if v is not None:
        if v.get("ok"):
            j = v.get("json") or {}
            print(f"  VLM 质检 ({v.get('src')} · {v.get('latency_ms')}ms): 合格={j.get('合格')} "
                  f"问题={j.get('问题')} 清晰度={j.get('目标清晰度')}")
        else:
            print(f"  VLM 质检: 不可用 ({v.get('why')}) → 只用几何判据")
    d = rec.get("diversity")
    if d:
        print(f"  采集进度: {d.get('n')} 帧 · 平面性 {d.get('planarity')} (需≥0.15) · "
              f"姿态散布 {d.get('tilt_deg')}° (需≥10°) · {'✅ 位姿合格' if d.get('ok') else '⏳ ' + str(d.get('why'))}")
    print(f"  本帧: {'✅ 可用' if rec.get('ok') else '❌ 不可用'} " + (f"— {rec.get('why')}" if rec.get('why') else ""))
    print(f"  ➡️ 下一步: {c.next_instruction(rec)}")


def do_report():
    """标定报告: 解算器状态 + 最近一次 VLM/采集会话汇总 (JSON + 人读文本)"""
    st_path = STATE
    st = {}
    if os.path.exists(st_path):
        try:
            st = json.load(open(st_path, encoding="utf-8"))
        except Exception as e:                                                 # noqa: BLE001
            print(f"⚠️ 读 {st_path} 失败: {e}")
    sessions = sorted([d for d in (os.path.join(OUT, x) for x in os.listdir(OUT))
                       if os.path.isdir(d)], key=os.path.getmtime)[-1:] if os.path.isdir(OUT) else []
    rows = []
    for d in sessions:
        f = os.path.join(d, "session.jsonl")
        if not os.path.exists(f):
            continue
        for ln in open(f, encoding="utf-8"):
            try:
                rows.append(json.loads(ln))
            except Exception:                                                  # noqa: BLE001
                pass
    ok_rows = [r for r in rows if r.get("ok")]
    vlm_ok = [r for r in rows if (r.get("vlm_quality") or {}).get("ok")]
    rep = {
        "生成时间": time.strftime("%F %T"),
        "解算器": {"已标定": bool(st.get("P")), "拟合残差px": st.get("rms_px"),
                    "留出残差px": st.get("holdout_rms_px"),
                    "夹持偏移mm": (None if not st.get("off_m") else
                                   [round(float(v) * 1000, 1) for v in st["off_m"]]),
                    "尺寸mm": st.get("size_mm"), "尺寸来源": st.get("size_src"),
                    "夹持转角": st.get("rrel_src"), "帧数": st.get("n_obs"),
                    "手眼": (None if not st.get("T_cam_from_base") else "已解出 (内参K已知)")},
        "最近会话": {"目录": (sessions[-1] if sessions else None), "判读帧数": len(rows),
                     "几何合格帧": len(ok_rows), "VLM 判定合格帧": len(vlm_ok)},
    }
    txt = (f"🎯 Z-MAX 真机标定报告 ({rep['生成时间']})\n"
           f"· 解算器: " + ("**已标定**" if rep["解算器"]["已标定"] else "未标定") +
           f" (残差 {rep['解算器']['拟合残差px']}px / 留出 {rep['解算器']['留出残差px']}px)\n"
           f"· 夹持偏移 {rep['解算器']['夹持偏移mm']}mm · 尺寸 {rep['解算器']['尺寸mm']}mm"
           f"({rep['解算器']['尺寸来源']}) · 夹持转角 {rep['解算器']['夹持转角']}\n"
           f"· 手眼外参 {rep['解算器']['手眼']} · 采样帧 {rep['解算器']['帧数']}\n"
           f"· 最近会话: {rep['最近会话']['目录']} → 判读 {rep['最近会话']['判读帧数']} 帧, "
           f"几何合格 {rep['最近会话']['几何合格帧']}, VLM 合格 {rep['最近会话']['VLM 判定合格帧']}")
    print(txt)
    out = os.path.expanduser(f"~/zmax_data/calib_report_{time.strftime('%Y%m%d_%H%M%S')}.json")
    json.dump(rep, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n证据: {out}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=float, default=3.0)
    ap.add_argument("--collect", action="store_true", help="合格帧进解算器, 攒够自动拟合+落盘")
    ap.add_argument("--min-conf", type=float, default=0.4)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--no-vlm", action="store_true", help="只用规则判据 (VLM 不可用时也这样)")
    ap.add_argument("--seconds", type=float, default=0.0)
    ap.add_argument("--report", action="store_true",
                    help="出标定报告: 汇总本工具会话 + 当前 models/box3d_state.json 的标定结果")
    args = ap.parse_args()
    if args.report:
        return do_report()
    c = Copilot(use_vlm=not args.no_vlm, min_conf=args.min_conf, imgsz=args.imgsz)
    print(f"🎯 标定向导启动 · 会话目录 {c.dir}")
    print(f"   模型: {json.dumps(c.vlm.status(), ensure_ascii=False) if c.vlm else '无 (规则路径)'}")
    print(f"   解算器: {json.dumps(c.solver.status(), ensure_ascii=False)[:220]}")
    t_end = time.time() + args.seconds if args.seconds else None
    last_fit_n = len(c.solver.obs)
    try:
        while True:
            c.n_seen += 1
            rec = c.observe()
            c.log_rec(rec)
            if rec.get("ok"):
                c.n_acc += 1
            print_rec(c, rec, tag=f"#{c.n_seen}")
            if args.collect and not c.solver.fitted and (c.n_acc % 5 == 0) and len(c.solver.obs) >= last_fit_n:
                r = c.fit()
                if r.get("ok") and not r.get("already"):
                    print(f"\n✅ 自监督标定成功 → {STATE}")
                    if c.solver.fitted:
                        b3 = c.solver.predict_box3d(rec["box"], tcp=rec["tcp"], quat=rec["quat"])
                        print(f"   本帧 3D 边界框: mode={b3['mode']} 中心={b3.get('center')} "
                              f"IoU={b3.get('iou')} σ={b3.get('sigma_mm')}")
                    break
            if not args.loop:
                break
            if t_end and time.time() >= t_end:
                break
            time.sleep(max(0.2, args.interval))
    except KeyboardInterrupt:
        print("\n(操作员中断)")
    finally:
        print(f"\n本次: 采 {c.n_seen} 帧 · 合格 {c.n_acc} 帧 · 解算器 {'已标定' if c.solver.fitted else '未标定'} "
              f"· 会话日志 {os.path.join(c.dir, 'session.jsonl')}")
        c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
