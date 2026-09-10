#!/usr/bin/env python3
"""🧠 muscle_memory.py — 原子技能肌肉记忆 (2026-09-07 老倪: 仿人类小脑, 越练越顺)

核心思想 (仿生):
  大脑皮层(决策层: MLP前馈+卡尔曼+调制器) 每步精算 → 慢而准
  小脑(肌肉记忆) 观察重复动作 → 稳定后固化标杆 u_exec 序列 → 快通道整段重放
  (跳过决策精算 = "练熟的动作小脑直接给力"); 持续练习 → 标杆指数融合 → 越练越顺

机制 (阶段级, 按 seed 场景分桶):
  1. 观察期: 每轮记录每个技能段 (stage) 的实际 u_exec 序列 + 段轨迹
  2. 固化判定: 同 (seed, stage) 连续成功 ≥ MIN_OK_RUNS 次 → 固化标杆
  3. 标杆模板: 各成功段轨迹对齐后逐点平均 → 平滑去噪 (数据增强)
  4. 快通道: 固化后 run() 预取整段标杆 u_exec → 逐帧重放 (小脑接管前馈)
     (安全链 decide/反馈/饱和限幅全保留 — 异常时反馈仍可修正)
  5. 持续更新: 每次成功新轨迹与标杆指数融合 → 渐进优化 (练得越多越顺)

存储: data/muscle_memory.json (每 seed+stage 一桶: 样本数/标杆)
"""
import json
import os
import numpy as np

# 配置
MIN_OK_RUNS = 3          # 同技能连续成功 ≥3 次才固化 (人练 3 遍成形)
E_MERGE = 0.3            # 新成功轨迹融合进标杆的权重 (指数滑动, 越练越精)
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "data")

# 8 阶段序 (固化只认成功完成的段)
STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]


