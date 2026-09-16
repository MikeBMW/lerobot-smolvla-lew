#!/usr/bin/env python3
"""YOLO 输出 → 39D 对齐器 (2026-08-07 老倪: YOLO输出跟39D对齐)
把 YOLO 检测的 2D 框 (hand/光模块/hole) → 相机反投影 → 3D 坐标 → 替换 39D obs 中对应段
这样仿真与真机同构: 真机也只有 YOLO 2D 检测, 没有模拟器直接给的 39D
"""
import os, sys, numpy as np
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")

# ── 感知输入源抽象 (2026-09-17 老倪: sim→real 无缝移植的唯一差异点收口) ──
#   仿真/真机的差异只有 5 处: 图像从哪来 · 内参 · 深度 · 外参 · 朝向/通道口径。
#   全部收口到 frame_source.FrameSource, 检测与反投影只有这一份代码。
try:
    import frame_source as _fsrc
except ImportError:                                                        # 包内/异路径加载
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import frame_source as _fsrc
SimFrameSource = _fsrc.SimFrameSource
load_real_calib = _fsrc.load_real_calib

# 🐛 2026-09-17: Jetson/Orin 上 torch 与 torchvision 的 C++ 扩展 ABI 不匹配 →
#   ultralytics 的 NMS 直接崩 (YOLO 起不来)。此处在加载 ultralytics 前探测并挂纯 torch 备用实现。
#   正常机器 (本机 4060 / WSL) 探测通过 → 完全不动。
try:
    import tv_ops_shim as _tvshim
    _tvshim.install()
