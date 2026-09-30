#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧹 画布结构重构 (2026-09-24, 老倪指令) —— 幂等可复跑

老倪原话: 「L4 光模块插拔链 环境渲染这一层, 位置不合理, 这层删掉, 渲染功能放到最下面的可视化层,
其它必要的功能精简合并到 L4 层, 如果这层的功能没啥用就删掉。L5 的大模型, deepseek flash, 再次检查画布,
不要出现孤立节点, L2 层的功能不要越层升到 L4 层。节点要是进不了系统则删掉该节点, 要保证节点的完备性。
待办任务也要面向节点功能, 例如 MOE 架构这样的改造, 也要显示在状态空间的整个工程里, 作为一个功能节点;
MOE 是不是放在大模型层更合理? L4 和 L3 层的 LoRA 微调节点需要显示在画布上。」

本脚本做 8 件事 (全部按名字定位, 因为画布加载会重映射 id):
  ① 删「🌍 L4 · 光模块插拔链」行带 (4 个节点拆解安置, 见 ②)
  ② swds/swvideo → 🔭 可视化层 (渲染功能归可视化); swintact/swworld → 🏆 L4 专家自主功能 (必要功能并入 L4)
  ③ 💪 L2 肌肉记忆技能库 (n_l2_muscle) 从 L4 记忆行 → 🔧 L2 记忆行 (老倪: L2 功能不许越层升到 L4)
  ④ 🧿 n_dsvl 更名/补注为 DeepSeek-V4-Flash (L5 大模型主路) + smolvlm2-500m 本地兜底
  ⑤ 新增 3 个真功能节点: 🧬 阶段专家 MOE / 🎛 L4 LoRA 微调 / 🎛 L3 LoRA 微调 (node_logic 已注册 + 真源码映射)
  ⑥ 修全部断头/悬空 (任务指令/意图丛/技能词典/跨层连接/意图直读/环境渲染源 + SK02-08 + 肌肉记忆技能库)
  ⑦ 去重边 (3 对完全重复) + 修端口冲突 (ssworld→swds in2 被两源占用)
  ⑧ 硬断言: 孤岛 0 · 断头/悬空 只剩合法终端与数据源 · 无节点落在行带外 · L2 功能不在 L4 带 · 端点/端口合法

用法: python3 tools/canvas_restructure_20260924.py [--apply]   (默认 dry-run, 打印将要做的改动)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOW = os.path.join(ROOT, "flows", "state_space_obs.json")

BAND_DELETE = "光模块插拔链"
MOVE = {                      # node id → 目标行带关键字
    "swds": "可视化层", "swvideo": "可视化层",
    "swintact": "L4 专家自主功能", "swworld": "L4 专家自主功能",
    "n_l2_muscle": "L2 记忆",
}
DEDUP = True

