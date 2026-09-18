# -*- coding: utf-8 -*-
"""取证: 仿真源(metaworld)也要能看画面 + 能标定 + 数据分开存
① 仿真源真渲染帧 (480x480, 非纯色) 进窗口, 两窗都有
② 仿真模式下能进标定 → 拖框 → 保存: 落 **仿真数据根** (classes=peg/hole/hand, 会话带 sim, 设备标 mujoco)
③ 仿真数据根能构建/体检 (data.yaml nc=3, names=peg/hole/hand)
④ 真机数据根**零污染** (张数不变)
跑法: DISPLAY=:0 QT_QPA_PLATFORM=offscreen gui-venv311/bin/python 本文件
"""
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DISPLAY", ":0")
REAL_ROOT = tempfile.mkdtemp(prefix="annot_real_")
SIM_ROOT = tempfile.mkdtemp(prefix="annot_sim_")
os.environ["ZMAX_ANNOT_ROOT"] = REAL_ROOT
os.environ["ZMAX_ANNOT_ROOT_SIM"] = SIM_ROOT

import numpy as np                                                            # noqa: E402
from PyQt5 import QtWidgets                                                   # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
import yolo_annot_dataset as yad                                              # noqa: E402
import yolo_input_viewer as yiv                                               # noqa: E402

ok = True


def chk(tag, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(f"  {'✅' if cond else '❌'} {tag} {detail}")


def pump(sec):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents()
        time.sleep(0.02)


print("① 仿真源: metaworld 渲染帧进窗口 + 两窗都有画面")
v = yiv.YoloInputViewer(None, module=None, source="sim")
v.resize(1320, 760)
v.show()
t0 = time.time()
while time.time() - t0 < 60 and v._rgb is None:
    pump(0.2)
chk("拿到仿真帧", v._rgb is not None, f"| shape={None if v._rgb is None else v._rgb.shape}")
if v._rgb is not None:
    chk("是真渲染帧 (480x640+非纯色, 对齐真机 D405 分辨率)", v._rgb.shape[:2] == (480, 640) and float(v._rgb.std()) > 5,
        f"| shape={v._rgb.shape[:2]} std={float(v._rgb.std()):.1f} 均值={float(v._rgb.mean()):.0f}")
chk("左窗+右窗都有画面", v.w_orig.pixmap() is not None and not v.w_orig.pixmap().isNull()
    and v.w_rot.pixmap() is not None and not v.w_rot.pixmap().isNull(),
    f"| 左 {v.w_orig.pixmap().width()}x{v.w_orig.pixmap().height()} 右 {v.w_rot.pixmap().width()}x{v.w_rot.pixmap().height()}")
print("② 数据根随源切换 (真机 / 仿真 分开存, 别混训)")
chk("仿真模式 → 仿真数据根", v.annot_root == SIM_ROOT, f"| {v.annot_root}")
chk("仿真类别表 = peg/hole/hand", yad.load_classes(SIM_ROOT) == ["peg", "hole", "hand"],
    f"| {yad.load_classes(SIM_ROOT)}")
chk("数据行标注『🧪仿真数据根』", "🧪仿真" in v.lbl_data.text(), f"| {v.lbl_data.text()[:80]}")
print("③ 仿真模式标定: 冻结 → 拖框 → 保存 (落仿真根)")
v.chk_annot.setChecked(True)
pump(0.3)
chk("标定模式进入 (冻结+可编辑)", v._frozen and v.w_orig._editable)
v.w_orig.add_box_px((150, 250, 260, 330), "peg")
v.w_orig.add_box_px((300, 300, 380, 380), "hole")
pump(0.2)
chk("两窗框同步", [b["box"] for b in v.w_rot.boxes()] == [b["box"] for b in v.w_orig.boxes()],
    f"| 左 {len(v.w_orig.boxes())} 右 {len(v.w_rot.boxes())}")
rec = v._save_annot()
chk("保存成功", bool(rec) and rec["n_boxes"] == 2, f"| {os.path.basename(rec['image']) if rec else None}")
if rec:
    chk("落盘在**仿真**数据根 (不是真机根)", rec["image"].startswith(SIM_ROOT), f"| {rec['image'].replace(SIM_ROOT,'<sim>')}")
    chk("会话名带 sim 标记", "sim" in rec["session"], f"| {rec['session']}")
    chk("记录里设备标为 mujoco 渲染 (不是真机相机)",
        any(k in str(rec.get("device", "")).lower() for k in ("mujoco", "渲染")), f"| device={rec.get('device')}")
    chk("来源标为仿真源", "sim" in str(rec.get("src", "")), f"| src={rec.get('src')}")
    lines = open(rec["label"]).read().strip().splitlines()
    chk("标签 2 行 + 类别 id 在表内", len(lines) == 2 and all(int(float(l.split()[0])) < 3 for l in lines),
        f"| {lines}")
print("④ 仿真数据根构建 + 体检")
st = yad.build_dataset(SIM_ROOT, val_ratio=0.5, seed=0)
txt = open(os.path.join(SIM_ROOT, "dataset", "data.yaml")).read()
chk("data.yaml nc=3 + names=peg/hole/hand", "nc: 3" in txt and all(n in txt for n in ("peg", "hole", "hand")),
    "| " + " ".join(txt.splitlines()[-4:]))
r = yad.check_dataset(SIM_ROOT, strict=True)
chk("仿真数据集体检通过", not r["errors"], f"| 图 {r['n_images']} 框 {r['n_boxes']} 分布 {r['per_class']}")
yad.ensure_layout(REAL_ROOT)                    # 真机根初始化 (正常由窗口在真机模式构造时做)
n_real = len(list(yad.iter_samples(REAL_ROOT)))
chk("真机数据根零污染 (仿真标注没写进真机根)", n_real == 0, f"| 真机根张数={n_real}")
chk("真机根类别 = peg (与 CLASS_MAP 对齐, 可接感知链; 旧 optical_module 已废弃)",
    yad.load_classes(REAL_ROOT) == ["peg"], f"| {yad.load_classes(REAL_ROOT)}")
v.close()
shutil.rmtree(REAL_ROOT, ignore_errors=True)
shutil.rmtree(SIM_ROOT, ignore_errors=True)
print("\n结论:", "✅ 全部通过" if ok else "❌ 有不通过项")
sys.exit(0 if ok else 1)
