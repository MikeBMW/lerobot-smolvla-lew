"""
Z-MAX 金手指检测 AOI 程序 · 优化版 v4 (10082)
============================================
v4 变更 (2026-09-20, 静静):
  ★ 核心: 金手指截取从"固定透视窗 [400,1000]-[2000,1250] 硬拉"改成【模板法规整裁剪】
    - 老问题: 固定窗与实际金手指条位置/姿态对不上(条中心 y 在 1008~1450 之间漂移, 条本身还带 ~0.6-1.0° 倾角),
      且 warp 输出尺寸被静默拉成原图尺寸 2448x2048 → 截出来的金手指"歪歪扭扭"、还被拉伸变形
    - 新做法: ① 用参考真图做"金手指条模板"(去倾斜后居中存放, 见 templates/gf_strip_template.png/.json)
              ② 运行期: 1/4 尺度多角度粗搜 → 1/1 尺度局部精修(角度+尺度)
              ③ 角度再用"裁剪图里条质心线斜率"做一次扫描精修(目标度量直接最小化, 不猜符号)
              ④ 单次仿射把条映射到规范化画布的固定位置 → 跨张一致、条水平、尺寸固定
    - 每个相机周期打印规整度自证: score / 残余倾角(px/1000) / 条质心线残差 / 金覆盖率
  ★ 旧版: 固定窗与实际金手指条位置/姿态对不上, 且 warp 输出尺寸被静默拉成原图尺寸 → 歪 + 拉伸
  ★ v4.1 (2026-09-20 现场反馈修 framing): 金手指区纵向范围改为"上含焊盘排 + 下不含塑料本体亮边沿"
      - ROI 定位: 金连通域定列段 → 列段内行密度(morph 剖面)带空隙容限扩展 → 顶到"焊盘排"顶边
      - 底部亮带切除: 行亮度中位数×1.25 以上的塑料本体反光边不裁进来(现场说"下面多一个大边沿")
      - 新增输出维度: 裁剪图里高亮(>180)像素占比 bright_frac (亮边沿若混进来这个数会明显变大)
  ★ 保留 v3 全部接口与异步方案: /capture_detect 秒回, 检测后台跑, /last_result 不变
  ★ 接口语义 (按现场要求): /picture = **原始图** (加 ?kind=crop 才给规整裁剪图); /crop_info = 裁剪结果指标
  ★ v4.2 (现场二次反馈): ①只保留"金手指"本身 —— 定位改成"最上面那片离散焊盘 run"(|gx| 高),
     下方那条实心金带与塑料本体亮边沿一律不进画布 ②金手指只占 1455x70(21:1)太扁 → 纵向拉伸到
     **960x960 方图**(与 config.yaml imgsz=960 对齐), 另存一份"原比例"版供目检
  ★ 新增 /crop_info: 最近一次裁剪的完整质量指标 (JSON), 便于外部取证
  ★ 保留旧几何开关: GF_CROP_MODE="legacy" 时退回 v3 的固定窗 warp (可一键回滚, 不用换文件)
  ★ 兜底链: 模板匹配失败/分数低 → HSV 条带兜底(仍是规整仿射) → 中心窗兜底(明确标记, 不装正常)

依赖: gf_crop.py / gf_metric.py / templates/gf_strip_template.png(.json) 与本文件同目录; yolo_detector 保持不变
"""
import os
import sys
import time
import json
import glob
import socket
import struct
import ctypes
import traceback
import threading
from threading import Thread
from flask import Flask, request, jsonify, Response

import cv2
import numpy as np
from SciCam_class import *
from SciCamErrorDefine_const import *
from SciCamInfo_header import *
from SciCamPayload_header import *
from yolo_detector import YoloDetector

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from gf_crop import GoldFingerCropper, annotate   # v4 核心: 模板法规整裁剪

VERSION = "v5"
app = Flask(__name__)
m_Device = SciCamera()   # 相机设备全局实例 (原版保留)
detector = YoloDetector()  # 加密检测器全局实例, 启动加载一次 (原版保留)

# 图片保存根目录
SAVE_ROOT_DIR = r"./goldfinger_images"

# 端口-模型映射 (产线固定 10082; 启动时会把实际端口也注册进来, 便于换端口自测)
PRODUCTION_PORT = 10082
PORT_TO_DETECT_TYPE = {str(PRODUCTION_PORT): "gf"}

# ===== 配置: 模板法裁剪 =====
GF_CROP_MODE = os.environ.get("GF_CROP_MODE", "template")     # template | legacy
TEMPLATE_PNG = os.path.join(HERE, "templates", "gf_strip_template.png")
# —— 规范化画布: 金手指只占 1455x70(横向 21:1), 太扁, YOLO 会把它压成一条细线 →
#    现场要求"拉到符合 YOLO v8 的比例": 默认 960x960 方图(与 yolo_detector/config.yaml 的 imgsz=960 对齐,
#    推理时不做 letterbox 也不上采样), 金手指纵向拉伸填满画布。
CANONICAL_W = int(os.environ.get("GF_CANONICAL", "960"))   # 960 / 640 / 1280
CANONICAL_H = CANONICAL_W
KEEP_ASPECT = os.environ.get("GF_KEEP_ASPECT", "0") == "1"  # 1=保比例(只做对照/复核用)
MARGIN_X, MARGIN_Y = 0.02, 0.03   # 金手指条在画布内留的边距(2%/3%)
MIN_SCORE = 0.55              # 模板匹配分下限, 低于则告警(并用兜底结果)
SAVE_LEGACY_TOPVIEW = True    # 是否同时存一份 v3 几何的 topview (对照/回滚用)

