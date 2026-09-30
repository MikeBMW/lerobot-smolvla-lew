#!/usr/bin/env python3
"""🏭 光模块工厂 三大场景 → 原子技能组合 JSON 生成器 (2026-08-09 老倪)

专业工艺工程师视角: 从 242 条原子技能中, 按光模块工程真实工艺流程,
组合出三个可落地场景 (插拔 / 搬运 / 光学检测), 每个场景带:
  - 工艺性指标 (操作成功率>99%, 节拍时间, CPK, 良率)
  - 结构尺寸 (工装/工件/公差)
  - 工序流程 (原子技能序列)
  - 传感器与执行器配置

输出: flows/scenes.json (Simulink 场景 node 数据源 + ECS 网站传递)
"""
import json
import os
from collections import OrderedDict

RAW = os.path.join(os.path.dirname(__file__), "atomic_skill_tokens.json")
OUT = os.path.join(os.path.dirname(__file__), "scenes.json")

# ── 三个场景定义 (光模块工厂真实工艺) ─────────────────────────────
SCENES = [
    {
        "scene_id": "SCN-INSERT-100G",
        "scene_type": "插拔",
        "name": "100G 光模块精密插拔场景",
        "desc": "100G QSFP 光模块从托盘取料 → 预插 → 力控插入 → 锁止确认 → 拔出 → 回托盘 (光模块工厂核心插拔工艺)",
        "process": [
            {"step": 1, "skill_id": "NPO006", "name": "VCSEL/PIC/PD阵列微小件取料", "action": "pick",
             "desc": "真空/微夹持从精密料盘单件取料, 防双取"},
            {"step": 2, "skill_id": "NPO016", "name": "高速电接口焊盘/插座预检", "action": "inspect",
             "desc": "金手指/焊盘视觉预检, 排除污染与损伤"},
            {"step": 3, "skill_id": "NPO017", "name": "可分离高速互连/LGA插座对准", "action": "align",
             "desc": "视觉引导模块对准笼子插座, 6D位姿收敛"},
            {"step": 4, "skill_id": "NPO030", "name": "盲插光连接器/MT端面对准", "action": "pre_insert",
             "desc": "MT端面主动对准, 光功率预搜索"},
            {"step": 5, "skill_id": "NPO031", "name": "光连接器受控插入与锁止确认", "action": "insert",
             "desc": "力控插入 (阈值保护), 锁止机构到位确认"},
            {"step": 6, "skill_id": "NPO043", "name": "Tx/Rx光功率与波长测试", "action": "test",
             "desc": "插入后立即光功率测试, 确认链路建立"},
        ],
        "metrics": {
            "operation_success_rate": ">99%",       # 工艺性指标: 操作成功率
            "cycle_time": "≤12s",                   # 节拍时间 (含取放+插拔+测试)
            "tact_time_per_module": "12s",          # 单模块节拍
            "throughput": "300 pcs/hr",             # 小时产能
            "insertion_force_limit": "≤15N",        # 插入力上限 (防损伤)
            "insertion_speed": "2-5 mm/s",          # 插入速度 (柔顺控制)
            "positioning_accuracy": "±0.05mm",      # 定位精度
            "angular_accuracy": "±0.1°",            # 角度精度
            "cpk": "≥1.33",                         # 过程能力指数
            "yield": "≥99.5%",                      # 良率
        },
        "dimensions": {
            "module": "QSFP-100G: 18.35×8.5×70.0mm",   # 模块结构尺寸
            "connector": "LC双工 / MT-12, 端面φ1.25mm",
            "tray_pitch": "料盘穴位间距 4.0mm (防碰撞余量)",
            "cage_opening": "笼子开口 17.6×7.8mm (含导向倒角)",
            "gripper": "夹爪开口 20-30mm, 夹持力 3-8N",
            "tolerance": "插入导向区公差 ±0.1mm",
        },
        "sensors": ["RGB相机", "六维力传感器", "激光位移计", "光功率计"],
        "actuators": ["6轴机械臂", "真空吸取器", "力控夹爪"],
        "skills": ["NPO006", "NPO016", "NPO017", "NPO030", "NPO031", "NPO043"],
    },
    {
        "scene_id": "SCN-TRANSFER-OPTIC",
        "scene_type": "搬运",
        "name": "光电引擎精密搬运场景",
        "desc": "光电引擎基板/子载板在工装-料盘-贴装台之间精密转运 (防划伤/防污染/低力落位)",
        "process": [
            {"step": 1, "skill_id": "NPO002", "name": "精密料盘穴位与满空映射", "action": "locate",
             "desc": "识别料盘穴位地图, 生成可取列表"},
            {"step": 2, "skill_id": "NPO015", "name": "光电引擎从料盘低力取出", "action": "pick",
             "desc": "低力取出防粘连, 真空微夹持"},
            {"step": 3, "skill_id": "NPO003", "name": "主板/PCB中介板载具6D定位", "action": "locate",
             "desc": "粗定位→基准识别→手眼变换→装配坐标"},
            {"step": 4, "skill_id": "NPO008", "name": "光电芯片精密贴装/低力落位", "action": "place",
             "desc": "微米级位置角度放置, 低力落位确认"},
            {"step": 5, "skill_id": "NPO021", "name": "模块拆卸/抬升防粘连", "action": "extract",
             "desc": "受控抬升防粘连, 残留检查"},
            {"step": 6, "skill_id": "NPO010", "name": "光纤阵列/MT类端头精密取放", "action": "place",
             "desc": "光纤阵列端头精密取放, 防光纤损伤"},
        ],
        "metrics": {
            "operation_success_rate": ">99%",
            "cycle_time": "≤8s",
            "tact_time_per_part": "8s",
            "throughput": "450 pcs/hr",
            "placement_force": "≤2N",              # 低力落位: 贴装力上限
            "pick_speed": "20 mm/s",               # 取料速度 (防震动)
            "transport_speed": "≤500 mm/s",        # 转运速度
            "positioning_accuracy": "±0.02mm",     # 微米级贴装
            "angular_accuracy": "±0.05°",
            "surface_protection": "无划伤/无污染",   # 表面防护指标
            "cpk": "≥1.67",
            "yield": "≥99.8%",
        },
        "dimensions": {
            "engine": "光电引擎基板: 12.0×10.0×2.5mm",
            "substrate": "子载板: 8.0×6.0×1.0mm",
            "tray": "JEDEC托盘: 穴位 2.0mm深, 壁厚 0.5mm",
            "fixture": "工装定位销: φ1.0mm, 公差 +0/-0.01mm",
            "gripper": "真空吸嘴: φ3mm 软质, 吸取力 0.5-2N",
            "tolerance": "贴装间隙 0.05-0.1mm",
        },
        "sensors": ["显微相机", "激光传感器", "力传感器", "真空压力计"],
        "actuators": ["高精度6轴机械臂", "真空吸嘴", "精密台"],
        "skills": ["NPO002", "NPO015", "NPO003", "NPO008", "NPO021", "NPO010"],
    },
    {
        "scene_id": "SCN-INSPECT-OPTIC",
        "scene_type": "光学检测",
        "name": "光模块 AOI 光学检测场景",
        "desc": "光模块金手指/端面/焊点显微 AOI 检测 (缺陷分级, 数据回灌)",
        "process": [
            {"step": 1, "skill_id": "NPO004", "name": "ASIC周边禁入区/装配位检查", "action": "inspect",
             "desc": "3D扫描比对CAD, 干涉体检查"},
            {"step": 2, "skill_id": "NPO013", "name": "微互连/焊点/金线显微复检", "action": "inspect",
             "desc": "显微复检焊点金线, 缺陷分级"},
            {"step": 3, "skill_id": "NPO032", "name": "光纤端面显微检查与局部处理", "action": "inspect",
             "desc": "光纤端面划痕/污染检查, 局部清洁"},
            {"step": 4, "skill_id": "NPO043", "name": "Tx/Rx光功率与波长测试", "action": "test",
             "desc": "光功率/波长测试, 判定合格"},
            {"step": 5, "skill_id": "NPO044", "name": "200G/lane高速电通道连续性/接触测试", "action": "test",
             "desc": "高速电通道连续性测试"},
            {"step": 6, "skill_id": "NPO045", "name": "多通道BER/眼图/链路裕量测试", "action": "test",
             "desc": "BER/眼图/链路裕量, 最终判定"},
        ],
        "metrics": {
            "operation_success_rate": ">99%",
            "cycle_time": "≤20s",
            "tact_time_per_unit": "20s",
            "throughput": "180 pcs/hr",
            "detection_resolution": "1μm",          # 显微检测分辨率
            "defect_classification": "≥5级",        # 缺陷分级
            "false_negative_rate": "<0.5%",        # 漏检率
            "false_positive_rate": "<1%",           # 误检率
            "repeatability": "±0.5μm",              # 检测重复性
            "cpk": "≥1.33",
            "yield": "≥99%",
        },
        "dimensions": {
            "field_of_view": "显微视场 1.2×0.9mm @ 20X",
            "endface": "光纤端面检测: φ0.125mm 纤芯区",
            "gold_finger": "金手指: 0.5mm pitch, 划痕判据 <0.1mm",
            "solder_joint": "焊点: φ0.3mm, 虚焊判据",
            "stage": "AOI载台: 定位精度 ±0.01mm",
            "tolerance": "检测公差 ±0.5μm",
        },
        "sensors": ["20X显微相机", "金相显微镜", "光谱仪", "光功率计", "误码仪"],
        "actuators": ["高精度XY载台", "自动对焦机构", "旋转台"],
        "skills": ["NPO004", "NPO013", "NPO032", "NPO043", "NPO044", "NPO045"],
    },
]

def build():
    flow = {
        "format": "zmax-scenes",
        "version": "1.0",
        "generated": "2026-08-09",
        "author": "老倪 · 智蜂创元",
        "engineer_note": "专业工厂工艺工程师视角: 光模块工厂真实工艺场景, 成功率>99%, 节拍/良率/CPK 全部量化",
        "scenes": SCENES,
    }
    json.dump(flow, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"✅ 生成 {len(SCENES)} 个场景 → {OUT}")
    for s in SCENES:
        print(f"   [{s['scene_type']}] {s['name']} — {len(s['skills'])} 技能, 成功率{s['metrics']['operation_success_rate']}, 节拍{s['metrics']['cycle_time']}")

if __name__ == "__main__":
    build()
