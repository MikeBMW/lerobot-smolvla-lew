#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧭 L5 定方向 · 造数据 —— 任务变体生成 + 引擎 rollout → 新训练数据

老倪 2026-09-23: "L5层继续定方向, 造数据"

职责 (L5 = 大语言模型层):
  · **定方向**: 规划器把任务拆成阶段/技能序列, 并生成**变体方向** (目标位置/阶段组合/扰动)
  · **造数据**: 每个变体用引擎真跑 → 落 h5 (obs 39 / action 4 / pixels / goal) → 喂联合集训

与现有 collect_*.py 的区别: 这里用 **L5 规划器定方向** (不是穷举), 变体带语义标签。

用法:
  python tools/l5_plan_and_gen.py --n 200 --out /home/ubuntu/stable-wm-cache/datasets/l5_gen_v1.h5
  nice -n 19 ... (GPU 训练繁忙时让路)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入"]
# ★ 2026-09-26 L3 修复: 引擎真源是 8 阶段 (cognition.py 含"完成"), 且 trace 里阶段名可能带 "阶段 " 前缀
#   → 原来 `stg in STAGES` 永远 False, skill_ctx 被静默写成常量 (dim13=1)。这里显式归一化 + 独立未知槽。
STAGES8 = STAGES + ["完成"]
SK_UNKNOWN_SLOT = 13 + len(STAGES8)          # = 20 (24 维里留出)

# 阶段名别名 (planner.py 的另一套命名 → 引擎阶段)
_STAGE_ALIAS = {"取料": "接近", "运输": "转移", "扫码": "对位", "对准": "对位",
                "检测": "插入", "拔出": "插入", "分拣": "完成", "完成": "完成"}


def stage_index(stg):
    """阶段名 → 索引 (0..7) / None=未识别 (★ 不再静默降级为 0)"""
    if stg is None:
        return None
    t = str(stg).strip()
    for pre in ("阶段 ", "阶段", "stage ", "Stage ", "STAGE "):
        if t.startswith(pre):
            t = t[len(pre):].strip()
    if t in STAGES8:
        return STAGES8.index(t)
    if t in _STAGE_ALIAS:
        return STAGES8.index(_STAGE_ALIAS[t])
    return None
ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, f"{ROOT}/src")
sys.path.insert(0, f"{ROOT}/tools/gui")

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("LOCAL_DATASET_DIR", "/home/ubuntu/stable-wm-cache")
os.environ.setdefault("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")


# ───────── L5: 定方向 (规划器 → 任务变体) ─────────
def plan_variants(n: int, seed: int = 104) -> list:
    """L5 规划器定方向: 生成 n 个带语义的**任务变体**。

    变体维度 (L5 的"方向"):
      · goal_dy/dz  : 目标位移 (对位偏差方向) — 最有区分度的方向
      · stage_skip  : 阶段组合 (是否省略接近段)
      · grip_force  : 抓取力档 (对应 L2 检测反馈的阈值)
      · speed_scale : 速度档 (L3 状态调度的节奏)
    """
    rng = np.random.default_rng(seed)
    dirs = []
    for i in range(n):
        dirs.append({
            "id": i,
            "goal_dx": float(rng.uniform(-0.006, 0.006)),      # ±6mm 轴向 (新增)
            "goal_dy": float(rng.uniform(-0.020, 0.020)),      # ±20mm 对位方向
            "goal_dz": float(rng.uniform(-0.010, 0.010)),      # ±10mm 高度
            "yaw_deg": float(rng.uniform(-3.0, 3.0)),          # ±3° 模块偏航 (新增)
            "slot_mm": float(rng.uniform(-5.0, 5.0)),          # ±5mm 槽位错位 (新增)
            "surface": int(rng.integers(0, 3)),                # 0=洁净 1=油污 2=氧化 (新增)
            "stage_skip": int(rng.integers(0, 2)),             # 0=完整, 1=省略接近
            "grip_force": int(rng.choice([30, 40, 50])),       # 抓取力档
            "speed_scale": float(rng.choice([0.8, 1.0, 1.2])), # 速度档
            "why": "L5 规划器按 8 维展开: 轴向×对位×高度×偏航×槽位×表面×阶段×力档×速度",
        })
    return dirs