# 金手指检测相机SN
TARGET_SN = "D265250070"
CAM_DESC = "金手指检测相机 OPT-CC1-GG50"

# 相机参数 (可调)
EXPOSURE_US = 10000.0
GAIN_DB = 1.0
GAMMA_VAL = 1.0

# ===== v3 保留: 最近一次照片 / 最近一次检测判决 =====
_LAST_PIC = {"origin": None, "topview": None, "t": 0.0}


# ───────────────────── v5: 内存帧 + 按需落盘 + 保留上限 ─────────────────────
# 老倪 2026-09-27: 「不检测的时候, 不用保存那么多图片」⇒
#   · 只"看一眼/取图"(GET /picture?grab=1) 一律**不落盘**, 图只留内存(编码后几百 KB);
#   · 只有真检测(POST /capture_detect, 模型要读文件)才落盘, 落完按上限清旧图;
#   · 诊断用的额外图(标注图/legacy)默认不写, 要写设 AOI_SAVE_DEBUG=1;
#   · GET /storage 看占用/张数, POST /prune 手动清。
AOI_SAVE_DEBUG = os.environ.get("AOI_SAVE_DEBUG", "0").strip().lower() in ("1", "true", "yes")
KEEP_CANON = int(os.environ.get("AOI_KEEP_CANON", "400"))
KEEP_ORIGIN = int(os.environ.get("AOI_KEEP_ORIGIN", "120"))
_PRUNE_PATTERNS = [("Finger_TopView_W*_H*_No_*.png", KEEP_CANON),
                   ("Finger_Image_W*_H*_No_*.png", KEEP_ORIGIN),
                   ("Finger_CropNatural_W*_No_*.png", KEEP_CANON),
                   ("Finger_CropAnno_No_*.png", KEEP_ORIGIN if AOI_SAVE_DEBUG else 0),
                   ("Legacy_TopView_No_*.png", KEEP_ORIGIN if AOI_SAVE_DEBUG else 0)]
_MEM = {"crop": None, "origin": None, "natural": None, "ts": 0.0}
_MEM_LOCK = threading.Lock()
_TL = threading.local()          # 每次抓帧的落盘开关(线程安全: /capture_detect 与 /picture?grab=1 可能并发)


def _enc_jpg(bgr, quality=90):
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    return buf.tobytes() if ok else b""


def _mem_put(crop=None, origin=None, natural=None):
    """把当前这帧编码进内存 (取图走内存, 磁盘就不需要那么多文件)。"""
    with _MEM_LOCK:
        if crop is not None:
            _MEM["crop"] = _enc_jpg(crop, 92)
        if origin is not None:
            _MEM["origin"] = _enc_jpg(origin, 88)
        if natural is not None:
            _MEM["natural"] = _enc_jpg(natural, 92)
        _MEM["ts"] = time.time()


def _mem_get(kind, t0=0.0):
    """取内存帧: kind=origin/raw 要原图, 其余要规范图; 没有就退回另一张。"""
    with _MEM_LOCK:
        b = _MEM.get(kind) or _MEM.get("crop") or _MEM.get("origin")
        ts = _MEM.get("ts", 0.0)
    return b, ts


def _iw(path, img, *a, **kw):
    """落盘开关: 只有真检测(或 AOI_SAVE_DEBUG 下的诊断图)才写盘。"""
    save = getattr(_TL, "save", True)
    p = str(path)
    if save or (AOI_SAVE_DEBUG and ("Anno" in p or "Legacy" in p)):
        return cv2.imwrite(path, img, *a, **kw)
    return True


def _prune_dir(patterns=None):
    """按保留上限删最旧的图; patterns=[(glob, keep_n), ...] (keep_n=0 表示这类全清)。"""
    patterns = patterns if patterns is not None else _PRUNE_PATTERNS
    removed = 0
    for pat, keep in patterns:
        try:
            files = sorted(glob.glob(os.path.join(SAVE_ROOT_DIR, pat)), key=os.path.getmtime)
        except OSError:
            continue
        if keep >= 0 and len(files) > keep:
            for f in files[:len(files) - keep]:
                try:
                    os.remove(f)
                    removed += 1
                except OSError:
                    pass
    return removed


def _dir_stat():
    out = {"dir": os.path.abspath(SAVE_ROOT_DIR), "groups": {}}
    total = n_total = 0
    for pat, keep in _PRUNE_PATTERNS:
        files = glob.glob(os.path.join(SAVE_ROOT_DIR, pat))
        sz = 0
        for f in files:
            try:
                sz += os.path.getsize(f)
            except OSError:
                pass
        out["groups"][pat] = {"count": len(files), "mb": round(sz / 1048576.0, 1), "keep": keep}
        total += sz
        n_total += len(files)
    out["files_total"] = n_total
    out["mb_total"] = round(total / 1048576.0, 1)
    out["save_debug"] = AOI_SAVE_DEBUG
    return out
