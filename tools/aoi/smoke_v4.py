"""v4 程序离线冒烟测试 (不接真相机):
用桩模块替掉 SciCam SDK / flask / yolo_detector, 用**真图**跑通 v4 的完整取图→规整裁剪→落盘链路,
逐张打印规整度指标, 并校验产物文件。相机 SDK 本身无法离线验证(需现场), 这点如实标注。
"""
import os
import sys
import types
import json
import glob
import cv2
import numpy as np

WORK = "/home/ubuntu/aoi_v4"
STUB = os.path.join(WORK, "_stubmods")
OUTDIR = os.path.join(WORK, "smoke_out")
os.makedirs(STUB, exist_ok=True)
os.makedirs(OUTDIR, exist_ok=True)
sys.path.insert(0, WORK)
sys.path.insert(0, STUB)

# ---------------- 桩: SciCam SDK ----------------
class _Pixel:
    Mono1p, Mono2p, Mono4p, Mono8s, Mono8 = 101, 102, 103, 104, 105
    Mono10, Mono10p, Mono12, Mono12p, Mono14, Mono16 = 106, 107, 108, 109, 110, 111
    Mono10Packed, Mono12Packed, Mono14p = 112, 113, 114
    RGB8 = 200

class _TL:
    SciCam_TLType_Gige = 1
    SciCam_TLType_Usb3 = 2

class _PayloadMode:
    SciCam_PayloadMode_2D = 1

class _DevInfo:
    def __init__(self):
        self.tlType = _TL.SciCam_TLType_Gige
        self.info = types.SimpleNamespace(gigeInfo=types.SimpleNamespace(serialNumber=b"D265250070"))

class _DevList:
    def __init__(self):
        self.count = 1
        self.pDevInfo = [_DevInfo()]

class _ImgAttr:
    def __init__(self):
        self.width = 0
        self.height = 0
        self.pixelType = _Pixel.RGB8

class _Attr:
    def __init__(self):
        self.isComplete = 1
        self.payloadMode = _PayloadMode.SciCam_PayloadMode_2D
        self.imgAttr = _ImgAttr()

class SciCamera:
    @staticmethod
    def SciCam_DiscoveryDevices(devInfos, tl):
        devInfos.count = 1
        devInfos.pDevInfo = [_DevInfo()]
        return 0

    def SciCam_CreateDevice(self, dev):
        return 0

    def SciCam_OpenDevice(self):
        return 0

    def SciCam_SetGrabStrategy(self, s):
        return 0

    def SciCam_SetFloatValue(self, k, v):
        return 0

    def SciCam_StartGrabbing(self):
        return 0

    def SciCam_StopGrabbing(self):
        return 0

    def SciCam_Grab(self, p):
        return 0

    def SciCam_CloseDevice(self):
        return 0

    def SciCam_DeleteDevice(self):
        return 0

    def SciCam_FreePayload(self, p):
        return 0

SCI_CAMERA_OK = 0
SCI_DEVICE_INFO_LIST = _DevList
SCI_CAM_PAYLOAD_ATTRIBUTE = _Attr
SciCamPixelType = _Pixel
SciCamTLType = _TL
SciCamPayloadMode = _PayloadMode

_CURRENT = {"img": None}

def SciCam_Payload_GetAttribute(pp, attr):
    if _CURRENT["img"] is None:
        _CURRENT["img"] = cv2.imread(IMAGES.pop(0))
    h, w = _CURRENT["img"].shape[:2]
    attr.isComplete = 1
    attr.payloadMode = _PayloadMode.SciCam_PayloadMode_2D
    attr.imgAttr.width, attr.imgAttr.height, attr.imgAttr.pixelType = w, h, _Pixel.RGB8
    return 0

def SciCam_Payload_GetImage(pp, p):
    return 0

def SciCam_Payload_ConvertImage(imgAttr, imgData, target, dst, size, flag):
    # 注意: 第一个参数是 imgAttr 本身 (不是 payloadAttribute)
    if dst is None:
        size.value = imgAttr.width * imgAttr.height * 3
        return 0
    import ctypes as _ct
    img = _CURRENT["img"]
    _ct.memmove(dst, img.tobytes(), img.size)
    size.value = img.size
    return 0

def SciCam_Payload_SaveImage(path, pixeltype, data, w, h):
    img = np.frombuffer(bytes(data), dtype=np.uint8).reshape(h, w, 3)
    cv2.imwrite(path, img)
    return 0

