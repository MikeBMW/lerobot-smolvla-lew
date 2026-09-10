#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运动基元全局记忆 (Motor Primitive Hub) — L2 肌肉记忆的共享抽象层

老倪要求 (2026-09-10):
  "状态空间的原子技能 L2 功能都是肌肉记忆, 应该都知道怎么发力、速度、加速度, 怎么更快
   更稳更准 — 把这个信息共享给总装记忆, 提取出机器人能做的肌肉记忆操作。"

──────────────────────────────────────────────────────────
理论基础
──────────────────────────────────────────────────────────
1) **运动基元 (Motor Primitives / DMP, Ijspeert 2002)**
   生物运动不是"每条轨迹各存一份", 而是由**少量基元**组合而成: 每个基元 = 一个带吸引子的
   动力学模板 (发力曲线/速度剖面/加速度剖面)。学会 N 个技能 ≠ 记 N 条轨迹, 而是
   "一套共享基元 + 每个技能的调制参数"。这正是"老教练的发力/抛物线/重心转移是同一套"。

2) **共享编码器 (INTACT 的隐性版 → 本模块是显式版)**
   INTACT 用多任务梯度共享把通用物理规律压进权重(隐式、不可读); 本模块从 L2 标杆库里
   **显式提取**"发力规律"并聚成全局共享基元(可读、可审计、可编辑 — 老倪零容忍黑盒)。

3) **参数压缩 (回答"记下来了是不是参数就能少")**
   一条 28 帧 × 4 维轨迹 = 112 个数值 → "基元 id + 时长 + 幅值缩放" ≈ 3~5 个数值。
   压缩比可达 20~30×, 而且新场景只需匹配基元, 不必重放整段死轨迹。

──────────────────────────────────────────────────────────
产出 (写入 data/shared_memory.json 的 motor 层, 全局可查)
──────────────────────────────────────────────────────────
  motor.primitives : [ {id, name, n_member, stages, template_u, template_v, feat, spread} ]
  motor.mapping    : { stage: {primitive, dur_scale, amp_scale, n_src} }
  motor.sharing    : 共享度统计 (哪些基元被多个技能段共用)
  motor.compression: 参数压缩比
