
import sys, types, os, runpy, ctypes
import cv2, numpy as np
WORK = '/home/ubuntu/aoi_v4'
sys.path.insert(0, WORK)

class _Pixel:
    Mono1p, Mono2p, Mono4p, Mono8s, Mono8 = 101,102,103,104,105
    Mono10, Mono10p, Mono12, Mono12p, Mono14, Mono16 = 106,107,108,109,110,111
    Mono10Packed, Mono12Packed, Mono14p = 112,113,114
    RGB8 = 200
class _TL: SciCam_TLType_Gige = 1; SciCam_TLType_Usb3 = 2
class _PM: SciCam_PayloadMode_2D = 1
class _GI:
    def __init__(self): self.serialNumber = b"D265250070"
class _DI:
    def __init__(self):
        self.tlType = _TL.SciCam_TLType_Gige
        self.info = types.SimpleNamespace(gigeInfo=_GI())
class _DL:
    def __init__(self): self.count = 1; self.pDevInfo = [_DI()]
class _IA:
    def __init__(self): self.width = 0; self.height = 0; self.pixelType = _Pixel.RGB8
class _AT:
    def __init__(self):
        self.isComplete = 1; self.payloadMode = _PM.SciCam_PayloadMode_2D; self.imgAttr = _IA()
class SciCamera:
    _IMGS = ['/home/ubuntu/aoi_v4/imgs/Finger_Image_W2448_H2048_No_3.png', '/home/ubuntu/aoi_v4/imgs/Finger_Image_W2448_H2048_No_5.png', '/home/ubuntu/aoi_v4/imgs/Finger_Image_W2448_H2048_No_7.png', '/home/ubuntu/aoi_v4/imgs/Finger_Image_W2448_H2048_No_8.png', '/home/ubuntu/aoi_v4/imgs/Finger_Image_W2448_H2048_No_9.png']
    _i = 0
    @staticmethod
    def SciCam_DiscoveryDevices(d, tl):
        d.count = 1; d.pDevInfo = [_DI()]; return 0
    def SciCam_CreateDevice(self, d): return 0
    def SciCam_OpenDevice(self): return 0
    def SciCam_SetGrabStrategy(self, s): return 0
    def SciCam_SetFloatValue(self, k, v): return 0
    def SciCam_StartGrabbing(self): return 0
    def SciCam_StopGrabbing(self): return 0
    def SciCam_Grab(self, p): return 0
    def SciCam_CloseDevice(self): return 0
    def SciCam_DeleteDevice(self): return 0
    def SciCam_FreePayload(self, p): return 0

_CUR = {"img": None}
def _next():
    p = SciCamera._IMGS[SciCamera._i % len(SciCamera._IMGS)]
    SciCamera._i += 1
    return cv2.imread(p)
def SciCam_Payload_GetAttribute(pp, attr):
    _CUR["img"] = _next()
    h, w = _CUR["img"].shape[:2]
    attr.isComplete = 1; attr.payloadMode = _PM.SciCam_PayloadMode_2D
    attr.imgAttr.width, attr.imgAttr.height, attr.imgAttr.pixelType = w, h, _Pixel.RGB8
    return 0
def SciCam_Payload_GetImage(pp, p): return 0
def SciCam_Payload_ConvertImage(imgAttr, imgData, target, dst, size, flag):
    if dst is None:
        size.value = imgAttr.width * imgAttr.height * 3; return 0
    img = _CUR["img"]
    ctypes.memmove(dst, img.tobytes(), img.size)
    size.value = img.size; return 0
def SciCam_Payload_SaveImage(path, pt, data, w, h):
    cv2.imwrite(path, np.frombuffer(bytes(data), np.uint8).reshape(h, w, 3)); return 0

mod = types.ModuleType("SciCam_class")
for k, v in list(globals().items()):
    if k.startswith("SciCam") or k in ("SCI_CAMERA_OK","SCI_DEVICE_INFO_LIST","SCI_CAM_PAYLOAD_ATTRIBUTE"):
        setattr(mod, k, v)
mod.SCI_CAMERA_OK = 0
mod.SCI_DEVICE_INFO_LIST = _DL
mod.SCI_CAM_PAYLOAD_ATTRIBUTE = _AT
mod.SciCamPixelType = _Pixel
mod.SciCamTLType = _TL
mod.SciCamPayloadMode = _PM
sys.modules["SciCam_class"] = mod
for s in ("SciCamErrorDefine_const", "SciCamInfo_header", "SciCamPayload_header"):
    sys.modules[s] = types.ModuleType(s)
ym = types.ModuleType("yolo_detector")
class YoloDetector:
    def detect(self, p, detect_type=None):
        return {"detections": [{"class_name": "pin_defect", "confidence": 0.71, "bbox": [10,20,30,40]}]}
ym.YoloDetector = YoloDetector
sys.modules["yolo_detector"] = ym

# 以 __main__ 跑目标程序 → 走它自己的端口注册 + 占用自检 + 线程启动
runpy.run_path(os.path.join(WORK, "cam_finger_10082_work_v4.py"), run_name="__main__")
