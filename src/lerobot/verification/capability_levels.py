#!/usr/bin/env python3
"""capability_levels.py — Z-MAX 三级功能清单 (2026-09-08 v2: 对齐画布新架构命名)

画布三级能力 (2026-09-09 老倪定稿语义 → 本文件权威数据源):
  L2 🔧 基础辅助功能   = 肌肉记忆类: 分段式小模型 + 原子技能固化 (YOLO+前馈MLP+13段状态机+安全限幅)
  L3 🚀 高级自动功能   = 长程任务模仿类: 端到端 VLM(通用视觉) + Flow-Matching DiT ActionHead
  L4 🏆 专家自主功能   = 精细交互类 + 抗干扰类: 世界模型 (潜空间预测/流形导航/标定/自主恢复/肌肉记忆)
                        + 光耦合精密操作 (压电台纳米级对准) + 外力干扰容忍 (来料转台 90° 回正抓取)

任务链 13 段 (接近→对位→下降→抓取→抬起→转移→插入→拔出→AOI转移→AOI检测→
回程→放下→完成) = L2 分段技能执行层真实跑通 (mode=insert 回归 / full 全链闭环);
L3 = VLM+DiT 端到端席位 (教学演示层→真实权重推理接入点 smolvla_lew);
L4 = 世界模型 (右脑) 辅助信号/流形地图/标定, 非决策者。

每级功能映射 verification_layer.py 真实断言方法组 (t_<前缀>_*), 测试=真实执行。
"""

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "tools", "gui"))