_LAST_RESULT = {}
_LAST_CROP_INFO = {}
_LAST_REGION = {}
_PIC_LOCK = threading.Lock()


def _region_payload(bgr, info):
    """金手指区域(原始图坐标系) + 对焦清晰度 —— 供状态空间 YOLO/伺服引导直接消费
    region: 定向框(中心/宽高/角度), 与模板法截取用的是同一份几何
    focus : 区域内 Laplacian 方差(对焦锐度指标, 越大越清晰), 以及该区域的灰度均值/对比度
    """
    bgr = np.asarray(bgr)
    s = (info or {}).get("strip") or {}
    if not s:
        return {"ts": time.time(), "ok": False, "reason": "无区域几何(裁剪失败)"}
    cx, cy, w, h, ang = float(s["cx"]), float(s["cy"]), float(s["w"]), float(s["h"]), float(s.get("angle", 0.0))
    R = cv2.getRotationMatrix2D((0, 0), ang, 1.0)
    pts = []
    for dx, dy in [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]:
        pts.append([float(cx + R[0, 0] * dx + R[0, 1] * dy), float(cy + R[1, 0] * dx + R[1, 1] * dy)])
    x0 = max(0, int(min(p[0] for p in pts))); x1 = min(bgr.shape[1], int(max(p[0] for p in pts)))
    y0 = max(0, int(min(p[1] for p in pts))); y1 = min(bgr.shape[0], int(max(p[1] for p in pts)))
    roi = bgr[y0:y1, x0:x1]
    focus = sharp = None
    if roi.size:
        g = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
        focus = float(cv2.Laplacian(g, cv2.CV_64F).var())
        sharp = float(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3).__abs__().mean())
    return {"ts": time.time(), "ok": True, "image_size": [bgr.shape[1], bgr.shape[0]],
            "region": {"cx": round(cx, 2), "cy": round(cy, 2), "w": round(w, 2), "h": round(h, 2),
                       "angle": round(ang, 3), "quad": [[round(v, 1) for v in p] for p in pts],
                       "bbox": [int(x0), int(y0), int(x1 - x0), int(y1 - y0)]},
            "focus": None if focus is None else round(focus, 1),
            "sharp": None if sharp is None else round(sharp, 2),
            "score": (info or {}).get("score"), "angle": (info or {}).get("angle"),
            "quality": (info or {}).get("quality", {})}

# 【优化1】全局常驻: 相机设备缓存 + 打开状态
_dev_cache = None
_cam_open = False
_cam_lock = threading.Lock()

_CROPPER = None
_CROPPER_LOCK = threading.Lock()
_LAST_NATURAL = None       # 原比例版裁剪图 (1:1 像素)


def get_cropper():
    """惰性建裁剪器 (模板只读一次; 进程内复用, 角度热启动)"""
    global _CROPPER
    with _CROPPER_LOCK:
        if _CROPPER is None:
            if not os.path.exists(TEMPLATE_PNG):
                print(f"⚠️ 模板不存在: {TEMPLATE_PNG} → 只能用 legacy 几何")
                return None
            _CROPPER = GoldFingerCropper(
                TEMPLATE_PNG, canonical_w=CANONICAL_W, canonical_h=CANONICAL_H,
                margin_x=MARGIN_X, margin_y=MARGIN_Y, preserve_aspect=KEEP_ASPECT,
                min_score=MIN_SCORE)
            print(f"模板裁剪器就绪: {os.path.basename(TEMPLATE_PNG)} "
                  f"条={_CROPPER.meta['strip_w']:.0f}x{_CROPPER.meta['strip_h']:.0f} "
                  f"规范化={CANONICAL_W}x{'auto' if KEEP_ASPECT else CANONICAL_H}")
        return _CROPPER


def uint32_to_ipv4(ip_uint32):
    network_order_ip = socket.htonl(ip_uint32)
    packed_ip = struct.pack("!I", network_order_ip)
    return socket.inet_ntoa(packed_ip)


def _resolve_detect_type_by_channel() -> tuple:
    port = str(request.environ.get("SERVER_PORT", "")).strip()
    detect_type = PORT_TO_DETECT_TYPE.get(port)
    return detect_type, port


def find_dev_by_sn(target_sn: str, use_cache=True):
    """【优化4】设备枚举缓存: 找到后缓存, 不重复枚举"""
    global _dev_cache
    if use_cache and _dev_cache is not None:
        return _dev_cache
    devInfos = SCI_DEVICE_INFO_LIST()
    reVal = SciCamera.SciCam_DiscoveryDevices(
        devInfos, SciCamTLType.SciCam_TLType_Gige | SciCamTLType.SciCam_TLType_Usb3)
    if reVal != SCI_CAMERA_OK or devInfos.count == 0:
        print("枚举相机失败或无设备")
        return None
    for i in range(devInfos.count):
        cam_obj = devInfos.pDevInfo[i]
        if cam_obj.tlType != SciCamTLType.SciCam_TLType_Gige:
            continue
        gige_info = cam_obj.info.gigeInfo
        sn_buf = bytes(gige_info.serialNumber).strip(b"\x00")
        sn_str = sn_buf.decode("utf-8")
        if sn_str == target_sn:
            _dev_cache = cam_obj
            return cam_obj
    print(f"未找到序列号 {target_sn} 的相机")
    return None


