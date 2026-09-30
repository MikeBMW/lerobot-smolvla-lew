"""perception.py — S1 时空感知前端 (状态空间模型画布)

传感器融合: RGB-D + 力觉 + 触觉 → 43D 统一状态向量 obs。

状态空间视角: 观测方程 y = C·x
  x  = 真实世界状态 (末端位姿/工件位姿/接触力)
  C  = 观测矩阵 (传感器模型)
  y  = 43D obs (K_obs = 1.0, 状态直接作为观测)

43D = 39D 视觉结构 (node_logic.node_obs39) + 触觉 4D (grasp/contact/dir)
时空感知 = 当前帧 + 历史帧时序堆叠。
"""
import numpy as np

OBS_DIM = 43          # 统一状态向量维度
VISUAL_DIM = 39       # 视觉结构维度 (坐标=逻辑主线, 图像=背景)
TACTILE_DIM = 4       # 触觉增维: [grasp, contact, dir_x, dir_y]


def fuse_sensors(rgbd_feats, force_6d, tactile_marker, K_obs=1.0):
    """融合三类传感器 → 43D obs。

    Args:
        rgbd_feats: 39D 视觉结构特征 (YOLO 2D→3D 反投影后)
        force_6d:   六维力/力矩 (接触检测用, 不直接进 obs)
        tactile_marker: 4D 触觉标记 (grasp/contact/dir)
    Returns:
        obs: 43D 统一状态向量
    """
    assert rgbd_feats.shape[-1] == VISUAL_DIM
    obs = np.concatenate([K_obs * np.asarray(rgbd_feats, dtype=float),
                          np.asarray(tactile_marker, dtype=float)])
    assert obs.shape[-1] == OBS_DIM
    return obs