NEW_NODES = [
    {"id": "ss_moe", "type": "model", "name": "🧬 阶段专家 MOE · 7 专家 + 先验门控路由 (建设中)",
     "icon": "🧬", "color": "#a371f7", "w": 330, "h": 120, "band": "L4 专家自主功能",
     "inputs": ["in1", "in2"], "outputs": ["out1", "out2"],
     "params": {"desc": "[L4 认知主干改造·建设中] 7 阶段专属专家 (接近/对位/下降/抓取/抬起/转移/插入) + 先验门控路由 (skill_ctx 24D dim13:20 阶段概率), 主干 SmolVLM2 SigLIP 768d 冻结 (86.4M), 只训专家+门控; 数据 v6_sub25k (25k 帧, 3.5GB 缓存); 实测 s1 留出 观测 0.0106@1500 → s2 best 观测 0.0093 / 动作 0.0503 (平凡基线 0.0366/0.0955 → 优 75%/47%); ⏳ 待办: 门控分化诊断 → 同数据密集基线 A/B → 引擎闭环 n=10",
                "source": "tools/stage_moe_backbone.py", "source_symbol": "class StageMoE",
                "status": "建设中", "todo": True, "ckpt": "checkpoints/stage_moe/moe.pt (351MB)"}},
    {"id": "ss_lora_l4", "type": "model", "name": "🎛 L4 · INTACT LoRA 微调 (r8/α16 · A/B 未证明提升)",
     "icon": "🎛", "color": "#ffa657", "w": 330, "h": 120, "band": "L4 专家自主功能",
     "inputs": ["in1"], "outputs": ["out1"],
     "params": {"desc": "[L4 微调] INTACT 本域 LoRA: 注入 112 层线性 (r=8/α=16), 从官方 pusht 权重初始化, 数据 optical_insert v6 真机示教; 产物必须 merge 后才可部署 (包装键→Missing key→trained=False 零动作); 现状: 200 步产物 A/B 未证明提升 → 不切在役指针; 2026-09-24 Δu 逐帧诊断定位根因 = 幅值比中位 5.2~5.8× (闸门红线 1.5×) 被 L2 收口闸逐帧否决",
                "source": "tools/lora_inject.py", "source_symbol": "def inject_lora",
                "status": "未证明提升", "todo": True,
                "ckpt": "checkpoints/intact_goal_optical_insert_v6lora_200"}},
    {"id": "ss_lora_l3", "type": "model", "name": "🎛 L3 · SmolVLA LoRA 微调 (200 步 · loss 0.192)",
     "icon": "🎛", "color": "#ffa657", "w": 330, "h": 120, "band": "L3 高级自动功能",
     "inputs": ["in1"], "outputs": ["out1"],
     "params": {"desc": "[L3 微调] SmolVLA 本域 LoRA: VLM 注意力 + action expert (flow-matching 头) 注入, batch2 / LoRA; 实测 200 步 / 3670s · loss 0.192 · action_loss 0.2368 · 显存 3.75GB; ⏳ 待办: 与统一主干/阶段专家 MOE 同口径评测后才进默认档",
                "source": "tools/lora_inject.py", "source_symbol": "class LoRALinear",
                "status": "已产出未评测", "todo": True,
                "ckpt": "outputs/train/smolvla_lew_lora_200r4/checkpoints"}},
]

NEW_EDGES = [   # (f, t, f_port, t_port, label)
    ("ssobs", "ss_moe", "out1", "in1", "43D 统一状态 → 阶段专家"),
    ("ssvlm", "ss_moe", "out1", "in2", "潜空间 z → 阶段专家"),
    ("ss_moe", "ssmani_exp", "out1", "in4", "阶段专家预测 → 流形专家"),
    ("ss_moe", "sssched", "out2", "in7", "门控路由/阶段置信 → 调度"),
    ("ssz700", "ss_lora_l4", "out1", "in1", "真机示教数据 → L4 LoRA 训练"),
    ("ss_lora_l4", "ssintact", "out1", "in5", "LoRA 权重 → 在役策略 (merge 后)"),
    ("ssz700", "ss_lora_l3", "out1", "in1", "真机示教数据 → L3 LoRA 训练"),
    ("ss_lora_l3", "ssvlm", "out1", "in4", "LoRA 适配器 → VLM 编码器"),
    ("ssllm_in", "n_dsvl", "out1", "in2", "任务指令文本 → 场景理解"),
    ("ssllm_in", "ssllm", "out1", "in2", "任务指令 → 长程规划"),
    ("n_intent_bundle", "ssintact_dec", "out1", "in7", "意图四槽 (goal/from/skill/gate) → 意图解码"),
    ("n_skill_dict", "ss_mem_l2", "out1", "in2", "技能词典 → L2 肌肉记忆库"),
    ("n_mem_links", "ss_mem_share", "out1", "in7", "记忆图谱 → 总装记忆融合"),
    ("n_intent_direct", "sssched", "out1", "in2", "意图直读 → 动作调制"),
    ("ssskill", "n_l2_muscle", "out1", "in1", "L3 序列 → 调用 L2 肌肉记忆技能库"),
    ("swds", "swintact", "out1", "in1", "渲染真图 224² RGB → INTACT 策略输入"),
] + [(f"ssskill", f"sssk{i}", "out1", "in1", "技能序列 → 原子技能") for i in range(2, 9)]

# 合法终端 (显示/观察类, 天生有入无出) 与合法数据源 (天生有出无入)
TERMINALS = {"ssbypv", "ssff_hist", "ssvideo", "ss3d_view", "ssvideo2", "sstest", "ssfeat"}
SOURCES = {"ssdata", "ssz700", "n_eng_mem"}


