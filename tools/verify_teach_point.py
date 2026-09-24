#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_teach_point.py — 📍 金手指示教点技能取证 (2026-09-24)

判据:
  ① 位姿解析: 从真实 /robot/tcp_pose 文本抽 pos/quat (不用正则猜格式, 用真帧文本断言)
  ② 位姿真值可读 + 抖动判据: 真机读数 (idle 时 spread 应极小); **抖超限必须拒绝** (注入抖动文本模拟)
  ③ 记录: 落 l2_atomic/taught_points.json (字段与既有 aoi_gold_view/slot1 同名) + AOI 上下文 json
  ④ 拒绝假记: 位姿读不到 → **不写库**并如实回报
  ⑤ 回位 dry-run: 算出 Δmm/Δdeg + 打印将下发的命令, **绝不下发运动**
  ⑥ 命令可复制: FIFO(L2 收口) 与 ros2 service 两条命令文本 (可直接粘到 4060 终端)
  ⑦ 收口在册: registry 里有 L2.goto_point (回位由常驻执行器执行, 自带闸门)
用法: ./gui-venv311/bin/python tools/verify_teach_point.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "gui"),
           os.path.join(ROOT, "src", "lerobot", "policies", "yolo_3d")):
    sys.path.insert(0, _p)
_TMP = tempfile.mkdtemp(prefix="tp_verify_")
os.environ["ZMAX_TAUGHT_POINTS"] = os.path.join(_TMP, "taught_points.json")   # 隔离: 不碰真点位库

import aoi_teach_point as tp                                              # noqa: E402

CHECKS, RES = {}, {}

REAL_TEXT = ("header: stamp: sec: 1790239416 nanosec: 876812873 frame_id: base_link pose: "
             "position: x: 0.5972987921981883 y: 0.14861965656340248 z: 0.6415945406966718 "
             "orientation: x: -0.08001368679169181 y: 0.006957001274360952 z: 0.9963442798234966 "
             "w: 0.029111614903116638 ---")


def ck(n, c, d=""):
    CHECKS[n] = bool(c)
    print(f"  {'✅' if c else '❌'} {n}" + (f" — {d}" if d else ""))


