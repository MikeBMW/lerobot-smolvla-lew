#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_v13_exposure.py — 离线验证 **表面 v13「曝光/增益运行时可调」**, 不接真相机。

老倪 2026-09-30: 「修改工控机的代码, 调曝光度」。

为什么不是"改个常量再部署": 原来曝光只在**启动时**按常量设一次 ⇒ 现场每试一个值都要
改代码 + 重部署 + 重启(实测起服务 ~90s) ⇒ 试参数根本试不动。v13 把它变成**一次 HTTP**。

断言(硬证据, 全部离线可复现):
  ① GET  /exposure            → 200 · 报 us/gain/来源/文件/版本 · 只读不动相机
  ② POST /exposure?us=&gain=  → 200 · ok=true · us_ok/gain_ok
  ③ **相机 API 真收到**: 桩记录到 ("ExposureTime", 20000.0) 与 ("Gain", 0.0)   ← 核心证据
  ④ 落盘 surface_exposure.json(值 + 时间 + 来源) ⇒ **重启不丢**
  ⑤ 重启模拟: 重新读文件得到 20000/0.0
  ⑥ POST 无参 → 400(不瞎猜)
  ⑦ 相机未开时 → 回执**如实**说"待首次取帧生效", 不假装 ok
  ⑧ 改参数会让内存帧失效(否则"新参数配旧帧", 看着改了其实没改)
  ⑨ 模型输入口径未变: CANONICAL_W 仍 1280(改"人看的/参数"绝不动"模型吃的")
  ⑩ GetFloatValue 不存在是本机事实 ⇒ 真值只能靠图像实测(测试里明写这句话, 别以后又去找)
用法: cd ~/aoi_v4 && /home/ubuntu/zmax/gui-venv311/bin/python test_v13_exposure.py
"""
import json
import os
import shutil
import sys
import types

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_stub"))
sys.path.insert(0, HERE)
TMP = os.path.join(HERE, "_v13test_tmp")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)
os.environ["TEMP"] = os.environ["TMP"] = TMP

import test_v5_offline as T5            # noqa: E402  复用桩(SciCam 底层 + 合成图机制)

import cv2                              # noqa: E402

yd = types.ModuleType("yolo_detector")


class YoloDetector:
    def detect(self, path, detect_type=None):
        return {"detections": [], "saved_incoming": "_stub.png"}


yd.YoloDetector = YoloDetector
sys.modules["yolo_detector"] = yd

import cam_surface_10083_work_v13 as M   # noqa: E402

FLT = []          # [(name, value)] —— 相机 API 到底收到了什么
ok = True


def chk(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print("  %s %s%s" % ("✅" if cond else "❌", name, (" — " + str(detail)) if detail else ""))
    return bool(cond)


class DevRec:
    """记录器: 桩的 __getattr__ 返回 lambda 会把参数丢掉 ⇒ 换成能记账的。"""

    def __getattr__(self, n):
        if n == "SciCam_SetFloatValue":
            def f(name, val):
                FLT.append((str(name), float(val)))
                return 0                     # 0 = SCI_CAMERA_OK
            return f
        return lambda *a, **k: 0


def main():
    bgr = np.full((2048, 2448, 3), 40, np.uint8)
    cv2.rectangle(bgr, (300, 1100), (2100, 1300), 255, -1)      # 一根亮条(合成)
    print("══ 桩相机 + 合成图 %dx%d · 版本=%s ══" % (bgr.shape[1], bgr.shape[0], M.VERSION))
    T5._wire(M, bgr)
    M.m_Device = DevRec()               # 换成记录器(在 _wire 之后覆盖)
    M.ensure_camera = lambda: True
    M.SAVE_ROOT_DIR = TMP
    if os.path.exists(M._EXPO_FILE):
        os.remove(M._EXPO_FILE)
    c = M.app.test_client()

    # ① 只读
    r = c.get("/exposure")
    j = r.get_json() or {}
    chk("① GET /exposure → 200", r.status_code == 200 and j.get("code") == 200,
        "us=%s gain=%s src=%s ver=%s" % (j.get("us"), j.get("gain"), j.get("src"), j.get("version")))
    chk("①b 版本=v13", j.get("version") == "v13", j.get("version"))
    chk("①c 报出落盘文件路径", bool(j.get("file")), j.get("file"))

    # ⑦ 相机未开: 如实回执
    M._cam_open = False
    r = c.post("/exposure?us=30000&gain=0")
    j7 = r.get_json() or {}
    chk("⑦ 相机未开 → 如实说明(不假装 ok)", (not j7.get("ok")) and "首次取帧" in str(j7.get("reason")),
        "ok=%s reason=%s" % (j7.get("ok"), j7.get("reason")))

    # ②③④⑤ 相机已开: 真设 + 记账 + 落盘
    M._cam_open = True
    FLT.clear()
    r = c.post("/exposure?us=20000&gain=0")
    j2 = r.get_json() or {}
    chk("② POST /exposure?us=20000&gain=0 → 200/ok", r.status_code == 200 and j2.get("ok"),
        "us_ok=%s gain_ok=%s reopened=%s" % (j2.get("us_ok"), j2.get("gain_ok"), j2.get("reopened")))
    got_us = [v for n, v in FLT if n == "ExposureTime"]
    got_gn = [v for n, v in FLT if n == "Gain"]
    chk("③ 相机 API 真收到 ExposureTime=20000", 20000.0 in got_us, "实际收到 %s" % got_us[-4:])
    chk("③b 相机 API 真收到 Gain=0", 0.0 in got_gn, "实际收到 %s" % got_gn[-4:])
    fe = json.load(open(M._EXPO_FILE, encoding="utf-8")) if os.path.exists(M._EXPO_FILE) else {}
    chk("④ 落盘 surface_exposure.json", fe.get("us") == 20000.0 and fe.get("gain") == 0.0,
        json.dumps(fe, ensure_ascii=False)[:120])
    f2 = M._read_expo_file()
    chk("⑤ 重启模拟: 重新读文件得 20000/0.0", f2 and f2["us"] == 20000.0 and f2["gain"] == 0.0,
        json.dumps(f2, ensure_ascii=False) if f2 else "None")
    chk("⑤b 模块内存变量也同步", M.EXPOSURE_US == 20000.0 and M.GAIN_DB == 0.0,
        "us=%s gain=%s src=%s" % (M.EXPOSURE_US, M.GAIN_DB, M.EXPO_SRC))

    # ⑧ 内存帧失效
    with M._MEM_LOCK:
        M._MEM.update({"crop": b"xx", "origin": b"xx", "judge": b"xx", "ts": 123.0})
    c.post("/exposure?us=25000")
    with M._MEM_LOCK:
        cleared = M._MEM.get("crop") is None and M._MEM.get("origin") is None
    chk("⑧ 改参数后内存帧被清(不拿旧帧糊弄)", cleared)

    # ⑥ 无参
    r = c.post("/exposure")
    chk("⑥ POST /exposure 无参 → 400", r.status_code == 400, r.get_json())

    # ⑨ 模型输入口径未变
    chk("⑨ CANONICAL_W 仍 1280(模型吃的那张没动)", M.CANONICAL_W == 1280, M.CANONICAL_W)

    # ⑩ 事实记录
    print("  ℹ️ ⑩ 本 SDK 无 GetFloatValue ⇒ 真值只能靠图像实测: GET /picture?kind=origin&grab=1 后看 /crop_info")

    print("\n%s  (共 12 项断言)" % ("★ 全部通过 ✓" if ok else "✗ 有失败项"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
