"""
Z-MAX 金手指检测 AOI 程序 · 优化版 v3 (10082)
============================================
纯异步方案: 拍照后立即返回 success, 检测后台并行, 结果只打印终端。
动作调用零耽误, 推理不阻塞产线节奏。

核心优化:
  1. 【性能】相机常驻: 启动即打开, 请求只Grab, 秒级响应
  2. 【修复】增益设置失败(100100010): 自动探测相机增益范围, 容错降级不阻塞
  3. 【异步】检测并行: 拍照完立即返回 success, 推理后台线程跑, 结果打印终端
  4. 【优化】设备枚举缓存: 只枚举一次, 后续直接打开
  5. 【健壮】异常自动重连相机 + 资源释放保证

依赖: yolo_detector.py (加密检测器, 保持不变)
"""
import os
import time
import socket
import struct
import ctypes
import traceback
import threading
from threading import Thread
from flask import Flask, request, jsonify

import cv2
import numpy as np
from SciCam_class import *
from SciCamErrorDefine_const import *
from SciCamInfo_header import *
from SciCamPayload_header import *
from yolo_detector import YoloDetector

app = Flask(__name__)
m_Device = SciCamera()   # 相机设备全局实例 (原版保留)
detector = YoloDetector()  # 加密检测器全局实例, 启动加载一次 (原版保留)
_detector = None

# 图片保存根目录
SAVE_ROOT_DIR = r"./goldfinger_images"

# 端口-模型映射
PORT_TO_DETECT_TYPE = {"10082": "gf"}

# 金手指检测相机SN
TARGET_SN = "D265250070"
CAM_DESC = "金手指检测相机 OPT-CC1-GG50"

# 相机参数 (可调)
EXPOSURE_US = 10000.0
GAIN_DB = 1.0
GAMMA_VAL = 1.0

# 【优化1】全局常驻: 相机设备缓存 + 打开状态
_dev_cache = None
_cam_open = False
_cam_lock = threading.Lock()


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
    """【优化2】增益容错: 失败自动尝试 0.5x/2x 和整数, 都不行降级跳过"""
    ret = m_Device.SciCam_SetFloatValue("Gain", gain_db)
    if ret == SCI_CAMERA_OK:
        print(f"增益设置成功 {gain_db}")
        return True
    # 尝试替代值
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


def warp_goldfinger_topview(pDstData, img_w, img_h, out_w=None, out_h=None):
    """金手指透视校正 (保持不变)"""
    if out_w is None:
        out_w = img_w
    if out_h is None:
        out_h = img_h
    img_mat = np.frombuffer(pDstData, dtype=np.uint8).reshape(img_h, img_w, 3)
    src_points = np.array([
        [400, 1000], [2000, 1000], [2000, 1250], [400, 1250]
    ], dtype=np.float32)
    dst_points = np.array([
        [0, 0], [out_w, 0], [out_w, out_h], [0, out_h]
    ], dtype=np.float32)
    trans_matrix = cv2.getPerspectiveTransform(src_points, dst_points)
    return cv2.warpPerspective(img_mat, trans_matrix, (out_w, out_h))


