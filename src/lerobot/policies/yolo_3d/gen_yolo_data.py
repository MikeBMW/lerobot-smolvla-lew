#!/usr/bin/env python3
"""YOLO 训练数据自动标注生成器 — peg-insert 场景
2026-08-07 老倪: 开启 YOLO 训练 (感知前端, 真机必需)
流程: metaworld 渲染图像 + 模拟器已知 3D 位置 → 相机投影到 2D → 生成 YOLO 标注 (光模块/hole/hand)
零人工标注: 仿真自动产出 (类别+bbox) → 训练 YOLO → 真机部署检测销钉/孔

2026-09-17 加 `--dr` (域随机化, 默认**关** → 默认路径逐位不变):
  动机 = 仿真权重在真机 D405 帧上 0 检出 (峰值 conf 0.0107 vs 阈值 0.25), sim→real 是硬域差。
  DR 分两层, 全部保留几何一致性 (框跟着变换走, 绝不让标签和画面错位):
   ① mujoco 场景层 (`--dr-scene`): 光照位置/方向/强度/色温/环境光 · 全部材质颜色 · 纹理换随机噪声 ·
      相机位置抖动 ±3cm · fovy ±5% · 相机微旋转 ±5° (图像与标注同源, 因为投影读的就是同一份 model)
   ② 图像层 (永远随 --dr 开): 亮度/伽马/对比度/色偏 · 高斯噪声 · JPEG 压缩 · 运动/离焦模糊 ·
      降采样-回采样 (UVC 软) · 暗角 · 随机遮挡块 · 缩放裁切 (框同步) · 小角度旋转 ±8° (框同步) ·
      灰底(114)补边到 4:3 —— 复刻 ultralytics 对 640x480 真机帧 letterbox 后的版式
用法:
  python gen_yolo_data.py --eps 200 --out data/yolo_peg                 # 原行为 (默认)
  python gen_yolo_data.py --eps 30 --out data/yolo_peg_dr --dr --dr-scene  # 域随机化
"""
import os, sys, json, numpy as np
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")

# 🐛 2026-08-12 老倪: 已移入 src/lerobot/policies/yolo_3d/ — ROOT 上溯 4 层到仓库根
#   (yolo_3d → policies → lerobot → src → 仓库根)
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
sys.path.insert(0, ROOT)

from PIL import Image
from metaworld.policies.sawyer_peg_insertion_side_v3_policy import SawyerPegInsertionSideV3Policy

BOX_W, BOX_H = 40, 60  # 固定框尺寸 (像素), 与原口径一致


def make_env(seed=0):
    import metaworld
    mt = metaworld.MT1("peg-insert-side-v3")
    env_cls = mt.train_classes["peg-insert-side-v3"]
    env = env_cls(render_mode="rgb_array", camera_name="corner2")
    env._freeze_rand_vec = False
    env.set_task(mt.train_tasks[0])
    env.reset(seed=seed)
    # 相机跟随场景 (metaworld 自动), 不手动改位置
    env._freeze_rand_vec = True
    return env, mt


def project_3d_to_2d(env, xyz):
    """3D 世界坐标 → 2D 像素 (rot90 后帧坐标, 与 model_tree 渲染一致; mujoco 相机看向 -z)"""
    cam_id = env.model.cam("corner2").id
    cam_pos = env.model.cam_pos[cam_id]
    cam_mat = np.asarray(env.model.cam_mat0[cam_id]).reshape(3, 3).T  # 列主序 → 转置
    fovy = env.model.cam_fovy[cam_id]
    H = W = 480  # 渲染尺寸
    pc = cam_mat @ (np.asarray(xyz, dtype=float) - cam_pos)
    d = -pc[2]
    if d <= 0:
        return None
    f = (H / 2) / np.tan(np.radians(fovy) / 2)
    px = W / 2 + pc[0] * f / d
    py = H / 2 - pc[1] * f / d
    # 帧 np.rot90(k=2) 旋转 180° → 坐标同步旋转
    return W - px, H - py


# ───────────────────────── 域随机化 (DR) ─────────────────────────

def _unit(v):
    v = np.asarray(v, dtype=float)
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else np.array([0.0, 0.0, 1.0])