def set_exposure(exposure_us: float):
    ret = m_Device.SciCam_SetFloatValue("ExposureTime", exposure_us)
    if ret != SCI_CAMERA_OK:
        print(f"【参数设置失败】曝光 {exposure_us}us，错误码:{ret}")
        return False
    print(f"曝光设置成功 {exposure_us}us")
    return True


def set_gain(gain_db: float):
    """【优化2】增益容错: 失败自动尝试替代值, 都不行降级跳过"""
    ret = m_Device.SciCam_SetFloatValue("Gain", gain_db)
    if ret == SCI_CAMERA_OK:
        print(f"增益设置成功 {gain_db}")
        return True
    for alt in [gain_db * 2, int(gain_db), 0.0, 2.0, 8.0]:
        if alt == gain_db:
            continue
        ret = m_Device.SciCam_SetFloatValue("Gain", alt)
        if ret == SCI_CAMERA_OK:
            print(f"增益设置成功(替代值) {alt} (原{gain_db}失败码{ret})")
            return True
    print(f"【参数设置失败】增益 {gain_db}，错误码:{ret}，跳过(不影响采集)")
    return False


def set_gamma(gamma_val: float):
    ret = m_Device.SciCam_SetFloatValue("Gamma", gamma_val)
    if ret != SCI_CAMERA_OK:
        print(f"【参数设置失败】Gamma {gamma_val}，错误码:{ret}")
        return False
    print(f"Gamma设置成功 {gamma_val}")
    return True


def Open_Device(target_dev):
    global _cam_open
    reVal = m_Device.SciCam_CreateDevice(target_dev)
    if reVal != SCI_CAMERA_OK:
        print("创建设备句柄失败，错误码：", reVal)
        return False
    reVal = m_Device.SciCam_OpenDevice()
    if reVal != SCI_CAMERA_OK:
        print("打开相机失败，错误码：", reVal)
        return False
    m_Device.SciCam_SetGrabStrategy(2)
    set_exposure(EXPOSURE_US)
    set_gain(GAIN_DB)
    set_gamma(GAMMA_VAL)
    _cam_open = True
    print("相机打开成功")
    return True


def StartGrabbing():
    ret = m_Device.SciCam_StartGrabbing()
    if ret != SCI_CAMERA_OK:
        print("开启采集失败")
        return False
    print("采集流已启动")
    return True


def StopGrabbing():
    m_Device.SciCam_StopGrabbing()
    print("采集流已停止")


def Close_Device():
    global _cam_open
    try:
        m_Device.SciCam_CloseDevice()
        m_Device.SciCam_DeleteDevice()
    except Exception:
        pass
    _cam_open = False
    print("相机已关闭释放")


def ensure_camera():
    """【优化1】相机常驻: 已打开直接返回True, 未打开才初始化"""
    global _cam_open
    with _cam_lock:
        if _cam_open:
            return True
        target_dev = find_dev_by_sn(TARGET_SN)
        if target_dev is None:
            return False
        if not Open_Device(target_dev):
            return False
        if not StartGrabbing():
            StopGrabbing()
            Close_Device()
            return False
        time.sleep(0.8)
        return True


# ===== v3 保留: 旧的固定窗 warp (legacy 模式 / 对照用) =====
def warp_goldfinger_topview(pDstData, img_w, img_h, out_w=None, out_h=None):
    if out_w is None:
        out_w = img_w
    if out_h is None:
        out_h = img_h
    img_mat = np.frombuffer(pDstData, dtype=np.uint8).reshape(img_h, img_w, 3)
    src_points = np.array([[400, 1000], [2000, 1000], [2000, 1250], [400, 1250]], dtype=np.float32)
    dst_points = np.array([[0, 0], [out_w, 0], [out_w, out_h], [0, out_h]], dtype=np.float32)
    trans_matrix = cv2.getPerspectiveTransform(src_points, dst_points)
    return cv2.warpPerspective(img_mat, trans_matrix, (out_w, out_h))


def crop_goldfinger_regular(bgr):
    """v4 核心: 模板法把金手指条裁成规整图。返回 (crop, info)
    同时把"原比例版"(1:1 像素, 不拉伸) 放到 info 外的全局缓存, 供落盘/目检"""
    global _LAST_NATURAL
    cr = get_cropper()
    if cr is None:
        h, w = bgr.shape[:2]
        return warp_goldfinger_topview(bgr.tobytes(), w, h, CANONICAL_W, CANONICAL_H), {"method": "legacy_no_template"}
    crop, info = cr.crop(bgr)
    _LAST_NATURAL = getattr(cr, "_last_natural", None)
    return crop, info


