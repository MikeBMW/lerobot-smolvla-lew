#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z-MAX 表面检测 AOI 程序 · 优化版 v6 (端口 10083)   ——— 2026-09-23 静静

⚠️ 本文与 **V2 完全隔离**: 新文件名, 不改 V2 的任何文件/接口/端口; 部署时"先停 V2 → 再启 V4",
   相机独占(D265250099), 出问题可原样回到 V2。
   (金手指通道 10082 的 V4 见 cam_finger_10082_work_v4.py, 两者结构一致)

v6 = v5 + 取图两路由(/picture?grab=1 · /region?grab=1)补"冷启/空闲后首抓失败→重连再抓", 与 /capture_detect 同口径 (2026-09-27)

v12.1 相对 v12 (2026-09-30, 老倪): **表面「判据图」** —— /picture?kind=judge 返回"只切光模块 + 调平 + 去背景"的定尺图。
  现场原话: 「将光模块整体切割出来, 调整好水平状态; 类似金手指的判据图, 只要光模块的部分, 不要背景; 现在有点倾斜, 要修正」。
  算法: 固定站位 ROI → (a)亮条上边缘滑窗最直段直线  (b)ROI 掩膜 minAreaRect  双法互校估倾角(|diff|≤1.5° 才用, 取均值)
        → 反旋 → 亮连通域并集外接框(含左端连接器头) → 留边 → 定尺 letterbox 到 JUDGE_CANVAS。
  **失败(找不到直边/两法不一致/模块太小/边缘发亮) ⇒ judge_ok=False + judge_why, 回退全幅规范图, 绝不硬裁一张错的**。
  ⚠️ 模型吃的仍是 `letterbox_square` 那张 1280x1280 全幅图, **一字未改**(沿用金手指 v7/v10 铁律: 改"人看的图"绝不动"模型吃的图")。

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
import json
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

VERSION = "v13"             # v13 = v12.2 + **曝光/增益运行时可调** GET|POST /exposure (现场调参数不用重部署/重启)
#   v12.2 = v12.1 + 判据图右界改"数据驱动认台阶"(去掉右边那块夹具)+纵向收带; 模型输入口径未变
app = Flask(__name__)
m_Device = SciCamera()          # 相机设备全局实例
detector = YoloDetector()       # 加密检测器全局实例, 启动加载一次

SAVE_ROOT_DIR = r"./surface_images"
PRODUCTION_PORT = 10083
PORT_TO_DETECT_TYPE = {str(PRODUCTION_PORT): "housing"}   # 表面 = housing

TARGET_SN = "D265250099"
CAM_DESC = "表面检测相机 OPT-CC1-C050-GG3-00"

# 相机参数 —— 🆕 v13: 优先级 = 环境变量 > 落盘文件(现场调好的) > 内置默认
#   老倪 2026-09-30: 「修改工控机的代码, 调曝光度」⇒ 参数要能**运行时改**且**重启不丢**:
#   · POST /exposure?us=&gain= 现场改, 立刻生效, 并写 surface_exposure.json;
#   · 下次重启自动读该文件 ⇒ 不用重部署、不用改代码。
#   ⚠️ SDK 只有 SetFloatValue, **没有 GetFloatValue** ⇒ 真值只能靠**图像实测**验收:
#      GET /picture?kind=origin&grab=1 后看 /crop_info 的 mean 与饱和占比。
_DEF_EXPOSURE_US = 80000.0        # 出厂默认(仅当既无文件也无环境变量时使用)
_DEF_GAIN_DB = 1.8
_EXPO_FILE = os.path.join(HERE, "surface_exposure.json")


