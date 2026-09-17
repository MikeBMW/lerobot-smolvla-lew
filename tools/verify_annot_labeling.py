# -*- coding: utf-8 -*-
"""取证: 标定功能 (画框标注) 全链路
① 控件坐标映射: 拖框 → 原始帧像素坐标 (含 180°/90° 旋转窗的换算)
② 标定会话落盘: 图片/YOLO 标签/annotations.jsonl/session.json/meta.json/classes.txt, 两窗同步
③ 数据集构建 + 体检 (含"注入坏标签 → 体检必须抓出来"的反向验证)
④ (--real) 用真机 D405 帧跑一遍 ①②③: 真机帧 + 真落盘
跑法: DISPLAY=:0 QT_QPA_PLATFORM=offscreen gui-venv311/bin/python 本文件 [--real]
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

import numpy as np                                                            # noqa: E402
from PyQt5 import QtCore, QtGui, QtWidgets                                    # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
import yolo_annot_dataset as yad                                              # noqa: E402
import yolo_label_widget as ylw                                               # noqa: E402
import yolo_input_viewer as yiv                                               # noqa: E402

ok = True
REAL = "--real" in sys.argv


def chk(tag, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(f"  {'✅' if cond else '❌'} {tag} {detail}")


def pump(sec=0.15):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents()
        time.sleep(0.01)


print("① 控件坐标映射 (拖框 → 原始帧像素坐标; 旋转窗要换算回来)")
W, H = 640, 480
frame = np.zeros((H, W, 3), np.uint8)
frame[200:260, 280:400] = (0, 220, 180)          # 一块"目标" (原始帧坐标 x280-400, y200-260)
# 纯函数往返
for deg in (0, 90, 180, 270):
    a = ylw.map_pt(100, 50, deg, W, H)
    b = ylw.unmap_pt(a[0], a[1], deg, W, H)
    chk(f"map/unmap 往返 {deg}°", abs(b[0] - 100) < 1e-6 and abs(b[1] - 50) < 1e-6, f"{a} → {b}")
    rb = ylw.map_box((280, 200, 400, 260), deg, W, H)
    ub = ylw.unmap_box(rb, deg, W, H)
    chk(f"box 往返 {deg}°", all(abs(p - q) < 1e-6 for p, q in zip(ub, (280, 200, 400, 260))), f"{ub}")
# 真控件: 在控件上"拖"出目标 → 断言得到的框 ≈ 目标框
for deg in (0, 180, 90):
    w = ylw.YoloLabelWidget(rot_deg=deg, editable=True)
    w.resize(640, 480)
    w.set_frame_rgb(frame)
    w.set_current_class("optical_module")
    w.show()
    pump(0.2)
    s, ox, oy, dw, dh = w._geom()
    p1 = ylw.map_pt(280, 200, deg, W, H)         # 目标框左上角在显示坐标系里的位置
    p2 = ylw.map_pt(400, 260, deg, W, H)
    q1 = QtCore.QPoint(int(ox + p1[0] * s), int(oy + p1[1] * s))
    q2 = QtCore.QPoint(int(ox + p2[0] * s), int(oy + p2[1] * s))
    QtWidgets.QApplication.sendEvent(w, QtGui.QMouseEvent(
        QtCore.QEvent.MouseButtonPress, q1, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier))
    QtWidgets.QApplication.sendEvent(w, QtGui.QMouseEvent(
        QtCore.QEvent.MouseMove, q2, QtCore.Qt.NoButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier))
    QtWidgets.QApplication.sendEvent(w, QtGui.QMouseEvent(
        QtCore.QEvent.MouseButtonRelease, q2, QtCore.Qt.LeftButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier))
    pump(0.1)
    bx = w.boxes_px()
    got = bx[0][:4] if bx else None
    exp = (280, 200, 400, 260)
    good = got is not None and all(abs(a - b) <= 3 for a, b in zip(got, exp))
    chk(f"控件拖框 {deg}° → 框落在原始帧目标上 (±3px)", good, f"拖出 {got} vs 目标 {exp}")
    if good:
        chk(f"  {deg}° 框类别/尺寸正确", bx[0][4] == "optical_module"
            and abs((got[2] - got[0]) - 120) <= 4 and abs((got[3] - got[1]) - 60) <= 4,
            f"类别={bx[0][4]} 尺寸={got[2]-got[0]:.0f}x{got[3]-got[1]:.0f}")
    w.close()

print("② 标定会话落盘 (窗口集成: 标定模式 → 框 → 保存)")
tmp = tempfile.mkdtemp(prefix="annot_ui_")
os.environ["ZMAX_ANNOT_ROOT"] = tmp
yiv.ANNOT_ROOT = tmp
yiv._RemoteChain.ensure = classmethod(lambda cls: "mock (取证: 不拉真链路)")
v = yiv.YoloInputViewer(None, module=None, source="real")
v.resize(1320, 760)
v.show()
pump(0.3)
print("②a 入口可达性 (根因取证: 「标定按钮怎么没有找到?」= 勾选框被自己也藏了)")
v.chk_annot.show()                                  # 模拟真实窗口 (offscreen 下 isVisible 需窗口已 show)
pump(0.2)
_btns = {b.text(): b for b in v.findChildren(QtWidgets.QPushButton)}
chk("默认状态: 「✏️ 标定模式」勾选框可见且可用 (标定唯一入口必须常显)",
    v.chk_annot.isVisible() and v.chk_annot.isEnabled(), f"| visible={v.chk_annot.isVisible()}")
_early = [t for t in v._ANNOT_BTNS if t in _btns and _btns[t].isVisible()]
chk("默认状态: 标定/数据按钮隐藏 (勾上标定模式后才出现)", not _early, f"| 意外可见: {_early}")
chk("默认状态: 常显提示告诉工程师下一步点哪", v.lbl_annot_hint.isVisible() and "标定模式" in v.lbl_annot_hint.text(),
    f"| {v.lbl_annot_hint.text()[:40]}")
v.chk_annot.setChecked(True)              # 进标定模式 (冻结)
pump(0.2)
_miss = [t for t in v._ANNOT_BTNS
         if t not in _btns or not _btns[t].isVisible() or _btns[t].width() < 20]
chk("标定模式打开后 12 个按钮全部可见且未塌缩 (宽>20px)", not _miss, f"| 缺/塌: {_miss}")
_mock_meta = os.path.join(tmp, "live_frame.json")
with open(_mock_meta, "w") as f:          # 冻结后再喂帧, 且把 meta 指到 mock → 记录可确定性断言
    json.dump({"ok": True, "src": "uvc", "device": "/dev/video2 Intel(R) RealSense(TM) 8086:0b5b sn=255323073856",
               "w": W, "h": H, "seq": 42, "age_s": 0.4, "jpeg_bytes": 1000, "encode_ms": 3.0,
               "quality": 70, "server_fps": 10.0, "server": "probe", "stale": False}, f)
yiv.LIVE_META = _mock_meta
pump(0.2)
v._rgb = frame.copy()                     # 直接喂一帧 (不走链路; 冻结中不会被实时帧顶掉)
v._paint_frames()
chk("标定模式: 画面冻结 + 左窗可编辑", v._frozen and v.w_orig._editable)
v.w_orig.add_box_px((280, 200, 400, 260), "optical_module")
v.cb_cls.setCurrentText("fiber_connector")     # 新类别 (手输) → 应写进 classes.txt
pump(0.2)
v.w_orig.add_box_px((100, 60, 180, 120), "fiber_connector")
pump(0.1)
chk("两窗框同步 (旋转窗能看到同一组框)",
    [b["box"] for b in v.w_rot.boxes()] == [b["box"] for b in v.w_orig.boxes()],
    f"左 {len(v.w_orig.boxes())} 个 / 右 {len(v.w_rot.boxes())} 个")
rec = v._save_annot()
chk("保存返回记录", bool(rec) and rec["n_boxes"] == 2, f"{os.path.basename(rec['image']) if rec else None}")
if rec:
    img_p, lbl_p = rec["image"], rec["label"]
    chk("图片落盘 (sessions/<会话>/frames/)", os.path.isfile(img_p) and os.path.getsize(img_p) > 500,
        f"{img_p.replace(tmp, '<root>')} {os.path.getsize(img_p)} B")
    lines = open(lbl_p).read().strip().splitlines()
    chk("YOLO 标签 2 行且字段=5", len(lines) == 2 and all(len(l.split()) == 5 for l in lines),
        f"| {lines}")
    # 手算核对第一条 (280,200,400,260)/640x480 → cls cx cy w h
    p = lines[0].split()
    exp = (0, (280 + 400) / 2 / 640, (200 + 260) / 2 / 480, 120 / 640, 60 / 480)
    good = (int(p[0]) == exp[0] and all(abs(float(p[i + 1]) - exp[i + 1]) < 1e-4 for i in range(4)))
    chk("标签数值 == 手算归一化值", good, f"| {p} vs {[round(x,5) for x in exp]}")
    chk("新类别已进 classes.txt 且 id 连续", yad.load_classes(tmp) == ["optical_module", "fiber_connector"],
        f"| {yad.load_classes(tmp)}")
    meta = json.load(open(os.path.join(tmp, "sessions", rec["session"], "session.json")))
    chk("会话元信息含设备身份/标定员", "RealSense" in (meta.get("device") or "") and meta.get("annotator"),
        f"| device={str(meta.get('device'))[:40]}… annotator={meta.get('annotator')}")
    recs = [json.loads(l) for l in open(os.path.join(tmp, "annotations.jsonl")) if l.strip()]
    chk("annotations.jsonl 追加了完整记录 (像素框+设备+帧号)",
        len(recs) == 1 and recs[0]["boxes"][0]["box_px"] == [280.0, 200.0, 400.0, 260.0]
        and recs[0]["seq"] == 42, f"| box_px={recs[0]['boxes'][0]['box_px'] if recs else None} seq={recs[0]['seq'] if recs else None}")
    mm = json.load(open(os.path.join(tmp, "meta.json")))
    chk("meta.json 记录会话与张数", mm["n_images"] == 1 and mm["sessions"][0]["name"] == rec["session"],
        f"| n_images={mm['n_images']} classes={mm.get('classes')}")
    chk("状态行显示数据根/会话/已存张数",
        v.annot_root in v.st.text() and rec["session"] in v.st.text())
# "保存并下一帧" 在冻结下应取到新帧
v._save_next()
pump(0.3)
print("④ 快捷键 (Enter 保存 / N 下一帧 / F 冻结) 已绑定 + 输入框有焦点时不抢键")
chk("快捷键对象齐 4 个 (Enter/Return/N/F)", len(v._shortcuts) == 4,
    f"| {[k for k, _kind, _s in v._shortcuts]}")
_n0 = v._n_saved
_sc_save = [s for k, kind, s in v._shortcuts if kind == "save"][0]
vw = QtWidgets.QApplication.focusWidget()
if isinstance(vw, QtWidgets.QLineEdit):
    vw.clearFocus()
v.setFocus()
pump(0.1)
v._save_annot  # noqa: B018  (快捷键走的就是它)
_sc_save.activated.emit()
pump(0.3)
chk("触发保存快捷键 → 真存下一张", v._n_saved == _n0 + 1, f"| 已存 {v._n_saved}")
guard = v._shortcut_guard("save")
v.ed_who.setFocus()
pump(0.05)
_n1 = v._n_saved
guard()
chk("标定员输入框有焦点 → 快捷键不抢键 (不误存)", v._n_saved == _n1, f"| 已存 {v._n_saved}")
print("③ 数据集构建 + 体检 (含反向验证: 坏标签必须被抓出来)")
st = yad.build_dataset(tmp, val_ratio=0.5, seed=0)
yml = os.path.join(tmp, "dataset", "data.yaml")
chk("data.yaml 生成", os.path.isfile(yml))
txt = open(yml).read()
chk("data.yaml 含 train/val/nc/names 且 nc 与类别表一致",
    all(k in txt for k in ("train:", "val:", "nc: 2", "names:")) and "optical_module" in txt,
    "| " + " ".join(txt.splitlines()[-3:]))
chk("划分可复现且 val 非空", st["n_train"] + st["n_val"] >= 1 and st["n_val"] >= 1, f"| {st}")
r = yad.check_dataset(tmp, strict=True)
chk("体检通过 (干净数据)", not r["errors"], f"| 图 {r['n_images']} 框 {r['n_boxes']} 类别分布 {r['per_class']}")
bad = None
for s in yad.iter_samples(tmp):
    bad = s["label"]
    break
orig = open(bad).read()
open(bad, "w").write("9 0.5 0.5 0.4 0.25\n0 2.0 0.5 0.1 0.1\n")   # 类别越界 + 中心越界
r2 = yad.check_dataset(tmp, strict=True)
open(bad, "w").write(orig)
chk("体检能抓出坏标签 (反向验证)", len(r2["errors"]) >= 2, f"| {r2['errors'][:2]}")
r3 = yad.check_dataset(tmp, strict=True)
chk("恢复后再次体检通过 (0 误报)", not r3["errors"])
print("   目录结构:")
for dp, dn, fn in os.walk(tmp):
    d = dp.replace(tmp, "<root>")
    if fn or not dn:
        print(f"     {d}/ {sorted(fn)[:4]}{' …' if len(fn) > 4 else ''}")
loc = len([l for l in open(os.path.join(tmp, "annotations.jsonl"))])
print(f"   annotations.jsonl 行数 = {loc}")
v.close()
if not REAL:
    shutil.rmtree(tmp, ignore_errors=True)
else:
    print(f"   数据保留在 {tmp}")

print("\n结论:", "✅ 全部通过" if ok else "❌ 有不通过项")
sys.exit(0 if ok else 1)
