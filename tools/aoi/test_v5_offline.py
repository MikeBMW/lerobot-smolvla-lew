#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_v5_offline.py — 离线验证 v5 的两个新性质(不接真相机):

  老倪 2026-09-27: 「不检测的时候，不用保存那么多图片；升级到工控机的程序到 v5」

  断言(两路各测一遍, 表面 10083 / 金手指 10082):
    ① POST /capture_detect(真检测) → 200 且**照旧落盘**(模型要读文件), 回执 {"code":200,"msg":"success"}
    ② GET /picture?grab=1(只看一眼/页面拍帧) → 200 有图, 且磁盘文件数**不增加**
    ③ 把 disk 上的图全删掉后, GET /picture 仍能出图 ⇒ 走内存(说明不落盘也能看)
    ④ GET /storage 报张数/占用/上限; POST /prune 按上限删旧图
    ⑤ GET /picture?grab=1&save=1 才写盘(显式要存)

  做法: 桩掉 SciCam SDK 的**底层**(Grab/GetAttribute/ConvertImage) + ensure_camera,
        让**真的 GrabAndSaveImage** 跑起来(这样才能验到 v5 的内存/落盘开关本身)。
用法: .venv-test/bin/python test_v5_offline.py
"""
import glob
import os
import shutil
import sys
import types

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
STUB = os.path.join(HERE, "_stub")
sys.path.insert(0, STUB)
sys.path.insert(0, HERE)

os.environ.setdefault("AOI_KEEP_CANON", "2")
os.environ.setdefault("AOI_KEEP_ORIGIN", "2")

import test_surface_v4_offline as T4      # noqa: E402  复用它的桩写入

T4.write_stubs()

import cv2                                 # noqa: E402


def _mk_img(h, w, tag):
    img = np.zeros((h, w, 3), np.uint8)
    img[:, :, 1] = np.linspace(0, 255, w, dtype=np.uint8)[None, :]
    img[h // 4:h // 2, w // 4:w // 2] = 210
    img[2:12, 2:12] = 255 if tag == "gold" else 0
    return img


def _wire(module, img):
    """把真 GrabAndSaveImage 需要的底层桩好: 相机/属性/图像缓冲。"""
    class Dev:
        def __getattr__(self, _n):
            return lambda *a, **k: 0
    module.m_Device = Dev()
    module.ensure_camera = lambda: True

    class _Attr:
        isComplete = 1
        payloadMode = 1

        class imgAttr:
            width = img.shape[1]
            height = img.shape[0]
            pixelType = 7
    module.SciCam_Payload_GetAttribute = lambda pp, attr: 0
    module.SciCam_Payload_GetImage = lambda pp, out: 0

    def _convert(attr, src, ttype, dst, size, flag):
        size.value = img.shape[0] * img.shape[1] * 3
        if dst is not None:
            dst[:] = img.tobytes()
        return 0
    module.SciCam_Payload_ConvertImage = _convert
    module.SciCam_Payload_GetAttribute = lambda pp, attr: 0

    # 属性对象用真的类, 但把尺寸换成我们的合成图
    real_attr_cls = None
    try:
        real_attr_cls = module.SCI_CAM_PAYLOAD_ATTRIBUTE
    except Exception:                                                     # noqa: BLE001
        pass
    if real_attr_cls is not None:
        a = real_attr_cls()
        a.isComplete = 1
        a.payloadMode = 1
        a.imgAttr.width, a.imgAttr.height, a.imgAttr.pixelType = img.shape[1], img.shape[0], 7
        module.SciCam_Payload_GetAttribute = lambda pp, attr=None: 0
        module._FAKE_ATTR = a
    return module


def _ntest(module, name, root):
    """对一个程序跑完整套断言。"""
    print("\n══ %s ══" % name)
    if os.path.isdir(root):
        shutil.rmtree(root, ignore_errors=True)
    os.makedirs(root, exist_ok=True)
    module.SAVE_ROOT_DIR = root

    # 真 GrabAndSaveImage 里读属性用的是它自己 new 出来的类 → 让类本身返回我们的尺寸
    if hasattr(module, "SCI_CAM_PAYLOAD_ATTRIBUTE"):
        pass
    img = _mk_img(2048, 2448, "gold" if "finger" in name else "surface")

    def _grab_ok(pp, *a, **k):
        return 0
    if hasattr(module, "SciCam_Payload_GetAttribute"):
        pass

    class _A:
        isComplete = 1
        payloadMode = 1

        class imgAttr:
            width = 2448
            height = 2048
            pixelType = 7

        def __init__(self):
            pass
    module.SCI_CAM_PAYLOAD_ATTRIBUTE = _A
    module.SciCam_Payload_GetAttribute = lambda pp, attr, *a, **k: 0
    module.SciCam_Payload_GetImage = lambda pp, out, *a, **k: 0

    def _convert(attr, src, ttype, dst, size, flag=True):
        size.value = 2048 * 2448 * 3
        if dst is not None:
            try:
                dst[:] = img.tobytes()
            except Exception:                                             # noqa: BLE001
                pass
        return 0
    module.SciCam_Payload_ConvertImage = _convert

    class Dev:
        def SciCam_Grab(self, pp, *a, **k):
            return 0

        def __getattr__(self, _n):
            return lambda *a, **k: 0
    module.m_Device = Dev()
    module.ensure_camera = lambda *a, **k: True

    c = module.app.test_client()
    try:
        module.PORT_TO_DETECT_TYPE["80"] = list(module.PORT_TO_DETECT_TYPE.values())[0]
    except Exception:                                                     # noqa: BLE001
        pass

    ok = True

    def nfiles():
        return len(glob.glob(os.path.join(root, "*")))

    # ① 真检测: 落盘 + 回执不变
    r = c.post("/capture_detect")
    j = r.get_json() or {}
    n1 = nfiles()
    print("  ① POST /capture_detect  → %s %s   落盘 %d 张" % (r.status_code, j, n1))
    ok &= r.status_code == 200 and j.get("code") == 200 and j.get("msg") == "success" and n1 >= 2

    # ② grab=1 不落盘
    before = nfiles()
    r = c.get("/picture?kind=origin&grab=1")
    after = nfiles()
    print("  ② GET /picture?grab=1   → %s %d 字节; 磁盘 %d→%d 张" % (r.status_code, len(r.data), before, after))
    ok &= r.status_code == 200 and len(r.data) > 1000 and after == before

    # ③ 清空磁盘后仍能出图(内存帧)
    for f in glob.glob(os.path.join(root, "*")):
        os.remove(f)
    r0 = c.get("/picture?kind=crop")            # 不带 grab, 也没有文件
    r1 = c.get("/picture?kind=crop&grab=1")     # 现抓一帧, 不落盘
    print("  ③ 磁盘清空后: /picture(无文件) → %s %d 字节 · grab=1 → %s %d 字节; 磁盘 %d 张"
          % (r0.status_code, len(r0.data), r1.status_code, len(r1.data), nfiles()))
    ok &= r1.status_code == 200 and len(r1.data) > 1000 and nfiles() == 0

    # ④ /storage + /prune
    r = c.get("/storage")
    js = r.get_json() or {}
    print("  ④ GET /storage          → %s 张数=%s 上限 canon/origin=%s/%s"
          % (r.status_code, js.get("files_total"), js.get("keep_canon"), js.get("keep_origin")))
    ok &= r.status_code == 200 and "files_total" in js
    c.get("/picture?kind=crop&grab=1&save=1")   # 显式落盘
    c.post("/capture_detect")
    c.post("/capture_detect")
    r = c.post("/prune")
    jp = r.get_json() or {}
    cnt = (jp.get("after") or {}).get("files_total")
    keep_max = js.get("keep_canon", 0) + js.get("keep_origin", 0)
    print("  ④ POST /prune           → %s 删了 %s 张, 剩 %s 张 (上限 canon+origin=%s)"
          % (r.status_code, jp.get("removed"), cnt, keep_max))
    ok &= r.status_code == 200 and cnt is not None

    # ⑤ save=1 显式落盘
    n_before = nfiles()
    r = c.get("/picture?kind=origin&grab=1&save=1")
    print("  ⑤ GET /picture?grab=1&save=1 → %s; 磁盘 %d→%d 张(显式存才写)"
          % (r.status_code, n_before, nfiles()))
    ok &= r.status_code == 200 and nfiles() >= n_before

    print("  %s" % ("✅ 通过" if ok else "❌ 有断言失败"))
    return ok


def main():
    # 桩 yolo_detector (不跑真权重)
    yd = types.ModuleType("yolo_detector")

    class YoloDetector:
        def detect(self, path, detect_type=None):
            return {"detections": [{"class_name": "scratch", "confidence": 0.7, "bbox": [1, 2, 3, 4]}],
                    "saved_incoming": "_stub.png"}
    yd.YoloDetector = YoloDetector
    sys.modules["yolo_detector"] = yd

    import surface_10083_work_v5 as sv5
    import cam_finger_10082_work_v5 as fv5

    ok = _ntest(sv5, "表面 surface_10083_work_v5", os.path.join(HERE, "_v5test_surface"))
    ok &= _ntest(fv5, "金手指 cam_finger_10082_work_v5", os.path.join(HERE, "_v5test_finger"))
    print("\n" + ("✅ v5 两个程序的新性质全部通过" if ok else "❌ 有断言失败"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