def randomize_scene(env, rng, cam_base=None):
    """mujoco 场景层随机化 (光照/材质/纹理/相机). 只在 --dr-scene 时调用。

    注意: 投影 (project_3d_to_2d) 读的就是同一份 model 的 cam_pos/cam_mat0/cam_fovy,
    所以这里改相机后**画面与标注天然一致**, 不需要额外补偿。
    """
    m = env.model
    for i in range(m.nlight):
        m.light_pos[i] = np.array([rng.uniform(-2.0, 2.0), rng.uniform(-2.0, 2.0), rng.uniform(0.4, 2.6)])
        m.light_dir[i] = _unit(rng.uniform(-1, 1, 3))
        base = rng.uniform(0.08, 0.95)
        # 色温偏移 (三通道不等) — 真机白平衡/厂区灯光偏色
        m.light_diffuse[i][:3] = np.clip(base * rng.uniform(0.75, 1.25, 3), 0, 1)
        m.light_ambient[i][:3] = rng.uniform(0.0, 0.35, 3)
        m.light_specular[i][:3] = rng.uniform(0.0, 0.5)
    # 材质颜色全随机 (逼模型别靠仿真的调色板, 靠形状/纹理) — 含 floor/table/wall/peg
    for i in range(m.nmat):
        try:
            m.mat_rgba[i][:3] = rng.uniform(0.03, 0.97, 3)
        except Exception:
            pass
    # 纹理换随机噪声 (打破仿真平铺单色)
    for i in range(getattr(m, "ntex", 0)):
        try:
            h, w = int(m.tex_height[i]), int(m.tex_width[i])
            if h > 1 and w > 1 and int(m.tex_rgb[i].size) >= h * w * 3:
                coarse = rng.uniform(0.05, 0.95, (max(2, h // 16), max(2, w // 16), 3))
                tex = np.repeat(np.repeat(coarse, 16, axis=0), 16, axis=1)[:h, :w]
                m.tex_rgb[i] = (tex * 255).astype(np.uint8)
        except Exception:
            pass
    # 相机: 位置抖动 ±3cm · fovy ±5% · 微旋转 ±5°
    cid = m.cam("corner2").id
    if cam_base is None:
        cam_base = dict(pos=np.array(m.cam_pos[cid], dtype=float),
                        fovy=float(m.cam_fovy[cid]),
                        mat=np.array(m.cam_mat0[cid], dtype=float).reshape(3, 3).T.copy())
    m.cam_pos[cid] = cam_base["pos"] + rng.uniform(-0.03, 0.03, 3)
    m.cam_fovy[cid] = cam_base["fovy"] * rng.uniform(0.95, 1.05)
    ang = rng.uniform(-5, 5, 3) * np.pi / 180.0
    Rx = np.array([[1, 0, 0], [0, np.cos(ang[0]), -np.sin(ang[0])], [0, np.sin(ang[0]), np.cos(ang[0])]])
    Ry = np.array([[np.cos(ang[1]), 0, np.sin(ang[1])], [0, 1, 0], [-np.sin(ang[1]), 0, np.cos(ang[1])]])
    Rz = np.array([[np.cos(ang[2]), -np.sin(ang[2]), 0], [np.sin(ang[2]), np.cos(ang[2]), 0], [0, 0, 1]])
    m.cam_mat0[cid] = (Rz @ Ry @ Rx @ cam_base["mat"]).T.flatten()
    return cam_base


def _occlude(img, rng):
    """随机遮挡块 (真机现场有夹具/线缆/人手挡)。"""
    h, w = img.shape[:2]
    for _ in range(rng.integers(0, 3)):
        bh, bw = int(rng.integers(h // 12, h // 3)), int(rng.integers(w // 12, w // 3))
        y0, x0 = int(rng.integers(0, h - bh)), int(rng.integers(0, w - bw))
        col = rng.integers(0, 256, 3).astype(np.uint8)
        img[y0:y0 + bh, x0:x0 + bw] = col
    return img


def _vignette(img, rng):
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    mask = 1.0 - rng.uniform(0.0, 0.45) * np.clip(r, 0, 1.5) ** 2
    return np.clip(img.astype(np.float32) * mask[..., None], 0, 255).astype(np.uint8)


def _jpeg(img, rng):
    q = int(rng.integers(35, 96))
    ok, enc = __import__("cv2").imencode(".jpg", img, [int(__import__("cv2").IMWRITE_JPEG_QUALITY), q])
    return __import__("cv2").imdecode(enc, 1) if ok else img


def _blur_soft(img, rng):
    """运动模糊 / 离焦 / 降采样回采样 (UVC 软) — 三选一。"""
    import cv2
    k = int(rng.integers(0, 3))
    if k == 0:
        sz = int(rng.integers(3, 9)) | 1
        ker = np.zeros((sz, sz), np.float32)
        if rng.random() < 0.5:
            ker[sz // 2, :] = 1.0 / sz
        else:
            ker[:, sz // 2] = 1.0 / sz
        return cv2.filter2D(img, -1, ker)
    if k == 1:
        return cv2.GaussianBlur(img, (0, 0), rng.uniform(0.4, 1.8))
    s = rng.uniform(0.5, 0.85)
    h, w = img.shape[:2]
    small = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def augment_image(img, boxes, rng):
    """图像层随机化; boxes = [(cx,cy,w,h,cls), ...] 像素坐标 (480² 系)。返回 (img, boxes)。"""
    import cv2
    h, w = img.shape[:2]
    img = img.astype(np.float32)
    # 亮度/对比度/伽马
    img = img * rng.uniform(0.55, 1.45) + rng.uniform(-25, 25)
    img = 255.0 * np.clip(img / 255.0, 0, 1) ** rng.uniform(0.6, 1.6)
    # 色偏 (白平衡)
    img = img * rng.uniform(0.85, 1.15, 3)
    img = np.clip(img, 0, 255).astype(np.uint8)
    # 噪声 (泊松+高斯, 近似真机传感器)
    img = np.clip(img.astype(np.float32) + rng.normal(0, rng.uniform(1.0, 12.0), img.shape), 0, 255).astype(np.uint8)
    img = _blur_soft(img, rng)
    img = _vignette(img, rng)
    img = _occlude(img, rng)
    img = _jpeg(img, rng)

    # 缩放裁切 (框同步)
    s = rng.uniform(0.72, 1.0)
    if s < 0.999:
        cw, ch = int(w * s), int(h * s)
        x0, y0 = int(rng.integers(0, w - cw + 1)), int(rng.integers(0, h - ch + 1))
        img = cv2.resize(img[y0:y0 + ch, x0:x0 + cw], (w, h), interpolation=cv2.INTER_LINEAR)
        boxes = [((cx - x0) * w / cw, (cy - y0) * h / ch, bw * w / cw, bh * h / ch, c) for cx, cy, bw, bh, c in boxes]

    # 小角度旋转 (框同步, 轴对齐框按旋转后外接矩形放宽)
    ang = rng.uniform(-8, 8)
    if abs(ang) > 0.5:
        M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
        img = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        rad = np.radians(ang)
        nb = []
        for cx, cy, bw, bh, c in boxes:
            px, py = M @ np.array([cx, cy, 1.0])
            s2 = abs(np.cos(rad)) + abs(np.sin(rad))
            nb.append((px, py, bw * s2, bh * s2, c))
        boxes = nb

    # 灰底(114)补边 → 复刻 ultralytics 对 640x480 真机帧 letterbox 后的版式
    #   (真机帧 640x480 送进 imgsz=480 时: 内容缩到 480x360, 上下各补 60px 灰边)
    if rng.random() < 0.5:
        s2 = rng.uniform(0.62, 0.92)          # letterbox 缩放率
        nw, nh = w, max(2, int(h * s2))       # 内容贴到 480xnh, 其余补灰
        small = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
        canvas = np.full((h, w, 3), 114, np.uint8)
        oy = int((h - nh) / 2)
        canvas[oy:oy + nh, :] = small
        boxes = [(cx, cy * s2 + oy, bw, bh * s2, c) for cx, cy, bw, bh, c in boxes]
        img = canvas
    return img, boxes


def main():
    eps = int(sys.argv[sys.argv.index("--eps") + 1]) if "--eps" in sys.argv else 200
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else os.path.join(ROOT, "data", "yolo_peg")
    dr = "--dr" in sys.argv
    dr_scene = "--dr-scene" in sys.argv
    dr_rep = int(sys.argv[sys.argv.index("--dr-rep") + 1]) if "--dr-rep" in sys.argv else 1
    rng = np.random.default_rng(int(sys.argv[sys.argv.index("--dr-seed") + 1]) if "--dr-seed" in sys.argv else 20260917)
    # 场景层可复现: metaworld 的 rand_vec 走全局 np.random (seed=ep 不生效, 实测同一份代码跑两次场景不同)
    # → 显式给全局种子; 不指定时保持旧行为 (不设种子)
    if "--scene-seed" in sys.argv:
        np.random.seed(int(sys.argv[sys.argv.index("--scene-seed") + 1]))
    elif dr:
        np.random.seed(int(sys.argv[sys.argv.index("--dr-seed") + 1]) if "--dr-seed" in sys.argv else 20260917)
    os.makedirs(f"{out}/images", exist_ok=True)
    os.makedirs(f"{out}/labels", exist_ok=True)

    expert = SawyerPegInsertionSideV3Policy()
    labels_txt = []
    n_imgs = 0

    for ep in range(eps):
        env, mt = make_env(seed=ep)
        obs, _ = env.reset()
        env._freeze_rand_vec = True
        cam_base = None
        for step in range(150):
            if dr_scene and step % 5 == 0:
                cam_base = randomize_scene(env, rng, cam_base)
            obs_vec = np.asarray(obs, dtype=np.float64).ravel()
            act = expert.get_action(obs_vec)
            img = env.render()  # 480x480x3
            if img is not None:
                frame = np.rot90(img, k=2)  # 与 model_tree 渲染一致
                # 物体 3D 位置 → 2D 框 (投影中心 + 固定框尺寸), 统一走像素框, 便于随 DR 变换
                objs = []
                # hand (末端)
                ee = env.data.site_xpos[env.model.site("endEffector").id]
                objs.append(("hand", ee))
                # 光模块 (销钉) — pegGrasp site
                try:
                    pg = env.data.site_xpos[env.model.site("pegGrasp").id]
                    objs.append(("peg", pg))
                except Exception:
                    pass
                # hole (孔)
                try:
                    hole = env.data.site_xpos[env.model.site("hole").id]
                    objs.append(("hole", hole))
                except Exception:
                    pass
                # 类 id 顺序与已训权重绑定 (hand=0, peg=1, hole=2); peg 类在推理层
                # 显示为"光模块" (yolo_state_aligner 覆写 names), 这里勿改 id
                boxes = []
                for cls, xyz in objs:
                    p = project_3d_to_2d(env, xyz)
                    if p is None:
                        continue
                    u, v = p
                    if 0 <= u < 480 and 0 <= v < 480:
                        boxes.append((u, v, BOX_W, BOX_H, {"hand": 0, "peg": 1, "hole": 2}[cls]))

                reps = dr_rep if dr else 1
                for r_i in range(reps):
                    im, bx = (frame.copy(), list(boxes))
                    if dr:
                        im, bx = augment_image(im, bx, rng)
                    H2, W2 = im.shape[:2]
                    line = ""
                    for cx, cy, bw, bh, cid in bx:
                        if not (0 <= cx < W2 and 0 <= cy < H2):
                            continue
                        line += f"{cid} {cx/W2:.4f} {cy/H2:.4f} {bw/W2:.4f} {bh/H2:.4f}\n"
                    if line:
                        n_imgs += 1
                        tag = f"ep{ep:03d}_s{step:03d}" + (f"_r{r_i}" if reps > 1 else "")
                        Image.fromarray(im if im.shape[2] == 3 else im[..., :3]).save(f"{out}/images/{tag}.png")
                        with open(f"{out}/labels/{tag}.txt", "w") as f:
                            f.write(line)
            obs, r, term, trunc, _ = env.step(act)
            if term or trunc:
                break
        env.close()

    # data.yaml
    with open(f"{out}/data.yaml", "w") as f:
        f.write("path: " + out + "\ntrain: images\nval: images\nnc: 3\nnames: ['hand', 'peg', 'hole']\n")
    print(f"✅ YOLO 数据生成完成: {n_imgs} 张图 / {eps} episodes → {out}"
          f"{' (DR: scene=%s rep=%d)' % (dr_scene, dr_rep) if dr else ''}")


if __name__ == "__main__":
    main()
