# -*- coding: utf-8 -*-
"""
══════════════════════════════════════════════════════════════════
🧠🧬 记忆图谱 — 三层记忆的跨层连接 (S1, 2026-09-10 老倪: 意图丛架构落地)
══════════════════════════════════════════════════════════════════
设计文档: docs/design/zmax_intent_bundle_3layer.md

问题: 三层记忆此前是"并列记录"(各写各的条目) → 各自为政, L2 已有的插拔能力
      L3/L4 看不到。本模块提供**连接层**:
  · link()      : 层间链接 (L4 筹划 → L3 流程 → L2 技能) — 写 shared_memory.links
  · recall()    : 意图检索 — 按"阶段序列 + 布局(seed/cap)邻近"在 L3 流程库里找
                  相似经验, 并带出其关联的 L2 技能与 L4 筹划条目
  · skill_io()  : 技能入口/出口契约 (entry/exit 状态 + 夹持相位; S2 采集, 现可能为空)
  · skill_dict(): 技能词典 — {skill → 该技能动作块的 Δz 摘要} (L4 动作基, S2 完善)
  · graph_summary(): 画布/中枢消费的图谱摘要

诚实边界: 意图向量(Δz)相似度检索待 S2/S3 真意图向量接入; 当前检索键 = 阶段序列 + 布局邻近,
          无数据一律返回空 + reason, 不伪造命中。
真源: data/shared_memory.json (memory_store) + data/muscle_memory.json (L2 标杆库)
"""
import json
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 8 段 → 原子技能 id 映射 (与 tools/gui/muscle_memory.py STAGES 同序)
STAGE_TO_SK = {"接近": "SK01", "对位": "SK02", "下降": "SK03", "抓取": "SK04",
               "抬起": "SK05", "转移": "SK06", "插入": "SK07", "完成": "SK08"}
# full 链扩展段 (13 段状态机): 不在 8 技能内 → 标注扩展
EXT_STAGES = ("拔出", "AOI", "AOI转移", "回程", "放下", "接触", "转移", "对准")


def _ms():
    """memory_store (延迟导入, 失败不打断)"""
    try:
        from lerobot.memory import memory_store as ms
        return ms
    except Exception:
        return None