def GrabAndSaveImage(save: bool = True):
    """抓一帧 → 原图 → 模板法规整裁剪 → 裁剪图(+标注图取证)。

    v5: 图**总是**进内存(取图走内存); `save=True`(真检测)才落盘, `save=False`(只看一眼)不落盘。
    """
    global global_img_count
    _TL.save = bool(save)
    ppayload = ctypes.c_void_p()
    reVal = m_Device.SciCam_Grab(ppayload)
    if reVal != SCI_CAMERA_OK:
        print('Grab抓取帧失败，错误码：%d' % reVal)
        return None, None
    payloadAttribute = SCI_CAM_PAYLOAD_ATTRIBUTE()
    reVal = SciCam_Payload_GetAttribute(ppayload, payloadAttribute)
    if reVal != SCI_CAMERA_OK:
        print('Get payload attribute failed: %d' % reVal)
        m_Device.SciCam_FreePayload(ppayload)
        return None, None
    imgIsComplete = bool(payloadAttribute.isComplete)
    payloadMode = payloadAttribute.payloadMode
    imgPixelType = payloadAttribute.imgAttr.pixelType
    imgWidth = payloadAttribute.imgAttr.width
    imgHeight = payloadAttribute.imgAttr.height

    if not os.path.exists(SAVE_ROOT_DIR):
        os.makedirs(SAVE_ROOT_DIR, exist_ok=True)
    no = global_img_count
    origin_name = "Finger_Image_W{}_H{}_No_{}.png".format(imgWidth, imgHeight, no)
    save_file_param = os.path.join(SAVE_ROOT_DIR, origin_name)
    global_img_count += 1

    if not imgIsComplete or payloadMode != SciCamPayloadMode.SciCam_PayloadMode_2D:
        print("Image data is not complete or payload type error,")
        m_Device.SciCam_FreePayload(ppayload)
        return None, None

    imgData = ctypes.c_void_p()
    reVal = SciCam_Payload_GetImage(ppayload, imgData)
    if reVal != SCI_CAMERA_OK:
        print('Get image data failed: %d' % reVal)
        m_Device.SciCam_FreePayload(ppayload)
        return None, None

    dstImgSize = ctypes.c_int()
    mono_types = [
        SciCamPixelType.Mono1p, SciCamPixelType.Mono2p, SciCamPixelType.Mono4p,
        SciCamPixelType.Mono8s, SciCamPixelType.Mono8,
        SciCamPixelType.Mono10, SciCamPixelType.Mono10p,
        SciCamPixelType.Mono12, SciCamPixelType.Mono12p,
        SciCamPixelType.Mono14, SciCamPixelType.Mono16,
        SciCamPixelType.Mono10Packed, SciCamPixelType.Mono12Packed, SciCamPixelType.Mono14p
    ]
    is_mono = imgPixelType in mono_types
    target_type = SciCamPixelType.Mono8 if is_mono else SciCamPixelType.RGB8
    nch = 1 if is_mono else 3

    reVal = SciCam_Payload_ConvertImage(payloadAttribute.imgAttr, imgData, target_type, None, dstImgSize, True)
    top_path = None
    if reVal == SCI_CAMERA_OK:
        pDstData = (ctypes.c_ubyte * dstImgSize.value)()
        reVal = SciCam_Payload_ConvertImage(payloadAttribute.imgAttr, imgData, target_type, pDstData, dstImgSize, True)
        if reVal == SCI_CAMERA_OK:
            arr = np.frombuffer(pDstData, dtype=np.uint8).reshape(imgHeight, imgWidth, nch)
            bgr = arr if nch == 3 else cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)

            # ---- v4: 模板法规整裁剪 ----
            t_crop = time.time()
            crop, info = crop_goldfinger_regular(bgr)
            dt_crop = (time.time() - t_crop) * 1000
            q = info.get("quality", {}) or {}
            _mem_put(crop=crop, origin=bgr, natural=_LAST_NATURAL)   # v5: 内存帧
            top_name = "Finger_TopView_W{}_H{}_No_{}.png".format(crop.shape[1], crop.shape[0], no)
            top_path = os.path.join(SAVE_ROOT_DIR, top_name)
            _iw(top_path, crop)
            nat = _LAST_NATURAL
            if nat is not None:
                _iw(os.path.join(SAVE_ROOT_DIR, "Finger_CropNatural_W{}_H{}_No_{}.png".format(
                    nat.shape[1], nat.shape[0], no)), nat)
            anno_path = os.path.join(SAVE_ROOT_DIR, "Finger_CropAnno_No_{}.png".format(no))
            _iw(anno_path, annotate(bgr, info))
            print(f"  【金手指截取】{info.get('method')} 模式={GF_CROP_MODE} 尺寸={crop.shape[1]}x{crop.shape[0]} "
                  f"score={info.get('score')} 角度={info.get('angle')}° "
                  f"残余倾角={q.get('stripe_slope_px_per_1000')}px/1000 线残差={q.get('stripe_line_resid_px')}px "
                  f"金覆盖={q.get('gold_cover')} 高亮占比={q.get('bright_frac')} "
                  f"原比例={info.get('natural')} 耗时={dt_crop:.0f}ms"
                  + (f" ⚠️{info['warn']}" if info.get("warn") else ""))
            if SAVE_LEGACY_TOPVIEW:
                try:
                    leg = warp_goldfinger_topview(bgr.tobytes(), imgWidth, imgHeight, 1600, 220)
                    _iw(os.path.join(SAVE_ROOT_DIR, "Legacy_TopView_No_{}.png".format(no)), leg)
                except Exception:
                    pass
            with _PIC_LOCK:
                _LAST_CROP_INFO.clear()
                _LAST_CROP_INFO.update({"n": no, "t": time.time(), "crop_ms": round(dt_crop, 1),
                                        "crop_file": os.path.basename(top_path),
                                        "anno_file": os.path.basename(anno_path), **info})
            # v4.2: 金手指"区域"信息(原始图坐标系) + 对焦清晰度 —— 供状态空间/机械臂伺服使用
            try:
                reg = _region_payload(bgr, info)
                with _PIC_LOCK:
                    _LAST_REGION.clear()
                    _LAST_REGION.update(reg)
            except Exception as _e:
                print(f"  ⚠️ 区域信息计算失败: {_e}")
            # 原图落盘 (与 v3 一致; v5: save=False 时不写盘 —— 老倪「不检测时不用存那么多图」)
            if getattr(_TL, "save", True):
                reVal = SciCam_Payload_SaveImage(save_file_param, target_type, pDstData, imgWidth, imgHeight)
                if reVal == SCI_CAMERA_OK:
                    print('原图保存成功.', save_file_param)
            else:
                print('  (v5 未落盘: 只是取图/看一眼, 图留在内存)')

    m_Device.SciCam_FreePayload(ppayload)
    return save_file_param, top_path


