#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""frame_source.py — 感知输入源抽象 (仿真 → 真机无缝移植的**唯一差异点收口**)

老倪 2026-09-17: 「这段代码原来是适配仿真程序的, 现在引入真机 realsense 相机…目标是
仿真运行完成后要无缝移植到真机」+「yolo 模型跑在 Orin 上感知真实环境」。

设计原则 (为什么这样拆):
  仿真与真机的差异只有 5 处 —— 图像从哪来、相机内参从哪来、深度从哪来、相机外参从哪来、
  图像朝向/通道口径。把**这 5 处**收口到 FrameSource, 检测/反投影/39D 对齐**一份代码**
  (yolo_state_aligner.detect_3d) → 仿真与真机完全同源, 换源即换世界, 不需要第二套实现。
  「不静默降级」: 任何一处缺失 (无外参/无内参/无深度) 都显式标 uncalibrated/reason,
  绝不填假值 (老倪红线: 缺证据就标缺口)。

每个源必须声明 (profile):
  rgb_order   : 'RGB' | 'BGR'      —— 送 YOLO 前的通道顺序 (ultralytics 吃 BGR)
  train_rot_k : 0/2  (90/270 不支持, 显式断言) —— 与训练数据朝向对齐 (仿真训练集是 rot90(k=2))
  depth_metric: True=深度是米制真值(RealSense) / False=YOLO depth head 预测(仿真)
  depth_scale : 预测深度的尺度校准 (仿真 depth head 需要, 米制深度恒 1.0)
  class_map   : 训练类名 → 业务名 (peg→光模块; 类 id 顺序不许改)
  frame       : 3D 点所在坐标系 ('base_link' 真机 / 'world' 仿真)

可用源:
  SimFrameSource(env, camera_name)      仿真 metaworld (与既有行为逐位一致)
  RosFrameSource(...)                   ROS2 话题 (Orin 本机 或 4060 侧 Docker 只读订阅)
  UvcFrameSource(device, w, h, fps)     直读 /dev/videoN (RealSense 免装 SDK/驱动; Orin 已装 cv2)
  FileFrameSource(dir)                  录制的帧回放 (离线回归/标定)
