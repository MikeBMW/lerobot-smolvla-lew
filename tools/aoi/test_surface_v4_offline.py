#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_surface_v4_offline.py — 离线验证 表面检测 v4 程序的 HTTP 契约 (不接真相机)

做法: 用**桩模块**替掉 SciCam SDK 与 yolo_detector, 让 surface_10083_work_v4 在本机跑起来,
      再用 Flask test_client 打真实请求, 断言:
        ① POST /capture_detect → 200, 且落盘 "原图 + 规范图(1280 letterbox)"
        ② GET /picture?kind=crop → 200 image/png, 图尺寸 = 1280x1280 (保比例, 不变形)
        ③ GET /picture?kind=origin → 200 (原图 2448x2048)
        ④ GET /last_result → 200, verdict/count/defects 字段齐全 (桩检测器投 2 个缺陷 → NG)
        ⑤ GET /crop_info → 200, 含 mean/focus/imgsz_expected=1280
用法: gui-venv311/bin/python /home/ubuntu/aoi_v4/test_surface_v4_offline.py
"""
import os
import sys
import types

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
STUB = os.path.join(HERE, "_stub")
os.makedirs(STUB, exist_ok=True)


# ── 桩: SciCam SDK ──
def _mk_stub():
    sc = types.ModuleType("SciCam_class")
    sc.SciCamera = type("SciCamera", (), {
        "SciCam_DiscoveryDevices": staticmethod(lambda *a, **k: 0),
        "SciCam_SetFloatValue": lambda self, *a: 0,
        "SciCam_CreateDevice": lambda self, *a: 0,
        "SciCam_OpenDevice": lambda self: 0,
        "SciCam_SetGrabStrategy": lambda self, *a: 0,
        "SciCam_StartGrabbing": lambda self: 0,
        "SciCam_StopGrabbing": lambda self: 0,
        "SciCam_CloseDevice": lambda self: 0,
        "SciCam_DeleteDevice": lambda self: 0,
        "SciCam_FreePayload": lambda self, *a: 0,
    })
    sc.SCI_DEVICE_INFO_LIST = type("SCI_DEVICE_INFO_LIST", (), {})
    sc.SciCamTLType = type("SciCamTLType", (), {"SciCam_TLType_Gige": 1, "SciCam_TLType_Usb3": 2})
    import cv2
    # 桩抓帧: 造一张"有内容"的 2448x2048 图 (渐变+方块, 保证非全黑)
    img = np.zeros((2048, 2448, 3), np.uint8)
    img[:, :, 0] = np.linspace(0, 255, 2448, dtype=np.uint8)[None, :]
    img[800:1200, 900:1600] = 200
    _STATE = {"img": img}

    def _grab(self, ppayload):
        _STATE["pp"] = True
        return 0

    sc.SciCamera.SciCam_Grab = _grab
    return sc, _STATE


_SDK, _ST = _mk_stub()


class _Attr:
    def __init__(self):
        self.isComplete = 1
        self.payloadMode = 1
        self.imgAttr = type("A", (), {"width": 2448, "height": 2048, "pixelType": 7})()


def write_stubs():
    import cv2
    # SciCam_class
    with open(os.path.join(STUB, "SciCam_class.py"), "w") as f:
        f.write(
            "import numpy as np\n"
            "class SciCamera:\n"
            "    _img = None\n"
            "    @staticmethod\n"
            "    def SciCam_DiscoveryDevices(*a, **k): return 0\n"
            "    def SciCam_SetFloatValue(self, *a): return 0\n"
            "    def SciCam_CreateDevice(self, *a): return 0\n"
            "    def SciCam_OpenDevice(self): return 0\n"
            "    def SciCam_SetGrabStrategy(self, *a): return 0\n"
            "    def SciCam_StartGrabbing(self): return 0\n"
            "    def SciCam_StopGrabbing(self): return 0\n"
            "    def SciCam_CloseDevice(self): return 0\n"
            "    def SciCam_DeleteDevice(self): return 0\n"
            "    def SciCam_Grab(self, ppayload):\n"
            "        SciCamera._grabbed = True\n"
            "        return 0\n"
            "    def SciCam_FreePayload(self, *a): return 0\n"
            "class SCI_DEVICE_INFO_LIST: pass\n"
            "class SciCamTLType:\n"
            "    SciCam_TLType_Gige = 1\n"
            "    SciCam_TLType_Usb3 = 2\n")
    # 常量/头文件
    with open(os.path.join(STUB, "SciCamErrorDefine_const.py"), "w") as f:
        f.write("SCI_CAMERA_OK = 0\n")
    with open(os.path.join(STUB, "SciCamInfo_header.py"), "w") as f:
        f.write(
            "class _Gige:\n    serialNumber = b'D265250099\\x00'\n"
            "class _Info:\n    gigeInfo = _Gige()\n"
            "class _Dev:\n    tlType = 1\n    info = _Info()\n"
            "class SCI_DEVICE_INFO_LIST:\n"
            "    count = 1\n"
            "    class pDevInfo:\n"
            "        pass\n"
            "SCI_DEVICE_INFO_LIST.pDevInfo = [_Dev()]\n")
    with open(os.path.join(STUB, "SciCamPayload_header.py"), "w") as f:
        f.write(
            "import numpy as np\n"
            "class _ImgAttr:\n    width = 2448\n    height = 2048\n    pixelType = 7\n"
            "class SCI_CAM_PAYLOAD_ATTRIBUTE:\n"
            "    isComplete = 1\n    payloadMode = 1\n    imgAttr = _ImgAttr()\n"
            "class SciCamPayloadMode:\n    SciCam_PayloadMode_2D = 1\n"
            "class SciCamPixelType:\n"
            "    RGB8 = 7\n    Mono8 = 1\n    Mono1p = 2\n    Mono2p = 3\n    Mono4p = 4\n"
            "    Mono8s = 5\n    Mono10 = 6\n    Mono10p = 8\n    Mono12 = 9\n    Mono12p = 10\n"
            "    Mono14 = 11\n    Mono16 = 12\n    Mono10Packed = 13\n    Mono12Packed = 14\n    Mono14p = 15\n"
            "def SciCam_Payload_GetAttribute(pp, attr): return 0\n"
            "def SciCam_Payload_GetImage(pp, out): return 0\n"
            "def SciCam_Payload_ConvertImage(attr, src, t, dst, size, flag):\n"
            "    size.value = 2448*2048*3\n"
            "    return 0\n"
            "def SciCam_Payload_SaveImage(path, t, data, w, h): return 0\n")


def main():
    write_stubs()
    sys.path.insert(0, STUB)
    sys.path.insert(0, HERE)
    # 桩 yolo_detector: 投 2 个缺陷 → 期望 verdict=NG
    yd = types.ModuleType("yolo_detector")

    class YoloDetector:
        def detect(self, path, detect_type=None):
            return {"detections": [{"class_name": "scratch", "confidence": 0.71, "bbox": [10, 20, 60, 40]},
                                   {"class_name": "dirt", "confidence": 0.44, "bbox": [200, 300, 260, 340]}],
                    "saved_incoming": "D:/AOI_images/housing/incoming/_stub.png"}
    yd.YoloDetector = YoloDetector
    sys.modules["yolo_detector"] = yd

    import surface_10083_work_v4 as s

    # 抓帧: 让 stub 的 Grab 路径产出我们的合成图 → 直接替换内部函数, 只验证 HTTP 契约
    import cv2
    img = np.zeros((2048, 2448, 3), np.uint8)
    img[:, :, 2] = np.linspace(0, 255, 2448, dtype=np.uint8)[None, :]
    img[800:1200, 900:1600] = 200
    os.makedirs(s.SAVE_ROOT_DIR, exist_ok=True)
    _seq = {"n": 1}

    def fake_grab():
        n = _seq["n"]
        _seq["n"] += 1
        op = os.path.join(s.SAVE_ROOT_DIR, "Surface_Image_W2448_H2048_No_%d.png" % n)
        cv2.imwrite(op, img)
        canvas, r, off = s.letterbox_square(img)
        tp = os.path.join(s.SAVE_ROOT_DIR, "Surface_Letterbox_W1280_H1280_No_%d.png" % n)
        cv2.imwrite(tp, canvas)
        with s._PIC_LOCK:
            s._LAST_CROP_INFO.clear()
            s._LAST_CROP_INFO.update({"n": n, "crop_file": os.path.basename(tp),
                                      **s._crop_metrics(canvas, img, r, off)})
        return op, tp

    s.GrabAndSaveImage = fake_grab
    s.ensure_camera = lambda: True
    s._enqueue_detect = lambda tv, o, dt: s._LAST_RESULT.update(
        {"n": 1, "detect_type": dt, "origin": o, "topview": tv,
         "defects": YoloDetector().detect(tv, dt)["detections"], "count": 2,
         "verdict": "NG", "ms": 12.3, "saved_incoming": "D:/AOI_images/housing/incoming/_stub.png"})

    c = s.app.test_client()
    ok = True
    # Flask test_client 的 SERVER_PORT 是 80 → 按程序自身逻辑(main() 会注册实际端口)把它也注册成表面通道
    s.PORT_TO_DETECT_TYPE["80"] = "housing"

    r = c.post("/capture_detect")
    print("① POST /capture_detect            →", r.status_code, r.get_json())
    ok &= r.status_code == 200

    r = c.get("/picture?kind=crop")
    ct = r.headers.get("Content-Type", "")
    arr = np.frombuffer(r.data, np.uint8)
    im = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    print("② GET  /picture?kind=crop         →", r.status_code, ct, (im.shape if im is not None else None))
    ok &= r.status_code == 200 and im is not None and im.shape[0] == 1280 and im.shape[1] == 1280

    r = c.get("/picture?kind=origin")
    arr = np.frombuffer(r.data, np.uint8)
    im2 = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    print("③ GET  /picture?kind=origin       →", r.status_code, (im2.shape if im2 is not None else None))
    ok &= r.status_code == 200 and im2 is not None and im2.shape[1] == 2448

    r = c.get("/last_result")
    j = r.get_json() or {}
    print("④ GET  /last_result               →", r.status_code, {k: j.get(k) for k in ("verdict", "count", "ms")})
    ok &= r.status_code == 200 and j.get("verdict") == "NG" and j.get("count") == 2

    r = c.get("/crop_info")
    j = r.get_json() or {}
    print("⑤ GET  /crop_info                 →", r.status_code,
          {k: j.get(k) for k in ("canonical", "letterbox_ratio", "mean", "focus_laplacian_var", "imgsz_expected")})
    ok &= r.status_code == 200 and j.get("imgsz_expected") == 1280 and j.get("canonical") == [1280, 1280]

    print("\n" + ("✅ 表面 v4 HTTP 契约全部通过" if ok else "❌ 有断言失败"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