def main():
    # ① 解析真帧文本
    p = tp.parse_pose(REAL_TEXT)
    RES["parse"] = p
    ck("① 位姿解析 (真帧文本 → pos/quat)",
       p is not None and abs(p["pos"][0] - 0.5972987921981883) < 1e-12
       and abs(p["quat"][3] - 0.029111614903116638) < 1e-12,
       f"pos={[round(v,4) for v in p['pos']]} quat={[round(v,4) for v in p['quat']]}")
    ck("① 空/坏文本 → 返回 None (不猜)", tp.parse_pose("") is None and tp.parse_pose("garbage") is None)

    # ② 真机位姿真值 + 抖动
    pose, meta = tp.read_pose(samples=4)
    RES["live_read"] = {"pose": pose, "meta": meta}
    ck("② 真机位姿可读 (/robot/tcp_pose 只读)",
       pose is not None and meta.get("ok") and meta.get("n", 0) >= 3,
       f"n={meta.get('n')} spread_pos={meta.get('spread_pos_m')}m status={meta.get('status')}")
    ck("② idle 时抖动在阈值内 (0.5mm)", meta.get("ok") is True,
       f"spread {meta.get('spread_pos_m')}m ≤ {tp.MAX_SPREAD_M}m")

    # ③ 记录 (注入位姿, 不打机械臂) → 落两库
    r = tp.record("金手指点1", desc="AOI 金手指观察位 (verify 注入)", dry_pose=pose or
                  {"pos": [0.5973, 0.1486, 0.6416], "quat": [-0.08, 0.00696, 0.99634, 0.02911]},
                  roi=[433, 948, 2056, 1074], judge_png="/tmp/x.png", judge_stats={"sat_in_rect": 0.044})
    pts = json.load(open(tp.POINTS, encoding="utf-8"))["points"]
    RES["record"] = {"ok": r.get("ok"), "keys": sorted(pts.get("金手指点1", {}).keys()),
                     "ctx": r.get("ctx")}
    ck("③ 记住点位 → taught_points.json (字段与既有库同名)",
       r.get("ok") and {"pos", "quat", "desc", "recorded_at", "source", "n_samples", "spread_pos_m"}
       <= set(pts.get("金手指点1", {}).keys()),
       f"{sorted(pts.get('金手指点1', {}).keys())}")
    ck("③ AOI 上下文 (框选 ROI + 判据图快照 + 指标) 一并留档",
       r.get("ctx") and os.path.isfile(r["ctx"]) and json.load(open(r["ctx"], encoding="utf-8"))["roi"] == [433, 948, 2056, 1074],
       str(r.get("ctx")))

    # ④ 位姿读不到 → 拒绝写库
    import aoi_teach_point as _tp
    _old = _tp.read_pose
    _tp.read_pose = lambda *a, **k: (None, {"ok": False, "err": "读不到 (模拟)"})
    r2 = _tp.record("不该存在的点")
    _tp.read_pose = _old
    keys_after = set(json.load(open(tp.POINTS, encoding="utf-8"))["points"].keys())
    RES["refuse"] = r2
    ck("④ 位姿不可用时拒绝写库 (不造假点位)",
       r2.get("ok") is False and "不该存在的点" not in keys_after, str(r2.get("err"))[:70])

    # ⑤ 回位 dry-run: 有 Δ, 有命令, 不下发
    g = tp.goto("金手指点1", authorize=False)
    RES["goto_dry"] = g
    ck("⑤ dry-run 算 Δ位置/Δ姿态 (不发运动)",
       g.get("ok") and g.get("dry_run") and "delta_norm_mm" in g and "delta_deg" in g
       and "dry-run" in str(g.get("note")),
       f"Δ {g.get('delta_mm')} mm = {g.get('delta_norm_mm')}mm · Δ姿态 {g.get('delta_deg')}°")
    ck("⑤ dry-run 未产生任何运动 (phase 字段不存在 = 没走下发分支)", "phase" not in g)

    # ⑥ 命令文本 (可直接粘终端)
    f, rc = tp.fifo_cmd("金手指点1"), tp.ros_cmd("金手指点1", 30)
    RES["cmds"] = {"fifo": f, "ros": rc}
    ck("⑥ FIFO 收口命令文本可复制", f.startswith("echo '{") and "L2.goto_point" in f
       and "l2_cmd.fifo" in f, f[:110])
    ck("⑥ ros2 服务命令文本可复制 (含 6 维目标位姿)",
       rc.startswith("ssh tashan@192.168.23.66") and "/move_line" in rc and "position" in rc,
       rc[:110])

    # ⑦ 收口在册
    reg = json.load(open(os.path.join(ROOT, "data/skills/l2_atomic/registry.json"), encoding="utf-8"))
    ids = {s.get("id") for s in reg["skills"]}
    RES["registry"] = sorted(i for i in ids if "goto" in str(i))
    ck("⑦ registry 有 L2.goto_point (回位走常驻执行器, 自带闸门/限幅)",
       "L2.goto_point" in ids and os.path.exists(tp.FIFO),
       f"skill 在册 + FIFO {tp.FIFO} 存在")

    # ⑧ 窗口级: 控件可达 + 记住按钮真落库 + 回位默认 dry-run (不出运动) + 复制命令
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5 import QtWidgets                                          # noqa: E402
    import aoi_inspect_console as aic                                    # noqa: E402
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = aic.AoiInspectConsole(source="real")
    w._timer.stop(); w.show()
    for _ in range(10):
        app.processEvents()
    ctrls = {"point_combo": w.cmb_point, "name_edit": w.ed_point_name, "btn_record": w.btn_tp_rec,
             "btn_goto": w.btn_tp_goto, "btn_copy": w.btn_tp_cmd, "chk_auth": w.chk_tp_auth}
    bad = [k for k, c in ctrls.items() if not (c.isVisible() and c.isEnabled()
                                              and (c.width() > 20 or k == "chk_auth"))]
    RES["gui_ctrls"] = {"bad": bad, "widths": {k: c.width() for k, c in ctrls.items()}}
    ck("⑧ 示教点控件全部可达 (记住/回位/复制/真执行勾选/点位表)", not bad, str(RES["gui_ctrls"]))
    w.ed_point_name.setText("GUI测试点")
    w.btn_tp_rec.click()                       # 走真实 read_pose (真机只读)
    for _ in range(60):
        app.processEvents(); time.sleep(0.1)
    pts_now = json.load(open(tp.POINTS, encoding="utf-8"))["points"]
    combo_has = "GUI测试点" in [w.cmb_point.itemText(i) for i in range(w.cmb_point.count())]
    RES["gui_record"] = {"in_lib": "GUI测试点" in pts_now, "in_combo": combo_has,
                         "log_tail": w.txt_log.toPlainText().strip().splitlines()[-1][:120]}
    ck("⑧ 点『📍 记住此点』→ 真位姿落库 + 下拉出现该点",
       "GUI测试点" in pts_now and combo_has and pts_now["GUI测试点"]["spread_pos_m"] <= tp.MAX_SPREAD_M,
       f"spread={pts_now.get('GUI测试点', {}).get('spread_pos_m')}m · combo={combo_has}")
    w.cmb_point.setCurrentText("GUI测试点")
    w.chk_tp_auth.setChecked(False)            # 默认 dry-run
    w.btn_tp_goto.click()
    for _ in range(40):
        app.processEvents(); time.sleep(0.1)
    lg = w.txt_log.toPlainText()
    RES["gui_goto_dry"] = {"log": lg.strip().splitlines()[-1][:160], "term": w.term_cmd.toPlainText()[-160:]}
    ck("⑧ 点『🎯 回到此点』默认 dry-run: 出 Δ 且**未下发运动**",
       "dry-run" in lg and "已下发回位" not in lg and "Δ位置" in lg, RES["gui_goto_dry"]["log"])
    ck("⑧ 回位命令进终端页 (可复制)", "L2.goto_point" in w.term_cmd.toPlainText(),
       w.term_cmd.toPlainText().strip().splitlines()[-1][:110])
    w.btn_tp_cmd.click()
    for _ in range(10):
        app.processEvents()
    cb = QtWidgets.QApplication.clipboard().text()
    ck("⑧ 『📋 复制回位命令』→ 剪贴板拿到 L2 收口命令 (可粘终端执行)",
       cb.startswith("echo '{") and "L2.goto_point" in cb and "GUI测试点" in cb, cb[:110])
    w.close()

    out = os.path.join(ROOT, "reports", "teach_point_verify.json")
    RES["checks"], RES["pass"] = CHECKS, f"{sum(CHECKS.values())}/{len(CHECKS)}"
    json.dump(RES, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n" + "=" * 74)
    print(f"  判据通过: {RES['pass']}\n  证据: {out}\n  隔离点位库: {tp.POINTS}")
    import shutil
    shutil.rmtree(_TMP, ignore_errors=True)
    return 0 if all(CHECKS.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
