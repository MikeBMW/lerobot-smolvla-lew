# -*- coding: utf-8 -*-
"""YOLO 感知模块 — 状态空间感知链实装 (2026-08-19 老倪: 用实际模型加载)

参考 Z700 方案书感知执行层 (视觉 800万像素/力觉/触觉) + 能力库 B 感知域:
  B1 目标识别定位 — YOLO 检测 (2D 框 + 类别 + 置信度)
  B2 空间位姿感知 — 2D 框 → 相机反投影 → 3D 位姿 (平面假设/标定)
  B5 外观质量检测 — 扩展: 检测区域裁剪 (供 AOI 判级)

真机同构原则 (2026-08-07 老倪): 真机只有 YOLO 2D 检测, 没有模拟器直接给的 39D。
本模块不依赖 metaworld/mujoco — 相机参数由配置提供, 仿真/真机统一走同一链路。

加载: YOLO(weights) 实际加载 (yolov8s.pt / yolo26n.pt / 训练过的 光模块 权重)
输出: 检测框 → 3D 位姿 → 替换 39D 观测对应段 → 43D 状态空间观测
"""
import os
import numpy as np

# 相机默认参数 (corner2 视角, 仿真标定; 真机用相机标定外参)
_DEF_CAM = {"cam_pos": np.array([0.0, -0.25, 0.9]),
            "cam_forward": np.array([0.0, 0.0, -1.0]),
            "fovy": 45.0, "H": 480, "W": 480}

# 39D 结构: [0:3]=hand, [18:21]=光模块, [36:39]=hole/goal (与 yolo_state_aligner 一致)
_SEG = {"hand": (0, 3), "peg": (18, 21), "hole": (36, 39)}
# 平面高度假设 (m) — 真机用深度相机/标定替代
_PLANE_Z = {"hand": 0.155, "peg": 0.03, "hole": 0.129}


class YoloPerception:
    """状态空间 YOLO 感知 (B1 识别 + B2 位姿 + 状态对齐)"""

    def __init__(self, weights=None, cam=None):
        self.weights = weights or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))))), "yolov8s.pt")
        self.cam = dict(_DEF_CAM)
        if cam:
            self.cam.update(cam)
        self.model = None
        self.names = {}
        self._load()

    # ── 实际模型加载 ──
    def _load(self):
        """加载 YOLO 权重 (实际模型)"""
        from ultralytics import YOLO
        self.model = YOLO(self.weights)
        self.names = self.model.names
        print(f"✅ YOLO 实际加载: {os.path.basename(self.weights)} "
              f"({len(self.names)} 类)")

    # ── B1 目标识别定位 (2D 检测) ──
    def detect(self, img, conf=0.4, classes=None):
        """图像 → 检测结果 {cls: {box, conf, cx, cy}}
        img: RGB uint8 (H,W,3) 或 0~1 float"""
        if img is None or getattr(img, "size", 0) == 0:
            return {}
        if img.dtype != np.uint8:
            img = (img * 255).astype(np.uint8)
        # 🐛 ultralytics 内部用 BGR (记忆坑: RGB 检测失败)
        import cv2
        img_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        res = self.model.predict(img_bgr, conf=conf, classes=classes,
                                 verbose=False)[0]
        out = {}
        for b in res.boxes:
            cls = res.names[int(b.cls)]
            x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
            out[cls] = {"box": [x1, y1, x2, y2], "conf": float(b.conf[0]),
                        "cx": (x1 + x2) / 2, "cy": (y1 + y2) / 2}
        return out

    # ── B2 空间位姿感知 (2D → 3D 反投影) ──
    def to_3d(self, det):
        """检测框中心 → 3D 位姿 (平面假设反投影) → {cls: (x,y,z)}"""
        cam = self.cam
        f = (cam["H"] / 2) / np.tan(np.radians(cam["fovy"]) / 2)
        fwd = np.asarray(cam["cam_forward"], dtype=float)
        fwd = fwd / np.linalg.norm(fwd)
        right = np.cross(fwd, np.array([0, 0, 1]))
        right = right / (np.linalg.norm(right) + 1e-9)
        up = np.cross(right, fwd)
        pos = np.asarray(cam["cam_pos"], dtype=float)
        out = {}
        for cls, d in det.items():
            ndc_x = (d["cx"] - cam["W"] / 2) / f
            ndc_y = (d["cy"] - cam["H"] / 2) / f
            dir_ = fwd + ndc_x * right + ndc_y * up
            dir_ = dir_ / (np.linalg.norm(dir_) + 1e-9)
            # 经验修正 (仿真标定; 真机用相机标定矩阵)
            dir_ = np.array([-dir_[0], -dir_[1], dir_[2]])
            plane_z = _PLANE_Z.get(cls, 0.1)
            if abs(dir_[2]) < 1e-8:
                continue
            t = (plane_z - pos[2]) / dir_[2]
            if t < 0:
                continue
            pt = pos + t * dir_ - np.array([0.04, 0.0, 0.0])  # 标定修正
            out[cls] = pt
        return out

    # ── 状态对齐 (→ 43D 状态空间观测) ──
    def align_obs(self, obs39=None, det3d=None):
        """39D 观测 + YOLO 3D 检测 → 43D 状态空间观测
        obs39 缺省 → 零向量; det3d {cls: (x,y,z)} 替换对应段"""
        obs39 = np.zeros(39, dtype=float) if obs39 is None \
            else np.asarray(obs39, dtype=float).ravel()[:39]
        aligned = obs39.copy()
        for cls, pt in (det3d or {}).items():
            if cls in _SEG and pt is not None:
                a, b = _SEG[cls]
                aligned[a:b] = np.asarray(pt, dtype=float)
        # 触觉 4D 缺省零 (perception.py 接口: 43D = 39D + 4D)
        tactile = np.zeros(4, dtype=float)
        return np.concatenate([aligned, tactile])

    # ── 冒烟验证 (用实际模型跑一张图) ──
    def smoke(self, img=None):
        """跑一次推理 → (ok, 检测数, 3D 结果)"""
        if img is None:
            img = np.zeros((480, 480, 3), dtype=np.uint8)
        det = self.detect(img)
        det3d = self.to_3d(det)
        obs43 = self.align_obs(None, det3d)
        return (len(det) > 0), len(det), det3d, obs43.shape[0]


def main():
    """CLI: python yolo_perception.py [weights] [image]"""
    import sys
    weights = sys.argv[1] if len(sys.argv) > 1 else None
    img_path = sys.argv[2] if len(sys.argv) > 2 else None
    p = YoloPerception(weights=weights)
    if img_path:
        from PIL import Image
        img = np.asarray(Image.open(img_path).convert("RGB"))
    else:
        img = np.zeros((480, 480, 3), dtype=np.uint8)
    det = p.detect(img)
    det3d = p.to_3d(det)
    print(f"检测: {len(det)} 个目标")
    for cls, d in det.items():
        print(f"  {cls}: conf={d['conf']:.2f} box={[round(x) for x in d['box']]} "
              f"3D={np.round(det3d.get(cls, [0, 0, 0]), 3).tolist() if cls in det3d else '-'}")
    obs43 = p.align_obs(None, det3d)
    print(f"43D 状态空间观测: dim={obs43.shape[0]} 前9维={np.round(obs43[:9], 3).tolist()}")


if __name__ == "__main__":
    main()