def _read_expo_file():
    """读现场调好并落盘的曝光/增益(没有/坏了就返回 None, 不抛)。"""
    try:
        with open(_EXPO_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return {"us": float(d["us"]), "gain": float(d["gain"]),
                "ts": str(d.get("ts") or ""), "by": str(d.get("by") or "file")}
    except Exception:
        return None


_F0 = _read_expo_file()
EXPOSURE_US = float(os.environ["SURFACE_EXPOSURE_US"]) if os.environ.get("SURFACE_EXPOSURE_US") \
    else (_F0["us"] if _F0 else _DEF_EXPOSURE_US)
GAIN_DB = float(os.environ["SURFACE_GAIN_DB"]) if os.environ.get("SURFACE_GAIN_DB") \
    else (_F0["gain"] if _F0 else _DEF_GAIN_DB)
EXPO_SRC = "env" if os.environ.get("SURFACE_EXPOSURE_US") else ("file" if _F0 else "default")
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
                   ("Surface_Judge_W*_No_*.png", KEEP_CANON),      # 🆕 v12.1 判据图(与规范图同保留上限)
                   ("Surface_Image_W*_No_*.png", KEEP_ORIGIN)]
_MEM = {"crop": None, "origin": None, "natural": None, "judge": None, "ts": 0.0}   # 🆕 v12.1: judge=判据图
_MEM_LOCK = threading.Lock()
_TL = threading.local()          # 每次抓帧的落盘开关(线程安全: /capture_detect 与 /picture?grab=1 可能并发)


def _enc_jpg(bgr, quality=90):
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    return buf.tobytes() if ok else b""


def _mem_put(crop=None, origin=None, natural=None, judge=None):
    """把当前这帧编码进内存 (取图走内存, 磁盘就不需要那么多文件)。"""
    with _MEM_LOCK:
        if crop is not None:
            _MEM["crop"] = _enc_jpg(crop, 92)
        if origin is not None:
            _MEM["origin"] = _enc_jpg(origin, 88)
        if natural is not None:
            _MEM["natural"] = _enc_jpg(natural, 92)
        if judge is not None:                          # 🆕 v12.1: 判据图(只切光模块+调平, 定尺)
            _MEM["judge"] = _enc_jpg(judge, 92)
        _MEM["ts"] = time.time()


def _mem_get(kind, t0=0.0):
    """取内存帧: kind=origin/raw 要原图, judge 要判据图; 没有就退回另一张。"""
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


# ═══════════════ 🆕 v12.1 判据图: 只切光模块 + 调平 + 去背景 ═══════════════
# 现场要求(2026-09-30): 「将光模块整体切割出来, 调整好水平状态; 类似金手指的判据图,
#   只要光模块的部分, 不要背景; 现在的光模块有点倾斜, 你要修正」。
# 站位固定 ⇒ 用固定 ROI 先把"模块可能在的那条带"框住; 右侧亮白台面与模块同为 255、
#   亮度分不开, 只能靠 ROI 右界拦住(实测台面从 x≈1820 起, 故右界取 1815)。
# 估倾角双法互校: (a) 上边缘滑窗最直段直线 (b) ROI 掩膜 minAreaRect —— 两法差 >1.5° 就判失败,
#   宁可回退全幅也不硬裁(实测整条拟合残差 ±100px 是脏的, 只有中段直线干净)。
JUDGE_ROI = (330, 960, 1815, 1440)          # 外框(右界只当兜底 —— 正常走"上边缘竖直台阶"收紧到模块本体)
JUDGE_TH_BAR = 200                          # 过曝条(模块壳体)阈值
JUDGE_TH_MOD = 170                          # 模块并集阈值(放宽: 含左端灰青连接器头, 实测灰 ~187)
JUDGE_CANVAS = (1400, 300)                  # 判据图定尺(宽,高) —— 模块水平居中, 背景灰填充
JUDGE_MARGIN = 12                           # 裁切留边 px
JUDGE_MAX_SKEW_DIFF = 1.5                   # 两法估角允许差(超过 ⇒ judge_ok=False)
JUDGE_MIN_WH = (400, 60)                    # 模块最小尺寸(小于 ⇒ 判失败)
# 🆕 v12.2: 模块本体右界 = 上边缘出现"竖直台阶"处(台阶右边是另一块料/夹具: 更高、更矮、材质不同)
#   依据(2026-09-30 像素级反解): 长条上边缘在 x≈1495 竖直上跳 35px、下边缘在 x≈1513 下掉 65px;
#   右侧那块高 277px(长条仅 175px)、底部磨砂麻点(190~240, 长条同高度纯 255)、并连到带螺钉/贴纸的底座。
JUDGE_RIGHT_PAD = 15                        # 台阶右侧再留一点, 保住模块端面
JUDGE_STEP_PX = 18                          # 台阶判据: 上边缘相对基线偏移 ≥18px 且持续 ≥8 列
JUDGE_BAND_K = 1.30                         # 纵向收带: 模块厚度 = 实测中位厚度 × 1.3(挡掉那块更高的料)
JUDGE_SCALE_MAX = 1.0                       # 只缩不放(不插值放大 ⇒ 保像素真实)


