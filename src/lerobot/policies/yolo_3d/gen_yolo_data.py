#!/usr/bin/env python3
"""YOLO 训练数据自动标注生成器 — peg-insert 场景
2026-08-07 老倪: 开启 YOLO 训练 (感知前端, 真机必需)
流程: metaworld 渲染图像 + 模拟器已知 3D 位置 → 相机投影到 2D → 生成 YOLO 标注 (peg/hole/hand)
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
    """3D 世界坐标 → 2D 像素坐标 (metaworld 相机投影)"""
    cam = env.model.camera("corner2")
    cam_id = env.model.camera("corner2").id
    # 用 mujoco 的 cam light 投影
    import mujoco
    m, d = env.model, env.data
    x = mujoco.MjvCamera()
    x.type = mujoco.mjtCamera.mjCAMERA_FIXED
    x.fixedcamid = cam_id
    d.geom_xpos = d.geom_xpos  # ensure updated
    # 构造投影矩阵
    up = np.zeros(3); up[2] = 1.0
    campos = m.cam_pos[cam_id].copy()
    cam_forward = np.array(m.cam_pos[cam_id])
    # 简单针孔投影 (metaworld 相机近似)
    fovy = m.cam_fovy[cam_id]
    H = W = 480  # 渲染尺寸
    f = (H / 2) / np.tan(np.radians(fovy) / 2)
    # 相机坐标转换 (相机朝向 -z)
    dir_z = -(campos - xyz)
    # 用 lookat: 相机看向 (0.5,0.5,0.1) 附近
    lookat = np.array([0.5, 0.5, 0.1])
    forward = lookat - campos
    forward = forward / np.linalg.norm(forward)
    right = np.cross(forward, np.array([0, 0, 1]))
    right = right / np.linalg.norm(right)
    upv = np.cross(right, forward)
    # 相机系坐标
    d_vec = xyz - campos
    x_cam = np.dot(d_vec, right)
    y_cam = np.dot(d_vec, upv)
    z_cam = np.dot(d_vec, forward)
    if z_cam <= 0:
        return None
    u = W / 2 + f * x_cam / z_cam
    v = H / 2 - f * y_cam / z_cam
    return u, v


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
        for step in range(150):
            obs_vec = np.asarray(obs, dtype=np.float64).ravel()
            act = expert.get_action(obs_vec)
            img = env.render()  # 480x480x3
            if img is not None:
                n_imgs += 1
                img_path = f"{out}/images/ep{ep:03d}_s{step:03d}.png"
                Image.fromarray(img).save(img_path)
                # 物体 3D 位置 → 2D bbox (用投影点 + 固定框尺寸)
                h = 60; w = 40
                objs = []
                # hand (末端)
                ee = env.data.site_xpos[env.model.site("endEffector").id]
                objs.append(("hand", ee))
                # peg (销钉) — pegGrasp site
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
                line = ""
                for cls, xyz in objs:
                    p = project_3d_to_2d(env, xyz)
                    if p is None:
                        continue
                    u, v = p
                    if 0 <= u < 480 and 0 <= v < 480:
                        xc, yc = u / 480, v / 480
                        bw, bh = w / 480, h / 480
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
