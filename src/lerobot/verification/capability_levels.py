#!/usr/bin/env python3
"""capability_levels.py — Z-MAX 三级能力清单 (2026-09-08 老倪: 参考自动驾驶分级)

🚗 SAE 自动驾驶分级类比 → 🤖 Z-MAX 精细操作分级 (光模块插拔任务):
  L2 基础辅助   = 车道保持+ACC (驾驶员监控)  → 分段技能辅助 (人在环)
  L3 高级 NOA   = 高速 NOA (特定场景自主)    → 端到端模仿学习 (域内自主)
  L4 专家城区   = 城区 NOA + 自主恢复         → 世界模型技术 (全自主+恢复)

每级功能映射到 verification_layer.py 的真实断言方法组 (t_<前缀>_*),
三级测试 = 自动跑各组真实断言 (非占位)。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # = src/lerobot/verification → src? no: 3 dirname = lerobot? 
# capability_levels.py 在 <repo>/src/lerobot/verification/ → 4 dirname = repo 根
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
ROOT = REPO
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "tools", "gui"))

# ── 三级能力定义 (tests: (ref前缀, 说明)) — 引用 verification_layer 真实方法组 ──
CAPABILITY_LEVELS = {
    "L2": {
        "name": "基础辅助",
        "auto_ref": "L2 车道保持+ACC (驾驶员监控, 系统辅助)",
        "tech": "分段式小模型技术",
        "rows": ["🔧 基础功能"],
        "summary": ("人在环的分段技能辅助 — 8 原子技能(接近/对位/下降/抓取/抬起/转移/插入/完成) "
                    "各自独立可执行, 操作员监控+可随时接管; 单段失败明确回报不越级; "
                    "分段模型 = YOLO 检测 + 前馈MLP + 状态机 + 安全限幅 各自可验"),
        "funcs": [
            {"fid": "L2-A01", "name": "目标检测", "desc": "YOLO 检测光模块/插孔/末端 (真实模型推理)",
             "groups": ["yolo"]},
            {"fid": "L2-A02", "name": "2D→3D 解算", "desc": "检测框反投影 3D 位姿 (真实深度模型)",
             "groups": ["2d3d"]},
            {"fid": "L2-A03", "name": "触觉感知", "desc": "力/触觉通道 → 接触感知",
             "groups": ["tac", "sssensor"]},
            {"fid": "L2-A04", "name": "状态融合", "desc": "多传感融合 → 43D 统一状态向量",
             "groups": ["sobs"]},
            {"fid": "L2-A05", "name": "前馈建议", "desc": "左脑 MLP 前馈 u_ff (蒸馏权重真实推理)",
             "groups": ["ff"]},
            {"fid": "L2-A06", "name": "状态机调度", "desc": "8 阶段状态机逐段推进 (人在环)",
             "groups": ["sched"]},
            {"fid": "L2-A07", "name": "安全边界", "desc": "饱和限幅/否决/力保护 — 单段执行不越界",
             "groups": ["lim"]},
            {"fid": "L2-A08", "name": "原子技能", "desc": "SK01-08 固定模板快速执行",
             "groups": ["skill"]},
            {"fid": "L2-A09", "name": "物理执行", "desc": "执行器→物理世界闭环 (metaworld)",
             "groups": ["act", "world"]},
        ],
    },
    "L3": {
        "name": "高级 NOA",
        "auto_ref": "L3 高速 NOA (特定场景自主, 人可接管)",
        "tech": "端到端模仿学习技术",
        "rows": ["🚀 高级功能"],
        "summary": ("特定场景端到端自主 — VLM 视觉语言编码 + Flow-Matching ActionHead "
                    "从任务指令直接解码动作块; 域内全自主, 出域/低置信交还 L2 分段控制"),
        "funcs": [
            {"fid": "L3-B01", "name": "感知推理", "desc": "视觉+异常推理 (端到端输入侧: 异常检测器)",
             "groups": ["rsn"]},
            {"fid": "L3-B02", "name": "规划序列", "desc": "任务指令→技能序列 (任务规划器/技能编排)",
             "groups": ["llm", "gskill", "gdata", "gpose"]},
            {"fid": "L3-B03", "name": "自主演示", "desc": "端到端自主演示 (全流程自动执行链)",
             "groups": ["auto", "auto_seq"]},
        ],
    },
    "L4": {
        "name": "专家城区 NOA",
        "auto_ref": "L4 城区 NOA + 自主恢复 (复杂场景全自主)",
        "tech": "世界模型技术",
        "rows": ["🏆 专家功能"],
        "summary": ("复杂场景全自主 + 自主恢复 — 状态估计器(右脑WM)+先验预测 预见风险; "
                    "接触/性能流形导航 走测地线通道; 夹持滑脱→重抓, 插入遇阻→分级重试; "
                    "肌肉记忆固化标杆→快通道, 越练越顺; 无需人在环"),
        "funcs": [
            {"fid": "L4-C01", "name": "状态估计", "desc": "自适应状态估计器 (卡尔曼 潜状态跟踪)",
             "groups": ["est"]},
            {"fid": "L4-C02", "name": "先验预测", "desc": "先验动力学预测 next_obs (右脑 WM 真权重)",
             "groups": ["pred"]},
            {"fid": "L4-C03", "name": "接触流形导航", "desc": "接触流形分解 e∥/e⊥ + 风险状态 (导航地图)",
             "groups": ["mc"]},
            {"fid": "L4-C04", "name": "性能流形导航", "desc": "性能流形 V_p/η 对准代价 (耦合效率)",
             "groups": ["mp"]},
            {"fid": "L4-C05", "name": "潜空间标定", "desc": "潜空间/世界模型标定 (维度/速度场)",
             "groups": ["lat", "cal"]},
            {"fid": "L4-C06", "name": "校正恢复", "desc": "状态校正器 残差闭环 (恢复偏离)",
             "groups": ["inn"]},
            {"fid": "L4-C07", "name": "真实化运行", "desc": "真实化 R1 视觉闭环 (真实化断言组)",
             "groups": ["sched_real"]},
        ],
    },
}


def level_list():
    out = []
    for lv, d in CAPABILITY_LEVELS.items():
        n_func = len(d["funcs"])
        out.append({"level": lv, "name": d["name"], "tech": d["tech"],
                    "auto_ref": d["auto_ref"], "funcs": n_func,
                    "groups": sum(len(f["groups"]) for f in d["funcs"]),
                    "summary": d["summary"]})
    return out


def all_funcs():
    return [(lv, f) for lv, d in CAPABILITY_LEVELS.items() for f in d["funcs"]]


def resolve_tests(level):
    """某级全部测试方法名 = 各组前缀展开的 verification_layer 真实方法"""
    import importlib.util
    import re
    _P = os.path.join(ROOT, "src", "lerobot", "verification", "verification_layer.py")
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
    return out


if __name__ == "__main__":
    print("=== Z-MAX 三级能力清单 (参考自动驾驶 L2/L3/L4) ===")
    for lv in level_list():
        print(f"\n[{lv['level']}] {lv['name']} · {lv['tech']}")
        print(f"  类比: {lv['auto_ref']} · {lv['funcs']} 功能 · {lv['groups']} 方法组")
        print(f"  {lv['summary']}")
    # 统计可跑测试数
    for lv in ("L2", "L3", "L4"):
        ts = resolve_tests(lv)
        print(f"\n{lv} 解析到 {len(ts)} 个真实断言方法")
        for t in ts[:5]:
            print(f"    {t['fid']} {t['name']}: {t['method']}")
