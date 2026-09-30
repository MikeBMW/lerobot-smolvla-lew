#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z-MAX 表面检测 AOI 程序 · 优化版 v6 (端口 10083)   ——— 2026-09-23 静静

⚠️ 本文与 **V2 完全隔离**: 新文件名, 不改 V2 的任何文件/接口/端口; 部署时"先停 V2 → 再启 V4",
   相机独占(D265250099), 出问题可原样回到 V2。
   (金手指通道 10082 的 V4 见 cam_finger_10082_work_v4.py, 两者结构一致)

v6 = v5 + 取图两路由(/picture?grab=1 · /region?grab=1)补"冷启/空闲后首抓失败→重连再抓", 与 /capture_detect 同口径 (2026-09-27)

v5 相对 v4: 取图走**内存**(GET /picture 不再读盘) · GET /picture?grab=1 默认**不落盘**
  (要存加 &save=1) · 真检测才落盘且按上限清旧图(AOI_KEEP_CANON/AOI_KEEP_ORIGIN) ·
  诊断图默认不写(AOI_SAVE_DEBUG=1 才写) · 新增 GET /storage 与 POST /prune。

相对 V2 的升级点 (把金手指 v4 的成熟做法搬到表面通道):
  ★ 接口补齐: 除 POST /capture_detect 外, 增加
      GET /picture        原图(默认) / ?kind=crop 规范化图(喂模型的 1280 方图, 保比例 letterbox)
      GET /last_result    判决: {verdict: OK/NG, count, defects[{class_name,conf,bbox}], ms, origin, detect}
      GET /crop_info      规范图指标 (尺寸/letterbox 比例/亮度/对焦清晰度 Laplacian 方差)
      GET /picture?meta=1 JSON 元信息 (不带图字节)
    → 本机(GUI/技能清单)终于能看到图 + 拿到判决, 不必再看工控机终端
  ★ 规范图口径: config.yaml housing 的 yolo.imgsz = **1280** → 原图按比例 letterbox 到 1280x1280
    (表面是全幅缺陷检测, **不拉伸变形**; 这点与金手指的 21:1 纵向拉长不同)
  ★ 相机常驻 + 单 worker 异步队列: /capture_detect 秒回, 模型只加载一次 (原版实测推理 ~7.8s)
  ★ 判决/图像/指标 全部落盘 + 打印自证 (原图、规范图、存档路径)

依赖 (与 V2 同环境): SciCam_* / SciCam_class / yolo_detector (加密权重 besthousing_zh0128.pt.enc)
模型与类别由 yolo_detector/config.yaml 的 detectors.housing 决定 (conf 0.25 / iou 0.45 / classes [0,1,2,3])

用法 (在工控机):
  python surface_10083_work_v4.py            # 默认 10083
  # 端口被占会直接报错退出 (不会和 V2 抢相机/端口)
  curl -X POST http://127.0.0.1:10083/capture_detect
  curl        http://127.0.0.1:10083/picture?kind=crop -o out.png
  curl        http://127.0.0.1:10083/last_result