# ---------------- 桩: flask / yolo_detector ----------------
flask = types.ModuleType("flask")

class Flask:
    def __init__(self, *a, **k):
        pass

    def route(self, rule, **opt):
        def deco(f):
            return f
        return deco

class _Req:
    args = {}
    environ = {"SERVER_PORT": "10082"}

class Response:
    def __init__(self, data=None, mimetype=None, headers=None):
        self.data = data

def jsonify(*a, **k):
    d = a[0] if a else k
    d = dict(d)
    d["_json"] = True
    return d

flask.Flask, flask.request, flask.jsonify, flask.Response = Flask, _Req, jsonify, Response
sys.modules["flask"] = flask

yolo = types.ModuleType("yolo_detector")

class YoloDetector:
    def detect(self, p, detect_type=None):
        return {"detections": []}

yolo.YoloDetector = YoloDetector
sys.modules["yolo_detector"] = yolo
sys.modules["SciCam_class"] = types.ModuleType("SciCam_class")
for name, val in list(globals().items()):
    if name.startswith("SciCam") or name in ("SCI_CAMERA_OK", "SCI_DEVICE_INFO_LIST", "SCI_CAM_PAYLOAD_ATTRIBUTE"):
        setattr(sys.modules["SciCam_class"], name, val)
for stub in ("SciCamErrorDefine_const", "SciCamInfo_header", "SciCamPayload_header"):
    sys.modules[stub] = types.ModuleType(stub)

# ---------------- 跑真链路 ----------------
IMAGES = sorted(glob.glob(os.path.join(WORK, "imgs", "Finger_Image_*.png")))
print(f"待处理真图 {len(IMAGES)} 张: {[os.path.basename(p)[-10:-4] for p in IMAGES]}\n")

import cam_finger_10082_work_v4 as v4
v4.SAVE_ROOT_DIR = OUTDIR
v4.SAVE_LEGACY_TOPVIEW = True
v4.get_cropper()

print("=" * 110)
print(f"{'图':<8}{'产物裁剪尺寸':<14}{'score':>8}{'角°':>8}{'残余倾角/1000':>14}{'线残差px':>10}{'金覆盖':>8}{'耗时ms':>8}{'方法':>12}")
print("=" * 110)
rows = []
while IMAGES:
    name = os.path.basename(IMAGES[0])[-10:-4]
    t0 = __import__("time").time()
    origin_path, top_path = v4.GrabAndSaveImage()
    dt = (__import__("time").time() - t0) * 1000
    import copy
    info = copy.deepcopy(v4._LAST_CROP_INFO)
    q = info.get("quality", {})
    ok = origin_path and top_path and os.path.exists(origin_path) and os.path.exists(top_path)
    crop = cv2.imread(top_path) if top_path else None
    rows.append((name, ok, info, dt))
    print(f"{name:<8}{f'{crop.shape[1]}x{crop.shape[0]}':<14}{str(info.get('score')):>8}{str(info.get('angle')):>8}"
          f"{str(q.get('stripe_slope_px_per_1000')):>14}{str(q.get('stripe_line_resid_px')):>10}"
          f"{str(q.get('gold_cover')):>8}{dt:>8.0f}{str(info.get('method')):>12}"
          + ("" if ok else "  ❌产物缺失"))
    _CURRENT["img"] = None

print("\n=== 产物清单 ===")
for f in sorted(os.listdir(OUTDIR)):
    print(f"  {f}  {os.path.getsize(os.path.join(OUTDIR, f))} B")
print("\n=== /crop_info 返回体 (JSON 可序列化自检) ===")
print(json.dumps(v4._LAST_CROP_INFO, ensure_ascii=False)[:600], "...")
print("\n=== 断言 ===")
ok1 = all(r[1] for r in rows)
ok2 = all(r[2].get("method") == "template" for r in rows)
slopes = [abs(r[2]["quality"]["stripe_slope_px_per_1000"]) for r in rows if r[2].get("quality", {}).get("stripe_slope_px_per_1000") is not None]
ok3 = all(s < 2.0 for s in slopes)
print(f"① 每张都产出 原图+规整裁剪图: {ok1}")
print(f"② 全部走 template 路径(非兜底): {ok2}")
print(f"③ 残余倾角全部 <2px/1000: {ok3} (实测 {[round(s,2) for s in slopes]})")
print("RESULT:" + ("PASS" if (ok1 and ok2 and ok3) else "FAIL"))
