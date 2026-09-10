#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全局记忆中枢 (Global Memory Hub) — 共享编码 + 三层记忆体 + 二态意图语法

老倪构思 (2026-09-10):
  "就像运动员肌肉强健, 高难度动作看一遍就会 —— 因为他对自己四肢的运动非常熟悉;
   歌唱家听一遍就能记住新歌 —— 因为她对韵律非常熟悉。因为熟悉, 所以肯定有一个
   **先验的记忆结构**, 遇到相似的目标就会马上掌握。现在的 L2 已掌握的技能, 对相似操作
   应该能马上学会。L4 物理规律记忆 / L3 流程记忆 / L2 肌肉记忆, 各层记忆要融会贯通。"

────────────────────────────────────────────────────────────────
理论映射
────────────────────────────────────────────────────────────────
1) **INTACT Fig.1 的图同构二态语法** (粘贴的论文原文):
   一个 **共享编码器** + 任务特定预测器对; 局部调用与目标调用走**同一输入语法**:
     · attached  local intent :  z_{t+1} − z_t     (逐步: 下一步往哪走)
     · detached  goal  intent :  s_g(z_g) − z_t    (整段: 目标在哪)
   推理时 goal 条件调用**直接出 action chunk** → search-free(不用测试时搜索)。
   → 我们落地: 同一套"意图坐标 Δz"驱动三层记忆, 不各说各话。

2) **运动图式 / 元学习 (learn-to-learn)**:
   "熟悉"的数学含义 = 存在一个**共享先验表示**, 新任务只需在其中"定位"(检索/最近邻),
   无需从零学。这正是"看一遍就会"—— 不是模型变神了, 而是记忆结构把新任务归到了已知类。

3) **三层记忆分工 (显式可审计, 拒绝黑盒)**
   L4 物理规律记忆: 这个动作会有什么后果? (可行性/接触/卡阻/恢复)
   L3 流程记忆:     这件事该分几段、什么顺序、何时切换?
   L2 肌肉记忆:     每一段该怎么发力、多快、多稳? (运动基元 + 调制, 见 motor_hub)