"""
import ctypes
import glob
import hashlib
import os
import socket
import struct
import sys
import threading
import time
import traceback
from threading import Thread

import cv2
import numpy as np
from flask import Flask, Response, jsonify, request

from SciCam_class import *
from SciCamErrorDefine_const import *
from SciCamInfo_header import *
from SciCamPayload_header import *
from yolo_detector import YoloDetector

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

VERSION = "v12"
app = Flask(__name__)
m_Device = SciCamera()          # 相机设备全局实例
detector = YoloDetector()       # 加密检测器全局实例, 启动加载一次

SAVE_ROOT_DIR = r"./surface_images"
PRODUCTION_PORT = 10083
PORT_TO_DETECT_TYPE = {str(PRODUCTION_PORT): "housing"}   # 表面 = housing

TARGET_SN = "D265250099"
CAM_DESC = "表面检测相机 OPT-CC1-C050-GG3-00"

# 相机参数 (现场可调; 首次上线请核对亮度: /crop_info 的 mean 应在 60~200 之间)
EXPOSURE_US = float(os.environ.get("SURFACE_EXPOSURE_US", "80000"))
GAIN_DB = float(os.environ.get("SURFACE_GAIN_DB", "1.8"))
GAMMA_VAL = 1.0
CANONICAL_W = int(os.environ.get("SURFACE_CANONICAL", "1280"))   # 与 config imgsz=1280 对齐
CANONICAL_H = CANONICAL_W

_LAST_PIC = {"origin": None, "topview": None, "t": 0.0}


# ───────────────────── v5: 内存帧 + 按需落盘 + 保留上限 ─────────────────────
# ───────────────────── v6: 取图两路由补"重连再抓", 版本号统一 — 2026-09-27 ─────────────────────
# 老倪 2026-09-27: 「不检测的时候, 不用保存那么多图片」⇒
#   · 只"看一眼/取图"(GET /picture?grab=1) 一律**不落盘**, 图只留内存(编码后几百 KB);
#   · 只有真检测(POST /capture_detect, 模型要读文件)才落盘, 落完按上限清旧图;
#   · 诊断用的额外图(标注图/legacy)默认不写, 要写设 AOI_SAVE_DEBUG=1;
#   · GET /storage 看占用/张数, POST /prune 手动清。
AOI_SAVE_DEBUG = os.environ.get("AOI_SAVE_DEBUG", "0").strip().lower() in ("1", "true", "yes")
KEEP_CANON = int(os.environ.get("AOI_KEEP_CANON", "400"))
KEEP_ORIGIN = int(os.environ.get("AOI_KEEP_ORIGIN", "120"))
_PRUNE_PATTERNS = [("Surface_Letterbox_W*_No_*.png", KEEP_CANON),
                   ("Surface_Image_W*_No_*.png", KEEP_ORIGIN)]
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
# 🆕 v12(2026-09-30, 与金手指 10082 v12 对齐): 把**喂进 detector.detect() 的同一份像素**
#   留在内存 + 记下它的 md5 ⇒ GET /picture?kind=modelin 能把"模型实际吃的那张"无损取回来,
#   并与 /last_result.model_input_md5 逐位对得上(同源硬证据, 不是"看起来像")。
_LAST_MODELIN_IMG = None
_LAST_MODELIN_META = {}
_PIC_LOCK = threading.Lock()
_cam_open = False
_cam_lock = threading.Lock()
_dev_cache = None
global_img_count = 1


# ───────────────────────── 相机 (SciCam SDK) ─────────────────────────
def uint32_to_ipv4(ip_uint32):
    return socket.inet_ntoa(struct.pack("!I", socket.htonl(ip_uint32)))


def _resolve_detect_type_by_channel() -> tuple:
    port = str(request.environ.get("SERVER_PORT", "")).strip()
    return PORT_TO_DETECT_TYPE.get(port), port


def find_dev_by_sn(target_sn: str, use_cache=True):
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
        sn_str = bytes(cam_obj.info.gigeInfo.serialNumber).strip(b"\x00").decode("utf-8")
        if sn_str == target_sn:
            _dev_cache = cam_obj
            return cam_obj
    print(f"未找到序列号 {target_sn} 的相机")
    return None


def _set_float(name, val, alts=()):
    ret = m_Device.SciCam_SetFloatValue(name, val)
    if ret == SCI_CAMERA_OK:
        print(f"{name} 设置成功 {val}")
        return True
    for alt in alts:
        if alt == val:
            continue
        if m_Device.SciCam_SetFloatValue(name, alt) == SCI_CAMERA_OK:
            print(f"{name} 设置成功(替代值) {alt} (原 {val} 失败码 {ret})")
            return True
    print(f"【参数设置失败】{name} {val} 错误码 {ret} (跳过, 不影响采集)")
    return False


def Open_Device(target_dev):
    global _cam_open
    if m_Device.SciCam_CreateDevice(target_dev) != SCI_CAMERA_OK:
        print("创建设备句柄失败")
        return False
    if m_Device.SciCam_OpenDevice() != SCI_CAMERA_OK:
        print("打开相机失败")
        return False
    m_Device.SciCam_SetGrabStrategy(2)
    _set_float("ExposureTime", EXPOSURE_US)
    _set_float("Gain", GAIN_DB, alts=(GAIN_DB * 2, int(GAIN_DB), 0.0, 2.0, 8.0))
    _set_float("Gamma", GAMMA_VAL)
    _cam_open = True
    print("相机打开成功")
    return True


def StartGrabbing():
    if m_Device.SciCam_StartGrabbing() != SCI_CAMERA_OK:
        print("开启采集失败")
        return False
    print("采集流已启动")
    return True


def StopGrabbing():
    try:
        m_Device.SciCam_StopGrabbing()
    except Exception:
        pass


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
    """相机常驻: 已打开直接 True; 未打开才初始化 (被别的程序独占 → False)"""
    global _cam_open
    with _cam_lock:
        if _cam_open:
            return True
        dev = find_dev_by_sn(TARGET_SN)
        if dev is None:
            return False
        if not Open_Device(dev):
            return False
        if not StartGrabbing():
            StopGrabbing()
            Close_Device()
            return False
        time.sleep(0.8)
        return True


# ───────────────────────── 规范图 (letterbox, 保比例) ─────────────────────────
def letterbox_square(bgr, size=CANONICAL_W, pad=114):
    """原图按比例缩放到 size×size 画布居中 (灰边填充) —— 表面是全幅检测, 严禁拉伸变形。
    这样模型输入不再二次缩放 (与 config imgsz=size 对齐)。返回 (canvas, ratio, (dw,dh))"""
    h, w = bgr.shape[:2]
    r = min(size / w, size / h)
    nw, nh = int(round(w * r)), int(round(h * r))
    resized = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_AREA if r < 1 else cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), pad, dtype=np.uint8)
    dw, dh = (size - nw) // 2, (size - nh) // 2
    canvas[dh:dh + nh, dw:dw + nw] = resized
    return canvas, r, (dw, dh)


def _crop_metrics(canvas, bgr, ratio, offset):
    """规范图/原图的健康度: 亮度、对比、对焦清晰度(Laplacian 方差)"""
    g = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
    go = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h, w = canvas.shape[:2]
    roi = g[max(0, h // 4):h * 3 // 4, max(0, w // 4):w * 3 // 4]
    return {"canonical": [canvas.shape[1], canvas.shape[0]], "src_size": [bgr.shape[1], bgr.shape[0]],
            "letterbox_ratio": round(float(ratio), 4), "pad_offset": list(map(int, offset)),
            "mean": round(float(roi.mean()), 1), "std": round(float(roi.std()), 1),
            "bright_frac": round(float((roi > 180).mean()), 4),
            "focus_laplacian_var": round(float(cv2.Laplacian(roi, cv2.CV_64F).var()), 1),
            "src_focus_laplacian_var": round(float(cv2.Laplacian(go, cv2.CV_64F).var()), 1),
            "imgsz_expected": CANONICAL_W}


def GrabAndSaveImage(save: bool = True):
    """抓一帧 → 规范图(letterbox1280) + 原图 → 返回 (origin_path, topview_path)。

    v5: 图**总是**进内存(取图走内存); `save=True`(真检测)才落盘, `save=False`(只看一眼)不落盘。
    """
    global global_img_count
    _TL.save = bool(save)
    ppayload = ctypes.c_void_p()
    if m_Device.SciCam_Grab(ppayload) != SCI_CAMERA_OK:
        print("Grab 抓取帧失败")
        return None, None
    attr = SCI_CAM_PAYLOAD_ATTRIBUTE()
    if SciCam_Payload_GetAttribute(ppayload, attr) != SCI_CAMERA_OK:
        print("Get payload attribute failed")
        m_Device.SciCam_FreePayload(ppayload)
        return None, None
    if not bool(attr.isComplete) or attr.payloadMode != SciCamPayloadMode.SciCam_PayloadMode_2D:
        print("图像不完整或 payload 类型错误")
        m_Device.SciCam_FreePayload(ppayload)
        return None, None

    iw, ih = attr.imgAttr.width, attr.imgAttr.height
    ptype = attr.imgAttr.pixelType
    mono = {SciCamPixelType.Mono1p, SciCamPixelType.Mono2p, SciCamPixelType.Mono4p,
            SciCamPixelType.Mono8s, SciCamPixelType.Mono8, SciCamPixelType.Mono10,
            SciCamPixelType.Mono10p, SciCamPixelType.Mono12, SciCamPixelType.Mono12p,
            SciCamPixelType.Mono14, SciCamPixelType.Mono16, SciCamPixelType.Mono10Packed,
            SciCamPixelType.Mono12Packed, SciCamPixelType.Mono14p}
    is_mono = ptype in mono
    ttype = SciCamPixelType.Mono8 if is_mono else SciCamPixelType.RGB8
    nch = 1 if is_mono else 3

    imgData = ctypes.c_void_p()
    if SciCam_Payload_GetImage(ppayload, imgData) != SCI_CAMERA_OK:
        print("Get image data failed")
        m_Device.SciCam_FreePayload(ppayload)
        return None, None
    dstImgSize = ctypes.c_int()
    if SciCam_Payload_ConvertImage(attr.imgAttr, imgData, ttype, None, dstImgSize, True) != SCI_CAMERA_OK:
        m_Device.SciCam_FreePayload(ppayload)
        return None, None
    pDstData = (ctypes.c_ubyte * dstImgSize.value)()
    if SciCam_Payload_ConvertImage(attr.imgAttr, imgData, ttype, pDstData, dstImgSize, True) != SCI_CAMERA_OK:
        m_Device.SciCam_FreePayload(ppayload)
        return None, None

    arr = np.frombuffer(pDstData, dtype=np.uint8).reshape(ih, iw, nch)
    bgr = arr if nch == 3 else cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    bgr = cv2.cvtColor(bgr, cv2.COLOR_RGB2BGR)      # SDK 给 RGB8 → OpenCV 用 BGR

    os.makedirs(SAVE_ROOT_DIR, exist_ok=True)
    no = global_img_count
    global_img_count += 1
    origin_path = os.path.join(SAVE_ROOT_DIR, "Surface_Image_W{}_H{}_No_{}.png".format(iw, ih, no))

    t0 = time.time()
    canvas, ratio, off = letterbox_square(bgr)
    _mem_put(crop=canvas, origin=bgr)          # v5: 内存帧(取图不用读盘)
    dt = (time.time() - t0) * 1000
    top_name = "Surface_Letterbox_W{}_H{}_No_{}.png".format(CANONICAL_W, CANONICAL_H, no)
    topview_path = os.path.join(SAVE_ROOT_DIR, top_name)
    _iw(topview_path, canvas)
    _iw(origin_path, bgr)
    met = _crop_metrics(canvas, bgr, ratio, off)
    # 🆕 v12: 记录"模型实际吃的那份像素"(只有真检测才更新; 只看一眼的 grab 不覆盖)
    global _LAST_MODELIN_IMG, _LAST_MODELIN_META
    _mi_fields = {}
    if save:
        _LAST_MODELIN_IMG = canvas
        _LAST_MODELIN_META = {
            "n": no, "t": time.time(),
            "hw": [int(canvas.shape[1]), int(canvas.shape[0])],
            "md5": hashlib.md5(np.ascontiguousarray(canvas).tobytes()).hexdigest(),
            "src": "letterbox_square(原图按比例 letterbox 到 %dx%d, 灰边填充)" % (CANONICAL_W, CANONICAL_H),
            "fed_to": "detector.detect(path=<规范图文件>, detect_type=housing)",
            "note": "表面是全幅检测: 模型吃的就是这张规范图(与 /crop_info.crop_file 同一张) —— 不像金手指要另派生一张 960"}
        _mi_fields = {"model_input_file": os.path.basename(topview_path),
                      "model_input_kind": "letterbox %dx%d (保比例, 不拉伸)" % (CANONICAL_W, CANONICAL_H),
                      "model_input_md5": _LAST_MODELIN_META["md5"],
                      "judge_file": os.path.basename(topview_path)}
    with _PIC_LOCK:
        _prev = {_k: _LAST_CROP_INFO[_k] for _k in
                 ("model_input_file", "model_input_kind", "model_input_md5", "judge_file", "crop_file")
                 if _k in _LAST_CROP_INFO}
        _LAST_CROP_INFO.clear()
        _LAST_CROP_INFO.update(_prev)          # grab 不落盘 ⇒ 沿用上次真检测的记录, 别写成空的
        _LAST_CROP_INFO.update({"n": no, "t": time.time(), "crop_ms": round(dt, 1),
                                "crop_file": os.path.basename(topview_path),
                                "origin_file": os.path.basename(origin_path), **_mi_fields, **met})
    print("  【表面规范图】{w}x{h} ← 原图 {sw}x{sh} · letterbox {r:.3f} · mean={m} std={s} "
          "focus={f} · 耗时 {dt:.0f}ms".format(w=CANONICAL_W, h=CANONICAL_H, sw=bgr.shape[1],
                                                sh=bgr.shape[0], r=ratio, m=met["mean"], s=met["std"],
                                                f=met["focus_laplacian_var"], dt=dt))
    if met["mean"] < 60:
        print("  ⚠️ 画面偏暗 (mean<60): 检查光照/曝光 SURFACE_EXPOSURE_US")
    return origin_path, topview_path


# ───────────────────────── 异步检测 worker ─────────────────────────
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
        topview_path, origin_path, detect_type = (list(item) + [None] * 3)[:3]
        try:
            if not topview_path or not os.path.exists(topview_path):
                print("  ⚠️ 跳过一项: 模型输入图已不在(%s) —— 不把不存在的路径喂给检测器" % topview_path)
                continue
            t0 = time.time()
            result = detector.detect(topview_path, detect_type=detect_type)
            dt_ms = (time.time() - t0) * 1000
            dets = result.get("detections", [])
            with _detect_lock:
                _detect_count += 1
                n = _detect_count
            print("\n" + "=" * 60)
            print(f"【检测结果 #{n}】{CAM_DESC} 推理耗时 {dt_ms:.0f}ms")
            print(f"  规范图: {topview_path}")
            print(f"  原图:   {origin_path}")
            print(f"  缺陷数: {len(dets)}  {'❌ NG' if dets else '✅ OK'}")
            for i, d in enumerate(dets):
                print("    [{}] {} conf={} bbox={}".format(
                    i + 1, d.get("class_name", d.get("name", "?")),
                    d.get("confidence", d.get("conf", 0)), d.get("bbox", d.get("box", "?"))))
            if result.get("saved_incoming"):
                print(f"  存档: {result['saved_incoming']}")
            with _PIC_LOCK:
                _LAST_RESULT.clear()
                _LAST_RESULT.update({"n": n, "t": time.time(), "detect_type": detect_type,
                                     "origin": origin_path, "topview": topview_path,
                                     # 🆕 v12: 明写"模型实际吃哪张" + 它的像素 md5(与 /picture?kind=modelin 同源对账)
                                     "model_input": topview_path,
                                     "model_input_kind": "letterbox %dx%d 规范图(保比例; 表面: 模型吃的=人看的同一张)" % (CANONICAL_W, CANONICAL_H),
                                     "model_input_md5": (dict(_LAST_MODELIN_META).get("md5") or ""),
                                     "judge": topview_path,
                                     "defects": dets, "count": len(dets),
                                     "verdict": ("NG" if dets else "OK"),
                                     "verdict_topview": ("NG" if dets else "OK"),
                                     "ms": round(dt_ms, 1),
                                     "saved_incoming": result.get("saved_incoming", "")})
            print("=" * 60 + "\n", flush=True)
        except Exception as e:                                          # noqa: BLE001
            print(f"【检测异常】{e}")
            traceback.print_exc()


def _ensure_detect_worker():
    global _detect_thread
    with _detect_lock:
        if _detect_thread is None or not _detect_thread.is_alive():
            _detect_thread = threading.Thread(target=_detect_worker_loop, daemon=True)
            _detect_thread.start()


_DETECT_Q_MAX = int(os.environ.get("AOI_DETECT_Q_MAX", "3"))   # 🆕 v12: 队列上限(挤压时丢最旧的)


def _enqueue_detect(topview_path, origin_path, detect_type):
    """入队。🆕 v12: 挤压时丢最旧 —— 表面单帧推理 ~7.8s, 页面高频触发会让队伍越排越长,
    结果就会一直落后(现场见过的"点了检测半天没结果")。丢最旧 + worker 跳过失效项都能治。"""
    with _detect_lock:
        _detect_queue.append((topview_path, origin_path, detect_type))
        while len(_detect_queue) > _DETECT_Q_MAX:
            _detect_queue.pop(0)
            print("  ⚠️ 检测队列积压 ⇒ 丢掉最旧的一项(只保留最新 %d 个)" % _DETECT_Q_MAX)
    _ensure_detect_worker()


# ───────────────────────── Flask 接口 ─────────────────────────
@app.route("/capture_detect", methods=["POST"])
def capture_detect_api():
    try:
        detect_type, channel_port = _resolve_detect_type_by_channel()
        if not detect_type:
            return jsonify({"code": 400,
                            "msg": f"当前通道端口 {channel_port or '未知'} 未配置检测模型，"
                                   f"可选端口: {sorted(PORT_TO_DETECT_TYPE.keys())}"}), 400
        print(f"\n===== 检测通道 {channel_port} · {CAM_DESC} =====")
        if not ensure_camera():
            return jsonify({"code": 500, "msg": "相机初始化失败"}), 500
        o, tv = GrabAndSaveImage(save=True)      # 真检测: 落盘(模型要读文件)
        if o is None or tv is None:
            print("⚠️ 抓帧失败, 重连相机后重试…")
            Close_Device()
            if ensure_camera():
                o, tv = GrabAndSaveImage()
            if o is None or tv is None:
                return jsonify({"code": 500, "msg": "图像抓取失败"}), 500
        with _PIC_LOCK:
            _LAST_PIC.update({"origin": o, "topview": tv, "t": time.time()})
        _enqueue_detect(tv, o, detect_type)
        _prune_dir()                             # v5: 按保留上限清旧图(不检测时不再堆图)
        print("   📸 已拍照, 检测已投递后台队列 (不阻塞产线节拍)")
        return jsonify({"code": 200, "msg": "success"})
    except Exception as e:                                              # noqa: BLE001
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
    """?kind=crop(默认,规范图1280方图)|origin(原图) · ?meta=1 返回JSON · ?grab=1 先抓一帧"""
    try:
        kind = (request.args.get("kind") or "crop").lower()
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
        if kind == "modelin":            # 🆕 v12: 模型**实际吃的那张**(内存里那份, 无损 PNG)
            with _PIC_LOCK:
                _img = _LAST_MODELIN_IMG
                _meta = dict(_LAST_MODELIN_META)
            if _img is None:
                return jsonify({"code": 404, "msg": "尚无模型输入图: 先 POST /capture_detect"}), 404
            if request.args.get("meta") in ("1", "true", "yes"):
                _meta["code"] = 200
                return jsonify(_meta)
            _ok, _buf = cv2.imencode(".png", _img)
            if not _ok:
                return jsonify({"code": 500, "msg": "编码失败"}), 500
            _hw = _meta.get("hw") or ["?", "?"]
            return Response(_buf.tobytes(), mimetype="image/png",
                            headers={"Cache-Control": "no-store",
                                     "X-Zmax-Modelin-Md5": str(_meta.get("md5") or ""),
                                     "X-Zmax-Modelin-HW": "%sx%s" % (_hw[0], _hw[1]),
                                     "X-Zmax-Modelin-N": str(_meta.get("n") or "")})
        with _PIC_LOCK:
            snap = dict(_LAST_PIC)
            ci = dict(_LAST_CROP_INFO)      # v12 修: 原来这两行写在 return 后面(不可达) ⇒ meta 分支 NameError
            lr = dict(_LAST_RESULT)
        mem, mts = _mem_get(kind)
        if mem and not request.args.get("file"):
            return Response(mem, mimetype="image/jpeg",
                            headers={"Cache-Control": "no-store",
                                     "X-Frame-Source": "memory", "X-Frame-Age-S": "%.3f" % (time.time() - mts)})
        path = snap.get("origin") if kind in ("origin", "raw") else snap.get("topview")
        if not path:
            path = snap.get("topview") or snap.get("origin")
        if not path or not os.path.exists(path):
            return jsonify({"code": 404, "msg": "尚无照片: 先 POST /capture_detect 或 GET /picture?grab=1"}), 404
        if request.args.get("meta") in ("1", "true", "yes"):
            return jsonify({"code": 200, "kind": kind, "file": os.path.basename(path),
                            "t": snap.get("t", 0), "size": os.path.getsize(path),
                            "origin": os.path.basename(snap.get("origin") or ""),
                            "topview": os.path.basename(snap.get("topview") or ""),
                            "crop_info": ci, "last_result": lr})
        with open(path, "rb") as fp:
            data = fp.read()
        mt = "image/png" if path.lower().endswith(".png") else "image/jpeg"
        return Response(data, mimetype=mt, headers={"Cache-Control": "no-store"})
    except Exception as e:                                              # noqa: BLE001
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
    with _PIC_LOCK:
        snap = dict(_LAST_CROP_INFO)
    if not snap:
        return jsonify({"code": 404, "msg": "尚无规范图记录"}), 404
    snap["code"] = 200
    snap["mode"] = "letterbox_keep_aspect"
    return jsonify(snap)


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
    """清旧图: POST 真删(按保留上限), GET 只报告会删多少(不删)。"""
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


# ───────────────────────── 启动 ─────────────────────────
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
    s = socket.socket()
    try:
        s.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def run_flask(port=PRODUCTION_PORT):
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PRODUCTION_PORT
    if port not in (10083, 10082):
        pass
    else:
        PORT_TO_DETECT_TYPE[str(port)] = "housing"
    print(__doc__)
    print(f"[V{VERSION}] 表面检测程序启动中 · 端口 {port} · 相机 SN {TARGET_SN} · "
          f"规范图 {CANONICAL_W}x{CANONICAL_H} · 权重由 yolo_detector/config.yaml 的 detectors.housing 决定")
    if _already_serving(port):
        print(f"❌ 端口 {port} 上已经有 AOI 服务在应答(/storage 200) —— 正式实例正在跑。")
        print("   → 本程序由计划任务托管(开机自启 + 每分钟自愈), **不要手动再起第二份**。")
        print(f"   → 要验证: curl -X POST http://127.0.0.1:{port}/capture_detect   (GET 不触发动作)")
        sys.exit(3)
    if not _port_available(port):
        print(f"❌ 端口 {port} 已被占用 (V2 还在跑?) → 先停掉 V2 再启动本程序; 相机是独占设备, 不能同时开")
        sys.exit(2)
    t_pre = threading.Thread(target=ensure_camera, daemon=True)   # 预热相机(不阻塞起服务)
    t_pre.start()
    run_flask(port)


if __name__ == "__main__":
    main()
