# -*- coding: utf-8 -*-
"""📦 v5 光模块插拔数据集 —— **带记忆层的抗干扰专家数据 + L2 原子技能上下文 (skill_ctx)**

为什么要 v5 (相对 v4):
  v4 = 单档干扰 (引擎默认 ±3.5cm/±15°) + 只记 (pixels, action, observation)。
  老倪 09-14 下令: "带着记忆层，适配训练 L4 的INTACT, 要能让L4看到 L2的原子技能，复用能力;
  你要作新的抗干扰的数据"。→ 本采集器做三件事:

  ① **skill_ctx 通道 (让 L4"看到" L2 原子技能)**: 每帧记 19 维
       [ 引擎相位 one-hot(13, cognition.STAGES mode=full 全 13 段 → 前 8 = SK01..SK08),
         L2 流程势场按状态软判的技能权重 w(8)  ← 这就是 L2 的原子技能"活跃度",
         到 L2 冠军轨迹管的横向距离 d_perp(1),   ← 复用能力的"贴合度"
         弧长进度 arc_frac(1), 夹爪指令 grip(1) ]
     口径: L2 字段来自 `MemoryLayerBridge.from_real_data` (真 muscle_memory.json + 引擎几何),
     d_perp 用**夹爪真实位置 obs[0:3]** 算 (v5.5.48 坐标系实锤: 引擎 self.x = obs[0:3], 不是 peg_head)。

  ② **多档抗干扰 (真注入, 可复现)**: 显式 `_jitter_override` 分 light/med/heavy 三档 +
     mixed (按 seed 轮转) —— 干扰是引擎 `_inject_peg_jitter` **真改 peg 的 qpos** 再 mj_forward,
     现场几何/obs 全重读, 不是贴图。每回合把 `_jitter_meta` 记进 meta 供溯源。
     ⚠️ 干扰注入时引擎会旁路 L2 快通道 (布局变了标杆失效) —— 这是**已知降级**, 本数据集
     如实记录 (skill_ctx 里的 w 会退化成"按状态判"的软权重, 不假装).

  ③ **专家口径**: cap=l4 (自主恢复档, 失败重抓不放弃) + success-only (只留成功回合窗口),
     与官方 *_single_expert 同语义。

用法 (gui-venv311, 引擎环境):
  ./gui-venv311/bin/python tools/intact_insert_dataset_v5.py \
      --seeds 0-299 --mode full --window 50 --coverage all --stride 50 \
      --disturb mixed --cap l4 --success-only 1 \
      --out-name optical_insert_v5_disturb --dest /home/ubuntu/stable-wm-cache/datasets
  然后 (INTACT venv, 有 h5py):
  /home/ubuntu/INTACT-JEPA/.venv/bin/python tools/intact_parts_to_h5.py \
      --parts 'reports/optical_insert_v5_disturb_part*.npz' \
      --out-name optical_insert_v5_disturb --dest /home/ubuntu/stable-wm-cache/datasets
  注意: 转 h5 时要带 --skill-ctx (把 npz 的 skill_ctx 一起写进 h5)。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.environ.setdefault("MUJOCO_GL", os.environ.get("MUJOCO_GL", "egl"))
_CACHE = os.environ.get("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
if os.path.isdir(_CACHE):
    os.environ.setdefault("STABLEWM_HOME", _CACHE)
    os.environ.setdefault("LOCAL_DATASET_DIR", _CACHE)

# 引擎 cognition.ActionModulator.STAGES (mode=full 13 段; mode=insert 只用前 8 段)
# → 前 8 段 = L2 的 SK01..SK08
STAGE_ORDER = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入",
               "拔出", "AOI转移", "AOI检测", "回程", "放下", "完成"]
# 三档干扰 (引擎 _inject_peg_jitter 的 override 口径; 平移 m / 高度 m / yaw rad)
DISTURB = {
    "none":  None,
    "light": {"dx": None, "dy": None, "dz": None, "yaw": None, "_scale": 0.45},
    "med":   {"dx": None, "dy": None, "dz": None, "yaw": None, "_scale": 1.00},
    "heavy": {"dx": None, "dy": None, "dz": None, "yaw": None, "_scale": 1.45},
}


def _parse_seeds(spec: str):
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def _level_of(a, seed, si):
    """mixed: 按 seed 轮转 light/med/heavy (2/5 中档 与引擎默认同量级)"""
    lv = str(a.disturb).lower()
    if lv == "mixed":
        return ["light", "med", "med", "heavy", "med"][si % 5]
    return lv


def _jitter_override(level, seed, scale):
    """显式可复现干扰: 基准 = 引擎默认域 (±3.5cm / -4~+10mm / ±15°), scale 缩放平移与角。
    yaw 上限钉在 ±15° (引擎注释: ±15° 是物理可成功域, 再大长条盒夹不住 = 造假成功不了)"""
    if level == "none":
        return None
    rng = np.random.RandomState(20260914 + int(seed) * 977)
    s = float(scale)
    dx, dy = rng.uniform(-0.035, 0.035, 2) * s
    dz = rng.uniform(-0.004, 0.010) * (1.0 if s <= 1.0 else 1.2)
    yaw = float(np.clip(rng.uniform(-0.26, 0.26) * s, -0.26, 0.26))
    return {"dx": float(dx), "dy": float(dy), "dz": float(dz), "yaw": float(yaw),
            "shell90": bool(rng.rand() < 0.5)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="0-299")
    ap.add_argument("--mode", default="full", choices=["insert", "full"])
    ap.add_argument("--max-steps", type=int, default=1600)
    ap.add_argument("--img", type=int, default=224)
    ap.add_argument("--window", type=int, default=50)
    ap.add_argument("--n-per-ep", type=int, default=4)
    ap.add_argument("--stride-back", type=int, default=15)
    ap.add_argument("--out-name", default="optical_insert_v5_disturb")
    ap.add_argument("--dest", default=os.path.join(_CACHE, "datasets"))
    ap.add_argument("--part-frames", type=int, default=20000)
    ap.add_argument("--max-sec", type=float, default=0)
    ap.add_argument("--cap", default="l4")
    ap.add_argument("--success-only", type=int, default=1)
    ap.add_argument("--action-key", default="u", choices=["env", "u"])
    ap.add_argument("--coverage", default="all", choices=["insert", "all"])
    ap.add_argument("--stride", type=int, default=50)
    ap.add_argument("--disturb", default="mixed",
                    help="none / light / med / heavy / mixed (按 seed 轮转 2/5 中档)")
    ap.add_argument("--l2-skill-ctx", type=int, default=1,
                    help="1 = 记 skill_ctx (L2 原子技能上下文, 24 维: stage13 + L2 w8 + d_perp/arc/grip)")
    a = ap.parse_args()

    import cv2
    from state_space_sim_real import RealStateSpaceSim
    from lerobot.policies.intact.skill_ctx import SKILL_CTX_DIM, build_skill_ctx

    print(f"🧠 skill_ctx 定义: {SKILL_CTX_DIM} 维 "
          f"[stage{len(STAGE_ORDER)} | L2 w8 | d_perp | arc_frac | grip] "
          f"(src/lerobot/policies/intact/skill_ctx.py, 与闭环桥同源)", flush=True)

    # ── L2 原子技能上下文 (只建一次: 真 muscle_memory.json + 引擎几何) ──
    _SKERR = [None]
    bridge = None
    if int(a.l2_skill_ctx):
        try:
            from lerobot.memory.potential_field import MemoryLayerBridge
            globals()["_PF_mod"] = __import__("lerobot.memory.potential_field",
                                              fromlist=["project_polyline"])
            bridge = MemoryLayerBridge.from_real_data(root=ROOT, seed=104, use_engine_geom=True)
            _n = len(bridge.process.fields) if bridge.process is not None else 0
            print(f"🧠 L2 势场就绪: {_n} 个原子技能 "
                  f"{[f.code for f in bridge.process.fields] if _n else '[]'}", flush=True)
        except Exception as e:                                   # noqa: BLE001
            print(f"⚠️ L2 势场不可用 ({type(e).__name__}: {e}) → skill_ctx 记零 (诚实标注)", flush=True)
            bridge = None

    def _skill_ctx(x, grip, stage):
        """🧠 单一事实来源: src/lerobot/policies/intact/skill_ctx.build_skill_ctx
        (与闭环桥 tools/intact_sw_optical_bridge.py 同一份代码 → 训练数据/推理口径逐位一致)"""
        _proc = getattr(bridge, "process", None) if bridge is not None else None
        return build_skill_ctx(_proc, x, stage, grip)

    seeds = _parse_seeds(a.seeds)
    os.makedirs(a.dest, exist_ok=True)
    ep_pix, ep_act, ep_obs, ep_sk, ep_len, meta_eps = [], [], [], [], [], []
    parts, t0 = [], time.time()

    def _flush(final=False):
        if not ep_len:
            return
        L = np.asarray(ep_len, dtype=np.int64)
        off = np.concatenate([[0], np.cumsum(L)[:-1]]).astype(np.int64)
        px = np.concatenate(ep_pix, axis=0)
        stds = [float(np.mean([px[int(off[i]) + j].std()
                               for j in np.linspace(0, L[i] - 1, 8).astype(int)])) for i in range(len(L))]
        bad = [i for i, v in enumerate(stds) if v <= 5.0]
        if bad:
            print(f"❌ 有 {len(bad)} 个黑帧回合 → 不落盘 (idx {bad[:6]})", flush=True)
        else:
            p = os.path.join(ROOT, "reports", f"{a.out_name}_part{len(parts):02d}.npz")
            kw = dict(pixels=px, action=np.concatenate(ep_act, axis=0).astype(np.float32),
                      observation=np.concatenate(ep_obs, axis=0).astype(np.float32))
            if ep_sk:
                _sk = np.concatenate(ep_sk, axis=0).astype(np.float32)
                assert _sk.shape[1] == SKILL_CTX_DIM, (
                    f"skill_ctx 维度 {_sk.shape[1]} != 定义 {SKILL_CTX_DIM} (口径漂移, 拒绝落盘)")
                kw["skill_ctx"] = _sk
            np.savez_compressed(
                p, **kw, ep_len=L, ep_offset=off,
                ep_idx=np.concatenate([np.full(n, i, dtype=np.int32) for i, n in enumerate(L)]),
                step_idx=np.concatenate([np.arange(n, dtype=np.int64) for n in L]),
                meta=np.array([{
                    "source": "Z-MAX 六层引擎 RealStateSpaceSim 真链路 (光模块插拔, metaworld 40×16mm 模块)",
                    "pixels": f"env.render() 真渲染 → {a.img}² RGB",
                    "action": "sink 实收引擎控制向量 sim._u_vec (4D, 同 tr u_exec_vec)",
                    "observation": "env 原生 o[:39]",
                    "skill_ctx": ("[stage_onehot(13) | L2 技能软权重 w(8) | d_perp | arc_frac | grip] "
                                  "= 24; L2 字段 = MemoryLayerBridge.from_real_data (真 muscle_memory.json "
                                  "+ 引擎几何); d_perp 口径 = 夹爪真实位置 obs[0:3] (v5.5.48 坐标系实锤)")
                    if ep_sk else "未记录 (--l2-skill-ctx 0)",
                    "skill_ctx_frames": int(sum(len(x) for x in ep_sk)) if ep_sk else 0,
                    "skill_ctx_err": _SKERR[0],
                    "disturb": a.disturb, "cap": a.cap, "mode": a.mode, "window": a.window,
                    "episodes": len(L), "frames": int(L.sum()),
                    "done_rate": round(float(np.mean([m["done"] for m in meta_eps[-len(L):]])), 4),
                    "ep_frame_std": [round(v, 2) for v in stds],
                    "ep_jitter": [m.get("jitter") for m in meta_eps[-len(L):]],
                    "ep_level": [m.get("level") for m in meta_eps[-len(L):]],
                    "ep_insert_mm": [m.get("insert_mm") for m in meta_eps[-len(L):]],
                    "ep_stage_end": [m["stage_end"] for m in meta_eps[-len(L):]],
                    "ts": time.strftime("%F %T")}], dtype=object))
            parts.append(p)
            print(f"   💾 part{len(parts)-1:02d}: 窗口 {len(L)} · 帧 {int(L.sum())} · "
                  f"{os.path.getsize(p)/1e6:.0f}MB · done_rate "
                  f"{np.mean([m['done'] for m in meta_eps[-len(L):]]):.2f} · "
                  f"干扰档 {sorted(set(str(m.get('level')) for m in meta_eps[-len(L):]))}", flush=True)
        ep_pix.clear(); ep_act.clear(); ep_obs.clear(); ep_sk.clear(); ep_len.clear()

    n_ok = n_fail = n_win = n_skip = 0
    per_level = {}
    for si, seed in enumerate(seeds):
        if a.max_sec > 0 and time.time() - t0 > a.max_sec:
            print(f"⏱ 到点收尾 (已 {si} 个 seed)", flush=True)
            break
        px, ac, ob, sk, st = [], [], [], [], []
        level = _level_of(a, seed, si)
        ov = _jitter_override(level, seed, DISTURB.get(level, DISTURB["med"])["_scale"])
        _uk = str(a.action_key).lower() == "u"

        def _sink(sim, act, o, _px=px, _ac=ac, _ob=ob, _sk=sk, _st=st, _uk=_uk, _br=bridge):
            _px.append(cv2.resize(np.asarray(sim.env.render()), (a.img, a.img),
                                  interpolation=cv2.INTER_AREA))
            if _uk:
                _a = getattr(sim, "_u_vec", None)
                _u = np.asarray(_a if _a is not None else act, dtype=np.float32).ravel()[:4]
            else:
                _u = np.asarray(act, dtype=np.float32).ravel()[:4]
            _ac.append(_u)
            _o = np.asarray(o, dtype=np.float32).ravel()[:39]
            _ob.append(_o)
            try:
                _sg = str(sim.sched.stage())
            except Exception:                                    # noqa: BLE001
                _sg = "?"
            _st.append(_sg)
            if _br is not None:
                try:
                    _sk.append(_skill_ctx(_o[0:3], _u[3], _sg))
                except Exception as _e:                          # noqa: BLE001
                    _SKERR[0] = f"{type(_e).__name__}: {_e}"
                    raise                                        # 🚫 不静默: skill_ctx 是 v6 的输入契约

        sim = RealStateSpaceSim(seed=seed, vision=False, mode=a.mode, log=lambda *x: None)
        if ov is not None:
            sim._jitter_override = ov
        sim._frame_sink = _sink
        _cap = None if str(a.cap).lower() in ("none", "0", "") else a.cap
        tr = sim.run(max_steps=a.max_steps, cap=_cap)
        done = bool(tr["done"][-1]) if tr.get("done") else False
        jm = getattr(sim, "_jitter_meta", None) or getattr(sim, "_jitter_override", None)
        n = len(px)
        # 几何自检: 插入深度 (真几何, 不信 done 标志)
        ins_mm = None
        try:
            xz = np.asarray(tr["x"], float)
            gg = np.asarray(tr["target"] if "target" in tr else [], float)
            if gg.size:
                ins_mm = round(float(np.min(np.linalg.norm(xz - gg, axis=1)) * 1000), 1)
        except Exception:                                        # noqa: BLE001
            pass
        per_level.setdefault(level, [0, 0])
        per_level[level][1] += 1
        if done:
            n_ok += 1
            per_level[level][0] += 1
        else:
            n_fail += 1
        if not done and int(a.success_only):
            n_skip += 1
            if (si + 1) % 20 == 0 or si == 0:
                print(f"[{si+1}/{len(seeds)}] seed {seed} ({level}): ⚠️未完成 (跳过切窗) {n} 步 · "
                      f"阶段末={st[-1] if st else '?'} · 窗口 {n_win} · 跳过 {n_skip} · "
                      f"用时 {time.time()-t0:.0f}s", flush=True)
            continue
        idx_done = next((i for i, d in enumerate(tr.get("done") or []) if d), None)
        if idx_done is None:
            idx_done = n - 1
        W = int(a.window)
        if str(a.coverage).lower() == "all":
            ends = list(range(W - 1, n, max(1, int(a.stride))))
            if not ends or ends[-1] != n - 1:
                ends.append(n - 1)
        else:
            ends = [idx_done - k * int(a.stride_back) for k in range(int(a.n_per_ep))]
        for end in ends:
            start = end - W + 1
            if start < 0 or end >= n:
                continue
            ep_pix.append(np.asarray(px[start:end + 1]))
            ep_act.append(np.asarray(ac[start:end + 1]))
            ep_obs.append(np.asarray(ob[start:end + 1]))
            if sk:
                ep_sk.append(np.asarray(sk[start:end + 1]))
            ep_len.append(W)
            meta_eps.append({"seed": seed, "done": done, "level": level,
                             "jitter": jm, "insert_mm": ins_mm, "stage_end": st[end], "end": int(end)})
            n_win += 1
        if (si + 1) % 20 == 0 or si == 0:
            print(f"[{si+1}/{len(seeds)}] seed {seed} ({level}): {'✅' if done else '⚠️'} {n} 步 · "
                  f"插入 {ins_mm}mm · 干扰 {jm} · 窗口 {n_win} · 用时 {time.time()-t0:.0f}s", flush=True)
        if len(ep_len) >= a.part_frames // W:
            _flush()
    _flush(final=True)
    print(f"\n✅ 完成: seed {len(seeds)} (成功 {n_ok} / 未完成 {n_fail} · 失败跳过 {n_skip}) · "
          f"窗口 {n_win} · 落盘 parts {len(parts)} · 用时 {time.time()-t0:.0f}s")
    for k, v in sorted(per_level.items()):
        print(f"   档位 {k:6s}: 成功 {v[0]}/{v[1]} = {v[0]/max(1,v[1]):.2f}")
    _has_sk = any("skill_ctx" in np.load(p, allow_pickle=True).files for p in parts)
    print(f"🧠 skill_ctx: {'✅ 已随 part 落盘' if _has_sk else '❌ 未落盘'} · "
          f"构造错误: {_SKERR[0] or '无'}")
    print("下一步 (INTACT venv 转官方 h5, 带 skill_ctx):")
    print(f"  /home/ubuntu/INTACT-JEPA/.venv/bin/python tools/intact_parts_to_h5.py "
          f"--parts 'reports/{a.out_name}_part*.npz' --out-name {a.out_name} --dest {a.dest} --skill-ctx")


if __name__ == "__main__":
    main()
