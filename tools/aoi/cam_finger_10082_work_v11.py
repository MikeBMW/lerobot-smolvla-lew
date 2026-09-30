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
import hashlib
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

VERSION = "v11"
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
_LAST_MODELIN = ""          # v10: 本轮送检的模型输入文件(960x960 同帧派生图, 在 %TEMP%, 检测完即删)
_LAST_SHADOW = ""           # v10: 本轮影子对照的临时图(判据图压 960x960; 空=不跑)
# 🆕 v11 (老倪: 「哪里是调用 YOLO 模型, 我看看实际输入给模型的图片, 和 YOLO 的返回值」):
#   把**喂给 detector.detect() 的同一份像素**留在内存 + 一个无损坏的 PNG 取图口, 供现场/自检核对:
#   GET /picture?kind=modelin  (= 模型实际吃的那张, 逐位相同; ?meta=1 给 md5/尺寸/来源)
_LAST_MODELIN_IMG = None
_LAST_MODELIN_META = {}
# 影子对照张数: 默认前 10 张(攒同口径对照数据), 之后自动停。设 AOI_AB_PAIRS=0 可完全关掉。
_AB_LEFT = int(os.environ.get("AOI_AB_PAIRS", "10"))
_AB_DONE = 0
TEMP_DIR = os.environ.get("TEMP") or os.environ.get("TMP") or "."


# ───────────────────── v5: 内存帧 + 按需落盘 + 保留上限 ─────────────────────
# ───────────────────── v6: 取图两路由补"重连再抓"(与 /capture_detect 同口径), 版本号统一 — 2026-09-27 ─────────────────────
# 老倪 2026-09-27: 「不检测的时候, 不用保存那么多图片」⇒
#   · 只"看一眼/取图"(GET /picture?grab=1) 一律**不落盘**, 图只留内存(编码后几百 KB);
#   · 只有真检测(POST /capture_detect, 模型要读文件)才落盘, 落完按上限清旧图;
#   · 诊断用的额外图(标注图/legacy)默认不写, 要写设 AOI_SAVE_DEBUG=1;
#   · GET /storage 看占用/张数, POST /prune 手动清。
AOI_SAVE_DEBUG = os.environ.get("AOI_SAVE_DEBUG", "0").strip().lower() in ("1", "true", "yes")
KEEP_CANON = int(os.environ.get("AOI_KEEP_CANON", "400"))
KEEP_ORIGIN = int(os.environ.get("AOI_KEEP_ORIGIN", "120"))
_PRUNE_PATTERNS = [("Finger_TopView_W*_H*_No_*.png", KEEP_CANON),   # v7: 这张现在是判据图口径
                   ("Finger_Image_W*_H*_No_*.png", KEEP_ORIGIN),
                   # v8: 老倪「Finger_ModelIn_…就不要了」⇒ keep=0, 自动清掉历史遗留文件(不再产出)
                   ("Finger_ModelIn_W*_H*_No_*.png", 0),
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


# ═══════════ v7 新增: 「判据图」渲染 (从 4060 侧 tools/aoi_exposure_fix.py 逐条移植) ═══════════
# 老倪 2026-09-29: 「在工控机保存的 topview 图片…改成判据图的样子」
#   口径与 4060 网页判据图完全一致(同一张原图 → 逐像素同源, 实测同尺寸灰度相关 r=1.000):
#     过曝带切除 + 只留金手指条 + 列方向裁死白列 + 短边×2 + 按实测倾角反旋(白底) + 定尺 900x332
#   ⚠️ 灰度加权是 0.299R+0.587G+0.114B ⇒ 进出各转一次颜色(喂 BGR 会裁错行 —— 4060 侧踩过的坑)
_SAT_LEVEL = 250                 # 判"饱和像素"的灰度门限
_JR_K = 2.0                      # 只把短边拉 k 倍(长边不动)
_JUDGE_HW = (900, 332)           # 判据图定尺(内容按比例适配, 逐帧不跳动)
_JR_DEF = {"sat_thr": 0.40, "edge_pct": 92, "min_h": 20, "merge_gap": 6, "pad": 8, "cliff_win": 15}


def _jr_gray(rgb):
    a = np.asarray(rgb)
    if a.ndim == 3:
        g = (0.299 * a[:, :, 0] + 0.587 * a[:, :, 1] + 0.114 * a[:, :, 2])
    else:
        g = a.astype(np.float32)
    return g.astype(np.float32)


def _jr_runs(mask, merge_gap):
    out, cur = [], None
    for y, m in enumerate(mask):
        if m:
            cur = [y, y] if cur is None else [cur[0], y]
        elif cur is not None:
            out.append(cur)
            cur = None
    if cur is not None:
        out.append(cur)
    merged = []
    for r in out:
        if merged and r[0] - merged[-1][1] <= merge_gap:
            merged[-1][1] = r[1]
        else:
            merged.append([r[0], r[1]])
    return merged


def _jr_row_stats(rgb):
    g = _jr_gray(rgb)
    gx = np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0))
    return {"mean": g.mean(axis=1), "sat": (g >= _SAT_LEVEL).mean(axis=1),
            "edge": gx.mean(axis=1), "H": g.shape[0], "W": g.shape[1],
            "sat_all": float((g >= _SAT_LEVEL).mean()), "mean_all": float(g.mean())}