"""
from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass, field

import numpy as np

# ── 业务口径常量 (单一事实来源: 训练脚本 gen_yolo_data.py 的绑定, 勿改 id 顺序) ──
ROT_K_TRAIN = 2                     # 仿真训练集: Image.fromarray(np.rot90(img, k=2))
CLASS_MAP = {"hand": "hand", "peg": "光模块", "hole": "hole"}
DEPTH_SCALE_PEG = 0.9616            # 仿真 depth head 尺度 (10 布局标定)
DEPTH_SCALE_HAND = 0.885
PLANE_Z_SIM = {"hand": 0.155, "光模块": 0.03, "hole": 0.129}   # 仿真写死 z 平面回退


@dataclass
class Frame:
    """一帧感知输入 (所有字段都是"实际拿到的东西", 缺就 None + 记 reason)"""
    rgb: np.ndarray | None = None                  # HxWx3 uint8 (源自然朝向)
    depth_m: np.ndarray | None = None              # HxW float32 米 (None=无深度)
    K: np.ndarray | None = None                    # 3x3 内参 (None=fovy 回退)
    dist: np.ndarray | None = None
    T_base_cam: np.ndarray | None = None           # 4x4 cam→base (None=无外参)
    fovy_deg: float | None = None                  # 仿真只有 fovy (单焦距近似)
    src: str = ""
    ts: float = 0.0
    notes: list = field(default_factory=list)

    def note(self, s: str):
        if s not in self.notes:
            self.notes.append(s)
        return self


class FrameSource:
    """源基类 — profile 声明口径, grab() 取一帧"""
    name = "base"
    rgb_order = "RGB"
    train_rot_k = ROT_K_TRAIN
    depth_metric = False
    depth_scale = 1.0
    class_map = CLASS_MAP
    frame = "world"

    # 供 aligner 用的相机几何 (仿真: env 常量; 真机: 标定文件/话题)
    def cam_pos(self) -> np.ndarray | None:
        return None

    def cam_mat(self) -> np.ndarray | None:
        return None

    def plane_z(self) -> dict:
        return {}

    def grab(self) -> Frame:
        raise NotImplementedError


# ══════════════════════════════════════════════════════════════════════════
# ① 仿真源 (与 2026-09 前行为逐位一致)
# ══════════════════════════════════════════════════════════════════════════
class SimFrameSource(FrameSource):
    """metaworld 环境源: render 取帧, 内参/外参来自 mujoco 相机模型, 深度走 YOLO depth head"""
    name = "sim"
    rgb_order = "RGB"
    train_rot_k = ROT_K_TRAIN
    depth_metric = False
    depth_scale = DEPTH_SCALE_PEG
    frame = "world"

    def __init__(self, env, camera_name: str = "corner2"):
        self.env = env
        self.camera_name = camera_name
        self.cam_id = env.model.camera(camera_name).id

    def cam_pos(self):
        return np.asarray(self.env.model.cam_pos[self.cam_id]).copy()

    def cam_mat(self):
        return np.asarray(self.env.model.cam_mat0[self.cam_id]).reshape(3, 3)

    def plane_z(self):
        return dict(PLANE_Z_SIM)

    def fovy(self):
        return float(self.env.model.cam_fovy[self.cam_id])

    def grab(self, img=None, reset_seed=None) -> Frame:
        if img is None:
            if reset_seed is not None:
                self.env._freeze_rand_vec = False
                self.env.reset(seed=reset_seed)
                self.env._freeze_rand_vec = True
            img = self.env.render()
        img = np.asarray(img)
        H, Wd = img.shape[:2]
        fovy = self.fovy()
        f = (H / 2) / np.tan(np.radians(fovy) / 2)
        K = np.array([[f, 0.0, Wd / 2], [0.0, f, H / 2], [0.0, 0.0, 1.0]])
        # 相机外参用**标准光学系约定** (+x 右/+y 下/+z 朝前)。mujoco 的 cam_mat0 是
        # "看向 -z" 约定 → 乘 S=diag(1,-1,-1) 换成标准系 (det=+1, 合法旋转);
        # 这样通用路径 estimate_3d 与 legacy 反投影数值等价 (已 parity 取证 2.2e-16)。
        T = np.eye(4)
        T[:3, :3] = self.cam_mat() @ np.diag([1.0, -1.0, -1.0])
        T[:3, 3] = self.cam_pos()
        return Frame(rgb=img, K=K, T_base_cam=T, fovy_deg=fovy, src="sim", notes=[])


# ══════════════════════════════════════════════════════════════════════════
# ② 真机标定文件 (内参/外参/平面 的唯一出处; 未标定 → 显式 uncalibrated)
# ══════════════════════════════════════════════════════════════════════════
CALIB_PATH_DEFAULT = os.environ.get(
    "ZMAX_REAL_CAM_CALIB",
    "/home/ubuntu/lerobot-smolvla-lew/models/real_cam_calib.json")


def load_real_calib(path: str | None = None) -> dict:
    """读真机相机标定: {K:[9], dist:[..], T_base_cam:[16], plane_z:{类:z}, depth_metric:bool}"""
    p = path or CALIB_PATH_DEFAULT
    if not os.path.isfile(p):
        return {"ready": False, "reason": f"标定文件不存在: {p}", "path": p}
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception as e:                                                 # noqa: BLE001
        return {"ready": False, "reason": f"标定文件解析失败: {type(e).__name__}: {e}", "path": p}
    d["ready"] = all(k in d for k in ("K",)) and (len(d.get("K") or []) == 9)
    if not d["ready"]:
        d.setdefault("reason", "缺 K (3x3)")
    d.setdefault("path", p)
    return d


# ══════════════════════════════════════════════════════════════════════════
# ③ ROS2 源 (Orin 本机 或 4060 侧 Docker ros:humble --net host 只读订阅)
# ══════════════════════════════════════════════════════════════════════════
class RosFrameSource(FrameSource):
    """订阅 ROS2 图像/深度/内参/位姿 → Frame

    真机口径:
      · 深度 = RealSense 米制 (16UC1 毫米或 32FC1 米) → depth_metric=True, scale=1.0,
        因此**不需要** YOLO depth head (仿真那套是补仿真缺深度的, 真机有真深度)
      · 相机外参 = tf(base_link→相机 frame) 或标定文件; 都没有 → uncalibrated (不编造)
      · hand 不用视觉 (R1 契约): 真机末端 = /robot/tcp_pose 真值 (50Hz, frame=base_link)
    """
    name = "ros"
    rgb_order = "RGB"
    train_rot_k = int(os.environ.get("ZMAX_REAL_ROT_K", "0"))   # 真机自然朝向=0 (sim=2)
    depth_metric = True
    depth_scale = 1.0
    frame = "base_link"

    def __init__(self, topic_color="/realsense/color/image_raw",
                 topic_depth="/realsense/depth/image_rect_raw",
                 topic_info="/realsense/color/camera_info",
                 topic_tcp="/robot/tcp_pose",
                 domain_id=None, depth_in_mm=True, calib_path=None, timeout=10.0):
        if domain_id is not None:
            os.environ["ROS_DOMAIN_ID"] = str(domain_id)
        self.topic_color, self.topic_depth, self.topic_info, self.topic_tcp = \
            topic_color, topic_depth, topic_info, topic_tcp
        self.depth_in_mm = depth_in_mm
        self.timeout = timeout
        self.calib = load_real_calib(calib_path)
        self._rgb = None
        self._depth = None
        self._ci = None
        self._tcp = None
        self._init_ros()

    def _init_ros(self):
        import rclpy
        from rclpy.node import Node
        from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
        from sensor_msgs.msg import CameraInfo, Image
        from geometry_msgs.msg import PoseStamped

        self._rclpy = rclpy
        self._BE = QoSProfile(depth=5, history=HistoryPolicy.KEEP_LAST,
                              reliability=ReliabilityPolicy.BEST_EFFORT)
        self._REL = QoSProfile(depth=5, history=HistoryPolicy.KEEP_LAST,
                               reliability=ReliabilityPolicy.RELIABLE)
        if not rclpy.ok():
            rclpy.init()
        self.node = Node("zmax_frame_source")
        self.node.create_subscription(Image, self.topic_color, self._on_rgb, self._BE)
        self.node.create_subscription(Image, self.topic_depth, self._on_depth, self._REL)
        self.node.create_subscription(CameraInfo, self.topic_info, self._on_info, self._REL)
        if self.topic_tcp:
            try:
                self.node.create_subscription(PoseStamped, self.topic_tcp, self._on_tcp, self._BE)
            except Exception:                                              # noqa: BLE001
                self._tcp = None

    # 解码 (处理 step 行填充)
    @staticmethod
    def _np_img(m):
        it = {"rgb8": np.uint8, "bgr8": np.uint8, "mono8": np.uint8,
              "16UC1": np.uint16, "mono16": np.uint16, "32FC1": np.float32}[m.encoding]
        ch = 3 if m.encoding in ("rgb8", "bgr8") else 1
        raw = np.frombuffer(bytes(m.data), dtype=it)
        raw = raw.reshape(m.height, m.step // raw.dtype.itemsize)[:, : m.width * ch]
        a = raw.reshape(m.height, m.width, ch)
        return a[:, :, 0] if ch == 1 else a[:, :, ::-1] if m.encoding == "bgr8" else a

    def _on_rgb(self, m):
        try:
            self._rgb = (self._np_img(m), m.header.frame_id or "camera")
        except Exception:                                                  # noqa: BLE001
            pass

    def _on_depth(self, m):
        try:
            a = self._np_img(m)
            if m.encoding == "16UC1" and self.depth_in_mm:
                a = a.astype(np.float32) * 0.001
            self._depth = a.astype(np.float32)
        except Exception:                                                  # noqa: BLE001
            pass

    def _on_info(self, m):
        self._ci = {"K": np.asarray(m.k, float).reshape(3, 3),
                    "D": np.asarray(m.d, float), "w": m.width, "h": m.height,
                    "frame_id": m.header.frame_id}

    def _on_tcp(self, m):
        self._tcp = {"frame_id": m.header.frame_id,
                     "p": np.array([m.pose.position.x, m.pose.position.y, m.pose.position.z]),
                     "q": np.array([m.pose.orientation.x, m.pose.orientation.y,
                                    m.pose.orientation.z, m.pose.orientation.w])}

    def spin(self, seconds: float):
        import time
        t0 = time.time()
        while time.time() - t0 < seconds and self._rgb is None:
            self._rclpy.spin_once(self.node, timeout_sec=0.2)

    def grab(self, spin_s: float | None = None) -> Frame:
        self.spin(spin_s if spin_s is not None else self.timeout)
        f = Frame(src="ros", notes=[])
        if self._rgb is None:
            return f.note(f"超时无图像帧: {self.topic_color} (发布者可能没在跑 — pub count 先查)")
        f.rgb, cam_frame = self._rgb
        if self._depth is not None:
            f.depth_m = self._depth
            if f.depth_m.shape[:2] != f.rgb.shape[:2]:
                f.note(f"深度尺寸 {f.depth_m.shape}≠图像 {f.rgb.shape[:2]} → 未对齐, 需 align 步骤/换 *_aligned_depth* 话题")
        else:
            f.note(f"无深度帧: {self.topic_depth}")
        if self._ci:
            f.K, f.dist = self._ci["K"], self._ci["D"]
        T = self._tf_base_cam(cam_frame)
        if T is not None:
            f.T_base_cam = T
        else:
            f.note(f"无 base_link→{cam_frame} 外参 (tf 无该链且标定文件未就绪) → 3D 输出相机系")
        if self.calib.get("ready"):
            f.note(f"标定文件已载入: {os.path.basename(self.calib['path'])}")
        return f

    def _tf_base_cam(self, cam_frame: str):
        """从 tf_static 拿 base_link→cam_frame (拿不到 → 用标定文件 T_base_cam)"""
        try:
            from tf2_msgs.msg import TFMessage
            import rclpy
            from rclpy.node import Node
            from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
            got = {}

            def _cb(m):
                for t in m.transforms:
                    got[(t.header.frame_id, t.child_frame_id)] = t.transform

            tmp = Node("zmax_tf_sniff")
            tmp.create_subscription(TFMessage, "/tf_static", _cb,
                                    QoSProfile(depth=1, history=HistoryPolicy.KEEP_LAST,
                                               reliability=ReliabilityPolicy.RELIABLE,
                                               durability=DurabilityPolicy.TRANSIENT_LOCAL))
            import time
            t0 = time.time()
            while time.time() - t0 < 2.0 and not got:
                rclpy.spin_once(tmp, timeout_sec=0.2)
            tmp.destroy_node()
            for (parent, child), tr in got.items():
                if "base" in parent and child == cam_frame:
                    T = np.eye(4)
                    T[:3, 3] = [tr.translation.x, tr.translation.y, tr.translation.z]
                    x, y, z, w = tr.rotation.x, tr.rotation.y, tr.rotation.z, tr.rotation.w
                    R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
                    T[:3, :3] = R
                    return T
        except Exception:                                                  # noqa: BLE001
            pass
        c = self.calib
        if c.get("ready") and c.get("T_base_cam") and len(c["T_base_cam"]) == 16:
            return np.asarray(c["T_base_cam"], float).reshape(4, 4)
        return None

    def plane_z(self) -> dict:
        c = self.calib
        return dict(c.get("plane_z") or {}) if c.get("ready") else {}

    def tcp(self):
        return self._tcp


# ══════════════════════════════════════════════════════════════════════════
# ④ UVC 直读源 (RealSense 免装 SDK/ROS 驱动: Orin 已装 cv2, 零安装即可取真像素)
# ══════════════════════════════════════════════════════════════════════════
class UvcFrameSource(FrameSource):
    """cv2.VideoCapture(/dev/videoN) — Orin 上 D405 的彩色/IR 流 (内核 uvcvideo 驱动)

    实测 (Orin, D405): /dev/video2 与 /dev/video4 可开, 640x480 MJPG 有画面;
    video0/1/3/5 被占用 → 彩色流是 2 或 4 (按帧内容判断: 彩色流 mean/std 与 IR 不同)。
    ⚠️ UVC 直读拿不到 RealSense 内参与硬件对齐深度 (那要 SDK/驱动) → 内参走标定文件,
    无标定则 3D 输出相机系 (诚实标注), 不编造。
    """
    name = "uvc"
    rgb_order = "BGR"            # cv2 读出即 BGR
    train_rot_k = int(os.environ.get("ZMAX_REAL_ROT_K", "0"))
    depth_metric = False         # UVC 单流无深度 (要深度需 SDK/驱动)
    depth_scale = 1.0
    frame = "camera"

    def __init__(self, device=2, width=640, height=480, fps=15, calib_path=None):
        import cv2
        self.cv2 = cv2
        self.device = device
        self.cap = cv2.VideoCapture(int(device), cv2.CAP_V4L2)
        if not self.cap.isOpened():
            raise RuntimeError(f"/dev/video{device} 打不开 (被占用或不支持)")
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FPS, fps)
        self.calib = load_real_calib(calib_path)
        for _ in range(3):                     # 丢弃预热帧 (曝光收敛)
            self.cap.read()

    def grab(self, img=None) -> Frame:
        f = Frame(src=f"uvc:{self.device}", notes=[], K=None, depth_m=None)
        if img is None:
            ok, fr = self.cap.read()
            if not ok:
                return f.note("UVC 读帧失败")
            img = fr
        f.rgb = np.asarray(img)
        c = self.calib
        if c.get("ready"):
            f.K = np.asarray(c["K"], float).reshape(3, 3)
            if c.get("T_base_cam") and len(c["T_base_cam"]) == 16:
                f.T_base_cam = np.asarray(c["T_base_cam"], float).reshape(4, 4)
        else:
            f.note(f"无相机标定 ({c.get('reason')}) → 只有 2D 框, 无 3D (不编造)")
        return f

    def plane_z(self):
        return dict(self.calib.get("plane_z") or {}) if self.calib.get("ready") else {}

    def release(self):
        try:
            self.cap.release()
        except Exception:                                                  # noqa: BLE001
            pass


# ══════════════════════════════════════════════════════════════════════════
# ⑤ 文件回放源 (离线回归/标定/无相机时验证全链路)
# ══════════════════════════════════════════════════════════════════════════
class FileFrameSource(FrameSource):
    """回放目录里的图片(+可选同名 .npy 深度) — 无相机环境下的全链路验证"""
    name = "file"
    rgb_order = "RGB"
    train_rot_k = int(os.environ.get("ZMAX_REAL_ROT_K", "0"))
    depth_metric = True
    depth_scale = 1.0
    frame = "camera"          # 回放的是真机/任意相机帧 → 3D 在相机系 (有标定才转 base)

    def __init__(self, directory, calib_path=None, pattern=("*.jpg", "*.png", "*.jpeg")):
        import cv2
        self.cv2 = cv2
        self.files = sorted(sum((glob.glob(os.path.join(directory, p)) for p in pattern), []))
        self.i = 0
        self.calib = load_real_calib(calib_path)
        if not self.files:
            raise RuntimeError(f"{directory} 里没有图片")

    def grab(self, img=None) -> Frame:
        f = Frame(src="file", notes=[])
        if img is None:
            img = self.cv2.imread(self.files[self.i % len(self.files)])
            self.i += 1
        f.rgb = self.cv2.cvtColor(img, self.cv2.COLOR_BGR2RGB)
        d = os.path.splitext(self.files[(self.i - 1) % len(self.files)])[0] + ".npy"
        if os.path.isfile(d):
            f.depth_m = np.load(d).astype(np.float32)
        c = self.calib
        if c.get("ready"):
            f.K = np.asarray(c["K"], float).reshape(3, 3)
            if c.get("T_base_cam") and len(c["T_base_cam"]) == 16:
                f.T_base_cam = np.asarray(c["T_base_cam"], float).reshape(4, 4)
        return f

    def plane_z(self):
        return dict(self.calib.get("plane_z") or {}) if self.calib.get("ready") else {}


def make_source(spec: str, **kw) -> FrameSource:
    """'sim' | 'ros' | 'uvc:N' | 'file:/dir' → 对应源 (给 CLI/GUI 统一入口)"""
    if spec == "sim":
        raise RuntimeError("sim 源需要传入 env (SimFrameSource(env))")
    if spec == "ros":
        return RosFrameSource(**kw)
    if spec.startswith("uvc"):
        dev = int(spec.split(":")[1]) if ":" in spec else 2
        return UvcFrameSource(device=dev, **{k: v for k, v in kw.items()
                                             if k in ("width", "height", "fps", "calib_path")})
    if spec.startswith("file:"):
        return FileFrameSource(spec.split(":", 1)[1],
                               **{k: v for k, v in kw.items() if k == "calib_path"})
    raise ValueError(f"未知源: {spec}")