global_img_count = 1

# 【异步】检测队列: 单worker串行处理, 模型只加载一次, API秒回
_detect_lock = threading.Lock()
_detect_count = 0
_detect_queue = []
_detect_thread = None


def _detect_worker_loop():
    global _detect_count
    while True:
        item = None
        with _detect_lock:
            if _detect_queue:
                item = _detect_queue.pop(0)
        if item is None:
            time.sleep(0.2)
            continue
        topview_path, origin_path, detect_type = item
        try:
            t0 = time.time()
            result = detector.detect(topview_path, detect_type=detect_type)
            dt_ms = (time.time() - t0) * 1000
            dets = result.get("detections", [])
            with _detect_lock:
                _detect_count += 1
                n = _detect_count
            print("\n" + "=" * 60)
            print(f"【检测结果 #{n}】{CAM_DESC} 推理耗时 {dt_ms:.0f}ms")
            print(f"  原图:   {origin_path}")
            print(f"  规整裁剪: {topview_path}")
            print(f"  缺陷数: {len(dets)}  {'❌ NG' if dets else '✅ OK'}")
            for i, d in enumerate(dets):
                cls = d.get("class_name", d.get("name", "?"))
                conf = d.get("confidence", d.get("conf", 0))
                bbox = d.get("bbox", d.get("box", "?"))
                print(f"    [{i+1}] {cls} conf={conf:.2f} bbox={bbox}")
            if result.get("saved_incoming"):
                print(f"  存档: {result['saved_incoming']}")
            with _PIC_LOCK:
                _LAST_RESULT.clear()
                _LAST_RESULT.update({
                    "n": n, "t": time.time(), "detect_type": detect_type,
                    "origin": origin_path, "topview": topview_path,
                    "defects": dets, "count": len(dets),
                    "verdict": ("NG" if dets else "OK"), "ms": round(dt_ms, 1),
                    "saved_incoming": result.get("saved_incoming", ""),
                })
            print("=" * 60 + "\n", flush=True)
        except Exception as e:
            print(f"【检测异常】{e}")
            traceback.print_exc()


def _ensure_detect_worker():
    global _detect_thread
    with _detect_lock:
        if _detect_thread is None or not _detect_thread.is_alive():
            _detect_thread = threading.Thread(target=_detect_worker_loop, daemon=True)
            _detect_thread.start()


def _enqueue_detect(topview_path, origin_path, detect_type):
    with _detect_lock:
        _detect_queue.append((topview_path, origin_path, detect_type))
    _ensure_detect_worker()


@app.route("/capture_detect", methods=["POST"])
def capture_detect_api():
    try:
        detect_type, channel_port = _resolve_detect_type_by_channel()
        if not detect_type:
            return jsonify({
                "code": 400,
                "msg": f"当前通道端口 {channel_port or '未知'} 未配置检测模型，可选端口: {sorted(PORT_TO_DETECT_TYPE.keys())}"
            }), 400

        print(f"\n===== 检测通道 {channel_port} · {CAM_DESC} =====")
        if not ensure_camera():
            return jsonify({"code": 500, "msg": "相机初始化失败"}), 500

        img_origin_path, img_topview_path = GrabAndSaveImage(save=True)   # 真检测: 落盘(模型要读文件)
        if img_origin_path is None or img_topview_path is None:
            print("⚠️ 抓帧失败, 尝试重连相机...")
            Close_Device()
            if ensure_camera():
                img_origin_path, img_topview_path = GrabAndSaveImage(save=True)
            if img_origin_path is None or img_topview_path is None:
                return jsonify({"code": 500, "msg": "图像抓取失败"}), 500

        print(f"   📸 已拍照 + 已规整裁剪, 投递检测队列 (不阻塞动作)")
        with _PIC_LOCK:
            _LAST_PIC.update({"origin": img_origin_path, "topview": img_topview_path, "t": time.time()})
        _prune_dir()                                # v5: 按保留上限清旧图(不检测时不再堆图)
        _enqueue_detect(img_topview_path, img_origin_path, detect_type)
        return jsonify({"code": 200, "msg": "success"})
    except Exception as e:
        print("==========接口异常完整堆栈==========")
        traceback.print_exc()
        try:
            StopGrabbing()
            Close_Device()
        except Exception:
            pass
        return jsonify({"code": 500, "msg": str(e)}), 500