def _jr_col_stats(rgb):
    g = _jr_gray(rgb)
    gy = np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1))
    return {"sat": (g >= _SAT_LEVEL).mean(axis=0), "edge": gy.mean(axis=0),
            "H": g.shape[0], "W": g.shape[1]}


def _jr_trim_x(rgb, sat_thr=0.60, min_w_frac=0.20, merge_gap=24):
    cs = _jr_col_stats(rgb)
    ok = cs["sat"] <= sat_thr
    runs = [r for r in _jr_runs(ok, merge_gap) if (r[1] - r[0] + 1) >= int(cs["W"] * min_w_frac)]
    if not runs:
        return 0, cs["W"], {"trimmed": False, "why": "没有合格列区间 → 保持全宽", "col_sat_max": round(float(cs["sat"].max()), 3)}
    best = max(runs, key=lambda r: (r[1] - r[0]))
    return best[0], best[1] + 1, {"trimmed": True, "x_span": [best[0], best[1] + 1],
                                  "dropped_cols": [0, best[0]] if best[0] else [],
                                  "col_sat_before_max": round(float(cs["sat"].max()), 3)}


def _jr_find_cliff(prof):
    d = np.diff(prof["mean"])
    w = _JR_DEF["cliff_win"]
    if len(d) <= w:
        return {"y": -1, "jump": 0.0}
    k = int(np.argmax(np.convolve(d, np.ones(w), "valid")))
    return {"y": k, "jump": float(d[k:k + w].mean())}


def _jr_stretch_short(rgb, k=_JR_K):
    a = np.asarray(rgb)
    h, w = a.shape[:2]
    if k is None or abs(float(k) - 1.0) < 1e-6:
        return a, {"k": 1.0, "axis": "none", "out_hw": [h, w], "in_hw": [h, w], "stretch_desc": "无拉长 (×1.0)"}
    if h <= w:
        out = (w, max(1, int(round(h * float(k)))))
        axis = "h"
    else:
        out = (max(1, int(round(w * float(k)))), h)
        axis = "w"
    img = cv2.resize(a, out, interpolation=cv2.INTER_CUBIC)
    _si, _so = (h, out[1]) if axis == "h" else (w, out[0])
    return img, {"k": round(float(k), 2), "axis": axis, "out_hw": [out[1], out[0]], "in_hw": [h, w],
                 "stretch_desc": "短边%s %d→%d (×%.1f) · 长边不动" % ("高" if axis == "h" else "宽", _si, _so, float(k))}