# ── 三级能力定义 (funcs.groups → verification_layer 真实 t_<前缀>_* 方法) ──
CAPABILITY_LEVELS = {
    "L2": {
        "name": "基础辅助功能",
        "auto_ref": "L2 车道保持+ACC (驾驶员监控, 系统辅助单段) → 分段技能辅助 (人在环/保底执行)",
        "tech": "分段式小模型: YOLO + 前馈MLP + 13段状态机 + 原子技能 + 安全限幅",
        "rows": ["🔧 基础功能"],
        "summary": ("人在环的分段技能执行层 — 13 段任务链 (接近→…→插入→**拔出**→**AOI检测**→放下→完成) "
                    "各自独立可执行; 操作员监控可接管; 单段失败明确回报不越级; full 链真实闭环 "
                    "(R0 4/4 seed · R1 视觉 877 步); AOI 检测报告=真实过程指标 (插深/力峰/回抓)"),
        "funcs": [
            {"fid": "L2-A01", "name": "目标检测", "desc": "YOLO 检测光模块/插孔/末端 (真实模型推理, 每帧)",
             "groups": ["yolo"]},
            {"fid": "L2-A02", "name": "2D→3D 解算", "desc": "检测框反投影 3D 位姿 (真实深度模型)",
             "groups": ["2d3d"]},
            {"fid": "L2-A03", "name": "触觉感知", "desc": "力/触觉通道 → 接触感知",
             "groups": ["tac", "sssensor"]},
            {"fid": "L2-A04", "name": "状态融合", "desc": "多传感融合 → 统一状态向量 (obs)",
             "groups": ["sobs"]},
            {"fid": "L2-A05", "name": "前馈建议", "desc": "左脑 MLP 前馈 u_ff (蒸馏权重真推理, 域内)",
             "groups": ["ff"]},
            {"fid": "L2-A06", "name": "状态机调度 · 13段", "desc": "13 段状态机 (插→拔→AOI→回放) 逐段推进, "
             "insert/full 双模式", "groups": ["sched", "chain"]},
            {"fid": "L2-A07", "name": "安全边界", "desc": "饱和限幅/否决/力保护 — 单段执行不越界 (三层安全)",
             "groups": ["lim"]},
            {"fid": "L2-A08", "name": "原子技能", "desc": "SK01-08 固定模板快速执行 (技能库 skills/atomic_skills.py)",
             "groups": ["skill"]},
            {"fid": "L2-A09", "name": "插拔工艺", "desc": "拔出两段式 (沿孔轴拉出→抬离) — full 链后续动作",
             "groups": ["chain"]},
            {"fid": "L2-A10", "name": "AOI 检测流程", "desc": "镜头对焦保持 + 检测报告 (真实过程指标 PASS/FAIL, "
             "光学判定留真机接口)", "groups": ["chain", "aoi"]},
            {"fid": "L2-A11", "name": "物理执行", "desc": "执行器→物理世界闭环 (metaworld 真实物理)",
             "groups": ["act", "world"]},
        ],
    },
    "L3": {
        "name": "高级自动功能",
        "auto_ref": "L3 高速 NOA (特定场景自主) → 端到端 VLM+DiT (域内自主, 出域交还 L2)",
        "tech": "端到端: SmolVLM 通用视觉编码 + Flow-Matching DiT ActionHead (smolvla_lew)",
        "rows": ["🚀 高级功能"],
        "summary": ("端到端席位: VLM 视觉语言编码 (图像/触觉/检测框 → 潜空间 z) + DiT 从任务指令直接解码 "
                    "action 块; 双下行通路: ① action→执行端直通 (端到端快路径) ② action→前馈层 "
                    "(练熟固化=肌肉记忆加速); 画布拓扑/接入点就位, 真实权重训练=smolvla_lew "
                    "(config 就绪, 图像数据管道已验证); 域内自主, 出域/低置信交还 L2 分段控制"),
        "funcs": [
            {"fid": "L3-B01", "name": "通用视觉编码", "desc": "VLM 场景目标识别 (光模块/插孔/AOI 设备) → 潜空间 z "
             "(教学演示层; 真实权重接入点=smolvla_lew)", "groups": ["vlm", "rsn"]},
            {"fid": "L3-B02", "name": "任务规划", "desc": "任务指令 → 技能序列 (任务规划器/技能编排, 规则+LLM 可插拔)",
             "groups": ["llm", "gskill", "gdata", "gpose"]},
            {"fid": "L3-B03", "name": "动作头解码", "desc": "DiT 解码 z→action 块; 教学演示 (轨迹实算 u_mani); "
             "真实 DiT 权重推理=smolvla_lew 接入点", "groups": ["dec", "auto"]},
            {"fid": "L3-B04", "name": "双通路执行", "desc": "DiT action 双下行: ①执行端直通 (画布 lkdc_act) "
             "②前馈层肌肉记忆固化 (lkdc_ff)", "groups": ["auto_seq", "muscle"]},
            {"fid": "L3-B05", "name": "端到端演示", "desc": "端到端自主演示链 (全流程自动执行; 仿真链已通, "
             "真 VLM+DiT 权重接管后验收)", "groups": ["auto", "auto_seq"]},
        ],
    },
    "L4": {
        "name": "专家自主功能",
        "auto_ref": "L4 城区 NOA + 自主恢复 → 世界模型技术 (复杂场景全自主+恢复, 无需人在环)",
        "tech": "世界模型: 潜空间预测/流形导航/标定/自主恢复/肌肉记忆 (右脑, 辅助非决策)",
        "rows": ["🏆 专家功能"],
        "summary": ("世界模型 (右脑): 状态估计器+先验预测 预见风险 (只预测 next_obs/接触, 辅助信号非决策); "
                    "接触/性能流形导航 走测地线通道 (输入 L4 流形→潜空-流形标定); 标定层拓扑: "
                    "引力-斥力-动作 (收 DiT action) + 潜空-流形 (收 L4 流形); 夹持滑脱→重抓, "
                    "插入遇阻→分级重试; 肌肉记忆固化标杆→快通道越练越顺"),
        "funcs": [
            {"fid": "L4-C01", "name": "状态估计", "desc": "自适应状态估计器 (潜状态跟踪, 卡尔曼 predict/update)",
             "groups": ["est"]},
            {"fid": "L4-C02", "name": "先验预测", "desc": "先验动力学预测 next_obs (右脑 WM 真权重)",
             "groups": ["pred"]},
            {"fid": "L4-C03", "name": "接触流形导航", "desc": "接触流形 e∥/e⊥ 分解 + 风险 (导航地图, 插拔安全通道)",
             "groups": ["mc"]},
            {"fid": "L4-C04", "name": "性能流形导航", "desc": "性能流形 V_p/η 对准代价 (光耦合效率)",
             "groups": ["mp"]},
            {"fid": "L4-C05", "name": "潜空-流形标定", "desc": "潜空间/世界模型流形标定 (维度/速度场 prior_A; "
             "输入 L4 接触/性能流形)", "groups": ["lat", "cal"]},
            {"fid": "L4-C06", "name": "校正恢复", "desc": "状态校正器残差闭环 (恢复偏离) + 滑脱重抓/遇阻分级重试",
             "groups": ["inn"]},
            {"fid": "L4-C07", "name": "肌肉记忆", "desc": "标杆模板固化 → 前馈快通道 (越练越顺, 引擎级小脑机制)",
             "groups": ["muscle", "ff"]},
            {"fid": "L4-C08", "name": "真实化运行", "desc": "R1 视觉闭环 (逐帧 YOLO 真感知; 真实化断言组)",
             "groups": ["sched_real", "chain"]},
            {"fid": "L4-C09", "name": "抗干扰作业", "desc": "来料外力干扰注入: 移位±3.5cm/转向±15° (引擎随机) + "
             "来料转台水平旋转90° (演示场景, 夹爪绕z转90°姿态适配回正抓取) — 现场几何重读自主适应, "
             "多布局 attempts 兜底 (L4 档自动触发; 90° 全真物理链路已实测)",
             "groups": ["sched_real", "chain"]},
            {"fid": "L4-C10", "name": "流形预测器", "desc": "JEPA 世界模型预测流形 (z+a→z'→流形6D): 训练 v1→v5 "
             "(CY 等距正则修复版, 抗干扰 64.6%/clean 43.3%, detach bug 消融实锤), 引擎每帧毫秒级真调, "
             "权重 models/l4_mani_predictor_v5.pt", "groups": ["mc", "sched_real"]},
            {"fid": "L4-C11", "name": "记忆分层 · BLMA", "desc": "三层记忆带 (小脑肌肉/海马情景/额叶筹划) + 总装记忆中枢: "
             "引擎每轮真实化自动写库 (流程经验/预测质量), 真源 src/lerobot/memory, 总装上下文喂 LLM",
             "groups": ["muscle", "sched_real"]},
            {"fid": "L4-C12", "name": "光耦合精密操作", "desc": "精细交互类: 光模块送件压电定位台 (参照芯明天: 底座+"
             "叠堆+载物台+光纤基准) → 真空治具吸附 → 压电 x/y 微动伺服 (行程±2mm) 使 δ(模块头−光纤基准)→0, "
             "η=exp(−δ²/2σ²) 性能流形收敛报告 (实测 η0.89→1.0000, 6 轮微动)",
             "groups": ["mp", "sched_real", "chain"]},
        ],
    },
}