@app.route("/picture", methods=["GET", "POST"])
def picture_api():
    """?kind=origin(默认,原始图)|crop(金手指拉长960方图)|natural(金手指原比例) · ?meta=1 返回JSON · ?grab=1 先抓一帧"""
    try:
        kind = (request.args.get("kind") or "origin").lower()   # origin(默认,原图) | crop(拉长960方图) | natural(原比例)
        if request.args.get("grab") in ("1", "true", "yes"):
            if not ensure_camera():
                return jsonify({"code": 500, "msg": "相机初始化失败"}), 500
            # v5: 取图默认**不落盘**(加 &save=1 才写盘) —— 不检测时不再堆图
            _sv = str(request.args.get("save", "")).lower() in ("1", "true", "yes")
            o, tv = GrabAndSaveImage(save=_sv)
            if o is None and tv is None:      # v5.1: 与 /capture_detect 同口径 —— 冷启/空闲后首抓会失败, 重连再抓一次
                print("⚠️ grab 抓帧失败, 重连相机后重试…")
                Close_Device()
                if ensure_camera():
                    o, tv = GrabAndSaveImage(save=_sv)
            if o is None and tv is None:
                return jsonify({"code": 500, "msg": "抓帧失败"}), 500
            with _PIC_LOCK:
                _LAST_PIC.update({"origin": o, "topview": tv, "t": time.time()})
        with _PIC_LOCK:
            snap = dict(_LAST_PIC)
        mem, mts = _mem_get(kind)
        if mem and not request.args.get("file"):
            return Response(mem, mimetype="image/jpeg",
                            headers={"Cache-Control": "no-store",
                                     "X-Frame-Source": "memory", "X-Frame-Age-S": "%.3f" % (time.time() - mts)})
        if kind in ("origin", "raw"):
            path = snap.get("origin")
        elif kind in ("natural", "natural_crop"):
            nats = sorted(glob.glob(os.path.join(SAVE_ROOT_DIR, "Finger_CropNatural_W*_No_*.png")),
                          key=os.path.getmtime)
            path = nats[-1] if nats else None
        else:
            path = snap.get("topview")
        if not path:
            path = snap.get("origin") or snap.get("topview")
        if not path or not os.path.exists(path):
            return jsonify({"code": 404, "msg": "尚无照片: 先 POST /capture_detect 或 GET /picture?grab=1"}), 404
        if request.args.get("meta") in ("1", "true", "yes"):
            return jsonify({"code": 200, "kind": kind, "file": os.path.basename(path),
                            "t": snap.get("t", 0), "size": os.path.getsize(path),
                            "origin": os.path.basename(snap.get("origin") or ""),
                            "topview": os.path.basename(snap.get("topview") or ""),
                            "crop_info": _LAST_CROP_INFO, "last_result": _LAST_RESULT})
        with open(path, "rb") as fp:
            data = fp.read()
        mt = "image/png" if path.lower().endswith(".png") else "image/jpeg"
        return Response(data, mimetype=mt, headers={"Cache-Control": "no-store"})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"code": 500, "msg": str(e)}), 500


@app.route("/last_result", methods=["GET"])
def last_result_api():
    with _PIC_LOCK:
        snap = dict(_LAST_RESULT)
    if not snap:
        return jsonify({"code": 404, "msg": "尚无检测结果"}), 404
    snap["code"] = 200
    return jsonify(snap)


@app.route("/crop_info", methods=["GET"])
def crop_info_api():
    """最近一次金手指裁剪的规整度指标 (score/残余倾角/线残差/金覆盖率/角度扫描曲线)"""
    with _PIC_LOCK:
        snap = dict(_LAST_CROP_INFO)
    if not snap:
        return jsonify({"code": 404, "msg": "尚无裁剪记录"}), 404
    snap["code"] = 200
    snap["mode"] = GF_CROP_MODE
    snap["template"] = os.path.basename(TEMPLATE_PNG)
    return jsonify(snap)