def _jr_analyze(rgb):
    prof = _jr_row_stats(rgb)
    cliff = _jr_find_cliff(prof)
    thr = float(np.percentile(prof["edge"], _JR_DEF["edge_pct"]))
    bands = [r for r in _jr_runs(prof["edge"] >= thr, _JR_DEF["merge_gap"]) if r[1] - r[0] + 1 >= _JR_DEF["min_h"]]
    cands = []
    for a, b in bands:
        cands.append({"y0": a, "y1": b, "h": b - a + 1,
                      "sat": round(float(prof["sat"][a:b + 1].mean()), 3),
                      "edge": round(float(prof["edge"][a:b + 1].mean()), 2),
                      "ok": float(prof["sat"][a:b + 1].mean()) <= _JR_DEF["sat_thr"]})
    return {"H": prof["H"], "W": prof["W"], "sat_all": round(prof["sat_all"], 4),
            "mean_all": round(prof["mean_all"], 1), "cliff": cliff, "gold_candidates": cands}


def _jr_clean(rgb, sat_thr=None, pad=None, return_natural=False, k=_JR_K):
    """原始图 → 无过曝条带(可另返原比例版)。找不到合格条带 ⇒ 如实返回 None, 不硬裁一张错的。"""
    sat_thr = _JR_DEF["sat_thr"] if sat_thr is None else sat_thr
    pad = _JR_DEF["pad"] if pad is None else pad
    prof = _jr_row_stats(rgb)
    a = _jr_analyze(rgb)
    ok = [c for c in a["gold_candidates"] if c["sat"] <= sat_thr]
    if not ok:
        return None, {"ok": False, "err": "没有找到未过曝的金手指条带 (全图都可能过曝)",
                      "sat_all": a["sat_all"], "analyze": a}
    best = max(ok, key=lambda c: c["edge"])
    y0 = max(0, best["y0"] - pad)
    y1 = min(prof["H"], best["y1"] + 1 + pad)
    band = np.asarray(rgb)[y0:y1]
    x0, x1, xmeta = _jr_trim_x(band)
    band = band[:, x0:x1]
    clean, kmeta = _jr_stretch_short(band, k)
    sat_dropped = int((prof["sat"] > sat_thr).sum())
    meta = {"ok": True, "kept_rows": [y0, y1], "kept_h": y1 - y0, "src_h": prof["H"], "src_w": prof["W"],
            "dropped_sat_rows": sat_dropped, "dropped_pct": round(sat_dropped / prof["H"] * 100, 1),
            "sat_before": round(a["sat_all"], 4),
            "sat_after": round(float((_jr_gray(clean) >= _SAT_LEVEL).mean()), 4),
            "cliff": a["cliff"], "candidate": best, "out": list(clean.shape[:2])[::-1], **kmeta,
            "x_trim": xmeta, "col_sat_after_max": round(float((_jr_gray(clean) >= _SAT_LEVEL).mean(axis=0).max()), 3),
            "rule": "sat≤%s 且 边缘密集(P%d) 且 高≥%d行, 上下留 %d 行" % (sat_thr, _JR_DEF["edge_pct"], _JR_DEF["min_h"], pad)}
    if return_natural:
        meta["natural"] = band
    return clean, meta


