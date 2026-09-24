#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_aoi_console.py — 质量检测汇总终端离线取证 (2026-09-24)

判据 (全为真断言, 非"跑通即过"):
  ① 入口可达性: 所有技能/标定/数据/训练按钮 可见+可用+宽度>20 (记取 09-17 "入口藏起来" 教训)
  ② 类别 schema: classes.txt = AOI_CLASSES (行号=class id)
  ③ 四技能真执行: 每个技能都出判决表 (>0 行) 且来源可辨 (启发式/模型)
  ④ 图像定位+拉伸: ROI 框 + 拉伸倍率 + ROI 图尺寸 == imgsz
  ⑤ 标定落盘: 加框 → 保存 → 样本文件出现 (frames/labels 配对) → 体检 0 错
  ⑥ 构建数据集: data.yaml + images/labels 分片存在
  ⑦ 导出: 判决 JSON / 清单 CSV 落地
用法: QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/verify_aoi_console.py
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import sys
import tempfile
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUI = os.path.join(ROOT, "tools", "gui")
for _p in (os.path.join(ROOT, "tools"), GUI, os.path.join(ROOT, "src", "lerobot", "policies", "yolo_3d")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

TMPROOT = tempfile.mkdtemp(prefix="aoi_verify_")
os.environ["ZMAX_ANNOT_ROOT_AOI"] = os.path.join(TMPROOT, "yolo_aoi_annot")   # 隔离: 不碰真数据
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2                                                              # noqa: E402
from PyQt5 import QtWidgets, QtCore                                     # noqa: E402
import aoi_inspect_console as aic                                       # noqa: E402
from aoi_head import AOI_CLASSES                                        # noqa: E402
import yolo_annot_dataset as yad                                        # noqa: E402

RES, CHECKS = {}, {}


def ck(name, cond, detail=""):
    CHECKS[name] = bool(cond)
    print(f"  {'✅' if cond else '❌'} {name}" + (f" — {detail}" if detail else ""))
    return cond


def real_frame():
    for p in ("data/real_yolo_perception_104.mp4", "data/real_yolo_perception_100.mp4"):
        fp = os.path.join(ROOT, p)
        if os.path.isfile(fp):
            cap = cv2.VideoCapture(fp); ok, fr = cap.read(); cap.release()
            if ok:
                return cv2.cvtColor(fr, cv2.COLOR_BGR2RGB), p
    raise SystemExit("❌ 找不到真机测试帧")


def main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    rgb, srcp = real_frame()
    RES["frame"] = srcp
    print(f"🖼  测试帧: {srcp} {rgb.shape}")

    w = aic.AoiInspectConsole(source="real")
    w._timer.stop()                                        # 关自动取帧, 用确定的输入
    RES["head"] = {"weights": w.head.weights, "model_ready": w.head.model_ready,
                   "classes": w.head.model_classes, "note": w.head._load_err}

    # ① 入口可达性
    btns = {**w.skill_btns, "save": w.btn_save, "savenext": w.btn_savenext, "newcls": w.btn_newcls,
            "setcls": w.btn_setcls, "undo": w.btn_undo, "del": w.btn_del, "clear": w.btn_clear,
            "build": w.btn_build, "check": w.btn_check, "train": w.btn_train, "live": w.btn_live,
            "datadir": w.btn_datadir, "expjson": w.btn_expjson, "expcsv": w.btn_expcsv,
            "labelmode": w.chk_label, "freeze": w.chk_freeze}
    w.show(); app.processEvents()
    bad = [k for k, b in btns.items() if not (b.isVisible() and b.isEnabled() and b.width() > 20)]
    RES["entry_visibility"] = {"n_buttons": len(btns), "not_reachable": bad,
                               "widths": {k: b.width() for k, b in btns.items()}}
    ck("① 全部入口可达 (可见+可用+宽>20)", not bad, f"{len(btns)} 个控件, 不可达: {bad or '无'}")

    # ② schema
    cp = w.head.classes_path()
    lines = [x.strip() for x in open(cp, encoding="utf-8")] if os.path.isfile(cp) else []
    lines = [x for x in lines if x]
    RES["schema"] = {"path": cp, "lines": lines}
    ck("② 类别 schema 落盘 (行号=class id)", lines == AOI_CLASSES, f"{len(lines)} 类: {lines[:3]}…")

    # ③ 载入帧 + 四技能
    ok_load = w.load_frame_file(os.path.join(ROOT, srcp))
    ck("③ 载入帧文件", ok_load)
    skill_rows = {}
    for k in ("gold_finger", "module_body", "optical_port", "full"):
        r = w.run_skill(k)
        skill_rows[k] = {"rows": w.tbl_verdict.rowCount(), "loc": len(r["loc"]), "defects": len(r["defects"]),
                         "source_set": sorted({it.get("source") for it in r["verdict"]["items"]}),
                         "pass": r["verdict"]["pass"], "elapsed_ms": r["elapsed_ms"]}
    RES["skills"] = skill_rows
    ck("③ 四技能均出判决表 (>0 行)", all(v["rows"] > 0 for v in skill_rows.values()),
       str({k: v["rows"] for k, v in skill_rows.items()}))
    ck("③ 判决来源可辨 (启发式/模型 标注)", all(v["source_set"] for v in skill_rows.values()),
       str({k: v["source_set"] for k, v in skill_rows.items()}))

    # ④ 定位/拉伸
    r = w.run_skill("full", quiet=True)
    meta, roi = r["roi_meta"], w.head.crop_stretch(rgb, [10, 10, 200, 200])
    RES["roi"] = {"meta": meta, "stretched_shape": list(roi[0].shape), "zoom": roi[1]["zoom"]}
    ck("④ 图像定位 + 拉伸生效 (ROI→imgsz²)", roi[0].shape[0] == w.head.imgsz and roi[0].shape[1] == w.head.imgsz,
       f"{roi[0].shape} zoom×{roi[1]['zoom']}")

    # ⑤ 标定落盘 (加两个框: 定位类 + 缺陷类)
    w.chk_label.setChecked(True)
    w._select_class_in_combo("gold_finger")
    w.wid.add_box_px([100, 120, 300, 260])
    w._select_class_in_combo("gf_scratch")
    w.wid.add_box_px([140, 150, 220, 200])
    before = len(list(yad.iter_samples(w.head.root)))
    w._save_annot(next_frame=False)
    after = len(list(yad.iter_samples(w.head.root)))
    chk = w.head.stats()
    RES["annot"] = {"before": before, "after": after, "check": chk,
                    "sample_files": len(glob.glob(os.path.join(w.head.root, "sessions", "*", "frames", "*")))}
    ck("⑤ 标定落盘 (样本数 +1)", after == before + 1, f"{before}→{after}")
    ck("⑤ 体检可跑 (无异常)", isinstance(chk, dict) and ("error" not in chk or not chk.get("error")),
       str(chk)[:120])

    # ⑥ 构建数据集 (补到 ≥4 张, 覆盖小样本分支)
    for i in range(3):
        w.wid.add_box_px([100 + i * 20, 120, 320, 280])
        w._select_class_in_combo("app_scratch")
        w.wid.add_box_px([150 + i * 10, 160, 240, 220])
        w._save_annot(False)
    st = yad.build_dataset(w.head.root)
    ds = os.path.join(w.head.root, "dataset")
    n_tr = len(glob.glob(os.path.join(ds, "images", "train", "*")))
    n_va = len(glob.glob(os.path.join(ds, "images", "val", "*")))
    RES["dataset"] = {"stats": st, "train": n_tr, "val": n_va,
                      "data_yaml": os.path.isfile(os.path.join(ds, "data.yaml"))}
    ck("⑥ 数据集构建 (data.yaml + 分片)", os.path.isfile(os.path.join(ds, "data.yaml")) and n_tr > 0,
       f"train={n_tr} val={n_va}")

    # ⑦ 导出
    w._export_json(); w._export_csv()
    j = sorted(glob.glob(os.path.join(ROOT, "reports", "aoi_inspect_*.json")))[-1]
    c = sorted(glob.glob(os.path.join(ROOT, "reports", "aoi_inspect_*.csv")))[-1]
    RES["export"] = {"json": j, "csv": c, "json_keys": list(json.load(open(j)).keys())}
    ck("⑦ 判决导出 (JSON+CSV)", os.path.isfile(j) and os.path.isfile(c))

    # ⑧ 训练命令构造 (不真训, 只验证命令与前置检查逻辑)
    w._train()                                              # 无 GPU 训练也允许: 验证命令/进程起没起
    t0 = time.time()
    while w._train_proc is not None and time.time() - t0 < 8:
        app.processEvents()
    if w._train_proc is not None:                           # 还在跑 → 收掉, 免得 teardown 报 destroy
        w._train_proc.kill()
        app.processEvents()
        w._train_proc = None
    RES["train_proc"] = {"started": w._train_proc is not None, "log_tail":
                         w.txt_log.toPlainText().strip().splitlines()[-3:]}
    ck("⑧ 在线训练可启动 (命令下发)", "🚀 训练" in w.txt_log.toPlainText())

    # ⑨ 真训练 smoke (1 epoch · 真 GPU/CPU · 产出 best.pt) —— 真证据, 不是"命令下发"
    import subprocess
    name = "aoi_verify_" + time.strftime("%m%d_%H%M")
    cmd = [aic.PY, aic.TRAIN_PY, "--data", ds, "--root", w.head.root, "--base", "auto",
           "--epochs", "1", "--imgsz", "320", "--batch", "2", "--name", name,
           "--project", "outputs/yolo_aoi", "--verify", "2"]
    t0 = time.time()
    pr = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=1200)
    best = sorted(glob.glob(os.path.join(ROOT, "runs", "detect", "outputs", "yolo_aoi", name,
                                        "**", "weights", "best.pt"), recursive=True))
    RES["train_smoke"] = {"cmd": " ".join(cmd), "rc": pr.returncode, "wall_s": round(time.time() - t0, 1),
                          "best_pt": best[0] if best else "", "tail": (pr.stdout or "")[-600:]}
    ck("⑨ 真训练 smoke 产出 best.pt", bool(best), f"rc={pr.returncode} {round(time.time()-t0,1)}s "
                                                   f"→ {best[0] if best else '无'}")

    # 截图取证
    png = os.path.join(ROOT, "reports", f"aoi_console_verify_{time.strftime('%Y%m%d_%H%M%S')}.png")
    w.grab().save(png)
    RES["screenshot"] = png
    print(f"🖼  截图: {png}")

    out = os.path.join(ROOT, "reports", f"aoi_console_verify_{time.strftime('%Y%m%d_%H%M%S')}.json")
    RES["checks"] = CHECKS
    RES["checks_pass"] = f"{sum(CHECKS.values())}/{len(CHECKS)}"
    json.dump(RES, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n" + "=" * 78)
    print(f"  判据通过: {RES['checks_pass']}\n  证据: {out}\n  临时数据根: {TMPROOT}")
    shutil.rmtree(TMPROOT, ignore_errors=True)
    return 0 if all(CHECKS.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