def _judge_bg_level(g, x0, y0, x1, y1):
    """背景灰度: 取 ROI 左右两条竖直条带的中位数(模块两侧都是机台暗底)。"""
    return int(np.median(np.concatenate([g[y0:y1, x0:x0 + 30].ravel(),
                                         g[y0:y1, x1 - 30:x1].ravel()])))


def _judge_top_edge(g, xa, xb, ya, yb, th=JUDGE_TH_BAR, min_run=40):
    """逐列取"模块上边缘"点: 该列里第一个亮像素(要求该列亮像素数≥min_run, 排除噪点)。"""
    pts = []
    for x in range(xa, xb):
        col = np.where(g[ya:yb, x] > th)[0]
        if len(col) >= min_run:
            pts.append((x, ya + col.min()))
    return np.array(pts, float) if pts else np.zeros((0, 2))


def _judge_fit(pts):
    """最小二乘拟合 + 最大残差 (点数太少返回 None)。"""
    if len(pts) < 20:
        return None
    k, c = np.polyfit(pts[:, 0], pts[:, 1], 1)
    return float(k), float(np.abs(pts[:, 1] - (k * pts[:, 0] + c)).max()), len(pts)


def render_judge_surface(bgr):
    """把光模块整体切出来 + 调平 + 去背景, 定尺输出。

    返回 (judge_img 或 None, meta)。meta 里 ok=False 时调用方必须回退全幅图并告警 —— 绝不硬裁。
    """
    H, W = bgr.shape[:2]
    x0, y0, x1, y1 = JUDGE_ROI
    x1, y1 = min(x1, W), min(y1, H)
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    met = {"roi": [x0, y0, x1, y1], "canvas": list(JUDGE_CANVAS), "ok": False, "why": ""}
    try:
        # ── 法(a): 滑窗找"最直的一段上边缘"当角度基准 ──
        pts = _judge_top_edge(g, x0, x1, y0, y1)
        if len(pts) < 200:
            met["why"] = "亮条上边缘点太少(%d) —— 画面里没找到过曝条(没拍到位/曝光变了?)" % len(pts)
            return None, met
        best = None
        for xa in range(int(pts[0, 0]), int(pts[-1, 0]) - 150, 50):
            sub = pts[(pts[:, 0] >= xa) & (pts[:, 0] < xa + 400)]
            f = _judge_fit(sub)
            if f and (best is None or f[1] < best[1]):
                best = (f[0], f[1], len(sub), xa)
        kA, rA, nA, xaA = best
        angA = float(np.degrees(np.arctan(kA)))
        # ── 法(b): ROI 掩膜 minAreaRect ──
        m = np.zeros_like(g)
        m[y0:y1, x0:x1] = (g[y0:y1, x0:x1] > JUDGE_TH_BAR).astype(np.uint8) * 255
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            met["why"] = "ROI 内没有亮掩膜连通域"
            return None, met
        c = max(cnts, key=cv2.contourArea)
        (_, _), (brw, brh), braw = cv2.minAreaRect(c)
        angB = float(braw if abs(braw) <= 45 else braw - 90 * np.sign(braw))
        met.update({"angA_deg": round(angA, 3), "angA_resid_px": round(rA, 2), "angA_win": [xaA, xaA + 400],
                    "angB_deg": round(angB, 3), "angB_box": [int(round(brw)), int(round(brh))],
                    "angB_area": int(cv2.contourArea(c))})
        if rA > 3.0:
            met["why"] = "上边缘不直(最直段残差 %.2fpx > 3px) ⇒ 不敢当模块边界" % rA
            return None, met
        if abs(angA - angB) > JUDGE_MAX_SKEW_DIFF:
            met["why"] = "两法估角不一致(直线 %.2f° / 掩膜 %.2f°, 差 %.2f° > %.1f°)" % (
                angA, angB, abs(angA - angB), JUDGE_MAX_SKEW_DIFF)
            return None, met
        ang = (angA + angB) / 2.0
        met["rot_deg"] = round(ang, 3)
        # ── 反旋(绕 ROI 中心, ROI 位置基本不动) ──
        bg = _judge_bg_level(g, x0, y0, x1, y1)
        met["bg_median"] = bg
        M = cv2.getRotationMatrix2D(((x0 + x1) / 2.0, (y0 + y1) / 2.0), ang, 1.0)
        rot = cv2.warpAffine(bgr, M, (W, H), flags=cv2.INTER_LINEAR, borderValue=(bg, bg, bg))
        gr = cv2.cvtColor(rot, cv2.COLOR_BGR2GRAY)
        # ── 🆕 v12.2: 在**旋后帧**里量模块几何(此时上边缘≈水平), 把掩膜收紧到模块本体 ──
        pts_r = _judge_top_edge(gr, x0, x1, y0, y1)
        if len(pts_r) < 200:
            met["why"] = "旋后上边缘点太少(%d)" % len(pts_r)
            return None, met
        y_base = float(np.median(pts_r[:, 1]))              # 旋后上边缘基线(中位比拟合稳)
        xa = int(np.median(pts_r[:, 0])) - 200
        ths = [int((gr[y0:y1, xx] > JUDGE_TH_BAR).sum()) for xx in range(max(x0, xa), min(x1, xa + 400))]
        ths = [v for v in ths if v > 20]
        thick = float(np.median(ths)) if ths else 0.0
        if thick < JUDGE_MIN_WH[1]:
            met["why"] = "量不到模块厚度(中位 %.0fpx)" % thick
            return None, met
        # 模块右端: 上边缘出现**向上**的竖直台阶(台阶右边是更高的另一块料/夹具)。
        #   注意方向性 —— 左端那块"舌尖"是更矮的(y_top 更小), 不会误触发。
        x_step = None
        for xx in range(x0 + 300, x1 - 12):
            col = np.where(gr[y0:y1, xx] > JUDGE_TH_BAR)[0]
            if len(col) < 40:
                continue
            if (y_base - (y0 + col.min())) >= JUDGE_STEP_PX:
                okpersist = True
                for d in range(1, 9):
                    cc = np.where(gr[y0:y1, xx + d] > JUDGE_TH_BAR)[0]
                    if len(cc) < 40 or (y_base - (y0 + cc.min())) < JUDGE_STEP_PX * 0.6:
                        okpersist = False
                        break
                if okpersist:
                    x_step = xx
                    break
        x_end = int(min(x1, (x_step + JUDGE_RIGHT_PAD) if x_step else x1))
        y_lo = max(y0, int(y_base - 12))
        y_hi = min(y1, int(y_base + thick * JUDGE_BAND_K))
        met.update({"y_base": round(y_base, 1), "thick_med": round(thick, 1), "band_y": [y_lo, y_hi],
                    "right_edge_x": int(x_step) if x_step else None,
                    "right_edge_src": ("上边缘竖直台阶 @x=%d (+%dpx 保端面)" % (x_step, JUDGE_RIGHT_PAD))
                                       if x_step else "ROI 右界(未找到台阶 ⇒ 可能切在亮料中间)"})
        # ── 模块掩膜: 旋后帧 ∩ ROI ∩ x≤右界 ∩ 纵向厚度带(挡掉那块更高的料) ──
        mm = np.zeros_like(gr)
        mm[y_lo:y_hi, x0:x_end] = (gr[y_lo:y_hi, x0:x_end] > JUDGE_TH_MOD).astype(np.uint8) * 255
        mm = cv2.morphologyEx(mm, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))
        n, lab, stats, _ = cv2.connectedComponentsWithStats(mm, 8)
        comps = [i for i in range(1, n) if stats[i, 4] >= 1500]
        if not comps:
            met["why"] = "旋后没有 ≥1500px 的模块连通域"
            return None, met
        bx = min(stats[i, 0] for i in comps)
        by = min(stats[i, 1] for i in comps)
        bw = max(stats[i, 0] + stats[i, 2] for i in comps) - bx
        bh = max(stats[i, 1] + stats[i, 3] for i in comps) - by
        met.update({"n_comps": len(comps), "comps_area": [int(stats[i, 4]) for i in comps],
                    "module_bbox_rot": [int(bx), int(by), int(bw), int(bh)],
                    "module_union_px": int(sum(stats[i, 4] for i in comps)),
                    "module_aspect": round(bw / max(1.0, bh), 2)})
        if bw < JUDGE_MIN_WH[0] or bh < JUDGE_MIN_WH[1]:
            met["why"] = "模块太小(%dx%d < %dx%d) ⇒ 疑似没拍到位" % (bw, bh, JUDGE_MIN_WH[0], JUDGE_MIN_WH[1])
            return None, met
        # ── 裁切 + 定尺 letterbox(模块水平居中) ──
        px0, py0 = max(0, bx - JUDGE_MARGIN), max(0, by - JUDGE_MARGIN)
        px1, py1 = min(W, bx + bw + JUDGE_MARGIN), min(H, by + bh + JUDGE_MARGIN)
        crop = rot[py0:py1, px0:px1]
        cw, ch = JUDGE_CANVAS
        r = min(cw / crop.shape[1], ch / crop.shape[0], JUDGE_SCALE_MAX)   # 只缩不放(不插值放大)
        nw, nh = max(1, int(round(crop.shape[1] * r))), max(1, int(round(crop.shape[0] * r)))
        rs = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_AREA if r < 1 else cv2.INTER_LINEAR)
        out = np.full((ch, cw, 3), bg, np.uint8)
        dx, dy = (cw - nw) // 2, (ch - nh) // 2
        out[dy:dy + nh, dx:dx + nw] = rs
        gc = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
        bd = [float(np.median(gc[:4, :])), float(np.median(gc[-4:, :])),
              float(np.median(gc[:, :4])), float(np.median(gc[:, -4:]))]
        met.update({"crop_bbox_rot": [int(px0), int(py0), int(px1), int(py1)],
                    "crop_size": [int(px1 - px0), int(py1 - py0)],
                    "canvas_scale": round(float(r), 4),
                    "cover_frac": round(float((gc > JUDGE_TH_MOD).mean()), 4),
                    "border_med": [round(v, 1) for v in bd]})
        if max(bd) >= max(120.0, bg + 60):
            met["why"] = "画布边缘发亮(留边 %s, 背景 %d) ⇒ 疑似把台面/夹具切进来了" % (met["border_med"], bg)
            return None, met
        met["ok"] = True
        return out, met
    except Exception as e:                                              # noqa: BLE001
        met["why"] = "判据图渲染异常: %s" % e
        traceback.print_exc()
        return None, met