except Exception:                                                          # noqa: BLE001
    pass


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

    def __init__(self, weights, env=None, depth_weights=None, source=None):
        from ultralytics import YOLO
        # 🎯 2026-09-17: 感知源 (仿真 env / 真机 ROS / UVC / 回放)。不传 source 时
        #   用 sim 源包住 env → 既有仿真调用 (node_logic / state_space_sim_real / tools)
        #   行为逐位不变 (零回退)。
        self.source = source if source is not None else SimFrameSource(env)
        self.model = YOLO(weights)
        # 🏷️ 2026-09-04 老倪: YOLO 检测类别名业务化 — peg(插销, 训练类名遗留) → 光模块。
        #   覆写底层 model.names (顶层 .names 赋值不生效, 实测) 后, 检测结果 res.names/cls、
        #   det3d 键、GUI 画框标签 (state_space_sim_real _vis["boxes"]) 全走业务名。
        #   注意: 类 id 顺序不变 (训练数据 gen_yolo_data.py 的 {hand:0, peg:1, hole:2} 绑定, 勿改 id)
        for _cid, _nm in list(self.model.model.names.items()):
            if _nm == "peg":
                self.model.model.names[_cid] = "光模块"
        self.env = env          # 兼容旧调用 (部分工具直接读 aligner.env)
        self.cam_id = env.model.camera("corner2").id if env is not None else None
        # 🎯 2026-08-23 老倪: 深度模型 (YOLO depth head) — 用真实深度反投影替代写死 z_map
        self.depth_model = YOLO(depth_weights) if depth_weights else None
        # 🎯 尺度校准 (SILog scale-invariant → 训练中模型尺度漂移)
        #   实测: 光模块/hole scale≈0.962, hand scale≈0.885 (peg_depth_v1-2)
        #   🐛 旧 1.685/1.566 是 peg_depth_v1 (CPU时代) 的, 已作废; 默认 1.0 是 bug → 反投影坐标错 0.4m
        #   🐛 2026-09-07 静静: 0.978 (8/24 单布局标定) 偏大 → R1 视觉 peg 系统偏 2-5cm →
        #     抓取对不准反复尝试 (R0 seed104 353步成功 vs R1 vision 500步失败实锤)。
        #     10 布局重标定: 隐含 scale 0.9577-0.9674, 平均 0.9616 → 悬停定位误差 30mm→1mm
        self._depth_scale = float(os.environ.get("DEPTH_SCALE", "0.9616"))
        self._hand_scale = float(os.environ.get("DEPTH_SCALE_HAND", "0.885"))
        self._last_res = None         # 最近一帧检测结果缓存 (可视化画框用)
        self._last_img_rot = None

    # ══════════════════════════════════════════════════════════════════════
    #  对外统一入口 (源无关) — sim 源逐位走下方 legacy 实现 (零回退),
    #  真机源 (ROS/UVC/回放) 走 estimate_3d 通用几何 (内参/外参/米制深度)
    # ══════════════════════════════════════════════════════════════════════
    def detect_3d(self, img=None, conf=0.4):
        """统一入口 → {业务类名: np.array([x,y,z])} (向后兼容旧签名 detect_3d(img))"""
        return self.detect_3d_meta(img, conf=conf)[0]

    def detect_3d_meta(self, img=None, conf=0.4):
        """统一入口 (带取证元数据) → (det3d, meta)

        meta = {frame, depth_src, K_src, ext_src, gaps[], notes[]}
        gaps 非空 = 该帧有"拿不到的证据" (无深度/无外参/未标定), 显式标注不编造。
        """
        if self.source.name == "sim":
            if img is None:
                img = self.source.grab().rgb
            meta = {"frame": "world", "K_src": "fovy(mujoco cam_fovy)",
                    "ext_src": "mujoco cam_pos/cam_mat0",
                    "depth_src": "yolo-depth-head" if self.depth_model is not None else "写死 z_map 回退",
                    "gaps": [], "notes": []}
            return self._detect_3d_sim_legacy(img, conf=conf), meta
        return self.estimate_3d(self.source.grab(img), conf=conf)

    def estimate_3d(self, frame, conf=0.4):
        """通用 2D→3D (仿真/真机同一份几何) → (det3d, meta)

        与仿真唯一的口径差异 (由源的 profile 声明, 不是分叉代码):
          · train_rot_k: 训练集朝向 (仿真 rot90 k=2 / 真机 0)
          · rgb_order : 源给的是 RGB 还是 BGR
          · 深度: 帧自带米制深度 (真机 RealSense) 优先; 无则 YOLO depth head (仿真校准)
          · 内参: camera_info/标定 K 优先; 无则 fovy 单焦距近似
          · 外参: T_base_cam (tf/标定); 无 → 输出**相机系**并标 gap (不冒充 base 系)
        """
        import cv2
        det3d = {}
        meta = {"frame": self.source.frame, "K_src": None, "ext_src": None,
                "depth_src": None, "gaps": list(frame.notes), "notes": []}
        img = frame.rgb
        if img is None:
            meta["gaps"].append("无图像帧")
            return det3d, meta
        if img.dtype != np.uint8:
            img = (img * 255).astype(np.uint8)
        k = int(getattr(self.source, "train_rot_k", 0) or 0)
        assert k in (0, 2), f"train_rot_k 只支持 0/2 (收到 {k}; 90/270 的坐标映射未定义)"
        img_used = np.rot90(img, k=2) if k == 2 else img
        if getattr(self.source, "rgb_order", "RGB") == "RGB":
            img_bgr = cv2.cvtColor(np.ascontiguousarray(img_used), cv2.COLOR_RGB2BGR)
        else:
            img_bgr = np.ascontiguousarray(img_used)
        res = self.model.predict(img_bgr, conf=conf, verbose=False)[0]
        self._last_res = res
        self._last_img_rot = img_used
        H, W = img_bgr.shape[:2]
        # ── 深度 ──
        # 口径由**源声明**决定 (depth_metric): 米制深度=1.0 直接用; 预测深度=套仿真尺度校准。
        # (不能用"帧里有没有 depth"来判断 —— 源可能提供的是预测深度, 那就必须校准。)
        depth_is_metric = bool(getattr(self.source, "depth_metric", False))
        depth_map = None
        if frame.depth_m is not None:
            depth_map = np.asarray(frame.depth_m, dtype=np.float32)
            meta["depth_src"] = (f"米制深度({self.source.name})" if depth_is_metric
                                 else f"预测深度({self.source.name}, 套尺度校准)")
            if depth_map.shape[:2] != (H, W):
                meta["gaps"].append(f"深度尺寸 {depth_map.shape[:2]} ≠ 图像 {(H, W)}")
                depth_map = None
            elif k == 2:
                depth_map = np.rot90(depth_map, k=2)
        elif self.depth_model is not None and self.source.name == "sim":
            # 🐛 2026-09-17: **只在仿真源**用 YOLO depth head — 它是在仿真渲染上标定的
            #   (DEPTH_SCALE 0.9616), 拿它预测真机像素深度 = 假证据。真机没有米制深度时
            #   就走"标定平面"回退 (plane_z), 或明确标 gap, 不用仿真深度冒充。
            try:
                _d = self.depth_model.predict(img_bgr, verbose=False)[0].depth.data
                depth_map = np.asarray(_d.detach().cpu().numpy()).squeeze()
                if depth_map.ndim != 2:
                    depth_map = depth_map[-1] if depth_map.ndim == 3 else None
                meta["depth_src"] = "YOLO depth head(仿真校准)"
            except Exception:                                              # noqa: BLE001
                depth_map = None
        if depth_map is None:
            meta["gaps"].append("无深度 (帧无米制深度且无 depth head)")
        # ── 内参 ──
        K = frame.K
        if K is not None and np.asarray(K).shape == (3, 3):
            fx, fy = float(K[0, 0]), float(K[1, 1])
            cx, cy = float(K[0, 2]), float(K[1, 2])
            meta["K_src"] = "camera_info/标定 K"
        elif frame.fovy_deg:
            f = (H / 2) / np.tan(np.radians(frame.fovy_deg) / 2)
            fx = fy = f
            cx, cy = W / 2, H / 2
            meta["K_src"] = "fovy(单焦距近似)"
        else:
            meta["gaps"].append("无内参 (K 与 fovy 都缺) → 无法反投影")
            return det3d, meta
        # ── 外参 ──
        T = frame.T_base_cam
        if T is not None:
            T = np.asarray(T, float).reshape(4, 4)
            cam_pos, R = T[:3, 3].copy(), T[:3, :3]
            meta["ext_src"] = "T_base_cam(tf/标定)"
        else:
            cam_pos, R = np.zeros(3), np.eye(3)
            meta["ext_src"] = "无外参 → 输出相机系"
            meta["gaps"].append("无 base↔cam 外参: 3D 点处于**相机系**, 不能直接与 base 系真值比")
            meta["frame"] = "camera"
        plane = self.source.plane_z()
        # 相机系约定 = 标准光学系 (OpenCV): +x 右 / +y 下 / **+z 朝前 (光轴)**。
        # 深度 d 是沿光轴的米制距离 → 沿射线距离 t = d / cosθ, cosθ = 归一化射线的 z 分量
        # (与仿真 legacy 的 dot(dir_w, forward) 数值等价, 已用 parity 取证逐位对齐)。
        for b in res.boxes:
            raw = res.names[int(b.cls)]
            cls = self.source.class_map.get(raw, raw)
            x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
            u, v = (x1 + x2) / 2, (y1 + y2) / 2
            if k == 2:                              # rot90(k=2) 帧坐标 → 原始帧坐标
                u, v = W - u, H - v
            d = None
            if depth_map is not None:
                x1i, y1i = int(np.clip(x1, 0, W - 1)), int(np.clip(y1, 0, H - 1))
                x2i, y2i = int(np.clip(x2, 0, W - 1)), int(np.clip(y2, 0, H - 1))
                if x2i > x1i and y2i > y1i:
                    d = float(np.median(depth_map[y1i:y2i, x1i:x2i]))
                else:
                    d = float(depth_map[int(np.clip(v, 0, H - 1)), int(np.clip(u, 0, W - 1))])
                if not depth_is_metric:             # 预测深度才需尺度校准 (米制深度=1.0)
                    d *= (self._hand_scale if raw == "hand" else self._depth_scale)
                if not (np.isfinite(d) and d > 0.1):
                    d = None
            ray_c = np.array([(u - cx) / fx, (v - cy) / fy, 1.0])
            ray_c = ray_c / np.linalg.norm(ray_c)
            dir_b = R @ ray_c
            dir_b = dir_b / np.linalg.norm(dir_b)
            if d is not None:
                cos_t = float(ray_c[2])            # 射线与光轴夹角余弦 (相机系, 已归一化)
                t = d / cos_t if abs(cos_t) > 1e-4 else d
                if t > 0:
                    det3d[cls] = cam_pos + t * dir_b
                continue
            pz = plane.get(cls)
            if pz is None or abs(dir_b[2]) < 1e-8:
                meta["gaps"].append(f"{cls}: 无深度且无该类 z 平面标定 → 不给 3D (不编造)")
                continue
            t = (float(pz) - cam_pos[2]) / dir_b[2]
            if t > 0:
                det3d[cls] = cam_pos + t * dir_b
        return det3d, meta

    def _detect_3d_sim_legacy(self, img, conf=0.4):
        """【仿真 legacy 实现 — 逐位保持原样, 零回退基线】YOLO 检测 → 3D (depth head + 写死 z 回退)"""
        # 2026-08-07: ultralytics 内部用 BGR — RGB 数组检测失败, BGR 数组成功 (内存方式快 100 倍)
        import cv2
        if img.dtype != np.uint8:
            img = (img * 255).astype(np.uint8)
        # 🐛 2026-08-23 静静: 训练数据 gen_yolo_data 存 rot90(k=2) 帧, 推理必须同方向
        #   否则倒置图检测失效 (只检出 光模块); box 中心反投影前转回原始帧坐标
        img_rot = np.rot90(img, k=2)
        img_bgr = cv2.cvtColor(img_rot, cv2.COLOR_RGB2BGR)
        res = self.model.predict(img_bgr, conf=conf, verbose=False)[0]
        self._last_res = res          # 🐛 2026-09-04: 缓存本帧检测 (可视化画框用, 免二次 predict)
        self._last_img_rot = img_rot  # 同步缓存 rot90 帧 (画框坐标系一致)
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
        z_map = {"hand": 0.155, "光模块": 0.03, "hole": 0.129}
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
        """YOLO 3D 检测替换 39D 中对应段 (hand→0:3, 光模块→4:7+22:25, hole→36:39)"""
        aligned = np.asarray(obs39, dtype=np.float64).copy()
        # 39D 结构 (node_logic.node_obs39 实测确认, 2026-08-23 静静修正 光模块 段):
        #   [0:3]=hand, [4:7]=光模块, [7:11]=peg_quat, [18:21]=prev_hand, [22:25]=prev_peg, [36:39]=hole
        #   🐛 旧版误把 光模块 写进 [18:21](prev_hand), 真 光模块 段 [4:7]/[22:25] 一直漏真值 → 训练泄漏
        if "hand" in det3d:
            aligned[0:3] = det3d["hand"]
        if "光模块" in det3d:
            aligned[4:7] = det3d["光模块"]
            aligned[22:25] = det3d["光模块"]
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