"""
import json
import os

import numpy as np

ROOT = os.environ.get("ZMAX_ROOT", "/home/ubuntu/lerobot-smolvla-lew")
MUSCLE = os.path.join(ROOT, "data", "muscle_memory.json")
SHARED = os.path.join(ROOT, "data", "shared_memory.json")
STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入"]
T = 32          # 基元模板统一帧数 (重采样基准, 刻画"发力曲线形状")
FEATS = ["dur", "dx", "dy", "dz", "disp", "v_peak", "v_mean", "a_peak", "f_peak", "f_mean", "grip_sw"]


def _resample(a, n=T):
    """把任意长度的序列重采样到 n 帧 (保形, 用于对齐后平均出基元模板)。"""
    a = np.asarray(a, float)
    if a.ndim == 1:
        a = a[:, None]
    if a.shape[0] == n:
        return a
    if a.shape[0] < 2:
        return np.repeat(a, n, axis=0)
    src = np.linspace(0.0, 1.0, a.shape[0])
    dst = np.linspace(0.0, 1.0, n)
    return np.stack([np.interp(dst, src, a[:, d]) for d in range(a.shape[1])], axis=1)


def _norm_stage(s):
    return str(s).replace("阶段 ", "").split("·")[0].strip()


def extract_feats(u, x, io):
    """从一条标杆 (动作序列 u / 位置序列 x) 提取"发力规律"特征。

    这些就是老倪说的"怎么发力、速度、加速度、更快更稳更准"的可量化形式:
      v_peak/v_mean : 速度剖面 (更快)
      a_peak        : 加速度剖面 (发力陡峭度 → 更稳/更柔和)
      f_peak/f_mean : 指令力剖面 (发力大小)
      grip_sw       : 夹爪切换次数 (抓取/释放时序)
      dur           : 段时长 (干活快慢)
    """
    u = np.asarray(u, float)
    x = np.asarray(x, float)
    if x.ndim == 1:
        x = x[:, None]
    dx = np.diff(x, axis=0) if x.shape[0] > 1 else np.zeros((1, x.shape[1]))
    v = dx                                   # 1 帧步长 → 速度剖面
    a = np.diff(v, axis=0) if v.shape[0] > 1 else np.zeros((1, v.shape[1]))
    sp = np.linalg.norm(v, axis=1)
    ac = np.linalg.norm(a, axis=1)
    f = np.linalg.norm(u[:, :3], axis=1) if u.shape[1] >= 3 else np.abs(u[:, 0])
    g = u[:, 3] if u.shape[1] > 3 else np.zeros(u.shape[0])
    gsw = float(np.sum(np.abs(np.diff(np.sign(g))) > 0))
    entry = np.asarray(io.get("entry", [np.nan] * 3), float)
    exit_ = np.asarray(io.get("exit", [np.nan] * 3), float)
    disp = exit_ - entry
    return np.array([
        float(u.shape[0]), float(disp[0]), float(disp[1]), float(disp[2]),
        float(np.linalg.norm(disp)),
        float(sp.max()), float(sp.mean()), float(ac.max()), float(f.max()),
        float(f.mean()), gsw,
    ], float)


def _rot_between(a, b):
    """罗德里格斯公式: 把向量 a 旋到向量 b 的最小旋转矩阵 (3×3)。"""
    a = np.asarray(a, float) / (np.linalg.norm(a) + 1e-12)
    b = np.asarray(b, float) / (np.linalg.norm(b) + 1e-12)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    s = float(np.linalg.norm(v))
    if s < 1e-9:
        return np.eye(3) if c > 0 else -np.eye(3)
    K = np.array([[0.0, -v[2], v[1]], [v[2], 0.0, -v[0]], [-v[1], v[0], 0.0]])
    return np.eye(3) + K + (K @ K) * ((1.0 - c) / (s * s))


def _kmeans(X, k, iters=200, seed=0):
    rng = np.random.RandomState(seed)
    k = max(1, min(k, len(X)))
    C = X[rng.choice(len(X), k, replace=False)].copy()
    lab = np.zeros(len(X), int)
    for _ in range(iters):
        d = ((X[:, None, :] - C[None, :, :]) ** 2).sum(-1)
        new = d.argmin(1)
        if np.array_equal(new, lab) and _ > 0:
            lab = new
            break
        lab = new
        for i in range(k):
            m = lab == i
            if m.sum():
                C[i] = X[m].mean(0)
    return lab, C


class MotorHub:
    """运动基元全局记忆: 提取 → 聚类 → 模板 → 写入共享记忆 → 查询。"""

    def __init__(self, muscle_path=MUSCLE, shared_path=SHARED):
        self.muscle_path = muscle_path
        self.shared_path = shared_path
        self.champs = []      # 每条标杆的原始数据
        self.feats = None
        self.labels = None
        self.centers = None
        self.primitives = []
        self.mapping = {}
        self.load()

    # ── 载入 L2 标杆 ────────────────────────────────────────
    def load(self):
        self.champs = []
        if not os.path.exists(self.muscle_path):
            return self
        db = json.load(open(self.muscle_path))
        for key, e in db.items():
            if not isinstance(e, dict) or e.get("champ_u") is None:
                continue
            seed_s, _, stage = key.partition("|")
            try:
                seed = int(seed_s)
            except ValueError:
                continue
            u = np.asarray(e["champ_u"], float)
            x = np.asarray(e.get("champ_x"), float)
            if u.ndim != 2 or u.shape[0] < 2:
                continue
            self.champs.append(dict(seed=seed, stage=_norm_stage(stage), u=u, x=x,
                                    io=e.get("io") or {}, n_ok=int(e.get("n_ok", 0))))
        return self

    # ── 聚类出共享基元 ──────────────────────────────────────
    def build(self, k=4, standardize=True):
        if not self.champs:
            return self
        F = np.stack([extract_feats(c["u"], c["x"], c["io"]) for c in self.champs])
        self.feats = F
        mu = F.mean(0) if standardize else np.zeros(F.shape[1])
        sd = F.std(0) + 1e-9 if standardize else np.ones(F.shape[1])
        Z = (F - mu) / sd
        k = max(1, min(k, len(Z)))
        self.labels, self.centers = _kmeans(Z, k)
        self._mu, self._sd = mu, sd

        self.primitives = []
        for i in range(k):
            idx = np.where(self.labels == i)[0]
            if len(idx) == 0:
                continue
            us = [_resample(self.champs[j]["u"]) for j in idx]
            xs = [_resample(self.champs[j]["x"]) for j in idx]
            U = np.stack(us)
            X = np.stack(xs)
            # 模板 = 成员平均 (对齐后) — 这就是"共享的发力方式"
            tpl_u = U.mean(0)
            tpl_v = np.linalg.norm(np.diff(X.mean(0), axis=0), axis=1)
            spread = float(np.mean([np.abs(u - tpl_u).max() for u in us])) if len(idx) > 1 else 0.0
            stg = sorted({self.champs[j]["stage"] for j in idx})
            self.primitives.append(dict(
                id=i, n_member=len(idx), stages=stg,
                seeds=sorted({self.champs[j]["seed"] for j in idx}),
                template_u=np.round(tpl_u, 5).tolist(),
                template_v=np.round(tpl_v, 5).tolist(),
                feat=np.round(F[idx].mean(0), 5).tolist(),
                spread=round(spread, 5),
                members=[f"{self.champs[j]['seed']}|{self.champs[j]['stage']}" for j in idx],
            ))
        # 命名: 用成员的阶段 + 主导运动方向给基元起可读名字
        for p in self.primitives:
            f = dict(zip(FEATS, p["feat"]))
            d = np.array([f["dx"], f["dy"], f["dz"]])
            main = ["+x 水平", "-x 水平", "+y 水平", "-y 水平", "+z 抬升", "-z 下压"][int(np.argmax(np.abs(d)))]
            p["name"] = f"{'/'.join(p['stages'][:2]) or '通用'}·{main}"
        # 每个阶段的映射 (用哪些基元 + 调制)
        for st in STAGES:
            idx = [j for j, c in enumerate(self.champs) if c["stage"] == st]
            if not idx:
                continue
            labs = self.labels[idx]
            main_lab = int(np.bincount(labs).argmax())
            src = [j for j in idx if self.labels[j] == main_lab]
            dur = float(np.mean([self.champs[j]["u"].shape[0] for j in src]))
            amp = float(np.mean([np.abs(self.champs[j]["u"][:, :3]).max() for j in src]))
            self.mapping[st] = dict(primitive=main_lab, dur=dur, amp=round(amp, 4),
                                    n_src=len(src), all_prims=sorted({int(l) for l in labs}))
        return self

    # ── 共享度 / 压缩比 ─────────────────────────────────────
    def sharing_stats(self):
        used = {}
        for p in self.primitives:
            for st in p["stages"]:
                used.setdefault(p["id"], set()).add(st)
        multi = [p for p in self.primitives if len(used.get(p["id"], ())) > 1]
        n_seg = len(self.champs)
        raw_vals = int(sum(c["u"].size for c in self.champs))              # 原始: 每段全序列
        prim_vals = int(sum(len(p["template_u"]) * len(p["template_u"][0]) for p in self.primitives))
        # 简化表达: 基元 id + 时长 + 幅值 = 3 数/段
        simp_vals = prim_vals + 3 * n_seg
        return dict(n_seg=n_seg, n_prim=len(self.primitives), n_multi_stage=len(multi),
                    raw_values=raw_vals, primitive_values=prim_vals, simplified_values=simp_vals,
                    compression=round(raw_vals / max(simp_vals, 1), 2),
                    per_primitive={p["id"]: {"name": p["name"], "n_member": p["n_member"],
                                             "stages": p["stages"], "spread": p["spread"]}
                                   for p in self.primitives})

    # ── 查询 (供引擎 / L3 / L4 用) ──────────────────────────
    def query(self, stage):
        """阶段 → (基元模板动作, 调制参数)。接口与 u_ff 槽位兼容。"""
        st = _norm_stage(stage)
        m = self.mapping.get(st)
        if not m:
            return None, {"hit": False, "stage": st}
        p = next((q for q in self.primitives if q["id"] == m["primitive"]), None)
        if p is None:
            return None, {"hit": False, "stage": st}
        U = np.asarray(p["template_u"], float)
        if U.shape[0] != m["dur"] and U.shape[0] > 1:      # 按时长调制重采样
            U = _resample(U, max(2, int(round(m["dur"]))))
        return U, {"hit": True, "stage": st, "primitive": p["id"], "name": p["name"],
                   "dur": m["dur"], "amp": m["amp"], "n_src": m["n_src"],
                   "shared_by": m["all_prims"]}

    # ── 该段的平均几何 (调制用) ─────────────────────────────
    def _stage_geom(self, stage):
        st = _norm_stage(stage)
        E, X = [], []
        for c in self.champs:
            if c["stage"] != st:
                continue
            io = c["io"] or {}
            e = np.asarray(io.get("entry", [np.nan] * 3), float)
            x = np.asarray(io.get("exit", [np.nan] * 3), float)
            if np.isfinite(e).all() and np.isfinite(x).all():
                E.append(e)
                X.append(x)
        if not E:
            return None
        return {"entry": np.stack(E).mean(0), "exit": np.stack(X).mean(0), "n": len(E)}

    # ── 版本 B: 基元 + 现场几何调制 (更准更快) ───────────────
    def query_modulated(self, stage, cur_pos, goal_pos, amp_scale=True, clip=(0.5, 2.0)):
        """🦾 基元模板 + 现场几何调制。

        纯模板重放只有"发力形状", 换场景会走弯路 (实测 seed7 346→510 帧)。
        调制 = 把模板按**现场目标**重新投影:
          ① 方向对齐: R = 把该段"模板位移方向"旋到"当前期望位移方向" (罗德里格斯)
          ② 幅值缩放: s = clip(|目标−当前| / |模板位移|)
        即: "怎么发力(形状)照旧, 往哪发/发多大按现场解算" → 更快更稳更准。
        """
        U, meta = self.query(stage)
        if U is None:
            return None, meta
        g = self._stage_geom(stage)
        if g is None:
            return U, dict(meta, mod="none(no_geom)")
        d_tpl = g["exit"] - g["entry"]
        d_now = (np.asarray(goal_pos, float).ravel()[:3]
                 - np.asarray(cur_pos, float).ravel()[:3])
        nt, nn = float(np.linalg.norm(d_tpl)), float(np.linalg.norm(d_now))
        if nt < 1e-9 or nn < 1e-9:
            return U, dict(meta, mod="none(degenerate)")
        R = _rot_between(d_tpl, d_now)
        s = float(np.clip(nn / nt, clip[0], clip[1])) if amp_scale else 1.0
        Um = np.asarray(U, float).copy()
        Um[:, :3] = (Um[:, :3] @ R.T) * s
        ang = float(np.degrees(np.arccos(np.clip(np.dot(d_tpl / nt, d_now / nn), -1, 1))))
        return Um, dict(meta, mod="dir+amp", rot_deg=round(ang, 1), scale=round(s, 3),
                        d_tpl=np.round(d_tpl, 4).tolist(), d_now=np.round(d_now, 4).tolist())

    # ── 写入全局共享记忆 ────────────────────────────────────
    def save(self):
        if not self.primitives:
            return False
        sh = {}
        if os.path.exists(self.shared_path):
            try:
                sh = json.load(open(self.shared_path))
            except Exception:
                sh = {}
        sh["motor"] = {
            "primitives": [dict(p, template_u=np.round(p["template_u"], 5).tolist(),
                                template_v=np.round(p["template_v"], 5).tolist()) for p in self.primitives],
            "mapping": self.mapping,
            "sharing": {k: v for k, v in self.sharing_stats().items() if k != "per_primitive"},
            "features": FEATS,
            "note": "L2 肌肉记忆的共享抽象层: 从标杆提取'发力/速度/加速度'规律聚成全局基元",
        }
        sh.setdefault("meta", {})
        import datetime
        sh["meta"]["motor_updated"] = datetime.datetime.now().strftime("%m-%d %H:%M")
        json.dump(sh, open(self.shared_path, "w"), ensure_ascii=False, indent=1)
        return True

    def report(self):
        if not self.primitives:
            return "（无标杆可提取）"
        s = self.sharing_stats()
        lines = [f"【运动基元全局记忆】从 {s['n_seg']} 条 L2 标杆提取 → {s['n_prim']} 个共享基元",
                 f"  其中 {s['n_multi_stage']} 个基元被 >1 类技能段共用（=真正的'共享肌肉记忆'）", ""]
        for p in self.primitives:
            f = dict(zip(FEATS, p["feat"]))
            lines.append(f"  基元#{p['id']} {p['name']:<22} 成员{p['n_member']:>2} 段 "
                         f"速度峰 {f['v_peak']:.4f} 加速峰 {f['a_peak']:.4f} 发力峰 {f['f_peak']:.3f} "
                         f"时长 {f['dur']:.0f}帧 离散度 {p['spread']:.4f}")
            lines.append(f"      覆盖技能: {'/'.join(p['stages'])}")
        lines += ["", f"  参数压缩: 原始 {s['raw_values']} 个数值 → 基元库+调制 {s['simplified_values']} "
                      f"(压缩 {s['compression']}×)"]
        for st, m in self.mapping.items():
            lines.append(f"  {st:<4} → 基元#{m['primitive']} ({m['dur']:.0f}帧, 幅值{m['amp']:.3f}, {m['n_src']}源)")
        return "\n".join(lines)


if __name__ == "__main__":
    hub = MotorHub().build(k=4)
    print(hub.report())
    ok = hub.save()
    print(f"\n{'✅ 已写入 data/shared_memory.json 的 motor 层' if ok else '❌ 写入失败'}")
