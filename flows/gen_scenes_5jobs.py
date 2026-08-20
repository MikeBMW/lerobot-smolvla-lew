# -*- coding: utf-8 -*-
"""生成 flows/scenes_5jobs.json — 五大作业场景权威数据源 (2026-08-20 老倪)

结构 = 物体布局 (自车坐标/尺寸/角色) + T+时间轴工艺步骤 (操作/时长/力控约束)
     + 性能约束 (performance → 技能编排器直接消费, 覆盖规则默认参数)

数据来源: 老倪 2026-08-20 提供的五大作业场景详细定义 (光模块工厂产线工艺)。
坐标约定: 自车坐标系 · 原点=R MPV中心地面投影 · +X=前进 · +Y=左侧 · +Z=上方 · 单位 m
"""
import json
import os

COORD = "自车坐标系: 原点=R MPV中心地面投影, +X=前进方向, +Y=左侧, +Z=上方, 单位m"

SCENES = [
    {
        "scene_id": "SCN-01-FW",
        "scene_type": "fw_loading",
        "name": "FW Loading + EEPROM 写/读校验",
        "desc": "对光模块成品执行固件下载与EEPROM校验, 产出经FW验证合格的光模块",
        "goal": "FW验证合格输出",
        "targets": {"合格率": "≥99%"},
        "objects": [
            {"name": "R MPV车体", "pos": [0, 0, 0], "size_mm": [800, 500, 700], "role": "坐标系原点·面向+X方向"},
            {"name": "工作台", "pos": [2.5, 0, 1.2], "size_mm": [1500, 750, 850], "role": "车辆正前方·浅灰防静电"},
            {"name": "来料吸塑盒", "pos": [2.5, -0.4, 1.24], "size_mm": [300, 200, 30], "role": "台面左侧·20穴位"},
            {"name": "EVB测试子板", "pos": [2.5, 0, 1.25], "size_mm": [200, 150, 2], "role": "台面中央·QSFP插座"},
            {"name": "QSFP插座", "pos": [2.5, 0, 1.26], "size_mm": [20, 75, 9], "role": "EVB子板上·插入深度35mm"},
            {"name": "扫码枪", "pos": [2.1, 0.4, 1.35], "size_mm": [160, 95, 70], "role": "台面右前·固定支架"},
            {"name": "Pass料盘", "pos": [3.0, 0.35, 1.24], "size_mm": [250, 180, 25], "role": "绿色防静电·12穴位"},
            {"name": "Fail料盘", "pos": [3.0, -0.35, 1.24], "size_mm": [250, 180, 25], "role": "红色防静电·12穴位"},
            {"name": "PC显示器", "pos": [3.3, 0, 2.0], "size_mm": [540, 320], "role": "台面后方·异步测试结果"},
        ],
        "steps": [
            {"t": 0.0, "dur": 0.6, "name": "取料", "desc": "左臂从归位移动到吸塑盒上方(X=2.5,Y=-0.4,Z=1.3), 夹爪闭合(力控1~5N)抓取光模块", "force": "1~5N"},
            {"t": 0.6, "dur": 1.0, "name": "扫码", "desc": "右臂携带模块移至扫码枪前(X=2.1,Y=0.4,Z=1.35), 红色十字激光扫描SN二维码"},
            {"t": 1.6, "dur": 0.8, "name": "翻转", "desc": "腕部旋转180°(150°/s), 模块标签面朝下, 金手指面朝上"},
            {"t": 2.4, "dur": 0.5, "name": "对位", "desc": "视觉定位QSFP插座导向槽, 末端移动到(X=2.5,Y=0,Z=1.26), 偏差<0.1mm", "accuracy": "0.1mm"},
            {"t": 2.9, "dur": 0.7, "name": "插入", "desc": "沿导向槽直推35mm, 力控≤2N, 弹簧卡扣锁紧", "force": "≤2N", "depth": "35mm"},
            {"t": 3.6, "dur": 50.0, "name": "异步测试", "desc": "PC自动下载固件→校验EEPROM→显示PASS/FAIL; R MPV可转向机台B", "async": True},
            {"t": 53.6, "dur": 0.8, "name": "拔出", "desc": "夹爪夹持模块, 力控拉出≤2N, 脱离QSFP插座", "force": "≤2N"},
            {"t": 54.4, "dur": 3.0, "name": "AOI飞拍", "desc": "金手指正反2面飞拍(0.5s×2)+4侧面飞拍(0.5s×4)=3.0s, 速度0.6m/s"},
            {"t": 57.4, "dur": 0.8, "name": "分拣", "desc": "PASS→绿色料盘(Y=0.35), FAIL→红色料盘(Y=-0.35), 行程0.4m·速度1.0m/s"},
        ],
        "performance": {
            "force_limit": 2.0, "tact_time": 15.0, "positioning_accuracy": 0.0001,
            "insert_depth": 0.035, "pick_force_max": 5.0, "pull_force_max": 2.0,
        },
    },
    {
        "scene_id": "SCN-02-HANDLE",
        "scene_type": "handle",
        "name": "料盘/治具上下料搬运",
        "desc": "完成物料在工位间的流转 (料盘级→治具级→治具内检测)",
        "goal": "配送流转",
        "targets": {"配送准时率": "≥99.5%"},
        "objects": [
            {"name": "缓存架", "pos": [0.5, -0.6, 1.0], "size_mm": [600, 400, 1800], "role": "料盘缓存·多层"},
            {"name": "对接台", "pos": [0.8, 0, 1.0], "size_mm": [400, 400, 850], "role": "物料对接工位"},
            {"name": "料盘", "pos": [0.8, 0, 1.05], "size_mm": [330, 330, 20], "role": "12槽·L1料盘级"},
            {"name": "治具", "pos": [0.8, 0, 1.1], "size_mm": [200, 200, 15], "role": "4定位孔·L2治具级"},
            {"name": "单颗物料", "pos": [0.8, 0, 1.12], "size_mm": [18, 9, 4], "role": "光模块单颗·L3治具内"},
        ],
        "steps": [
            {"t": 0.0, "dur": 3.0, "name": "取盘", "desc": "左臂从缓存架第3层抓取整盘→移至对接台(X=0.8,Y=0,Z=1.0)"},
            {"t": 3.0, "dur": 3.0, "name": "配送", "desc": "R MPV差速转向90°→导航至对接台前方→视觉定位销→下降入位"},
            {"t": 6.0, "dur": 6.0, "name": "精密对接", "desc": "右臂视觉定位治具4个定位孔(精度<0.1mm)→插入单颗物料", "accuracy": "0.1mm"},
            {"t": 12.0, "dur": 8.0, "name": "检测", "desc": "2D外观(2s)→3D尺寸(2s)→金线显微(2s)→缺陷分级(2s)"},
        ],
        "performance": {
            "force_limit": 5.0, "tact_time": 20.0, "positioning_accuracy": 0.0001,
            "pick_force_max": 8.0,
        },
    },
    {
        "scene_id": "SCN-03-BI",
        "scene_type": "bi_aging",
        "name": "BI老化箱模块插拔",
        "desc": "光模块高温老化测试上下料 (85°C±1°C, 1~4小时异步)",
        "goal": "老化测试上下料",
        "targets": {"成功率": "≥99%"},
        "objects": [
            {"name": "BI老化箱", "pos": [1.0, 0, 0.8], "size_mm": [800, 600, 2000], "role": "5层抽屉·每层10穴QSFP"},
            {"name": "R MPV车体", "pos": [0, 0, 0], "size_mm": [800, 500, 700], "role": "坐标系原点"},
            {"name": "料盘", "pos": [0.6, -0.4, 1.1], "size_mm": [330, 330, 20], "role": "待测模块料盘"},
        ],
        "steps": [
            {"t": 0.0, "dur": 5.0, "name": "导航就位", "desc": "R MPV至老化箱前对接位(X=1.0)"},
            {"t": 5.0, "dur": 3.0, "name": "升降就位", "desc": "电动丝杆升至第5层(Z=1.2m)"},
            {"t": 8.0, "dur": 2.0, "name": "拉出抽屉", "desc": "右臂拉出800mm·力控≤15kg", "force": "≤15kg"},
            {"t": 10.0, "dur": 60.0, "name": "批量插入", "desc": "左臂依次取模块→插入QSFP插座 (10颗×6s)", "count": 10},
            {"t": 72.0, "dur": 2.0, "name": "关闭", "desc": "推回抽屉·确认锁紧·状态灯变绿"},
            {"t": 74.0, "dur": 14400.0, "name": "老化", "desc": "85°C±1°C·1~4小时·R MPV可服务其他工位", "async": True},
            {"t": 14474.0, "dur": 13.0, "name": "批量拔出+分拣", "desc": "拉出抽屉→依次拔出10颗→按Pass/Fail分拣", "count": 10},
        ],
        "performance": {
            "force_limit": 15.0, "tact_time": 75.0, "positioning_accuracy": 0.0005,
            "pull_force_max": 15.0,
        },
    },
    {
        "scene_id": "SCN-04-THERMAL",
        "scene_type": "thermal_chamber",
        "name": "热海柜体电口+光口插拔",
        "desc": "光模块环境测试上下料 (电口+光口LC双接头插拔)",
        "goal": "环境测试上下料",
        "targets": {"成功率": "≥99%"},
        "objects": [
            {"name": "热海柜体", "pos": [0.8, 0, 0.9], "size_mm": [600, 600, 1800], "role": "槽位×N·底部电口·顶部光口"},
            {"name": "R MPV车体", "pos": [0, 0, 0], "size_mm": [800, 500, 700], "role": "坐标系原点"},
            {"name": "料盘", "pos": [0.5, 0.4, 1.15], "size_mm": [330, 330, 20], "role": "躯干A区料盘"},
            {"name": "LC光纤", "pos": [0.8, 0.1, 1.4], "size_mm": [2, 2, 300], "role": "双根LC接头"},
        ],
        "steps": [
            {"t": 0.0, "dur": 3.0, "name": "导航", "desc": "R MPV至柜体前对接位(X=0.8)"},
            {"t": 3.0, "dur": 2.0, "name": "取料", "desc": "左臂从躯干A区料盘取光模块→移至槽位前方"},
            {"t": 5.0, "dur": 2.0, "name": "插电口", "desc": "对准槽位底部电口·导向±0.5mm直推", "accuracy": "0.5mm"},
            {"t": 7.0, "dur": 1.5, "name": "光口检测", "desc": "右臂探头检查端面清洁度"},
            {"t": 8.5, "dur": 4.0, "name": "插光口×2", "desc": "依次插入两根光纤LC接头"},
            {"t": 12.5, "dur": 2.0, "name": "清洁", "desc": "棉签清洁→喷气除尘→重新检测", "optional": True},
            {"t": 14.5, "dur": 1800.0, "name": "测试", "desc": "柜体环境测试·气缸顶出模块", "async": True},
            {"t": 1814.5, "dur": 5.5, "name": "拉出+拔光口+分拣", "desc": "拉出电口(1.5s)→拔光口×2(3s)→分拣(1s)"},
        ],
        "performance": {
            "force_limit": 10.0, "tact_time": 20.0, "positioning_accuracy": 0.0005,
            "insert_depth": 0.03,
        },
    },
    {
        "scene_id": "SCN-05-ATS",
        "scene_type": "ats_test",
        "name": "ATS/线外检测插接 (核心挑战场景)",
        "desc": "全参数光学测试插接 (光功率·眼图·误码率·光谱, 遮光帘<1lux, 23±1°C)",
        "goal": "全参数光学测试",
        "targets": {"成功率": "≥99%", "测试读取": "≥99.9%"},
        "objects": [
            {"name": "光学平台", "pos": [1.0, 0, 1.0], "size_mm": [900, 600, 900], "role": "ATS托架·遮光帘·<1lux"},
            {"name": "R MPV车体", "pos": [0, 0, 0], "size_mm": [800, 500, 700], "role": "坐标系原点"},
            {"name": "ATS托架", "pos": [1.0, 0, 1.2], "size_mm": [250, 150, 20], "role": "模块承载·自动扫码"},
            {"name": "LC耦合器", "pos": [1.0, 0.15, 1.3], "size_mm": [30, 20, 15], "role": "光纤耦合"},
            {"name": "EVB电口", "pos": [1.0, -0.1, 1.25], "size_mm": [20, 75, 9], "role": "上电初始化"},
        ],
        "steps": [
            {"t": 0.0, "dur": 2.2, "name": "导航", "desc": "R MPV至光学平台前(X=1.0)·遮光帘降下·<1lux·23±1°C"},
            {"t": 2.2, "dur": 1.0, "name": "扫码", "desc": "模块放入ATS托架·自动扫码SN"},
            {"t": 3.2, "dur": 1.5, "name": "插光口检测", "desc": "光口对接·功率计初测基线"},
            {"t": 4.7, "dur": 1.0, "name": "清洁度检测", "desc": "端面检测探头检查"},
            {"t": 5.7, "dur": 2.0, "name": "清洁", "desc": "棉签+酒精+喷气·重新检测", "optional": True},
            {"t": 6.7, "dur": 1.2, "name": "插电口", "desc": "连接EVB电口·上电初始化"},
            {"t": 7.9, "dur": 1.5, "name": "插光纤", "desc": "连接LC光纤至耦合器"},
            {"t": 9.4, "dur": 120.0, "name": "测试", "desc": "光功率·眼图·误码率·光谱全参数", "async": True},
            {"t": 129.4, "dur": 3.6, "name": "拔光纤+拔模块+目检+分拣", "desc": "拔光纤(1s)→拔模块(0.8s)→金手指AOI(1s)→分拣(0.8s)"},
        ],
        "performance": {
            "force_limit": 5.0, "tact_time": 135.0, "positioning_accuracy": 0.0005,
            "insert_depth": 0.02,
        },
    },
]

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scenes_5jobs.json")
flow = {
    "format": "zmax-scenes-5jobs",
    "version": "1.0",
    "coordinate": COORD,
    "generated": "2026-08-20",
    "scenes": SCENES,
}
json.dump(flow, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"✅ 生成 {len(SCENES)} 个作业场景 → {OUT}")
for s in SCENES:
    print(f"   [{s['scene_id']}] {s['name']} — {len(s['steps'])} 步骤 · {len(s['objects'])} 物体 · 目标 {s['targets']}")