class MuscleMemory:
    """原子技能肌肉记忆 — 单例 (模块级 _INSTANCE, 引擎/GUI 共用)
    v2: 标杆记录 u_exec 序列 (小脑直接给力 = 重放实际执行指令);
    x 轨迹仅存证据/展示/未来状态匹配用。"""

    def __init__(self, path=None):
        self.path = path or os.path.join(DATA_DIR, "muscle_memory.json")
        self.db = {}          # (seed, stage) -> {n_ok, champ_u: 标杆u序列, champ_x: 标杆x序列}
        self._cur = None      # 本轮记录缓冲
        self._load()

    # ── 持久化 ──
    def _load(self):
        try:
            if os.path.isfile(self.path):
                with open(self.path) as f:
                    raw = json.load(f)
                for k, v in raw.items():
                    seed, stg = k.split("|")
                    entry = {"n_ok": int(v.get("n_ok", 0)),
                             "champ_u": (np.asarray(v["champ_u"], dtype=float)
                                         if v.get("champ_u") else None),
                             "champ_x": (np.asarray(v["champ_x"], dtype=float)
                                         if v.get("champ_x") else None)}
                    self.db[(int(seed), stg)] = entry
        except Exception:
            pass

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            raw = {}
            for (seed, stg), e in self.db.items():
                raw[f"{seed}|{stg}"] = {
                    "n_ok": e["n_ok"],
                    "champ_u": (e["champ_u"].tolist() if e["champ_u"] is not None else None),
                    "champ_x": (e["champ_x"].tolist() if e["champ_x"] is not None else None),
                }
            with open(self.path, "w") as f:
                json.dump(raw, f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    # ── 本轮记录 ──
    def begin_episode(self, seed):
        self._cur = {"seed": int(seed), "seg_u": {}, "seg_x": {}, "done": False}

    def feed(self, stage, x, u_exec):
        """每帧喂当前阶段 + 手位置 + 实际下发 u_exec → 累积该段轨迹"""
        if self._cur is None:
            return
        st = str(stage).replace("阶段 ", "").split("·")[0].strip()
        if st not in STAGES:
            return
        seg_u = self._cur["seg_u"].setdefault(st, [])
        seg_x = self._cur["seg_x"].setdefault(st, [])
        if len(seg_u) < 500:
            seg_u.append([round(float(v), 6) for v in np.asarray(u_exec).ravel()[:4]])
            seg_x.append([round(float(v), 6) for v in np.asarray(x).ravel()[:3]])

    def end_episode(self, success):
        """本轮结束 → 成功轮把完整段提交 (固化/精进); 失败轮不固化"""
        if self._cur is None:
            return
        seed = self._cur["seed"]
        seg_u = self._cur["seg_u"]
        seg_x = self._cur["seg_x"]
        self._cur = None
        if not success:
            return {"seed": seed, "learned": 0, "msg": "本轮未完成 — 失败不固化"}
        learned = 0
        report = []
        for st in STAGES:
            if st not in seg_u or len(seg_u[st]) < 3:
                continue
            u = np.asarray(seg_u[st], dtype=float)
            x = np.asarray(seg_x[st], dtype=float)
            key = (seed, st)
            e = self.db.setdefault(key, {"n_ok": 0, "champ_u": None, "champ_x": None})
            e["n_ok"] += 1
            if e["champ_u"] is None:
                if e["n_ok"] >= MIN_OK_RUNS:
                    # 只存最近一次 (固化基准) — 真实化多轮物理微差, 用最近成功轮作标杆
                    e["champ_u"] = u
                    e["champ_x"] = x
                    learned += 1
                    report.append(f"SK{STAGES.index(st)+1:02d}{st}固化(练{e['n_ok']}次)")
            else:
                # 已有标杆 → 指数融合 (数据增强: 平滑去噪, 越练越顺)
                e["champ_u"] = MuscleMemory._merge(e["champ_u"], u, E_MERGE)
                e["champ_x"] = MuscleMemory._merge(e["champ_x"], x, E_MERGE)
                learned += 1
                report.append(f"SK{STAGES.index(st)+1:02d}{st}精进")
        if learned:
            self.save()
        return {"seed": seed, "learned": learned, "msg": "; ".join(report)}

    # ── 轨迹处理 (数据增强核心) ──
    @staticmethod
    def _merge(champ, new, alpha):
        """指数融合: champ ← (1-α)champ + α·new (逐点对齐, 末端保持)"""
        L = max(len(champ), len(new))
        out = np.zeros((L, champ.shape[1] if champ.ndim > 1 else 1))
        for i in range(L):
            c = champ[min(i, len(champ) - 1)]
            n = new[min(i, len(new) - 1)]
            out[i] = (1 - alpha) * c + alpha * n
        return out

    # ── 快通道: 整段标杆 u_exec (小脑重放) ──
    def get_champ(self, seed, stage):
        """固化标杆查询: 返回 (champ_u, champ_x) 或 (None, None)"""
        st = str(stage).replace("阶段 ", "").split("·")[0].strip()
        e = self.db.get((int(seed), st))
        if e is None or e["champ_u"] is None:
            return None, None
        return e["champ_u"], e["champ_x"]

    def status(self):
        """GUI 展示: 各场景已固化技能数"""
        out = {}
        for (seed, stg), e in self.db.items():
            if e["champ_u"] is not None:
                out.setdefault(str(seed), []).append(f"{stg}(练{e['n_ok']}次)")
        return out


# 模块级单例 (引擎 import 复用同一记忆)
_INSTANCE = None


def get_memory():
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = MuscleMemory()
    return _INSTANCE


# ── CLI 自测 ──
if __name__ == "__main__":
    m = MuscleMemory(path="/tmp/test_muscle.json")
    for ep in range(4):
        m.begin_episode(104)
        for i in range(30):
            noise = (0.002 * (1.0 / (ep + 1))) * np.sin(i)
            m.feed("接近", [0.005 + i * 0.003 + noise, 0.60, 0.19],
                   [0.003 + noise, -0.001, 0.001, 0.0])
        for i in range(20):
            m.feed("对位", [0.09 + i * 0.0002, 0.52, 0.15], [0.0001, -0.002, 0.0, 0.0])
        r = m.end_episode(True)
        print(f"ep{ep+1}: {r['msg'] or '学习'}")
    print("固化状态:", m.status())
    cu, cx = m.get_champ(104, "接近")
    print(f"标杆 u 序列: {None if cu is None else cu.shape} 点")
    print("✅ 肌肉记忆 v2 自测完成")
