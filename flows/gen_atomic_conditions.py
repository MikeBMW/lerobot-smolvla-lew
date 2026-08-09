#!/usr/bin/env python3
"""🎛 原子技能 → 条件编码 生成器 (2026-08-09 老倪: ControlNet 核心思想)

核心思想 (ControlNet):
    原子技能 = 控制条件 (像 ControlNet 的 Canny/深度图 — 结构化控制信号)
    条件编码 = 多模态条件向量 (图像/力/位姿/触觉... 各模态 one-hot + 语义编码)
    注入结构条件节点 (coord_overlay) → latent += proj(cond)×gate
    → 技能条件"控制"VLA 动作生成 (图像是背景, 条件是主线)

输出: flows/atomic_skills_conditions.json
    [{
        "skill_id": "NPO002",
        "skill_name": "NPO精密料盘穴位与满空映射",
        "category": "NPO近封装光学",
        "cond_id": "D001",                    # D = 动态生成条件
        "condition": "料盘穴位满空映射条件",
        "topic": "/dds/cond/npo_tray_map",
        "modalities": ["image", "state_2d"],   # 自动从 input_cond 提取
        "encoding": {"image": 1, "force": 0, "pose": 0, "tactile": 0, "joint": 0, "pointcloud": 0, "temp": 0, "signal": 0},
        "action": "生成穴位地图",
        "gate": 0.5,
        "source": "atomic_skill"
    }, ...]
"""
import json
import re
import os

RAW = os.path.join(os.path.dirname(__file__), "atomic_skills_raw.json")
OUT = os.path.join(os.path.dirname(__file__), "atomic_skills_conditions.json")

# 模态关键词 → 编码位 (ControlNet 多模态条件通道)
MODALITY_RULES = [
    ("image",    ["图", "图像", "视觉", "相机", "显微"]),
    ("force",    ["力", "力矩", "力控", "六维力"]),
    ("pose",     ["位姿", "坐标", "手眼", "6D", "6d", "朝向"]),
    ("tactile",  ["触觉", "触感", "压觉"]),
    ("joint",    ["关节", "机械臂", "轴", "DH"]),
    ("pointcloud", ["点云", "3D", "三维", "扫描"]),
    ("temp",     ["温度", "温控", "测温"]),
    ("signal",   ["信号", "IO", "触发", "到位", "仓", "状态"]),
    ("code",     ["ID", "条码", "二维码", "扫码", "编码"]),
    ("cad",      ["CAD", "图纸", "模型比对"]),
]

# 动作语义 → 动作类型
ACTION_RULES = [
    ("取料", "pick"), ("取", "pick"), ("抓取", "grasp"),
    ("插", "insert"), ("预插", "pre_insert"), ("拔", "extract"),
    ("放", "place"), ("贴", "attach"), ("锁", "screw"),
    ("检测", "inspect"), ("测试", "test"), ("扫码", "scan"),
    ("定位", "locate"), ("对准", "align"), ("压", "press"),
    ("转运", "transfer"), ("搬运", "transfer"), ("装载", "load"),
    ("组装", "assemble"), ("焊接", "weld"), ("涂", "dispense"),
]

def encode_modalities(text):
    """从 input_cond/definition 提取模态编码 (ControlNet 通道)
    固定 11 通道: 10 模态 + state_2d 兜底 (无模态匹配时 state_2d=1)"""
    enc = {m: 0 for m, _ in MODALITY_RULES}
    enc["state_2d"] = 0  # 兜底通道 (固定第 11 位)
    mods = []
    for m, kws in MODALITY_RULES:
        for kw in kws:
            if kw in text:
                enc[m] = 1
                mods.append(m)
                break
    if not mods:
        enc["state_2d"] = 1
        mods.append("state_2d")
    return enc, mods

def encode_action(text):
    """从技能名/定义提取动作类型"""
    for kw, act in ACTION_RULES:
        if kw in text:
            return act
    return "operate"

def gen_cond_id(idx):
    return f"D{idx:03d}"

def build():
    skills = json.load(open(RAW, encoding="utf-8"))
    out = []
    for idx, s in enumerate(skills, 1):
        name = s.get("name", "")
        cat = s.get("category", "")
        ic = s.get("input_cond", "") or ""
        dfn = s.get("definition", "") or ""
        text = ic + " " + dfn + " " + name
        enc, mods = encode_modalities(text)
        action = encode_action(name + " " + dfn)
        cond = {
            "skill_id": s.get("id", f"S{idx:03d}"),
            "skill_name": name,
            "category": cat,
            "cond_id": gen_cond_id(idx),
            "condition": name + "条件",
            "topic": "/dds/cond/" + re.sub(r"[^a-z0-9_]", "_", name.lower())[:40].strip("_"),
            "modalities": mods,
            "encoding": enc,
            "action": action,
            "gate": 0.5,
            "source": "atomic_skill",
            "input_cond": ic[:80],
        }
        out.append(cond)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # 统计
    from collections import Counter
    print(f"✅ 生成 {len(out)} 条条件编码 → {OUT}")
    print("  分类:", dict(Counter(c["category"] for c in out)))
    print("  动作:", dict(Counter(c["action"] for c in out).most_common(8)))
    print("  模态示例:", out[0]["modalities"], out[0]["encoding"])
    return out

if __name__ == "__main__":
    build()