────────────────────────────────────────────────────────────────
统一意图坐标 (融会贯通的关键)
────────────────────────────────────────────────────────────────
一切以 **(阶段 stage, 意图位移 Δz = 目标 − 当前)** 为**公共键**, 三层各查各的表,
再回来做**一致性校验**: 三层互相印证 = 高置信(可直接执行); 互相矛盾 = 需要探索。
"""
import json
import os

import numpy as np

ROOT = os.environ.get("ZMAX_ROOT", "/home/ubuntu/lerobot-smolvla-lew")
SHARED = os.path.join(ROOT, "data", "shared_memory.json")
MUSCLE = os.path.join(ROOT, "data", "muscle_memory.json")
STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入"]
# 39D 引擎观测布局 (实测): [0:3]手 [3]gripper [4:7]速度v [7:10]peg [10:13]goal ...
O_HAND, O_GRIP, O_VEL, O_PEG, O_GOAL = slice(0, 3), 3, slice(4, 7), slice(7, 10), slice(10, 13)


def _nstage(s):
    return str(s).replace("阶段 ", "").split("·")[0].strip()


def _load(p):
    try:
        return json.load(open(p))
    except Exception:
        return {}


class GlobalMemory:
    """全局记忆: 共享编码(显式) + L4/L3/L2 三层记忆体 + 二态意图语法 + 一致性校验。"""

    def __init__(self, shared_path=SHARED, muscle_path=MUSCLE):
        self.shared_path, self.muscle_path = shared_path, muscle_path
        self.sh = _load(shared_path)
        self.muscle = _load(muscle_path)
        self._build_intent_index()
        self._build_layer_tables()

    # ══════════════════════════════════════════════════════════
    # ① 共享编码器 (显式版): 观测 → 统一表示
    #    对应 INTACT 的 shared encoder —— 三层记忆共用同一个"看世界"的方式
    # ══════════════════════════════════════════════════════════
    @staticmethod
    def encode(obs):
        """39D 引擎观测 → 统一表示 dict。三层都用它, 天然对齐。"""
        o = np.asarray(obs, float).ravel()
        return {
            "hand": o[O_HAND].copy(),
            "gripper": float(o[O_GRIP]),
            "vel": o[O_VEL].copy(),
            "peg": o[O_PEG].copy(),
            "goal": o[O_GOAL].copy(),
        }

    # ══════════════════════════════════════════════════════════
    # ② 二态意图语法 (INTACT Fig.1 图同构): 同一个 Δz, 两种取法
    # ══════════════════════════════════════════════════════════
    @staticmethod
    def local_intent(z_prev, z_now):
        """attached local intent: z_{t+1} − z_t —— 逐步(肌肉记忆用)。"""
        a, b = np.asarray(z_prev, float), np.asarray(z_now, float)
        return (b - a)[:3]

    @staticmethod
    def goal_intent(z_now, z_goal, scale=1.0):
        """detached goal intent: s_g(z_g) − z_t —— 整段(流程/物理用)。"""
        return (np.asarray(z_goal, float)[:3] - np.asarray(z_now, float)[:3]) * scale

    # ══════════════════════════════════════════════════════════
    # ③ 建索引: (阶段, Δz) → 三层各自的记忆
    # ══════════════════════════════════════════════════════════
    def _build_intent_index(self):
        """从肌肉标杆的 io 契约取每段"意图位移" (exit − entry) —— 这是公共键。"""
        self.intents = {}          # stage -> list[(dz(3), seed, key)]
        for key, e in self.muscle.items():
            if not isinstance(e, dict) or e.get("champ_u") is None:
                continue
            seed_s, _, stage = key.partition("|")
            io = e.get("io") or {}
            entry = np.asarray(io.get("entry", [np.nan] * 3), float)
            exit_ = np.asarray(io.get("exit", [np.nan] * 3), float)
            if not (np.isfinite(entry).all() and np.isfinite(exit_).all()):
                continue
            self.intents.setdefault(_nstage(stage), []).append((exit_ - entry, seed_s, key))

    def _build_layer_tables(self):
        l2 = (self.sh.get("l2") or {}).get("muscle") or {}
        self.l2_skills = l2.get("skills") or {}
        self.l3_flows = (self.sh.get("l3") or {}).get("flows") or []
        self.l3_shadow = (self.sh.get("l3") or {}).get("shadow") or []
        self.l4_predict = (self.sh.get("l4") or {}).get("predict") or []
        self.links = self.sh.get("links") or []
        self.motor = self.sh.get("motor") or {}

    # ══════════════════════════════════════════════════════════
    # ④ 三层联合查询 (融会贯通的核心)
    # ══════════════════════════════════════════════════════════
    def query(self, stage, dz=None, k=1):
        """给定阶段(+可选意图位移) → 三层记忆的联合视图 + 一致性校验。"""
        st = _nstage(stage)
        out = {"stage": st, "l4": None, "l3": None, "l2": None, "consistency": {}}

        # ── L2 肌肉记忆: 该段怎么发力 ──
        mmap = (self.motor.get("mapping") or {}).get(st)
        if mmap:
            prim = next((p for p in self.motor.get("primitives", []) if p.get("id") == mmap["primitive"]), None)
            out["l2"] = {"primitive": mmap["primitive"],
                         "name": (prim or {}).get("name", "?"),
                         "dur": mmap.get("dur"), "amp": mmap.get("amp"),
                         "n_src": mmap.get("n_src"),
                         "template_u": (prim or {}).get("template_u")}

        # ── L3 流程记忆: 该段处于什么顺序里 ──
        flows = [f for f in self.l3_flows if st in (_as_list(f.get("stages")) or [])]
        if flows:
            ok = sum(1 for f in flows if str(f.get("done")) in ("True", "true"))
            seqs = [_as_list(f.get("stages")) for f in flows]
            out["l3"] = {"n_flow": len(flows), "n_done": ok,
                         "done_rate": round(ok / len(flows), 3),
                         "example_seq": next((s for s in seqs if s), []),
                         "avg_steps": round(float(np.mean([_f(f.get("steps")) for f in flows])), 0)}
        sh = [s for s in self.l3_shadow if st in (s.get("shadow") or {})]
        if sh:
            seg = sh[0]["shadow"][st]
            out["l3"] = dict(out["l3"] or {}, shadow_du=seg.get("du_mean"),
                             shadow_dx=seg.get("dx_mean") if "dx_mean" in seg else None,
                             shadow_n=seg.get("n"))

        # ── L4 物理规律记忆: 这类任务的物理可行性/预测残差 ──
        if self.l4_predict:
            maes = [np.asarray(_as_list(f.get("mae")) or [0, 0, 0, 0, 0, 0], float) for f in self.l4_predict]
            M = np.stack([m for m in maes if m.size >= 3])
            if M.size:
                out["l4"] = {"n": len(M), "mae_mean": np.round(M.mean(0), 4).tolist(),
                             "mae_p90": np.round(np.percentile(M, 90, axis=0), 4).tolist(),
                             "feasible_ratio": round(float((M.max(1) < 0.15).mean()), 3)}

        # ── 意图位移最近邻 (公共键) ──
        if dz is not None and st in self.intents:
            cand = self.intents[st]
            d = [float(np.linalg.norm(np.asarray(dz, float)[:3] - c[0])) for c in cand]
            j = int(np.argmin(d))
            out["intent_match"] = {"dz_query": np.round(np.asarray(dz, float)[:3], 4).tolist(),
                                   "dz_nearest": np.round(cand[j][0], 4).tolist(),
                                   "dist": round(d[j], 4), "src": cand[j][2]}

        # ── 一致性校验 (三层互相印证 = "融会贯通"的量化) ──
        c = {}
        c["l2_ready"] = out["l2"] is not None
        c["l3_ready"] = out["l3"] is not None
        c["l4_ready"] = out["l4"] is not None
        if out["l3"] and out["l3"].get("done_rate") is not None:
            c["l3_reliable"] = out["l3"]["done_rate"] >= 0.5
        if out["l4"] and out["l4"].get("feasible_ratio") is not None:
            c["l4_feasible"] = out["l4"]["feasible_ratio"] >= 0.5
        c["score"] = round(sum(1 for kk in ("l2_ready", "l3_ready", "l4_ready") if c[kk]) / 3.0, 2)
        # 判定必须基于**证据**而非"有没有数据": L3 成功率与 L4 可行率都要达标才算可靠
        _l3_ok = bool(c.get("l3_reliable"))
        _l4_ok = bool(c.get("l4_feasible"))
        if c["l2_ready"] and _l3_ok and _l4_ok:
            c["verdict"] = "三层齐备且可靠 → 可直接执行 (看一遍就会)"
        elif c["l2_ready"] and (_l3_ok or _l4_ok):
            c["verdict"] = "部分可靠 → 可执行, 需影子监控"
        elif c["l2_ready"]:
            c["verdict"] = "仅有肌肉记忆 → 可试跑, 流程/物理未证实"
        else:
            c["verdict"] = "记忆缺失 → 需在线探索"
        out["consistency"] = c
        return out

    # ══════════════════════════════════════════════════════════
    # ⑤ 一次就位: goal intent → 直接出计划 (search-free, 对应 INTACT 直控)
    # ══════════════════════════════════════════════════════════
    def plan(self, obs_now, goal_xyz, stage_plan=None):
        """新目标 → 借三层记忆直接给计划: 段序列 + 每段的基元/时长/幅值。"""
        z = self.encode(obs_now)
        dz = self.goal_intent(z["hand"], goal_xyz)
        stages = stage_plan or STAGES[:6]
        plan, conf = [], []
        for st in stages:
            q = self.query(st, dz)
            plan.append({"stage": st, "l2": q["l2"], "l3_done_rate": (q["l3"] or {}).get("done_rate"),
                         "verdict": q["consistency"]["verdict"]})
            conf.append(q["consistency"]["score"])
        return {"dz": np.round(dz, 4).tolist(), "n_stage": len(stages),
                "plan": plan, "confidence": round(float(np.mean(conf)), 3) if conf else 0.0,
                "source": "全局记忆检索 (无梯度更新, search-free)"}

    # ══════════════════════════════════════════════════════════
    # ⑥ 固化为经验 (成功后写回, 让下一次"更熟悉")
    # ══════════════════════════════════════════════════════════
    def absorb(self, seed, mode, steps, stages, skills, l4_mae, cause="run", note=""):
        self.sh.setdefault("links", [])
        self.sh["links"].append({"seed": int(seed), "mode": mode, "cap": "", "steps": int(steps),
                                 "skills": skills, "cause": cause,
                                 "l4_mae": [round(float(x), 4) for x in l4_mae], "note": note})
        import datetime
        self.sh.setdefault("meta", {})["hub_updated"] = datetime.datetime.now().strftime("%m-%d %H:%M")
        json.dump(self.sh, open(self.shared_path, "w"), ensure_ascii=False, indent=1)
        return len(self.sh["links"])

    # ══════════════════════════════════════════════════════════
    # ⑦ 体检报告
    # ══════════════════════════════════════════════════════════
    def report(self):
        L = ["【全局记忆中枢 · 三层体检】"]
        s = self.motor.get("sharing") or {}
        L.append(f"  L2 肌肉记忆 : {s.get('n_prim', 0)} 个共享运动基元 / {s.get('n_seg', 0)} 条标杆 "
                 f"(参数量压缩 {s.get('compression', 0)}×, {s.get('n_multi_stage', 0)} 个基元被多技能共用)")
        L.append(f"  L3 流程记忆 : 流程记录 {len(self.l3_flows)} 条 · 影子对比 {len(self.l3_shadow)} 条")
        dr = [str(f.get('done')) in ('True', 'true') for f in self.l3_flows]
        L.append(f"                成功 {sum(dr)}/{len(dr)} ({round(100*sum(dr)/max(len(dr),1))}%)")
        L.append(f"  L4 物理规律 : 预测记录 {len(self.l4_predict)} 条")
        L.append(f"  跨层链接    : {len(self.links)} 条 (seed → 技能链 → L4 残差)")
        L.append("")
        L.append(f"  {'阶段':<5} {'L2基元':<24} {'L3成功率':>8} {'L4可行':>7}  判定")
        for st in STAGES:
            q = self.query(st)
            l2n = (q["l2"] or {}).get("name", "—")
            l3r = (q["l3"] or {}).get("done_rate")
            l4f = (q["l4"] or {}).get("feasible_ratio")
            L.append(f"  {st:<5} {l2n:<24} "
                     f"{(f'{l3r:.0%}' if l3r is not None else '—'):>8} "
                     f"{(f'{l4f:.0%}' if l4f is not None else '—'):>7}  {q['consistency']['verdict']}")
        return "\n".join(L)


def _as_list(v):
    """字段可能是真 list / JSON 字符串 / numpy 标量 (历史记录格式不统一)。"""
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        return list(v)
    if isinstance(v, str):
        t = v.strip()
        if t.startswith("[") or t.startswith("("):
            try:
                return list(eval(t))  # noqa: S307 - 自有数据, 仅解析列表字面量
            except Exception:
                return None
        return [t] if t else []
    return [v]


def _f(v):
    try:
        return float(v)
    except Exception:
        return 0.0


if __name__ == "__main__":
    gm = GlobalMemory()
    print(gm.report())
    print("\n—— 二态意图语法演示 (同一 Δz, 两种调用) ——")
    z_now = np.array([0.0, 0.60, 0.19])
    z_next = np.array([0.0, 0.58, 0.19])
    z_goal = np.array([-0.27, 0.55, 0.13])
    print(f"  attached 局部意图 (z_t+1 − z_t): {gm.local_intent(z_now, z_next)}")
    print(f"  detached 目标意图 (z_g − z_t)  : {np.round(gm.goal_intent(z_now, z_goal), 4)}")
    print("\n—— 一次就位 plan() ——")
    obs39 = np.zeros(39)
    obs39[O_HAND] = z_now
    obs39[O_GRIP] = 1.0
    p = gm.plan(obs39, z_goal)
    print(f"  Δz={p['dz']} · {p['n_stage']} 段 · 置信 {p['confidence']} · {p['source']}")
    for r in p["plan"]:
        print(f"    {r['stage']:<4} 基元 {(r['l2'] or {}).get('name', '—'):<24} "
              f"L3成功率 {r['l3_done_rate']} → {r['verdict']}")
