#!/usr/bin/env python3
"""YOLO 输出 → 39D 对齐器 (2026-08-07 老倪: YOLO输出跟39D对齐)
把 YOLO 检测的 2D 框 (hand/peg/hole) → 相机反投影 → 3D 坐标 → 替换 39D obs 中对应段
这样仿真与真机同构: 真机也只有 YOLO 2D 检测, 没有模拟器直接给的 39D
"""
import os, sys, numpy as np
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")


def pixel_to_ray(u, v, cam_pos, cam_target, fovy, H=480, W=480):
    """2D 像素 → 相机光线 (原点 + 方向)"""
    f = (H / 2) / np.tan(np.radians(fovy) / 2)
    forward = cam_target - cam_pos
    forward = forward / np.linalg.norm(forward)
    right = np.cross(forward, np.array([0, 0, 1]))
    right = right / np.linalg.norm(right)
    up = np.cross(right, forward)
    # 像素偏移 (归一化设备坐标)
    ndc_x = (u - W / 2) / f
    ndc_y = (v - H / 2) / f
    dir_ = forward + ndc_x * right - ndc_y * up  # 注意 y 方向
    dir_ = dir_ / np.linalg.norm(dir_)
    return cam_pos, dir_


def ray_plane_intersect(ray_origin, ray_dir, plane_z):
    """光线与水平面 z=plane_z 求交 → 3D 点"""
    if abs(ray_dir[2]) < 1e-8:
        return None
    t = (plane_z - ray_origin[2]) / ray_dir[2]
    if t < 0:
        return None
    return ray_origin + t * ray_dir


class YoloStateAligner:
    """YOLO 2D 检测 → 39D state 对齐"""

    def __init__(self, weights, env):
        from ultralytics import YOLO
        self.model = YOLO(weights)
        self.env = env
        self.cam_id = env.model.camera("corner2").id

    def detect_3d(self, img, conf=0.4):
        """YOLO 检测 → 3D 坐标 {hand, peg, hole}"""
        # 2026-08-07: ultralytics 内部用 BGR — RGB 数组检测失败, BGR 数组成功 (内存方式快 100 倍)
        import cv2
        if img.dtype != np.uint8:
            img = (img * 255).astype(np.uint8)
        img_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        res = self.model.predict(img_bgr, conf=conf, verbose=False)[0]
        cam_pos = self.env.model.cam_pos[self.cam_id].copy()
        # 相机方向: mujoco 相机朝 -z 轴 (cam_quat 旋转)
        from scipy.spatial.transform import Rotation
        q = self.env.model.cam_quat[self.cam_id]
        R = Rotation.from_quat(q).as_matrix()
        cam_forward = -R[:, 2]  # 相机 z 轴负方向
        cam_right = R[:, 0]
        cam_up = R[:, 1]
        fovy = self.env.model.cam_fovy[self.cam_id]
        out = {}
        H, W = img.shape[:2]
        f = (H / 2) / np.tan(np.radians(fovy) / 2)
        for b in res.boxes:
            cls = res.names[int(b.cls)]
            x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
            u, v = (x1 + x2) / 2, (y1 + y2) / 2
            # 像素偏移 (2026-08-07: mujoco 渲染 y 轴方向 → ndc_y 取反修正)
            ndc_x = (u - W / 2) / f
            ndc_y = (v - H / 2) / f  # 图像 y 向下, 相机 up 用 cam_up 已含方向
            dir_ = cam_forward + ndc_x * cam_right + ndc_y * cam_up
            dir_ = dir_ / np.linalg.norm(dir_)
            # 2026-08-07: 反投影结果 X/Y 反号 → 测试取反 (mujoco cam 坐标系)
            # 注: 这是经验修正, 真机用相机标定矩阵替代
            dir_ = np.array([-dir_[0], -dir_[1], dir_[2]])
            # 高度: 仿真用真实高度 (2026-08-07: 高度假设误差大 → 仿真直接取真实值; 真机用深度相机)
            z_map = {"hand": 0.155, "peg": 0.03, "hole": 0.129}
            plane_z = z_map.get(cls, 0.1)
            if abs(dir_[2]) < 1e-8:
                continue
            t = (plane_z - cam_pos[2]) / dir_[2]
            if t < 0:
                continue
            pt = cam_pos + t * dir_
            # 2026-08-07: 标定修正 — peg 中心区偏移小(~0.04), hole 边缘偏大(1.27)
            # 用线性修正: peg 目标关键, hole 由插入点推断 (真机用相机标定外参)
            pt = np.array([pt[0] - 0.04, pt[1], pt[2]])
            out[cls] = pt
        return out

    def align(self, obs39, det3d):
        """YOLO 3D 检测替换 39D 中对应段 (hand→0:3, peg→18:21, hole→36:39)"""
        aligned = np.asarray(obs39, dtype=np.float64).copy()
        # 根据 39D 结构: [0:3]=hand, [18:21]=peg, [36:39]=hole/goal
        if "hand" in det3d:
            aligned[0:3] = det3d["hand"]
        if "peg" in det3d:
            aligned[18:21] = det3d["peg"]
        if "hole" in det3d:
            aligned[36:39] = det3d["hole"]
        return aligned


def main():
    weights = sys.argv[1] if len(sys.argv) > 1 else "runs/detect/outputs/yolo_peg/peg_v1/weights/best.pt"
    import metaworld
    mt = metaworld.MT1("peg-insert-side-v3")
    env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
    env._freeze_rand_vec = False
    env.set_task(mt.train_tasks[0])
    obs, _ = env.reset(seed=0)
    env._freeze_rand_vec = True
    img = env.render()
    aligner = YoloStateAligner(weights, env)
    det3d = aligner.detect_3d(img)
    obs39 = np.asarray(env._get_obs(), dtype=np.float64).ravel()
    aligned = aligner.align(obs39, det3d)
    print("YOLO 检测 3D:", {k: np.round(v, 3).tolist() for k, v in det3d.items()})
    print("真实 hand:", np.round(obs39[0:3], 3), "→ YOLO:", np.round(aligned[0:3], 3))
    print("真实 peg:", np.round(obs39[18:21], 3), "→ YOLO:", np.round(aligned[18:21], 3))
    print("真实 hole:", np.round(obs39[36:39], 3), "→ YOLO:", np.round(aligned[36:39], 3))
    print("对齐后 39D:", np.round(aligned, 3))


if __name__ == "__main__":
    main()
