# -*- coding: utf-8 -*-
"""档位契约 (levels) —— L2/L3/L4/L5 各自"必须还能干的事", 以及它的可核查判据。

2026-09-28 迁移时立的规矩: 节点逻辑可以搬、可以重组, 但**这四层的功能不许掉** ——
所以每层都写死: ①画布上属于它的节点 ②每个节点必须能落到一条已注册的逻辑 ③该层的后端入口必须可导入。
`check()` 就是把这三条真跑一遍; 迁移前后各跑一次, 数字必须一致。
"""
from . import flows, paths
from .registry import match_node

# ── 四层 + 元层: 名称 / 该层"必须还能干的事" ────────────────────────────
LEVELS = {
    "L2": {"name": "基础功能 (分段感知 · 融合 · 小模型控制 · 状态机 · 原子技能 · 执行)",
           "must": ["分段感知(检测/触觉/2D→3D/质量)", "传感器融合 → 43D 状态", "估计/预测/校正/前馈",
                    "动作调制 + 安全限幅", "原子技能 SK01-08 可执行", "执行器 → 物理闭环",
                    "肌肉记忆 固化→直通"]},
    "L3": {"name": "连续功能 (长程序列规划 · 技能编排 · 海马体记忆 · VLM+Flow-Matching)",
           "must": ["长程序列规划(场景理解驱动)", "技能序列编排", "跨段技能序列入库/复用",
                    "VLM 编码 + Flow-Matching 连续动作输出"]},
    "L4": {"name": "自主安全功能 (工作安全 + 物理世界导航 · 档位 · 流形世界模型 · 筹划)",
           "must": ["工作安全(INTACT)", "物理世界导航", "能力档位切换", "标定/流形世界模型",
                    "恢复策略/筹划入库", "势场联络 (−∇Φ)"]},
    "L5": {"name": "场景理解 + 自动标注 (大模型层 · 任务/编排/记忆中枢)",
           "must": ["视觉语言场景理解(VLM/DeepSeek)", "自动标注 → 监督 L2/L3/L4",
                    "任务指令解析(MES/自然语言)", "工程记忆/技能库", "标注→自动训练闭环"]},
}

# 画布上按"行带(row_bg)"定位档位; 这些关键字覆盖带外的特例节点
OVERRIDE = {
    "ss_l5": "L5", "n_vlm_llm": "L5", "n_dsvl": "L5", "ssllm": "L5", "ssreason": "L5",
    "ssskill": "L3", "ss_mem_l3": "L3", "ss_lora_l3": "L3", "ssvlm": "L3", "ssdec": "L3",
    "sscap": "L4", "ssintact": "L4", "ssintact_dec": "L4", "ss_mem_l4": "L4", "ss_lora_l4": "L4",
    "ss_mem_l2": "L2", "n_l2_muscle": "L2", "ss_moe": "L2", "n_board_frame": "L2",
    "ss_mem_field": "L4", "ss_mem_share": "L4", "n_intent_bundle": "L4", "n_intent_direct": "L4",
}

META_BANDS = ("数据源", "验证层", "可视化层", "记忆")      # 跨层/元层, 不计入单层契约


def band_map(canvas=None):
    """节点 id → 档位 (按所属行带的名称判定; 带外的用 OVERRIDE)"""
    d = canvas or flows.load_canvas(validate=False)
    if isinstance(d, tuple):
        d = d[0]
    bands = [n for n in (d.get("nodes") or []) if n.get("type") in ("bg", "row_bg") and (n.get("w") or 0) > 500]
    out = {}
    for n in d.get("nodes") or []:
        if n.get("type") in ("bg", "row_bg"):
            continue
        nid = n.get("id")
        if nid in OVERRIDE:
            out[nid] = OVERRIDE[nid]
            continue
        y = n.get("y") or 0
        hit = None
        for b in bands:
            by, bh = b.get("y") or 0, b.get("h") or 0
            if by <= y <= by + bh:
                nm = str(b.get("name") or "")
                if "L2" in nm:
                    hit = "L2"
                elif "L3" in nm:
                    hit = "L3"
                elif "L4" in nm:
                    hit = "L4"
                elif "大模型层" in nm:
                    hit = "L5"
                elif any(k in nm for k in META_BANDS):
                    hit = "meta"
                if hit:
                    break
        out[nid] = hit or "?"
    return out


def level_nodes(level, canvas=None, band=None):
    bm = band or band_map(canvas)
    return [k for k, v in bm.items() if v == level]


def check(canvas=None, verbose=True):
    """三层判据全跑一遍: ①节点在画布上 ②节点能落到已注册逻辑 ③后端入口可导入"""
    d = canvas or flows.load_canvas(validate=False)
    if isinstance(d, tuple):
        d = d[0]
    names = {n.get("id"): str(n.get("name") or "") for n in (d.get("nodes") or [])}
    bm = band_map(d)
    res = {"canvas": flows.stats(d), "levels": {}, "problems": []}
    for lv in ("L2", "L3", "L4", "L5"):
        ids = level_nodes(lv, band=bm)
        miss_logic = [i for i in ids if not match_node(names.get(i, ""))]
        res["levels"][lv] = {"nodes": len(ids), "ids": ids, "no_logic_key": miss_logic,
                             "must": LEVELS[lv]["must"]}
        if miss_logic:
            res["problems"].append("%s: %d 个节点没有对应逻辑 key: %s" % (lv, len(miss_logic), miss_logic[:5]))
    res["unassigned"] = [k for k, v in bm.items() if v == "?"]
    res["meta"] = [k for k, v in bm.items() if v == "meta"]
    if verbose:
        print("画布: %s" % res["canvas"])
        for lv, v in res["levels"].items():
            print("  %s · %-58s 节点 %2d · 无逻辑 %d" % (lv, LEVELS[lv]["name"][:58], v["nodes"], len(v["no_logic_key"])))
        print("  未归层节点 %d: %s" % (len(res["unassigned"]), res["unassigned"][:8]))
        print("  元层/跨层 %d: %s" % (len(res["meta"]), res["meta"][:8]))
        print("  问题: %s" % (res["problems"] or "无"))
    return res


if __name__ == "__main__":
    check()