def _muscle():
    """读 L2 标杆库 data/muscle_memory.json"""
    try:
        with open(os.path.join(_ROOT, "data", "muscle_memory.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def stages_to_skills(stages):
    """段序列 → 技能 id 列表 (含扩展段标注)"""
    out = []
    for s in stages or []:
        s2 = str(s).replace("阶段 ", "").split("·")[0].strip()
        if s2 in STAGE_TO_SK:
            out.append(STAGE_TO_SK[s2])
        elif any(e in s2 for e in EXT_STAGES):
            out.append("SK-EXT:" + s2)
        elif s2:
            out.append("?" + s2)
    # 去重保序
    seen, uniq = set(), []
    for k in out:
        if k not in seen:
            seen.add(k)
            uniq.append(k)
    return uniq


def _stages_of(entry):
    return [str(s).replace("阶段 ", "").split("·")[0].strip() for s in (entry.get("stages") or [])]


def stage_similarity(a, b):
    """阶段序列相似度: Jaccard(集合) × 顺序一致率 → [0,1]"""
    sa, sb = set(_stages_of({"stages": a})), set(_stages_of({"stages": b}))
    if not sa or not sb:
        return 0.0
    j = len(sa & sb) / max(len(sa | sb), 1)
    # 顺序一致: 以 a 的顺序为基准看 b 中相对顺序保持率
    la, lb = _stages_of({"stages": a}), _stages_of({"stages": b})
    common = [x for x in la if x in lb]
    if len(common) < 2:
        return j
    idx_b = {x: i for i, x in enumerate(lb)}
    pairs = sum(1 for i in range(len(common) - 1)
               if idx_b[common[i]] < idx_b[common[i + 1]])
    order = pairs / (len(common) - 1)
    return 0.7 * j + 0.3 * order


def recall(stages=None, seed=None, cap=None, k=3, gate=0.35):
    """跨层意图检索: 在 L3 流程库里找与 (阶段序列, 布局) 相似的经验。
    返回 [{"flow":..., "score":..., "skills":[...], "l4":{...}, "reason":...}] (按分降序, 过门限)
    诚实: 库空/相似度不过门 → 空列表 + reason。
    """
    ms = _ms()
    if ms is None:
        return {"hits": [], "reason": "memory_store 不可用"}
    mem = ms.load()
    flows = (mem.get("l3", {}) or {}).get("flows") or []
    preds = (mem.get("l4", {}) or {}).get("predict") or []
    if not flows:
        return {"hits": [], "reason": "L3 流程库为空 (先跑一轮真实化自动入库)"}
    hits = []
    for fl in flows:
        s_sim = stage_similarity(stages or [], fl.get("stages") or []) if stages else 0.5
        # 布局邻近: 同 seed 满分, 同 cap 加分, 否则按 done 优先
        s_seed = 1.0 if (seed is not None and fl.get("seed") == seed) else 0.0
        s_cap = 0.5 if (cap and str(fl.get("cap", "")).lower() == str(cap).lower()) else 0.0
        s_done = 0.3 if fl.get("done") else 0.0
        score = round(0.55 * s_sim + 0.25 * s_seed + 0.1 * s_cap + 0.1 * s_done, 3)
        if score < gate:
            continue
        # 关联 L4 筹划 (同 seed 最近的预测质量)
        l4 = next((p for p in reversed(preds) if p.get("seed") == fl.get("seed")), None)
        hits.append({"flow": fl, "score": score, "skills": stages_to_skills(fl.get("stages")),
                     "l4": l4})
    hits.sort(key=lambda h: -h["score"])
    hits = hits[:k]
    return {"hits": hits,
            "reason": None if hits else f"相似度均 < 门限 {gate} (库 {len(flows)} 轮)"}


def _parse_key(key):
    """标杆库键 '104|接近' → (104, '接近')"""
    s = str(key)
    if "|" in s:
        a, b = s.split("|", 1)
        try:
            return int(a), b
        except Exception:
            return None, b
    return None, s


def skill_io(skill, seed=None):
    """技能入口/出口契约 (S2 采集; 现返回可用信息或明确缺省)"""
    ms = _ms()
    io = {}
    if ms is not None:
        mem = ms.load()
        sk = (((mem.get("l2", {}) or {}).get("muscle") or {}).get("skills") or {})
        io = sk.get(str(skill)) or {}
    lib = _muscle()
    buckets = []
    for key, e in (lib or {}).items():
        s, st = _parse_key(key)
        if STAGE_TO_SK.get(str(st)) == str(skill) or str(st) == str(skill):
            if seed is None or s == seed:
                buckets.append({"seed": s, "stage": st, "n_ok": e.get("n_ok"),
                                "champ_len": (len(e.get("champ_u") or []) or None)})
    return {"skill": skill, "io": io or None,
            "io_reason": None if io else "io 契约未采集 (S2: 固化时记录 entry/exit)",
            "buckets": buckets}


def skill_dict(seed=None):
    """技能词典 (L4 动作基): {skill → Δz 摘要} — 由 L2 标杆 champ_x 差分离线算 (S2 完善)"""
    lib = _muscle()
    out = {}
    for key, e in (lib or {}).items():
        s, st = _parse_key(key)
        if seed is not None and s != seed:
            continue
        sk = STAGE_TO_SK.get(str(st))
        if not sk:
            continue
        cx = e.get("champ_x") or []
        dz = None
        if len(cx) >= 2:
            try:
                a, b = cx[0], cx[-1]
                dz = [round(float(b[i]) - float(a[i]), 5) for i in range(min(3, len(a)))]
            except Exception:
                dz = None
        out.setdefault(sk, {"stage": st, "dz": dz, "n_ok": e.get("n_ok"),
                            "frames": len(cx) or None})
    return out


def intent_direct(dz, seed=None, k=2):
    """🔮 意图直读 (INTACT Direct): 用当前意图向量 Δz 检索技能词典 → 最近技能 (无搜索)
    当前实现 = 技能 Δz 基上的最近邻; 真意图向量相似度待 S2/S3。诚实标注 method。"""
    import time
    t0 = time.perf_counter()
    d = skill_dict(seed=seed)
    if not dz or not d:
        return {"hit": None, "latency_ms": round((time.perf_counter() - t0) * 1e3, 3),
                "reason": "无技能词典或未给 Δz (S2 生成词典)"}
    best, bd = None, None
    for sk, v in d.items():
        if not v.get("dz"):
            continue
        dd = sum((float(dz[i]) - float(v["dz"][i])) ** 2 for i in range(min(3, len(dz), len(v["dz"])))) ** 0.5
        if bd is None or dd < bd:
            best, bd = sk, dd
    return {"hit": best, "dist": round(bd, 5) if bd is not None else None,
            "latency_ms": round((time.perf_counter() - t0) * 1e3, 3),
            "method": "技能Δz基最近邻 (真意图向量检索待 S2/S3)",
            "reason": None if best else "词典里没有带 Δz 的技能"}


def link(flow, skills, cause="run", l4_mae=None, note=""):
    """写层间链接: L4 筹划 → L3 流程 → L2 技能 (委托 memory_store)"""
    ms = _ms()
    if ms is None:
        return False
    if not hasattr(ms, "put_link"):
        return False
    return ms.put_link({"seed": flow.get("seed"), "mode": flow.get("mode"),
                        "cap": flow.get("cap"), "steps": flow.get("steps"),
                        "skills": skills, "cause": cause,
                        "l4_mae": l4_mae, "note": note})


def sync_l2_from_muscle():
    """L2 标杆库 → shared_memory.l2.muscle.skills 摘要同步 (影子写, 供跨层检索/画布)"""
    ms = _ms()
    if ms is None:
        return 0
    lib = _muscle()
    if not lib:
        return 0
    skills = {}
    for key, e in lib.items():
        s, st = _parse_key(key)
        sk = STAGE_TO_SK.get(str(st), str(st))
        rec = skills.setdefault(str(sk), {"stage": st, "seeds": [], "n_ok": 0,
                                          "champ_len": None, "buckets": 0})
        if s is not None and s not in rec["seeds"]:
            rec["seeds"].append(s)
            rec["buckets"] += 1
        rec["n_ok"] = max(rec["n_ok"], e.get("n_ok") or 0)
        L = len(e.get("champ_u") or []) or None
        if L and (rec["champ_len"] is None or L > rec["champ_len"]):
            rec["champ_len"] = L
    mem = ms.load()
    mem.setdefault("l2", {}).setdefault("muscle", {})
    mem["l2"]["muscle"]["skills"] = skills
    mem["l2"]["muscle"]["updated"] = __import__("time").strftime("%m-%d %H:%M")
    ms.save()
    return len(skills)


def graph_summary():
    """图谱摘要 (画布节点/中枢消费): 层计数 + 链接数 + 最近链接 + 技能词典规模"""
    ms = _ms()
    if ms is None:
        return {"ok": False, "reason": "memory_store 不可用"}
    s = ms.summary()
    links = ms.get_links(5) if hasattr(ms, "get_links") else []
    return {"ok": True, "l2": s.get("l2"), "l3": s.get("l3"), "l4": s.get("l4"),
            "meta": s.get("meta"), "n_links": len(ms.get_links(999)) if hasattr(ms, "get_links") else 0,
            "recent_links": links, "skill_dict_size": len(skill_dict())}
