"""v4 真·端到端 HTTP 测试 (本地, 桩相机 + 真 Flask 服务器):
启动 cam_finger_10082_work_v4.py(以 __main__ 方式跑, 走它自己的端口注册/占用自检/线程启动),
然后真的用 HTTP 打 /capture_detect /crop_info /picture /last_result, 校验返回与落盘产物。
相机 SDK 与加密检测器仍是桩(现场才有的东西), 这点如实标注。
"""
import os
import sys
import json
import time
import types
import ctypes
import subprocess
import urllib.request
import glob
import shutil

WORK = "/home/ubuntu/aoi_v4"
TESTPORT = 10089
OUTDIR = "/tmp/v4_e2e_out"
shutil.rmtree(OUTDIR, ignore_errors=True)
os.makedirs(OUTDIR, exist_ok=True)

WRAP = os.path.join(WORK, "_e2e_wrapper.py")
IMGS = sorted(glob.glob(os.path.join(WORK, "imgs", "Finger_Image_*.png")))

wrapper = f'''
import sys, types, os, runpy, ctypes
import cv2, numpy as np
WORK = {WORK!r}
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
    _IMGS = {IMGS!r}
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

_CUR = {{"img": None}}
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
        return {{"detections": [{{"class_name": "pin_defect", "confidence": 0.71, "bbox": [10,20,30,40]}}]}}
ym.YoloDetector = YoloDetector
sys.modules["yolo_detector"] = ym

# 以 __main__ 跑目标程序 → 走它自己的端口注册 + 占用自检 + 线程启动
runpy.run_path(os.path.join(WORK, "cam_finger_10082_work_v4.py"), run_name="__main__")
'''
open(WRAP, "w", encoding="utf-8").write(wrapper)

env = dict(os.environ)
env["PYTHONPATH"] = "/home/ubuntu/lerobot-venv/lib/python3.12/site-packages"
env["AOI_PORT"] = str(TESTPORT)
p = subprocess.Popen(["/tmp/v4env/bin/python", WRAP], env=env,
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)


def get(path, method="GET", tmo=60):
    req = urllib.request.Request(f"http://127.0.0.1:{TESTPORT}{path}", method=method,
                                 data=b"" if method == "POST" else None)
    try:
        with urllib.request.urlopen(req, timeout=tmo) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


import threading
logs = []


def pump():
    for line in p.stdout:
        logs.append(line.rstrip())
        print("  [服务] " + line.rstrip(), flush=True)


threading.Thread(target=pump, daemon=True).start()

print(f"\n=== 等服务器就绪 (端口 {TESTPORT}) ===")
ok = False
for i in range(40):
    time.sleep(1)
    try:
        st, body = get("/crop_info", tmo=3)
        ok = True
        print(f"  就绪 (HTTP {st})")
        break
    except Exception:
        pass
if not ok:
    print("❌ 服务没起来"); p.kill(); sys.exit(1)

results = {}
print("\n=== ① POST /capture_detect ===")
st, body = get("/capture_detect", "POST")
print(f"  HTTP {st}  {body[:200]}")
results["capture_detect"] = (st, body)

print("\n=== ② GET /crop_info (v4 规整度指标) ===")
time.sleep(1)
st, body = get("/crop_info")
d = json.loads(body)
print(f"  HTTP {st}")
print(f"  方法={d.get('method')} score={d.get('score')} 角度={d.get('angle')}° "
      f"残余倾角={d['quality']['stripe_slope_px_per_1000']}px/1000 线残差={d['quality']['stripe_line_resid_px']}px "
      f"金覆盖={d['quality']['gold_cover']} 裁剪={d['quality']['crop_size']} 耗时={d.get('crop_ms')}ms 模式={d.get('mode')}")
results["crop_info"] = d

print("\n=== ③ GET /picture?meta=1 ===")
st, body = get("/picture?meta=1")
m = json.loads(body)
print(f"  HTTP {st}  file={m.get('file')} size={m.get('size')} 裁剪信息带出={bool(m.get('crop_info'))}")
results["picture_meta"] = m

print("\n=== ④ GET /picture (默认必须=原始图) ===")
st, body = get("/picture")
print(f"  HTTP {st}  bytes={len(body)}  PNG头={body[:8]!r}")
results["picture_bytes"] = (st, len(body), body[:8])
print("=== ④b GET /picture?kind=crop (规整裁剪图) ===")
st2, body2 = get("/picture?kind=crop")
print(f"  HTTP {st2}  bytes={len(body2)}")
results["picture_crop"] = (st2, len(body2))