def level_list():
    out = []
    for lv, d in CAPABILITY_LEVELS.items():
        out.append({"level": lv, "name": d["name"], "tech": d["tech"],
                    "auto_ref": d["auto_ref"], "rows": d["rows"],
                    "funcs": len(d["funcs"]),
                    "groups": sum(len(f["groups"]) for f in d["funcs"]),
                    "summary": d["summary"]})
    return out


def all_funcs():
    return [(lv, f) for lv, d in CAPABILITY_LEVELS.items() for f in d["funcs"]]


def resolve_tests(level):
    """某级全部测试方法名 = 各组前缀展开的 verification_layer 真实方法"""
    import importlib.util
    import re
    _P = os.path.join(REPO, "src", "lerobot", "verification", "verification_layer.py")
    _spec = importlib.util.spec_from_file_location("lerobot.verification.verification_layer", _P)
    _m = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_m)
    methods = [x for x in dir(_m.VerificationLayer) if x.startswith("t_")]
    out = []
    for f in CAPABILITY_LEVELS[level]["funcs"]:
        for g in f["groups"]:
            hits = sorted(m for m in methods if re.match(rf"t_{g}($|_)", m))
            for h in hits:
                out.append({"fid": f["fid"], "name": f["name"], "method": h})
    # 去重 (同方法被多功能引用)
    seen, uniq = set(), []
    for t in out:
        k = (t["fid"], t["method"])
        if k not in seen:
            seen.add(k)
            uniq.append(t)
    return uniq


if __name__ == "__main__":
    print("=== Z-MAX 三级功能清单 (新架构 2026-09-08) ===")
    for lv in level_list():
        print(f"\n[{lv['level']}] {lv['name']} · {lv['tech']}")
        print(f"  类比: {lv['auto_ref']} · {lv['funcs']} 功能 · {lv['groups']} 方法组")
        print(f"  {lv['summary']}")
    for lv in ("L2", "L3", "L4"):
        ts = resolve_tests(lv)
        print(f"\n{lv} 解析到 {len(ts)} 个真实断言方法")
        for t in ts[:6]:
            print(f"    {t['fid']} {t['name']}: {t['method']}")
