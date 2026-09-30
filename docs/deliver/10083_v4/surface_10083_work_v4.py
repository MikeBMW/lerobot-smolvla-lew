#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z-MAX 表面检测 AOI 程序 · 优化版 v4 (端口 10083)   ——— 2026-09-23 静静

⚠️ 本文与 **V2 完全隔离**: 新文件名, 不改 V2 的任何文件/接口/端口; 部署时"先停 V2 → 再启 V4",
   相机独占(D265250099), 出问题可原样回到 V2。
   (金手指通道 10082 的 V4 见 cam_finger_10082_work_v4.py, 两者结构一致)

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

VERSION = "v4"
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
_LAST_RESULT = {}
_LAST_CROP_INFO = {}
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


def GrabAndSaveImage():
    """抓一帧 → 存原图 + 规范图(letterbox1280) → 返回 (origin_path, topview_path)"""
    global global_img_count
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
    dt = (time.time() - t0) * 1000
    top_name = "Surface_Letterbox_W{}_H{}_No_{}.png".format(CANONICAL_W, CANONICAL_H, no)
    topview_path = os.path.join(SAVE_ROOT_DIR, top_name)
    cv2.imwrite(topview_path, canvas)
    cv2.imwrite(origin_path, bgr)
    met = _crop_metrics(canvas, bgr, ratio, off)
    with _PIC_LOCK:
        _LAST_CROP_INFO.clear()
        _LAST_CROP_INFO.update({"n": no, "t": time.time(), "crop_ms": round(dt, 1),
                                "crop_file": os.path.basename(topview_path),
                                "origin_file": os.path.basename(origin_path), **met})
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
                                     "defects": dets, "count": len(dets),
                                     "verdict": ("NG" if dets else "OK"), "ms": round(dt_ms, 1),
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


def _enqueue_detect(topview_path, origin_path, detect_type):
    with _detect_lock:
        _detect_queue.append((topview_path, origin_path, detect_type))
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
        o, tv = GrabAndSaveImage()
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
            o, tv = GrabAndSaveImage()
            if o is None and tv is None:
                return jsonify({"code": 500, "msg": "抓帧失败"}), 500
            with _PIC_LOCK:
                _LAST_PIC.update({"origin": o, "topview": tv, "t": time.time()})
        with _PIC_LOCK:
            snap = dict(_LAST_PIC)
            ci = dict(_LAST_CROP_INFO)
            lr = dict(_LAST_RESULT)
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


# ───────────────────────── 启动 ─────────────────────────
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
    if not _port_available(port):
        print(f"❌ 端口 {port} 已被占用 (V2 还在跑?) → 先停掉 V2 再启动本程序; 相机是独占设备, 不能同时开")
        sys.exit(2)
    t_pre = threading.Thread(target=ensure_camera, daemon=True)   # 预热相机(不阻塞起服务)
    t_pre.start()
    run_flask(port)


if __name__ == "__main__":
    main()