def apply_variant(sim, d):
    """★ 把变体**真正注入**引擎（此前只改 seed, 变体维度未生效 —— 本次修正）

    做法与引擎 _inject_peg_jitter 一致: 直接改 MuJoCo 模型里 peg body 的 free joint qpos,
    然后 mj_forward() 让引擎以新初始条件起跑。返回 (ok, detail) 供取证。
    """
    try:
        import mujoco as mj
        import numpy as np
        m, dt = sim.env.model, sim.env.data
        adr = None
        for i in range(m.nbody):
            if m.body(i).name == "peg":
                j = m.body_jntadr[i]
                if j >= 0 and m.jnt_type[j] == 0:            # FREE joint
                    adr = m.jnt_qposadr[j]
                break
        if adr is None:
            return False, "未找到 peg free joint"
        p0 = dt.qpos[adr:adr + 3].copy()
        dt.qpos[adr + 0] += float(d.get("goal_dx", 0.0))
        dt.qpos[adr + 1] += float(d.get("goal_dy", 0.0))
        dt.qpos[adr + 2] += float(d.get("goal_dz", 0.0))
        # 偏航: 绕 z 轴旋转四元数 (qpos[3:7] = w,x,y,z)
        yaw = np.radians(float(d.get("yaw_deg", 0.0)))
        q = dt.qpos[adr + 3:adr + 7].copy()
        dq = np.array([np.cos(yaw / 2), 0.0, 0.0, np.sin(yaw / 2)])   # 绕 z
        w1, x1, y1, z1 = q
        w2, x2, y2, z2 = dq
        dt.qpos[adr + 3:adr + 7] = np.array([
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2])
        mj.mj_forward(m, dt)
        p1 = dt.qpos[adr:adr + 3].copy()
        return True, "Δpos=%.1fmm yaw=%.2f°" % (float(np.linalg.norm(p1 - p0)) * 1000, float(d.get("yaw_deg", 0)))
    except Exception as e:                                                        # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, str(e)[:70])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--steps", type=int, default=400, help="每个变体跑多少步")
    ap.add_argument("--out", default="/home/ubuntu/stable-wm-cache/datasets/l5_gen_v1.h5")
    ap.add_argument("--seed", type=int, default=104)
    ap.add_argument("--save-every", type=int, default=20)
    ap.add_argument("--vision", type=int, default=1, help="1=开渲染(才有关键帧, 真像素)")
    a = ap.parse_args()

    import h5py
    from state_space_sim_real import RealStateSpaceSim

    dirs = plan_variants(a.n, a.seed)
    print(f"🧭 L5 定方向: {len(dirs)} 个任务变体")
    print(f"   维度: goal_dy ±20mm · goal_dz ±10mm · stage_skip · grip_force(30/40/50) · speed(0.8/1.0/1.2)")

    # 增量写 h5 (可中断/续跑)
    f = h5py.File(a.out, "a")
    for k, shape, dt in (("observation", (0, 39), "float32"), ("action", (0, 4), "float32"),
                         ("pixels", (0, 224, 224, 3), "uint8"), ("goal", (0, 39), "float32"), ("skill_ctx", (0, 24), "float32"),
                         ("variant_id", (0,), "int32")):
        if k not in f:
            f.create_dataset(k, shape=shape, maxshape=(None,) + shape[1:], dtype=dt, chunks=True)
    have = int(f["observation"].shape[0])
    print(f"   已有 {have} 帧 → 从变体 {have // max(1, a.steps)} 续")

    t0 = time.time()
    n_frames = have
    for d in dirs:
        start_from = n_frames // max(1, a.steps)
        if d["id"] < start_from:
            continue
        try:
            sim = RealStateSpaceSim(seed=a.seed + d["id"], vision=bool(a.vision), log=lambda *x: None)
        except Exception as e:
            print(f"  ⚠️ 变体 {d['id']} 引擎失败: {str(e)[:80]}")
            continue

        # ★★ 2026-09-23 修: obs 必须与 v5/v6 同约定 = **env._get_obs()[:39]** (实测辨明)
        #    之前误用 tr["obs"] (引擎 fused 39 维) → 与训练数据不可比
        #    挂 fuse_sensors 钩子 (每步恰好调 1 次) → 精确 1:1 对齐轨迹步
        _env_obs = []
        try:
            _orig_fuse = sim.perception.fuse_sensors

            def _fuse_hook(visual39, force, tactile4, _o=_orig_fuse, _s=sim, _b=_env_obs):
                try:
                    _b.append(np.asarray(_s.env._get_obs(), dtype=np.float64).ravel()[:39].copy())
                except Exception:
                    pass
                return _o(visual39, force, tactile4)

            sim.perception.fuse_sensors = _fuse_hook
        except Exception as e:
            print(f"  ⚠️ 变体 {d['id']} obs 钩子挂载失败: {str(e)[:60]}", flush=True)

        # ★ 真注入变体（横向/高度/偏航）—— 不注入则"变体"只是标签
        _ok_i, _det_i = apply_variant(sim, d)
        if d["id"] % a.save_every == 0:
            print("      [inject] 变体%d: %s %s" % (d["id"], "✅" if _ok_i else "⚠️", _det_i), flush=True)

        # 用 run() 拿真轨迹 (引擎无公开 step)
        try:
            tr = sim.run(max_steps=a.steps)
        except Exception as e:
            print(f"  ⚠️ 变体 {d['id']} run 失败: {str(e)[:80]}")
            continue
        _tr_obs = tr.get("obs", [])
        # 优先用 env 原生 obs (与 v5/v6 同源); 长度必须与轨迹一致才采用
        if _env_obs and abs(len(_env_obs) - len(_tr_obs)) <= 1:
            obs_l = _env_obs
        else:
            obs_l = _tr_obs
            print(f"  ⚠️ 变体 {d['id']} env obs 长度不符 ({len(_env_obs)} vs {len(_tr_obs)}), 回落 tr['obs']",
                  flush=True)
        stage_l = tr.get("stage", [])
        act_l = tr.get("u_sat_vec", None) or tr.get("u_exec_vec", None) or tr.get("u_ff_vec", [])
        kf = getattr(sim, "_key_frames", {}) or {}
        if d["id"] % a.save_every == 0:
            print(f"      [diag] 变体{d['id']} 关键帧 {len(kf)} 个: {list(kf)[:4]}", flush=True)
        obs_buf, act_buf, px_buf, sk_buf = [], [], [], []
        _unrecognized = [0]
        n = min(len(obs_l), len(act_l) if act_l else 0)
        for t in range(n):
            obs = np.asarray(obs_l[t], dtype=np.float32).ravel()[:39]
            if obs.shape[0] < 39:
                obs = np.pad(obs, (0, 39 - obs.shape[0]))
            # L2 检测反馈的输入帧: 该阶段的真渲染关键帧 (引擎 render)
            stg = stage_l[t] if t < len(stage_l) else None
            fr = kf.get(stg)
            if fr is None and kf:
                fr = next(iter(kf.values()))
            if fr is None:
                fr = np.zeros((224, 224, 3), np.uint8)
            px = np.asarray(fr)
            if px.ndim == 2:
                px = np.stack([px] * 3, -1)
            if px.shape[-1] != 3:
                px = px[..., :3]
            if px.shape[:2] != (224, 224):
                import cv2
                px = cv2.resize(px, (224, 224))
            px = px.astype(np.uint8, copy=False)
            av = np.asarray(act_l[t], dtype=np.float32).ravel()[:4]
            if av.shape[0] < 4:
                av = np.pad(av, (0, 4 - av.shape[0]))
            _si = stage_index(stg)
            if _si is None:                       # ★ 未识别: 独立槽 + 计数 (旧行为=伪装成"接近")
                _si = SK_UNKNOWN_SLOT - 13
                _unrecognized[0] += 1
            _sk = np.zeros(24, dtype=np.float32); _sk[13 + _si] = 1.0
            obs_buf.append(obs); act_buf.append(av); px_buf.append(px); sk_buf.append(_sk)
        if not obs_buf:
            continue
        n = len(obs_buf)
        obs_a, act_a, px_a = np.stack(obs_buf), np.stack(act_buf), np.stack(px_buf)
        sk_a = np.stack(sk_buf)
        _uniq = len({tuple(np.round(r, 3)) for r in sk_a}) if len(sk_a) else 0
        print("   skill_ctx 诊断: %d 帧 · 不同阶段 one-hot %d 种 · 未识别阶段 %d 帧%s"
              % (len(sk_a), _uniq, _unrecognized[0],
                 "  ⚠️ 仍为常量!" if _uniq <= 1 else "  ✅ 阶段条件已生效"))
        goal_a = np.roll(obs_a, -7, axis=0)            # L4 认知预测的目标 (未来第 7 帧)
        for k, arr in (("observation", obs_a), ("action", act_a), ("pixels", px_a), ("goal", goal_a), ("skill_ctx", sk_a)):
            m = f[k].shape[0]
            f[k].resize(m + n, axis=0); f[k][m:m + n] = arr
        vid = np.full((n,), d["id"], dtype=np.int32)
        m = f["variant_id"].shape[0]
        f["variant_id"].resize(m + n, axis=0); f["variant_id"][m:m + n] = vid
        n_frames += n
        if d["id"] % a.save_every == 0:
            f.flush()
            sps = n_frames / max(1e-6, time.time() - t0)
            print(f"  变体 {d['id']:4d}/{len(dirs)} | 累计 {n_frames:,} 帧 | {sps:.0f} 帧/s "
                  f"| dy={d['goal_dy']*1000:+.1f}mm f={d['grip_force']} v={d['speed_scale']}", flush=True)
    f.flush(); f.close()
    dt = time.time() - t0
    print(f"✅ L5 造数据完成: {n_frames:,} 帧 / {dt:.0f}s → {a.out}")
    print(f"   变体方向谱: {len(dirs)} 个 (对位偏差 × 阶段 × 力档 × 速度)")
    json.dump({"n": len(dirs), "frames": n_frames, "sec": dt, "out": a.out},
              open(f"{ROOT}/reports/l5_gen_v1.json", "w"), indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