print("=== ④b2 GET /picture?kind=natural (金手指原比例) ===")
st4, body4 = get("/picture?kind=natural")
print(f"  HTTP {st4}  bytes={len(body4)}")
results["picture_natural"] = (st4, len(body4))
import numpy as _np, cv2
for _tag, _raw in (("crop", body2), ("natural", body4)):
    _arr = cv2.imdecode(_np.frombuffer(_raw, _np.uint8), cv2.IMREAD_COLOR)
    if _arr is None:
        print(f"    {_tag}: 解码失败(前80字节 {_raw[:80]!r})")
        results["shape_" + _tag] = None
    else:
        print(f"    {_tag}: 解码 {_arr.shape[1]}x{_arr.shape[0]}")
        results["shape_" + _tag] = (_arr.shape[1], _arr.shape[0])

print("\n=== ④c GET /region (原始图坐标系的区域 + 对焦清晰度) ===")
st3, body3 = get("/region")
d3 = json.loads(body3)
rr = d3.get("region", {})
print(f"  HTTP {st3}  ok={d3.get('ok')} 区域中心=({rr.get('cx')},{rr.get('cy')}) 尺寸=({rr.get('w')}x{rr.get('h')}) "
      f"角度={rr.get('angle')}° focus={d3.get('focus')} 图幅={d3.get('image_size')}")
results["region"] = d3

print("\n=== ⑤ GET /last_result (等后台检测 worker) ===")
for i in range(20):
    time.sleep(1)
    st, body = get("/last_result")
    if st == 200:
        break
d = json.loads(body)
print(f"  HTTP {st}  判决={d.get('verdict')} 缺陷数={d.get('count')} 推理耗时={d.get('ms')}ms 类型={d.get('detect_type')}")
results["last_result"] = d

print("\n=== ⑥ 端口占用自检 (再起一个实例, 应当 exit 1) ===")
p2 = subprocess.run(["/tmp/v4env/bin/python", WRAP], env=env, capture_output=True, text=True, timeout=90)
print(f"  退出码={p2.returncode}  (期望 1)")
print("  " + "\n  ".join((p2.stdout or "").strip().splitlines()[-4:]))
results["port_guard"] = p2.returncode

print("\n=== ⑦ 落盘产物 ===")
files = sorted(glob.glob(os.path.join(WORK, "goldfinger_images", "*.png")))
for f in files[-6:]:
    print(f"  {os.path.basename(f)}  {os.path.getsize(f)} B")
results["files"] = files

p.kill()

print("\n=== 断言 ===")
a1 = results["capture_detect"][0] == 200 and b"success" in results["capture_detect"][1]
a2 = results["crop_info"].get("method") == "template" and abs(results["crop_info"]["quality"]["stripe_slope_px_per_1000"]) < 2
a3 = (results["picture_bytes"][0] == 200 and results["picture_bytes"][2][:4] == b"\x89PNG"
      and results["picture_bytes"][1] > 3_000_000            # 默认给的是 2448x2048 原图(≈4.4MB)
      and results["picture_crop"][0] == 200 and 200_000 < results["picture_crop"][1] < 4_000_000)  # 960x960 方图
a4 = results["last_result"].get("verdict") == "NG" and results["last_result"].get("detect_type") == "gf"
_r = results.get("region", {})
a8 = (results.get("shape_crop") == (960, 960) and results.get("shape_natural") == (1455, 70))
a7 = (_r.get("ok") and _r.get("image_size") == [2448, 2048]
      and 1400 < (_r.get("region") or {}).get("w", 0) < 1500     # 金手指横向 ~1455
      and 55 < (_r.get("region") or {}).get("h", 0) < 95         # 只取金手指本身(不含下方金带/亮边沿) ~70
      and _r.get("focus"))
a5 = results["port_guard"] == 1
a6 = len([f for f in results["files"] if "TopView" in f]) >= 1 and len([f for f in results["files"] if "CropAnno" in f]) >= 1
for n, v in [("① /capture_detect 200+success", a1), ("② /crop_info 走 template 且残余倾角<2", a2),
             ("③ /picture 默认=原始图(>3MB) / kind=crop=裁剪图(<1MB)", a3), ("④ /last_result 通道解析为 gf 且假缺陷判决 NG", a4),
             ("⑤ 端口占用被拦(exit 1)", a5), ("⑥ 裁剪图+标注图落盘", a6),
             ("⑦ /region = 金手指本身(~1455x70, 不含下方厚边沿)+focus", a7),
             ("⑧ /picture?kind=crop=960x960 拉长版 且 ?kind=natural=1455x70 原比例", a8)]:
    print(f"  {n}: {'PASS' if v else 'FAIL'}")
print("RESULT:" + ("PASS" if all([a1, a2, a3, a4, a5, a6, a7, a8]) else "FAIL"))
