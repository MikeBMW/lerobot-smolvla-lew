#!/usr/bin/env python3
"""🎛 原子技能 → W²-VLA Token 条件 JSON 生成器 (2026-08-09 老倪)

参考 W²-VLA "潜在建模 Token (Latent Modeling Tokens)" 思想:
  不直接把文本喂给动作预测器, 而是通过一组"潜在建模 Token"作为 VLM 与
  动作预测器之间的紧凑接口。

每条原子技能 → 6 元组 Token 序列:
  [SKILL_ID] [SEMANTIC] [SCENE] [STAGE] [MATURITY] [CoT]

分类: 9 大类 (NPO近封装光学 / XPO高密可插拔光学 / 操作动作 / 感知定位 /
       视觉检测 / 载具物流 / 移动导航 / 安全集成 / 学习泛化)

输出: flows/atomic_skill_tokens.json
  {
    "format": "zmax-skill-tokens",
    "categories": [...9 大类...],
    "skills": [{
        "skill_id": "NPO008",
        "category": "NPO近封装光学",
        "name": "光电芯片精密贴装/低力落位",
        "tokens": {
            "id": "[SKILL_NPO008]",
            "semantic": "[SEM_光电芯片_精密贴装_微米级_低力]",
            "scene": "[SCENE_光电芯片_基板_贴装工装]",
            "stage": "[STAGE_P1]",
            "maturity": "[MAT_1_5]",
            "cot": "[CoT_精密贴装_低力落位_微米级对准]"
        },
        "dimensions": {"id": 64, "semantic": 384, "scene": 32, "stage": 16, "maturity": 8, "cot": 256},
        "action": "pick",
        "gate": 0.5,
        "desc": "完整描述"
    }, ...]
  }
"""
import json
import re
import os

RAW = os.path.join(os.path.dirname(__file__), "atomic_skills_raw.json")
COND = os.path.join(os.path.dirname(__file__), "atomic_skills_conditions.json")
OUT = os.path.join(os.path.dirname(__file__), "atomic_skill_tokens.json")

# 阶段 → token (工艺阶段)
STAGE_RULES = [
    ("P1", ["P1", "核心", "MVP"]),
    ("P2", ["P2", "验证"]),
    ("P3", ["P3", "中试"]),
    ("P4", ["P4", "量产"]),
    ("PX", []),  # 兜底
]

# 成熟度 → token
def maturity_token(m):
    try:
        v = float(m)
        return f"[MAT_{v:g}]"
    except (TypeError, ValueError):
        return "[MAT_1_5]"

def parse_stage(phase):
    if not phase:
        return "[STAGE_PX]"
    for key, kws in STAGE_RULES:
        if key == "PX":
            continue
        if key in phase or any(k in phase for k in kws):
            return f"[STAGE_{key}]"
    return "[STAGE_PX]"

def sem_tokens(name, definition, input_cond):
    """语义 token: 技能名本身拆短语 + 定义去停用词 (取前6个语义块)"""
    STOP = {"进行", "对", "将", "与", "及", "在", "以", "从", "为", "实现", "识别",
            "检测", "验证", "输出", "输入", "完成", "基于", "通过", "确认", "包括",
            "等", "该", "其", "并", "或"}
    words = []
    # 1) 技能名按 / 或 空格拆 (如 "光电芯片精密贴装/低力落位" → 2段)
    for seg in re.split(r"[\/、\s]+", name):
        seg = seg.strip()
        if len(seg) >= 2 and seg not in words:
            words.append(seg)
    # 2) 定义中补: 长短语 (6-12字) 去停用词后
    dfn_clean = definition or ""
    for m in re.findall(r"[\u4e00-\u9fff]{6,12}", dfn_clean):
        if m not in STOP and m not in words and len(words) < 6:
            words.append(m)
    return words[:6]

def cot_keywords(category, name):
    """CoT 关键词: 按分类生成结构化操作线索"""
    CAT_COT = {
        "NPO近封装光学": ["精密对准", "微米级", "低力落位"],
        "XPO高密可插拔光学": ["键位极性", "端口防错", "插拔柔顺"],
        "操作动作": ["力阈值", "柔顺插入", "扭矩控制"],
        "感知定位": ["粗定位", "基准识别", "手眼变换"],
        "视觉检测": ["显微复检", "缺陷分级", "视觉判定"],
        "载具物流": ["料盘识别", "载具对接", "柔性搬运"],
        "移动导航": ["路径规划", "避障", "站点对接"],
        "安全集成": ["安全区", "碰撞检测", "急停"],
        "学习泛化": ["迁移学习", "域适应", "零样本"],
    }
    kws = CAT_COT.get(category, ["结构化执行", "条件满足", "动作完成"])
    return kws[:3]

def build():
    raw = json.load(open(RAW, encoding="utf-8"))
    conds = json.load(open(COND, encoding="utf-8"))
    cond_by_id = {c["skill_id"]: c for c in conds}

    categories = []
    seen = set()
    out_skills = []
    for s in raw:
        sid = s["id"]
        cat = s.get("category", "未分类")
        if cat not in seen:
            seen.add(cat)
            categories.append(cat)
        name = s.get("name", "")
        dfn = s.get("definition", "") or ""
        ic = s.get("input_cond", "") or ""
        sem = sem_tokens(name, dfn, ic)
        stage = parse_stage(s.get("phase", ""))
        mat = maturity_token(s.get("maturity_now", ""))
        cot_kws = cot_keywords(cat, name)
        cond = cond_by_id.get(sid, {})
        skill = {
            "skill_id": sid,
            "category": cat,
            "name": name,
            "tokens": {
                "id": f"[SKILL_{sid}]",
                "semantic": "[SEM_" + "_".join(sem[:6]) + "]",
                "scene": "[SCENE_" + "_".join((s.get("scene", "") or "").replace("/", "_").split("_")[:3]) + "]",
                "stage": stage,
                "maturity": mat,
                "cot": "[CoT_" + "_".join(cot_kws) + "]",
            },
            "dimensions": {"id": 64, "semantic": 384, "scene": 32, "stage": 16, "maturity": 8, "cot": 256},
            "action": cond.get("action", "operate"),
            "modalities": cond.get("modalities", []),
            "encoding": cond.get("encoding", {}),
            "gate": 0.5,
            "desc": dfn[:120] or name,
        }
        out_skills.append(skill)

    flow = {
        "format": "zmax-skill-tokens",
        "version": "1.0",
        "generated": "2026-08-09",
        "reference": "W²-VLA Latent Modeling Tokens",
        "categories": categories,
        "skills": out_skills,
    }
    json.dump(flow, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    from collections import Counter
    print(f"✅ 生成 {len(out_skills)} 条技能 Token → {OUT}")
    print(f"   分类 {len(categories)}: {dict(Counter(s['category'] for s in out_skills))}")
    ex = out_skills[0]
    print(f"   示例 {ex['skill_id']}: {ex['tokens']}")

if __name__ == "__main__":
    build()
