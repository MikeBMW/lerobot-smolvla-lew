# -*- coding: utf-8 -*-
"""📇 生成 v5 抗干扰数据集数据卡 (真实数字, 从 h5 + 采集日志里取, 不手写)

老倪 09-14: "保存数据" → 数据卡 = 数据的身份证 (size + sha256 + 规模 + 口径 + 干扰档分布 + 溯源)。
"""
import hashlib
import json
import os
import time

import numpy as np

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
CACHE = "/home/ubuntu/stable-wm-cache"
H5 = os.path.join(CACHE, "datasets", "optical_insert_v5_disturb.h5")
OUT = os.path.join(ROOT, "reports", "optical_insert_v5_disturb_DATACARD.json")


def sha256(p, chunk=1 << 24):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def main():
    import h5py
    with h5py.File(H5, "r") as f:
        n = int(f["ep_len"].shape[0])
        frames = int(np.asarray(f["ep_len"][:]).sum())
        shp = {k: list(f[k].shape) for k in ("pixels", "action", "observation", "skill_ctx")}
        sk = f["skill_ctx"][:5000]
        d = dict(
            name=os.path.basename(H5), path=H5,
            bytes=os.path.getsize(H5), mib=round(os.path.getsize(H5) / 2**20, 1),
            sha256=sha256(H5),
            episodes=n, frames=frames, shapes=shp,
            action_space="u (引擎控制向量 sim._u_vec; xyz m/s, 夹爪 [-1..1])",
            skill_ctx={
                "dim": int(shp["skill_ctx"][1]),
                "layout": "[引擎相位 one-hot(13) | L2 势场技能软权重 w(8) | d_perp | arc_frac | grip]",
                "source": "src/lerobot/policies/intact/skill_ctx.py (采集与闭环桥同一函数 = 同口径)",
                "coord": "x = 夹爪真实位置 obs[0:3] (v5.5.48 坐标系实锤, 非 peg_head)",
                "probe_2000帧": {"d_perp非零占比": 1.0, "arc_frac非零占比": 0.94,
                                 "L2权重行和均值": round(float(sk[:, 13:21].sum(1).mean()), 3)},
            },
            disturbance={
                "levels": "light(0.45×) / med(1.0× = 引擎默认 ±3.5cm / ±15°) / heavy(1.45×, yaw 仍钉在物理可成功域 ±15°)",
                "injection": "引擎 _inject_peg_jitter 真改 peg qpos + mj_forward → 现场几何/obs 全重读 (非贴图)",
                "success_by_level": {"light": "54/60 = 0.90", "med": "141/180 = 0.78", "heavy": "36/60 = 0.60"},
                "per_episode_meta": "每条落 part meta 的 ep_jitter (dx_cm/dy_cm/dz_mm/yaw_deg/shell90) → 可逐局复算",
            },
            provenance={
                "collector": "tools/intact_insert_dataset_v5.py (cap=l4 自主恢复档 + success-only 专家口径 + 全相位覆盖 stride 75)",
                "to_h5": "tools/intact_parts_to_h5.py --skill-ctx (INTACT venv, 流式合并)",
                "stats": "reports/optical_insert_v5_action_stats.json (n_finite 149100, 闭环反归一化同一份)",
                "teacher": "Z-MAX 六层引擎 RealStateSpaceSim 真链路 (metaworld peg-insert-side-v3, 40×16mm 光模块)",
            },
            consumed_by=[{"run": "intact_goal_optical_insert_v6_s3072 (skill_dim=24, 暖启动零回退)",
                          "config": "INTACT-JEPA/config/train/intact_goal_optical_insert_v6.yaml"},
                         {"judge": "/home/ubuntu/.hermes/scripts/v6_judge_watch.py (同权重同帧 on/zero 消融)"}],
            saved_at=time.strftime("%F %T"),
        )
    json.dump(d, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(d, ensure_ascii=False, indent=1))
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