def render_judge(bgr, deskew_deg=0.0, hw=_JUDGE_HW, k=_JR_K):
    """工控机原图(BGR) → **判据图**(BGR, 定尺 hw) —— 与 4060 网页判据图同一口径。

    返回 (judge_bgr | None, meta): meta 如实记录裁掉多少过曝行/保留行区间/列裁/倾角/定尺/饱和比。
    """
    clean_rgb, meta = _jr_clean(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), return_natural=True, k=k)
    if clean_rgb is None:
        return None, meta
    band = meta.get("natural") if meta.get("natural") is not None else clean_rgb
    img = cv2.cvtColor(np.asarray(band), cv2.COLOR_RGB2BGR)
    meta = dict(meta or {})
    if abs(float(deskew_deg)) > 0.05:
        h0, w0 = img.shape[:2]
        M = cv2.getRotationMatrix2D((w0 / 2.0, h0 / 2.0), -float(deskew_deg), 1.0)
        img = cv2.warpAffine(img, M, (w0, h0), flags=cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
        meta["deskew_deg"] = round(float(deskew_deg), 3)
    if hw:
        img = cv2.resize(img, (int(hw[0]), int(hw[1])), interpolation=cv2.INTER_LINEAR)
        meta["fix_hw"] = [int(hw[0]), int(hw[1])]
    meta["out"] = [int(img.shape[1]), int(img.shape[0])]
    meta["sat_after"] = round(float((_jr_gray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)) >= _SAT_LEVEL).mean()), 4)
    return img, meta


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
            # 🆕 v7 (2026-09-29 老倪「在工控机保存的 topview 图片…改成判据图的样子」):
            #   · 落盘/对外展示的 **topview = 判据图口径**(过曝切除+只留金手指条+列裁+短边×2+反倾角+定尺900x332)
            # 🆕 v8 (2026-09-30 老倪「Finger_ModelIn_…就不要了; 模型用的是这个图片; 确认模型使用的是不是 topview」):
            #   · **只落一张图** = Finger_TopView_*(判据图); Finger_ModelIn_* 不再写盘(老文件按上限自动清掉)
            #   · 影子对照: 同帧老口径 960 方图也跑一遍, 临时图 %TEMP% 跑完即删, 结果进 /last_result
            # 🆕 v9 (2026-09-30 现场实测修正): v8 让模型**直接吃 900x332 判据图** ——
            #      在工控机 app 里**卡死**(同一张图: app 进程 CPU 空转 3 分钟不返回、incoming 不再落图、
            #      %TEMP% 里堆了 ~90 张没删的临时图; 换 venv 解释器单独跑同一张只要 0.7s)
            #      ⇒ 该口径在工控机运行环境里**不可用**(检测通道会死)。
            #      改回: 模型吃**同帧派生的 960x960 方图**(与 v6/v7 逐位同口径, 保证召回), 但**不落盘**:
            #      临时图写 %TEMP%, 检测完即删 ⇒ goldfinger_images 里只剩判据图一张。
            #      影子对照改成: 用**判据图压成 960x960** 再喂一次(方形, 不走那条会卡死的路),
            #      两个口径同帧对照(自然条带 ×13.7  vs  判据图含上下内容 ⇒ 谁更准用数据说话)。
            t_j = time.time()
            judge, jmeta = render_judge(bgr, deskew_deg=float(info.get("angle") or 0.0))
            dt_j = (time.time() - t_j) * 1000
            model_in = crop                    # 主口径 960x960(金手指条带拉伸, 与 v6/v7 逐位同口径)
            if judge is None:
                print("  ⚠️ 判据图渲染失败(%s) ⇒ topview 回退为规整图口径(不硬裁一张错的)" % jmeta.get("err"))
                judge = crop
            _mem_put(crop=judge, origin=bgr, natural=_LAST_NATURAL)   # v5: 内存帧(kind=crop 给的就是判据图)
            top_name = "Finger_TopView_W{}_H{}_No_{}.png".format(judge.shape[1], judge.shape[0], no)
            top_path = os.path.join(SAVE_ROOT_DIR, top_name)
            _iw(top_path, judge)               # ✅ 唯一落盘的一张 = 判据图(不再写 Finger_ModelIn_*)
            # 主口径输入(960x960): 临时图, 检测完即删 ⇒ 目录里不留第二张
            # ⚠️ 2026-09-30 踩坑(v9⇒v10): 这两段临时图代码在 GrabAndSaveImage 里, 而"只看一眼"的
            #    grab(页面 0.5s 一次)也走这个函数 ⇒ 每次 grab 写 2 张临时图却没人删 ⇒ 实测 9 分钟
            #    在 %TEMP% 堆了 2180 张。现在**只有 save=True(真检测, 会入队)才写**, 并且每次真检测
            #    先做一次 _sweep_temp() 清残留(只碰我们自己的三个前缀, 只删 60s 以上的)。
            if save:
                _sweep_temp()
            mi_path = None
            if save and model_in is not None:
                try:
                    mi_path = os.path.join(TEMP_DIR, "zmax_main_960_No_%s.png" % no)
                    cv2.imwrite(mi_path, model_in)
                except Exception as e:                                     # noqa: BLE001
                    mi_path = None
                    print("  ⚠️ 主口径临时图写失败: %s" % e)
            # 影子对照: 判据图压成 960x960(方形, 避开那条会卡死的路) ⇒ 同帧两口径对照
            sh_path = None                     # 影子对照的临时图(在 %TEMP%, 检测完删)
            shadow_left = max(0, _AB_LEFT - _AB_DONE)
            if save and judge is not None and shadow_left > 0:
                try:
                    sh_path = os.path.join(TEMP_DIR, "zmax_ab_judge960_No_%s.png" % no)
                    cv2.imwrite(sh_path, cv2.resize(judge, (960, 960), interpolation=cv2.INTER_LINEAR))
                except Exception as e:                                     # noqa: BLE001
                    sh_path = None
                    print("  ⚠️ 影子对照临时图写失败: %s" % e)
            global _LAST_MODELIN, _LAST_SHADOW, _LAST_MODELIN_IMG, _LAST_MODELIN_META
            _LAST_MODELIN = mi_path or top_path
            _LAST_SHADOW = sh_path or ""
            if save and model_in is not None:      # 🆕 v11: 留一份"模型实际吃的那份像素"在内存
                _LAST_MODELIN_IMG = model_in
                _LAST_MODELIN_META = {"n": no, "t": time.time(),
                                      "hw": [int(model_in.shape[1]), int(model_in.shape[0])],
                                      "md5": hashlib.md5(np.ascontiguousarray(model_in).tobytes()).hexdigest(),
                                      "src": "crop_goldfinger_regular(模板法规整裁剪) → 960x960",
                                      "fed_to": "detector.detect(path=<该临时文件>, detect_type=<本端口类型: gf>)",
                                      "note": "detector 读的是 %TEMP% 下的同名临时文件, 检测完即删; 这里留的是同一份像素"}
            nat = _LAST_NATURAL
            if nat is not None:
                _iw(os.path.join(SAVE_ROOT_DIR, "Finger_CropNatural_W{}_H{}_No_{}.png".format(
                    nat.shape[1], nat.shape[0], no)), nat)
            anno_path = os.path.join(SAVE_ROOT_DIR, "Finger_CropAnno_No_{}.png".format(no))
            _iw(anno_path, annotate(bgr, info))
            print(f"  【判据图】与网页判据图同口径: 保留行={jmeta.get('kept_rows')} ({jmeta.get('kept_h')}行) "
                  f"切过曝行={jmeta.get('dropped_sat_rows')}({jmeta.get('dropped_pct')}%) "
                  f"列裁={jmeta.get('x_trim', {}).get('x_span')} 倾角={jmeta.get('deskew_deg')}° "
                  f"定尺={jmeta.get('fix_hw')} 饱和={jmeta.get('sat_after')} 耗时={dt_j:.0f}ms")
            print("  【送检】模型吃 960x960 方图(同帧派生, 不落盘) -> %s" % os.path.basename(mi_path or ""))
            print("  【落盘】只留判据图 -> %s (%dx%d)" % (top_name, judge.shape[1], judge.shape[0]))
            if sh_path:
                print("  【影子对照】判据图压 960 也跑一遍(临时图, 跑完删) 剩余 %d 张" % (shadow_left - 1))
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
                                        "model_input_file": os.path.basename(top_path),   # v8: 模型吃的=判据图
                                        "judge_ms": round(dt_j, 1),
                                        "judge": {k: jmeta.get(k) for k in
                                                  ("out", "kept_rows", "kept_h", "dropped_sat_rows", "dropped_pct",
                                                   "sat_before", "sat_after", "x_trim", "k", "fix_hw", "deskew_deg")},
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
        # v8: (判据图=模型输入, 原图, 类型, 台账用判据图, 影子对照临时图)
        topview_path, origin_path, detect_type, judge_path, shadow_path = (list(item) + [None] * 5)[:5]
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
            print(f"  模型输入(送检)=960x960 同帧派生(不落盘): {topview_path}")
            print(f"  判据图(唯一落盘/展示): {judge_path or ''}")
            print(f"  缺陷数(topview 口径): {len(dets)}  {'❌ NG' if dets else '✅ OK'}")
            for i, d in enumerate(dets):
                cls = d.get("class_name", d.get("name", "?"))
                conf = d.get("confidence", d.get("conf", 0))
                bbox = d.get("bbox", d.get("box", "?"))
                print(f"    [{i+1}] {cls} conf={conf:.2f} bbox={bbox}")
            if result.get("saved_incoming"):
                print(f"  存档: {result['saved_incoming']}")
            # ── v8 影子对照: 同帧再跑一遍老口径 960 方图(临时图, 跑完删) ──
            sh = None
            global _AB_DONE
            if shadow_path and os.path.exists(shadow_path):
                try:
                    t1 = time.time()
                    r2 = detector.detect(shadow_path, detect_type=detect_type)
                    d2 = r2.get("detections", []) or []
                    sh = {"input": "判据图压 960x960", "input_file": os.path.basename(shadow_path),
                          "count": len(d2), "verdict": ("NG" if d2 else "OK"), "ms": round((time.time() - t1) * 1000, 1),
                          "defects": d2}
                    print("  影子对照(判据图压 960 口径): 缺陷数 %d %s  %sms  %s" %
                          (len(d2), "❌ NG" if d2 else "✅ OK", sh["ms"],
                           "与主口径一致" if (len(d2) > 0) == (len(dets) > 0) else "⚠️ 两口径判决不同(需人工看)"))
                    _AB_DONE += 1
                except Exception as e:                                     # noqa: BLE001
                    print("  ⚠️ 影子对照失败: %s" % e)
                finally:
                    try:
                        os.remove(shadow_path)          # 临时图不留(老倪: 只留判据图)
                    except OSError:
                        pass
            # 主口径临时图同样删掉(只删我们自己写的临时图, 绝不碰落盘的判据图)
            if os.path.basename(topview_path or "").startswith("zmax_main_960"):
                try:
                    os.remove(topview_path)
                except OSError:
                    pass
            v_primary = "NG" if dets else "OK"
            v_shadow = (sh or {}).get("verdict")
            v_union = "NG" if (v_primary == "NG" or v_shadow == "NG") else "OK"
            with _PIC_LOCK:
                _LAST_RESULT.clear()
                _LAST_RESULT.update({
                    "n": n, "t": time.time(), "detect_type": detect_type,
                    "origin": origin_path,
                    "topview": judge_path or topview_path,      # v7: topview = 判据图(老倪看的那张)
                    "model_input": topview_path,                # v9: 模型真正吃的那张(960x960, 同帧派生)
                    "model_input_kind": "960x960 方图(同帧派生, 检测完即删; 与 v6/v7 同口径)",
                    "model_input_md5": (dict(_LAST_MODELIN_META).get("md5") or ""),   # 🆕 v11: 与 /picture?kind=modelin 逐位同源
                    "judge": judge_path or "",
                    "defects": dets, "count": len(dets),
                    # v8: verdict = 并集(topview 口径 ‖ 影子口径 任一 NG 即 NG ⇒ 不漏判);
                    #     单口径结果也分别报, 便于攒同口径对照数据。
                    "verdict": v_union, "verdict_topview": v_primary, "verdict_shadow": v_shadow,
                    "shadow": sh,
                    "ms": round(dt_ms, 1),
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


def _sweep_temp(max_age_s=60):
    """清掉我们自己在 %TEMP% 里的残留临时图。

    只碰三个前缀(zmax_main_960_* / zmax_ab_judge960_* / zmax_ab_960_*), 且只删 60s 之前的
    —— 免得把"正在被检测器读的那一张"删掉(Windows 下删被占用的文件会失败, 也就自然跳过了)。
    """
    try:
        now = time.time()
        for pat in ("zmax_main_960_*.png", "zmax_ab_judge960_*.png", "zmax_ab_960_*.png"):
            for p in glob.glob(os.path.join(TEMP_DIR, pat)):
                try:
                    if now - os.path.getmtime(p) > max_age_s:
                        os.remove(p)
                except OSError:
                    pass
    except Exception:                                                          # noqa: BLE001
        pass


def _enqueue_detect(model_path, origin_path, detect_type, judge_path=None, shadow_path=None):
    """v8: 入队的是**判据图本身**(模型直接吃它); shadow_path=老口径 960 临时图(对照用, 跑完删)。"""
    with _detect_lock:
        _detect_queue.append((model_path, origin_path, detect_type, judge_path, shadow_path))
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
        _enqueue_detect(_LAST_MODELIN or img_topview_path, img_origin_path, detect_type,
                        judge_path=img_topview_path, shadow_path=(_LAST_SHADOW or None))
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
        kind = (request.args.get("kind") or "origin").lower()   # origin|crop(判据图/内存帧)|natural|modelin(模型实际吃的那张)
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
        if kind == "modelin":                     # 🆕 v11: 模型实际吃的那张(= 喂 YOLO 的同一份像素)
            with _PIC_LOCK:
                _img = _LAST_MODELIN_IMG
                _meta = dict(_LAST_MODELIN_META)
            if _img is None:
                return jsonify({"code": 404, "msg": "尚无模型输入图: 先 POST /capture_detect"}), 404
            if str(request.args.get("meta", "")).lower() in ("1", "true", "yes"):
                return jsonify(_meta)
            ok_enc, buf = cv2.imencode(".png", _img)   # PNG 无损: 取回来解码后与喂进去的逐位相同
            if not ok_enc:
                return jsonify({"code": 500, "msg": "PNG 编码失败"}), 500
            resp = Response(buf.tobytes(), mimetype="image/png")
            resp.headers["X-Zmax-Modelin-Md5"] = str(_meta.get("md5", ""))
            resp.headers["X-Zmax-Modelin-HW"] = "%sx%s" % tuple(_meta.get("hw", ["?", "?"]))
            resp.headers["X-Zmax-Modelin-N"] = str(_meta.get("n", ""))
            return resp
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


def _already_serving(port, timeout=3.0):
    """v6.1: 该端口上是否已有 AOI 服务在应答(看 /storage 面, 只有 v5+ 才有)。
            用于启动自检 —— Windows 的 SO_REUSEADDR 会让第二个 socket 也 bind 成功,
            于是手动起的第二份会"看起来起来了", 然后被每分钟守护清掉(像自己退出)。"""
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/storage" % int(port), timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False

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
    if _already_serving(_port):
        print(f"❌ 端口 {_port} 上已经有 AOI 服务在应答(/storage 200) —— 正式实例正在跑。")
        print("   → 本程序由计划任务托管(开机自启 + 每分钟自愈), **不要手动再起第二份**。")
        print(f"   → 要验证: curl -X POST http://127.0.0.1:{_port}/capture_detect   (GET 不触发动作)")
        sys.exit(3)
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
