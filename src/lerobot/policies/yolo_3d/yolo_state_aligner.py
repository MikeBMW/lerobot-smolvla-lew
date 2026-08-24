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

    def __init__(self, weights, env, depth_weights=None):
        from ultralytics import YOLO
        self.model = YOLO(weights)
        self.env = env
        self.cam_id = env.model.camera("corner2").id
        # 🎯 2026-08-23 老倪: 深度模型 (YOLO depth head) — 用真实深度反投影替代写死 z_map
        self.depth_model = YOLO(depth_weights) if depth_weights else None
        # 🎯 尺度校准 (SILog scale-invariant → 训练中模型尺度漂移)
        #   实测: peg/hole scale≈1.685, hand scale≈1.566 (细长机械臂末端, 尺度不同)
        self._depth_scale = float(os.environ.get("DEPTH_SCALE", "1.0"))
        self._hand_scale = float(os.environ.get("DEPTH_SCALE_HAND", str(self._depth_scale)))

    def detect_3d(self, img, conf=0.4):
        """YOLO 检测 → 3D 坐标 {hand, peg, hole} (深度模型反投影, 回退写死 z_map)"""
        # 2026-08-07: ultralytics 内部用 BGR — RGB 数组检测失败, BGR 数组成功 (内存方式快 100 倍)
        import cv2
        if img.dtype != np.uint8:
            img = (img * 255).astype(np.uint8)
        # 🐛 2026-08-23 静静: 训练数据 gen_yolo_data 存 rot90(k=2) 帧, 推理必须同方向
        #   否则倒置图检测失效 (只检出 peg); box 中心反投影前转回原始帧坐标
        img_rot = np.rot90(img, k=2)
        img_bgr = cv2.cvtColor(img_rot, cv2.COLOR_RGB2BGR)
        res = self.model.predict(img_bgr, conf=conf, verbose=False)[0]
        # 🎯 深度图 (米, 与 img_bgr 像素对齐)
        depth_map = None
        if self.depth_model is not None:
            try:
                _d = self.depth_model.predict(img_bgr, verbose=False)[0].depth.data
                # 🐛 2026-08-24 静静: GPU 训练后 depth.data 是 cuda tensor, np.asarray 直接转抛
                #   TypeError 被 except 吞掉 → depth_map=None → 回退写死 z → 评估 0/8 卡"接近"
                depth_map = np.asarray(_d.detach().cpu().numpy()).squeeze()
                if depth_map.ndim != 2:
                    depth_map = depth_map[-1] if depth_map.ndim == 3 else None
            except Exception:
                depth_map = None
        cam_pos = self.env.model.cam_pos[self.cam_id].copy()
        # 🐛 2026-08-23 静静: 用 cam_mat0(列主序 .T) 反投影, 替代原 cam_quat+经验反号(从未验证, x差3m)
        cam_mat = np.asarray(self.env.model.cam_mat0[self.cam_id]).reshape(3, 3).T
        fovy = self.env.model.cam_fovy[self.cam_id]
        out = {}
        H, W = img.shape[:2]
        f = (H / 2) / np.tan(np.radians(fovy) / 2)
        z_map = {"hand": 0.155, "peg": 0.03, "hole": 0.129}
        # 光轴方向 (相机看向 -z) → 世界坐标单位向量
        forward = cam_mat.T @ np.array([0.0, 0.0, -1.0])
        forward = forward / np.linalg.norm(forward)
        for b in res.boxes:
            cls = res.names[int(b.cls)]
            x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
            u, v = (x1 + x2) / 2, (y1 + y2) / 2
            # 🎯 深度模型在 img_bgr(rot90) 坐标取框内中位数 (抗单点噪声)
            depth_m = None
            if depth_map is not None:
                x1i, y1i = int(np.clip(x1, 0, W - 1)), int(np.clip(y1, 0, H - 1))
                x2i, y2i = int(np.clip(x2, 0, W - 1)), int(np.clip(y2, 0, H - 1))
                if x2i > x1i and y2i > y1i:
                    depth_m = float(np.median(depth_map[y1i:y2i, x1i:x2i]))
                else:
                    depth_m = float(depth_map[int(np.clip(v, 0, H - 1)), int(np.clip(u, 0, W - 1))])
                # 🎯 尺度校准 (hand 单独 scale, 细长物体尺度不同)
                sc = self._hand_scale if cls == "hand" else self._depth_scale
                depth_m *= sc
            # 🐛 2026-08-23: rot90 帧坐标 → 原始帧坐标 (反投影相机模型基于原始帧)
            u, v = W - u, H - v
            ndc_x = (u - W / 2) / f
            ndc_y = (v - H / 2) / f
            # 相机坐标方向 (看向 -z): pc = d*[ndc_x, -ndc_y, -1] → 世界方向 = cam_mat.T @ pc
            pc = np.array([ndc_x, -ndc_y, -1.0])
            dir_w = cam_mat.T @ pc
            dir_w = dir_w / np.linalg.norm(dir_w)
            if depth_m is not None and depth_m > 0.1:
                # 🎯 沿光轴深度 d → 沿 dir_w 距离 t = d/cos(θ)
                cos_t = float(np.dot(dir_w, forward))
                t = depth_m / cos_t if abs(cos_t) > 1e-4 else depth_m
                if t > 0:
                    out[cls] = cam_pos + t * dir_w
                continue
            # 回退: 写死 z 平面 (无深度模型/深度无效时)
            plane_z = z_map.get(cls, 0.1)
            if abs(dir_w[2]) < 1e-8:
                continue
            t = (plane_z - cam_pos[2]) / dir_w[2]
            if t < 0:
                continue
            out[cls] = cam_pos + t * dir_w
        return out

    def align(self, obs39, det3d):
        """YOLO 3D 检测替换 39D 中对应段 (hand→0:3, peg→4:7+22:25, hole→36:39)"""
        aligned = np.asarray(obs39, dtype=np.float64).copy()
        # 39D 结构 (node_logic.node_obs39 实测确认, 2026-08-23 静静修正 peg 段):
        #   [0:3]=hand, [4:7]=peg, [7:11]=peg_quat, [18:21]=prev_hand, [22:25]=prev_peg, [36:39]=hole
        #   🐛 旧版误把 peg 写进 [18:21](prev_hand), 真 peg 段 [4:7]/[22:25] 一直漏真值 → 训练泄漏
        if "hand" in det3d:
            aligned[0:3] = det3d["hand"]
        if "peg" in det3d:
            aligned[4:7] = det3d["peg"]
            aligned[22:25] = det3d["peg"]
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