def _judge_save(bgr, no, save):
    """算判据图 → 落盘(真检测才写) → 进内存 → 返回 (path 或 None, meta)。"""
    t0 = time.time()
    img, met = render_judge_surface(bgr)
    met["ms"] = round((time.time() - t0) * 1000, 1)
    path = None
    if img is not None:
        path = os.path.join(SAVE_ROOT_DIR, "Surface_Judge_W{}_H{}_No_{}.png".format(
            JUDGE_CANVAS[0], JUDGE_CANVAS[1], no))
        if save:
            _iw(path, img)
        _mem_put(judge=img)                     # 判据图总进内存(取图不读盘)
    else:
        print("  ⚠️ 判据图未生成 ⇒ 回退全幅规范图; 原因: %s" % met.get("why"))
    met["file"] = os.path.basename(path) if path else ""
    met["save"] = bool(save)
    return (path if save else None), met


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
    # 🆕 v12.1: 判据图(只切光模块 + 调平 + 去背景) —— 人看的图; 模型吃的那张(规范图)不受影响
    judge_path, jmet = _judge_save(bgr, no, save)
    if jmet.get("ok"):
        print("  【表面判据图】模块 %s · 调平 %.2f° · 厚 %s · 右界 %s · 长宽比 %s · 覆盖率 %.0f%% · 留边 %s · %.0fms → %s"
              % (jmet.get("module_bbox_rot"), jmet.get("rot_deg") or 0.0, jmet.get("thick_med"),
                 jmet.get("right_edge_src"), jmet.get("module_aspect"),
                 (jmet.get("cover_frac") or 0) * 100, jmet.get("border_med"), jmet.get("ms"), jmet.get("file")))
    else:
        print("  ⚠️ 表面判据图未生成(回退全幅规范图): %s" % jmet.get("why"))
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
                                "origin_file": os.path.basename(origin_path), **_mi_fields, **met,
                                # 🆕 v12.1 判据图(只切光模块+调平) —— 与 model_input 明写区分
                                "judge_file": jmet.get("file") or os.path.basename(topview_path),
                                "judge_ok": bool(jmet.get("ok")),
                                "judge_why": jmet.get("why", ""),
                                "judge_rot_deg": jmet.get("rot_deg"),
                                "judge_bbox": jmet.get("module_bbox_rot"),
                                "judge_cover": jmet.get("cover_frac"),
                                "judge_ms": jmet.get("ms"),
                                "judge": jmet})
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
                _ci = dict(_LAST_CROP_INFO)
            _jf = ""
            if _ci.get("judge_ok") and _ci.get("judge_file"):      # 🆕 v12.1: 判据图(只切光模块+调平)
                _cand = os.path.join(SAVE_ROOT_DIR, str(_ci["judge_file"]))
                _jf = _cand if os.path.exists(_cand) else ""
            with _PIC_LOCK:
                _LAST_RESULT.clear()
                _LAST_RESULT.update({"n": n, "t": time.time(), "detect_type": detect_type,
                                     "origin": origin_path, "topview": topview_path,
                                     # 🆕 v12.1: judge=人看的判据图(切模块+调平); model_input=模型吃的那张(全幅规范图)
                                     "judge": (_jf or topview_path),
                                     "judge_ok": bool(_ci.get("judge_ok")),
                                     "judge_why": _ci.get("judge_why", ""),
                                     "judge_file": os.path.basename(_jf) if _jf else "",
                                     # 🆕 v12: 明写"模型实际吃哪张" + 它的像素 md5(与 /picture?kind=modelin 同源对账)
                                     "model_input": topview_path,
                                     "model_input_kind": "letterbox %dx%d 全幅规范图(保比例; 判据图另出 /picture?kind=judge)" % (CANONICAL_W, CANONICAL_H),
                                     "model_input_md5": (dict(_LAST_MODELIN_META).get("md5") or ""),
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
# ═══════════ 🆕 v13: 曝光/增益 运行时可调 (老倪 2026-09-30「修改工控机的代码, 调曝光度」) ═══════════
#   为什么要有它: 原来曝光只在**启动时**按常量设一次 ⇒ 现场每试一个值都要改代码+重部署+重启(~90s+),
#   而相机 SDK 没有 GetFloatValue, 改完也只能靠图看 ⇒ 必须把"试参数"变成**一次 HTTP**(几毫秒)。
_EXPO_LAST = {}
_EXPO_LOCK = threading.Lock()      # 与抓帧互斥: 改参数时别让抓帧拿到半帧


def _apply_expo(us, gain, save=False):
    """把曝光/增益**应用到正在跑的相机**(不重启进程), 结果**如实回执**(不假装成功)。

    ① 相机已开: 直接设; 失败再试"停流→设→重开流"(某些 SDK 要求空闲态)。
    ② 相机没开: 只记住参数, 等首次取帧初始化时按新值设 ⇒ 回执里写明。
    ③ 参数一变就让内存帧失效 ⇒ 避免"看着新参数、拿到旧帧"。
    """
    global EXPOSURE_US, GAIN_DB, EXPO_SRC
    with _EXPO_LOCK:
        us = float(us)
        gain = float(gain)
        res = {"us": us, "gain": gain, "ok": False, "us_ok": False, "gain_ok": False,
               "reopened": False, "cam_open": bool(_cam_open), "reason": ""}
        if not _cam_open:
            res["reason"] = "相机未打开: 参数已记住, 首次取帧初始化相机时生效"
        else:
            def _try():
                a = _set_float("ExposureTime", us)
                b = _set_float("Gain", gain, alts=(gain * 2, int(gain), 0.0, 2.0, 8.0))
                return a, b
            a, b = _try()
            if not (a and b):
                try:
                    StopGrabbing()
                    time.sleep(0.2)
                except Exception:
                    pass
                a2, b2 = _try()
                try:
                    StartGrabbing()
                except Exception:
                    pass
                res["reopened"] = True
                a, b = bool(a or a2), bool(b or b2)
            res["us_ok"], res["gain_ok"] = bool(a), bool(b)
            res["ok"] = bool(a and b)
            if not res["ok"]:
                res["reason"] = "相机拒绝了该值(SDK 返回非 0) ⇒ 以图像实测为准"
        EXPOSURE_US, GAIN_DB, EXPO_SRC = us, gain, "runtime"
        if save:
            try:
                with open(_EXPO_FILE, "w", encoding="utf-8") as f:
                    json.dump({"us": us, "gain": gain, "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                               "by": "POST /exposure", "version": VERSION}, f, ensure_ascii=False, indent=1)
                res["saved"] = _EXPO_FILE
            except Exception as e:                                                  # noqa: BLE001
                res["saved"], res["save_err"] = "", str(e)
        if res.get("ok", True):        # 只在"确实改了"时丢内存帧
            try:
                with _MEM_LOCK:
                    _MEM.update({"crop": None, "origin": None, "natural": None, "judge": None, "ts": 0.0})
            except Exception:
                pass
        _EXPO_LAST.clear()
        _EXPO_LAST.update(res)
        print("  【曝光】us=%s gain=%s ok=%s reopened=%s %s" % (us, gain, res["ok"], res["reopened"], res["reason"]))
        return res


@app.route("/exposure", methods=["GET", "POST"])
def exposure_api():
    """曝光/增益运行时可调 —— GET 只读; POST ?us=<微秒>&gain=<dB> 应用并落盘。

    效果怎么验(照抄): 改完 `GET /picture?kind=origin&grab=1`, 再看 `/crop_info` 的 mean/bright_frac;
    饱和(>=250)占比目标 ≤5%(老倪现场口径), mean 目标 60~200。
    """
    try:
        if request.method == "GET":
            return jsonify({"code": 200, "us": EXPOSURE_US, "gain": GAIN_DB, "src": EXPO_SRC,
                            "default": {"us": _DEF_EXPOSURE_US, "gain": _DEF_GAIN_DB},
                            "file": _EXPO_FILE, "file_exists": os.path.exists(_EXPO_FILE),
                            "version": VERSION, "cam_open": bool(_cam_open),
                            "last": dict(_EXPO_LAST)})
        us = request.args.get("us", type=float)
        gain = request.args.get("gain", type=float)
        if us is None and gain is None:
            return jsonify({"code": 400, "msg": "用法: POST /exposure?us=<微秒>[&gain=<dB>]"}), 400
        r = _apply_expo(EXPOSURE_US if us is None else us, GAIN_DB if gain is None else gain, save=True)
        return jsonify({"code": 200 if r["ok"] or not r["cam_open"] else 500, **r})
    except Exception as e:                                                          # noqa: BLE001
        return jsonify({"code": 500, "msg": str(e)}), 500


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
        if kind in ("origin", "raw"):
            path = snap.get("origin")
        elif kind == "judge":                          # 🆕 v12.1: 判据图(只切光模块+调平+去背景)
            _jf = ci.get("judge_file") if ci.get("judge_ok") else ""
            _jp = os.path.join(SAVE_ROOT_DIR, str(_jf)) if _jf else ""
            path = _jp if (_jp and os.path.exists(_jp)) else snap.get("topview")   # 没出过就回退规范图
        else:
            path = snap.get("topview")
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
    # 🆕 v12.1: 判据图口径(人看的) —— 与模型输入口径分开报, 免得再混
    snap["judge_mode"] = ("crop_module_deskew %dx%d" % JUDGE_CANVAS) if snap.get("judge_ok") else "fallback_letterbox"
    snap["model_input_mode"] = "letterbox_keep_aspect %dx%d" % (CANONICAL_W, CANONICAL_H)
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
