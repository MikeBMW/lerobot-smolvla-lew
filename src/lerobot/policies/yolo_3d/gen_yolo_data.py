#!/usr/bin/env python3
"""YOLO 训练数据自动标注生成器 — peg-insert 场景
2026-08-07 老倪: 开启 YOLO 训练 (感知前端, 真机必需)
流程: metaworld 渲染图像 + 模拟器已知 3D 位置 → 相机投影到 2D → 生成 YOLO 标注 (光模块/hole/hand)
零人工标注: 仿真自动产出 (类别+bbox) → 训练 YOLO → 真机部署检测销钉/孔
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


def quat_rotmat(q):
    """wxyz 四元数 → 旋转矩阵"""
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def bbox3d_rot90(env, center, half_world, pad_px=2.0):
    """3D 物体 (中心+世界半尺寸) → rot90 帧 bbox (cx,cy,w,h 像素), 8 角点投影包络
    🐛 2026-09-07 静静: 原固定 60×40 框 (26cm×17cm@1.8m) 远大于 peg 实际投影
    (24cm×3cm), 框内大部分是背景 → 深度提取/框语义差。真实尺寸标注:
    YOLO 学到贴合长条的框 → 框内中位数深度 ≈ peg 表面, 幻影更少。"""
    q = None
    # 角点 (局部尺寸 → 世界)
    corners = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                corners.append(center + np.array([sx, sy, sz]) * half_world)
    us, vs = [], []
    for c in corners:
        p = project_3d_to_2d(env, c)
        if p is None:
            return None
        us.append(p[0]); vs.append(p[1])
    u0, u1 = min(us), max(us)
    v0, v1 = min(vs), max(vs)
    u0 -= pad_px; v0 -= pad_px; u1 += pad_px; v1 += pad_px
    return (u0 + u1) / 2, (v0 + v1) / 2, (u1 - u0), (v1 - v0)


def main():
    eps = int(sys.argv[sys.argv.index("--eps") + 1]) if "--eps" in sys.argv else 200
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else os.path.join(ROOT, "data", "yolo_peg")
    os.makedirs(f"{out}/images", exist_ok=True)
    os.makedirs(f"{out}/labels", exist_ok=True)

    expert = SawyerPegInsertionSideV3Policy()
    labels_txt = []
    n_imgs = 0

    for ep in range(eps):
        env, mt = make_env(seed=ep)
        obs, _ = env.reset()
        env._freeze_rand_vec = True
        # 🐛 2026-09-07 静静: peg 真实尺寸标注 — 现场 geom 中心+朝向 (peg 会被碰移/旋转)
        _peg_gid = env.model.geom("peg").id
        _R = quat_rotmat(env.model.geom_quat[_peg_gid])
        _peg_half = _R @ np.asarray(env.model.geom_size[_peg_gid], dtype=float)
        for step in range(150):
            obs_vec = np.asarray(obs, dtype=np.float64).ravel()
            act = expert.get_action(obs_vec)
            img = env.render()  # 480x480x3
            if img is not None:
                n_imgs += 1
                img_path = f"{out}/images/ep{ep:03d}_s{step:03d}.png"
                Image.fromarray(np.rot90(img, k=2)).save(img_path)  # rot90 与 model_tree 渲染一致
                # 物体 3D 位置 → 2D bbox (peg=真实尺寸角点包络; hand/hole=中心+适度框)
                objs = []
                # hand (末端) — 视觉点中心, 适度固定框 (控制锚=编码器, 框语义不重要)
                ee = env.data.site_xpos[env.model.site("endEffector").id]
                _hp = project_3d_to_2d(env, ee)
                if _hp is not None:
                    objs.append(("hand", None, (_hp[0], _hp[1], 60.0, 40.0)))
                # 光模块 (销钉) — 🔴 真实尺寸 bbox (长 24cm 沿 x 长条)
                try:
                    pg = env.data.geom_xpos[_peg_gid].copy()
                    bb = bbox3d_rot90(env, pg, np.abs(_peg_half))
                    if bb is not None:
                        objs.append(("peg", None, bb))
                except Exception:
                    pass
                # hole (孔) — 中心+适度框 (孔口几何不在 geom, 不参与控制仅统计)
                try:
                    hole = env.data.site_xpos[env.model.site("hole").id]
                    _hp2 = project_3d_to_2d(env, hole)
                    if _hp2 is not None:
                        objs.append(("hole", None, (_hp2[0], _hp2[1], 48.0, 48.0)))
                except Exception:
                    pass
                line = ""
                for item in objs:
                    cls, xyz, bb = item
                    if bb is not None:
                        cx, cy, bw_px, bh_px = bb
                    else:
                        # 兼容: 无 bbox → 中心投影 + 固定框 (不应发生, 除 hand/hole 显式给框)
                        p = project_3d_to_2d(env, xyz)
                        if p is None:
                            continue
                        cx, cy = p
                        bw_px, bh_px = 60.0, 40.0
                    # 尺寸下限 (像素): 太小 YOLO 难学, 保底 8px
                    bw_px = max(bw_px, 8.0); bh_px = max(bh_px, 8.0)
                    xc, yc = cx / 480, cy / 480
                    bw, bh = bw_px / 480, bh_px / 480
                    if 0 <= cx < 480 and 0 <= cy < 480:
                        # 类 id 顺序与已训权重绑定 (hand=0, peg=1, hole=2); peg 类在推理层
                        # 显示为"光模块" (yolo_state_aligner 覆写 names), 这里勿改 id
                        cls_id = {"hand": 0, "peg": 1, "hole": 2}[cls]
                        line += f"{cls_id} {xc:.4f} {yc:.4f} {bw:.4f} {bh:.4f}\n"
                if line:
                    with open(f"{out}/labels/ep{ep:03d}_s{step:03d}.txt", "w") as f:
                        f.write(line)
            obs, r, term, trunc, _ = env.step(act)
            if term or trunc:
                break
        env.close()

    # data.yaml
    with open(f"{out}/data.yaml", "w") as f:
        f.write("path: " + out + "\ntrain: images\nval: images\nnc: 3\nnames: ['hand', 'peg', 'hole']\n")
    print(f"✅ YOLO 数据生成完成: {n_imgs} 张图 / {eps} episodes → {out}")


if __name__ == "__main__":
    main()