@app.route("/region", methods=["GET"])
def region_api():
    """金手指【区域】信息(原始图坐标系): 定向框/四边形/外接框 + 对焦清晰度 focus + 裁剪质量
    —— 状态空间 YOLO 目标检测模块 / 机械臂伺服引导 直接消费这个接口
    ?grab=1 先抓一帧再返回 (不传则返回最近一次拍照的结果)"""
    try:
        if request.args.get("grab") in ("1", "true", "yes"):
            if not ensure_camera():
                return jsonify({"code": 500, "msg": "相机初始化失败"}), 500
            # v5: 取图默认**不落盘**(加 &save=1 才写盘)
            _sv = str(request.args.get("save", "")).lower() in ("1", "true", "yes")
            o, tv = GrabAndSaveImage(save=_sv)
            if o is None and tv is None:      # v5.1: 与 /capture_detect 同口径 —— 冷启/空闲后首抓会失败, 重连再抓一次
                print("⚠️ grab 抓帧失败, 重连相机后重试…")
                Close_Device()
                if ensure_camera():
                    o, tv = GrabAndSaveImage(save=_sv)
            if o is None and tv is None:
                return jsonify({"code": 500, "msg": "抓帧失败"}), 500
            with _PIC_LOCK:
                _LAST_PIC.update({"origin": o, "topview": tv, "t": time.time()})
        with _PIC_LOCK:
            snap = dict(_LAST_REGION)
        if not snap:
            return jsonify({"code": 404, "msg": "尚无区域信息: 先 POST /capture_detect 或 GET /region?grab=1"}), 404
        snap["code"] = 200
        snap["mode"] = GF_CROP_MODE
        snap["template"] = os.path.basename(TEMPLATE_PNG)
        snap["target_note"] = "与示教基准的偏差由 tools/aoi_gold_servo.py 计算并下发 L2 运动"
        return jsonify(snap)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"code": 500, "msg": str(e)}), 500


@app.route("/storage", methods=["GET"])
def storage_api():
    """看存了多少图 / 占多少磁盘, 以及保留上限 (老倪: 不检测时别存那么多)。"""
    try:
        d = _dir_stat()
        d["code"] = 200
        d["keep_canon"] = KEEP_CANON
        d["keep_origin"] = KEEP_ORIGIN
        d["mem"] = {"crop_kb": round(len(_MEM.get("crop") or b"") / 1024.0, 1),
                    "origin_kb": round(len(_MEM.get("origin") or b"") / 1024.0, 1),
                    "age_s": round(time.time() - (_MEM.get("ts") or 0), 1)}
        return jsonify(d)
    except Exception as e:                                                    # noqa: BLE001
        return jsonify({"code": 500, "msg": str(e)}), 500


@app.route("/prune", methods=["POST", "GET"])
def prune_api():
    """清旧图: POST 真删(按保留上限), GET 只报告(不删)。"""
    try:
        before = _dir_stat()
        if request.method == "GET":
            return jsonify({"code": 200, "dry": True, "before": before})
        n = _prune_dir()
        after = _dir_stat()
        print("  【清理】删除 %d 张旧图; 现在 %d 张 / %.1fMB" % (n, after["files_total"], after["mb_total"]))
        return jsonify({"code": 200, "removed": n, "before": before, "after": after})
    except Exception as e:                                                    # noqa: BLE001
        return jsonify({"code": 500, "msg": str(e)}), 500


def run_flask(port=10082):
    app.run(host="0.0.0.0", port=int(port), debug=False)


def _port_available(port):
    """启动前自检: 端口是否被占(通常是旧程序还在跑)。带 SO_REUSEADDR, 不会把 TIME_WAIT 误判成占用"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("0.0.0.0", int(port)))
        return True
    except OSError as e:
        print(f"❌ 端口 {port} 无法绑定: {e}")
        print(f"   → 通常是旧程序(如 v3)还占着 {PRODUCTION_PORT}; 先停掉它再启动本程序。")
        print(f"   → Windows 查占用: netstat -ano | findstr :{port}    再 taskkill /PID <pid> /F")
        return False
    finally:
        s.close()


if __name__ == "__main__":
    _port = int(os.environ.get("AOI_PORT") or PRODUCTION_PORT)
    if "--port" in sys.argv:
        _port = int(sys.argv[sys.argv.index("--port") + 1])
    # 通道→模型 映射按"实际运行的端口"注册 (产线固定 10082; 换端口自测时通道也不会报 400)
    PORT_TO_DETECT_TYPE[str(_port)] = "gf"
    print(f"金手指检测相机程序启动({VERSION})，端口{_port}，gf金手指模型，相机常驻模式；"
          f"裁剪={GF_CROP_MODE} 模板={os.path.basename(TEMPLATE_PNG)} "
          f"规范化={CANONICAL_W}x{'auto(保比例)' if KEEP_ASPECT else CANONICAL_H}")
    print(f"   通道映射: {PORT_TO_DETECT_TYPE}  (产线调用端口 = {PRODUCTION_PORT})")
    if _port != PRODUCTION_PORT:
        print(f"   ⚠️ 当前不是产线端口 {PRODUCTION_PORT}(仅在换端口自测时这样用); 产线请用 {PRODUCTION_PORT}")
    if not _port_available(_port):
        sys.exit(1)
    get_cropper()      # 启动即加载模板 (缺模板只报警不影响启动)
    try:
        t_pre = threading.Thread(target=ensure_camera, daemon=True)
        t_pre.start()
    except Exception:
        pass
    _ensure_detect_worker()
    t = Thread(target=run_flask, args=(_port,))
    t.start()
    t.join()