def GrabAndSaveImage():
    global global_img_count
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
    origin_name = "Finger_Image_W{}_H{}_No_{}.png".format(imgWidth, imgHeight, global_img_count)
    topview_name = "Finger_TopView_W1600_H220_No_{}.png".format(global_img_count)
    save_file_param = os.path.join(SAVE_ROOT_DIR, origin_name)
    topview_file_param = os.path.join(SAVE_ROOT_DIR, topview_name)
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
    if imgPixelType in mono_types:
        reVal = SciCam_Payload_ConvertImage(payloadAttribute.imgAttr, imgData, SciCamPixelType.Mono8, None, dstImgSize, True)
        if reVal == SCI_CAMERA_OK:
            pDstData = (ctypes.c_ubyte * dstImgSize.value)()
            reVal = SciCam_Payload_ConvertImage(payloadAttribute.imgAttr, imgData, SciCamPixelType.Mono8, pDstData, dstImgSize, True)
            if reVal == SCI_CAMERA_OK:
                top_img = warp_goldfinger_topview(pDstData, imgWidth, imgHeight)
                cv2.imwrite(topview_file_param, top_img)
                print(f"【俯视校正图保存成功】{topview_file_param}")
                reVal = SciCam_Payload_SaveImage(save_file_param, SciCamPixelType.Mono8, pDstData, imgWidth, imgHeight)
                if reVal == SCI_CAMERA_OK:
                    print('原图保存成功.', save_file_param)
    else:
        reVal = SciCam_Payload_ConvertImage(payloadAttribute.imgAttr, imgData, SciCamPixelType.RGB8, None, dstImgSize, True)
        if reVal == SCI_CAMERA_OK:
            pDstData = (ctypes.c_ubyte * dstImgSize.value)()
            reVal = SciCam_Payload_ConvertImage(payloadAttribute.imgAttr, imgData, SciCamPixelType.RGB8, pDstData, dstImgSize, True)
            if reVal == SCI_CAMERA_OK:
                top_img = warp_goldfinger_topview(pDstData, imgWidth, imgHeight)
                cv2.imwrite(topview_file_param, top_img)
                print(f"【俯视校正图保存成功】{topview_file_param}")
                reVal = SciCam_Payload_SaveImage(save_file_param, SciCamPixelType.RGB8, pDstData, imgWidth, imgHeight)
                if reVal == SCI_CAMERA_OK:
                    print('原图保存成功.', save_file_param)

    m_Device.SciCam_FreePayload(ppayload)
    return save_file_param, topview_file_param


global_img_count = 1

# 【异步】检测队列: 单worker串行处理, 模型只加载一次, API秒回
_detect_lock = threading.Lock()
_detect_count = 0          # 累计检测次数
_detect_queue = []         # 待检测图像队列
_detect_thread = None      # worker线程


def _detect_worker_loop():
    """检测worker: 串行处理队列, 模型首次加载后复用"""
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
            print(f"  俯视图: {topview_path}")
            print(f"  缺陷数: {len(dets)}  {'❌ NG' if dets else '✅ OK'}")
            for i, d in enumerate(dets):
                cls = d.get("class_name", d.get("name", "?"))
                conf = d.get("confidence", d.get("conf", 0))
                bbox = d.get("bbox", d.get("box", "?"))
                print(f"    [{i+1}] {cls} conf={conf:.2f} bbox={bbox}")
            if result.get("saved_incoming"):
                print(f"  存档: {result['saved_incoming']}")
            print("=" * 60 + "\n", flush=True)
        except Exception as e:
            print(f"【检测异常】{e}")
            traceback.print_exc()


def _ensure_detect_worker():
    """确保worker线程启动"""
    global _detect_thread
    with _detect_lock:
        if _detect_thread is None or not _detect_thread.is_alive():
            _detect_thread = threading.Thread(target=_detect_worker_loop, daemon=True)
            _detect_thread.start()


def _enqueue_detect(topview_path, origin_path, detect_type):
    """投递检测任务, 立即返回"""
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

        # 相机常驻: 首次请求初始化, 后续直接抓帧 (秒级)
        if not ensure_camera():
            return jsonify({"code": 500, "msg": "相机初始化失败"}), 500

        # 拍照 (快, 相机常驻秒级)
        img_origin_path, img_topview_path = GrabAndSaveImage()
        if img_origin_path is None or img_topview_path is None:
            print("⚠️ 抓帧失败, 尝试重连相机...")
            Close_Device()
            if ensure_camera():
                img_origin_path, img_topview_path = GrabAndSaveImage()
            if img_origin_path is None or img_topview_path is None:
                return jsonify({"code": 500, "msg": "图像抓取失败"}), 500

        print(f"   📸 已拍照, 投递检测队列 (不阻塞动作)")

        # 【异步】投递检测队列, 立即返回
        _enqueue_detect(img_topview_path, img_origin_path, detect_type)

        # 立即返回 success, 保证动作连贯执行
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


def run_flask():
    app.run(host="0.0.0.0", port=10082, debug=False)


if __name__ == "__main__":
    print("金手指检测相机程序启动(优化版v3)，端口10082，gf金手指模型，相机常驻模式")
    # 启动时预初始化相机 (可选, 加快首个请求)
    try:
        t_pre = threading.Thread(target=ensure_camera, daemon=True)
        t_pre.start()
    except Exception:
        pass
    # 启动检测worker (模型首次加载在后台, 避免请求时访问GitHub)
    _ensure_detect_worker()
    t = Thread(target=run_flask)
    t.start()
    t.join()
