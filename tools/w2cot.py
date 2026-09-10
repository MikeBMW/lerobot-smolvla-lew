"""W2-CoT 结构化标注设计 — World-to-Wrist (2026-08-10 老倪: 结构化任务整合进model zoo)

W2-CoT = 操作进度 + 物理转换线索 + 腕部局部证据 (论文 W2-VLA 结构化标注)

每帧标注 (追加到 state 尾部, 与触觉段并列):
  [进度 onehot 4D]    phase: 0=接近 1=抓取 2=抬起 3=插入
  [物理线索 3D]       contact(接触0/1) + sliding(滑动0/1) + seated(到位0/1)
  [腕部证据 2D]       hand→光模块 距离 + 光模块→hole 距离
  → state 49D + 9D CoT = 58D

数据生成判定 (在 gen_metaworld_data.py 专家循环内):
  phase 判定:
    1 接近:   hand→光模块 距离 > 0.08
    2 抓取:   < 0.08 且夹爪未闭合
    3 抬起:   光模块 z 升高 > 0.02 (已抓起)
    4 插入:   光模块→hole < 0.15 (转移后下降)
  contact:  hand→光模块 < 0.05 (腕部接触)
  sliding:  接触中 光模块 z 变化 > 0.01 (滑动)
  seated:   光模块→hole < 0.05 且 光模块 z 稳定 (插入到位)
  wrist_evid: [dist(hand,光模块), dist(光模块,hole)] (腕部局部证据)

用途: 作为辅助监督训练 latent 接口 — 模型学习预测"下一阶段/接触时刻",
      等价于 W2-VLA 的 W2-CoT 监督塑造紧凑潜在接口 (预测未来腕部 latent)。
"""
import numpy as np

def w2cot_annotate(env, phase, prev_contact, prev_peg_z, peg_z0):
    """生成 W2-CoT 结构化标注 (9D) — 在专家循环每帧调用
    Returns: np.ndarray (9,) — [phase_oh(4), contact, sliding, seated, d_hp, d_ph]
    """
    # 位置
    try:
        hand = env.data.site_xpos[env.model.site("endEffector").id]
        peg = env.data.site_xpos[env.model.site("pegGrasp").id]
        hole = env.data.site_xpos[env.model.site("hole").id]
    except Exception:
        return np.zeros(9, dtype=np.float32)
    d_hp = float(np.linalg.norm(hand - peg))
    d_ph = float(np.linalg.norm(peg - hole))
    peg_z = float(peg[2])
    # 物理线索
    contact = 1.0 if d_hp < 0.05 else 0.0
    sliding = 1.0 if (contact > 0.5 and abs(peg_z - prev_peg_z) > 0.01) else 0.0
    seated = 1.0 if (d_ph < 0.05 and abs(peg_z - peg_z0) < 0.02) else 0.0
    # 阶段 onehot
    phase_oh = np.zeros(4, dtype=np.float32)
    phase_oh[int(min(phase, 3))] = 1.0
    # 腕部证据
    return np.concatenate([phase_oh, [contact, sliding, seated], [d_hp, d_ph]]).astype(np.float32)