def band_of(n, bands):
    cy = n["y"] + n["h"] / 2
    for b in bands:
        if b["y"] <= cy <= b["y"] + b["h"]:
            return b
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    d = json.load(open(FLOW, encoding="utf-8"))
    nodes = d["nodes"]
    ns = {n["id"]: n for n in nodes}
    bands = [n for n in nodes if n.get("type") == "row_bg"]
    log = []
    P = log.append

    def find_band(kw, exclude=None):
        r = [b for b in bands if kw in str(b.get("name", "")) and b is not exclude]
        assert len(r) == 1, f"行带 {kw!r} 命中 {[b.get('name') for b in r]}"
        return r[0]

    def place_in(band, n, after=None):
        mem = [m for m in nodes if m.get("type") != "row_bg"
               and m["id"] != n["id"] and band_of(m, [band]) is band]
        right = max([m["x"] + m["w"] for m in mem] + [band["x"] + 40])
        n["x"] = int(right + 300)
        n["y"] = int(band["y"] + 60)
        ensure_clear(n)

    def ensure_clear(n):
        """不与其他节点重叠: 与已就位节点重叠则继续右推"""
        for _ in range(80):
            hit = next((m for m in nodes if m is not n and m.get("type") != "row_bg"
                        and m["x"] < n["x"] + n["w"] and n["x"] < m["x"] + m["w"]
                        and m["y"] < n["y"] + n["h"] and n["y"] < m["y"] + m["h"]), None)
            if hit is None:
                return
            n["x"] = int(hit["x"] + hit["w"] + 200)

    # ① 删行带
    bdel = [b for b in bands if BAND_DELETE in str(b.get("name", ""))]
    if bdel:
        for b in bdel:
            P(f"① 删行带 {b.get('name')} (id={b['id']})")
            nodes.remove(b)
            bands.remove(b)
    else:
        P("① 行带已删 (幂等跳过)")

    # ②③ 移动节点
    def nm_(n):
        return str(n.get("name"))[:26]

    for nid, kw in MOVE.items():
        n = ns.get(nid)
        if not n:
            P(f"② 移动跳过: {nid} 不存在")
            continue
        tb = find_band(kw)
        if band_of(n, [tb]) is tb:
            P(f"② {nid} 已在「{kw}」行 (幂等跳过)")
            continue
        old = band_of(n, bands)
        place_in(tb, n)
        P(f"② {nm_(n)}: 「{old.get('name') if old else '未归属'}」→「{tb.get('name')}」 x={n['x']} y={n['y']}")

    # ④ DeepSeek-V4-Flash 更名/补注
    nd = ns.get("n_dsvl")
    if nd:
        nd["name"] = "🧿 DeepSeek-V4-Flash · 场景理解 (L5 大模型主路)"
        pr = nd.setdefault("params", {})
        pr["desc"] = ("[L5 大模型主路] DeepSeek-V4-Flash (API · 支持 Vision): 场景判读/工序纠错 → 结构化落 "
                      "data/scene_state.json, 喂 L3 规划/技能编排与 L4 意图解码; 本地兜底 = smolvlm2-500m "
                      "(HuggingFaceTB/SmolVLM2-500M, 权重在 ~/.cache/huggingface, GPU 单帧编码); "
                      "双路优先级 SS_VLM_PROVIDER > DeepSeek(flash) > 本地 worker")
        pr["provider"] = "deepseek-v4-flash"
        pr["fallback"] = "smolvlm2-500m (本地)"
        P("④ n_dsvl → " + nd["name"])

    # ⑤ 新增节点
    for spec in NEW_NODES:
        if spec["id"] in ns:
            P(f"⑤ {spec['id']} 已存在 (幂等跳过)")
            continue
        tb = find_band(spec["band"])
        n = {k: spec[k] for k in ("id", "type", "name", "icon", "color", "w", "h", "params", "inputs", "outputs")}
        n["x"], n["y"] = 0, 0
        nodes.append(n)
        ns[n["id"]] = n
        place_in(tb, n)
        P(f"⑤ 新增节点 {spec['id']} 「{spec['name']}」→ 「{tb.get('name')}」 x={n['x']} y={n['y']}")

    # ⑥⑦ 连线: 去重 + 修端口冲突 + 补边
    links = d["links"]
    # 记忆环语义: 总装记忆"下发"到 L2/L3/L4 是**反馈**(上层写回下层), 打 ↩ 标 → 断环优先断它们,
    # 从而保住"记忆→图谱→总装"的汇聚方向 (2026-09-24; 否则会去断 图谱→总装 使图谱节点成断头)
    for L in links:
        if L["f"] == "ss_mem_share" and L["t"] in ("ss_mem_l2", "ss_mem_l3", "ss_mem_l4"):
            lab = str(L.get("label") or "")
            if not lab.startswith("↩"):
                L["label"] = "↩ 反馈: " + lab
                P(f"⑦ 记忆下发打反馈标: {L['f']}→{L['t']} ({lab[:20]})")
    if DEDUP:
        seen, out = set(), []
        for L in links:
            k = (L["f"], L["t"], L.get("t_port"), str(L.get("label") or ""))
            if k in seen:
                P(f"⑦ 去重边 {L['f']}→{L['t']} ({L.get('t_port')})")
                continue
            seen.add(k)
            out.append(L)
        links = out
    for L in links:                                  # 修 swds in2 双占
        if L["t"] == "swds" and L["f"] == "ssworld" and L.get("t_port") == "in2":
            L["t_port"] = "in1"
            L["label"] = "↩ 渲染回流 (引擎 → 渲染图像源)"
            P("⑦ 修端口冲突: ssworld→swds in2→in1 (原被 ssdata 占用 in2)")
    have = {(L["f"], L["t"], L.get("t_port")) for L in links}
    for f, t, fp, tp, lab in NEW_EDGES:
        if f not in ns or t not in ns:
            P(f"⑥ 跳过 (端点缺): {f}→{t}")
            continue
        if (f, t, tp) in have:
            P(f"⑥ 已存在边 (幂等跳过): {f}→{t} {tp}")
            continue
        links.append({"id": f"lk{time.strftime('%m%d')}_{f}_{t}_{tp}", "f": f, "t": t,
                      "f_port": fp, "t_port": tp, "label": lab})
        P(f"⑥ 补边 {f}({fp}) → {t}({tp})  {lab}")

    # ⑧ 断言
    d["links"] = links                      # 🐛 2026-09-24 实锤坑: 局部变量赋值不回写 → 新边全丢 (新节点成孤岛)
    assert len(d["links"]) == len(links), "links 未回写"
    ids = [n["id"] for n in nodes if n.get("type") != "row_bg"]
    assert len(ids) == len(set(ids)), "节点 id 重复"
    allid = set(ids)
    bad = [(L["f"], L["t"]) for L in links if L["f"] not in allid or L["t"] not in allid]
    assert not bad, f"断头连线 {bad}"
    bands = [n for n in nodes if n.get("type") == "row_bg"]
    outside = [n["id"] for n in nodes if n.get("type") != "row_bg" and band_of(n, bands) is None]
    assert not outside, f"节点不在任何行带: {outside}"
    ind, outd = defaultdict(int), defaultdict(int)
    for L in links:
        outd[L["f"]] += 1
        ind[L["t"]] += 1
    iso = [i for i in ids if ind[i] == 0 and outd[i] == 0]
    dead = [i for i in ids if outd[i] == 0 and i not in TERMINALS]
    susp = [i for i in ids if ind[i] == 0 and i not in SOURCES]
    assert not iso, f"孤岛节点: {iso}"
    assert not dead, f"断头(非合法终端): {dead}"
    assert not susp, f"悬空(非数据源): {susp}"
    l4b = [b for b in bands if "L4" in str(b.get("name", ""))]
    for n in nodes:                                   # L2 功能不许在 L4 带
        if n.get("type") == "row_bg":
            continue
        b = band_of(n, bands)
        if b in l4b and any(t in str(n.get("name", "")) for t in ("💪", "🔧 L2", "SK0")):
            raise AssertionError(f"L2 功能越层到 L4: {n['name']} @ {b.get('name')}")
    dup = [k for k in {(L["f"], L["t"], L.get("t_port")) for L in links}
           if sum(1 for L in links if (L["f"], L["t"], L.get("t_port")) == k) > 1]
    assert not dup, f"重复端口连线: {dup}"
    P(f"⑧ 断言全过: 节点 {len(ids)} · 连线 {len(links)} · 行带 {len(bands)} · 孤岛 0 · "
      f"断头 {len([i for i in ids if outd[i] == 0])} 全为合法终端 · 悬空 {len([i for i in ids if ind[i] == 0])} 全为数据源")

    print("\n".join(log))
    if not a.apply:
        print("\n(dry-run; 加 --apply 写入)")
        return 0
    bak = FLOW + time.strftime(".bak_%Y%m%d_%H%M%S")
    shutil.copy2(FLOW, bak)
    json.dump(d, open(FLOW, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n✅ 已写入 · 备份 {os.path.relpath(bak, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
