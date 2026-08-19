# -*- coding: utf-8 -*-
"""🧩 模型 Feature 注册表 — 数据字典列表展示 (2026-08-19 老倪)

设计原则 (老倪: 模块化开发, 能更换成其它第三方模型):
1. **标准接口层 ModelSpec** — 所有模型共用 8 个标准接口 (输入/输出/配置/训练/
   部署/评估/监控/调度), 第三方模型实现同接口即可接入 (适配器模式)
2. **模型特征层** — 每个模型一份 feature 清单 (状态空间模型先行, 后续各模型补)
3. **工程映射** — 每个 feature 标注: 对应接口 + 工程落点 (文件/工具/场景/指标)
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QTreeWidgetItem

# ── 标准接口层 (ModelSpec · 第三方可替换的契约) ──
MODEL_INTERFACES = [
    ("输入接口 IN", "观测输入: 状态(关节角/末端位姿/触觉) + 图像(可选)"),
    ("输出接口 OUT", "动作输出: 7 轴目标角 + 夹爪开合指令"),
    ("配置接口 CFG", "参数配置: 物理参数/增益表/阶段参数 JSON 标定, 运行期可改"),
    ("训练接口 TRAIN", "训练输入: 标准数据集 (视频帧+状态+动作) + 训练配置 → 权重"),
    ("部署接口 DEPLOY", "部署输出: 权重导出 safetensors → 机端监听自动热更新"),
    ("评估接口 EVAL", "评估输出: rollout 成功率/力曲线/特征根稳定性验证"),
    ("监控接口 MON", "运行监控: 成功率/节拍/力值/决策链上报大屏与飞书"),
    ("调度接口 SCHED", "作业调度: 状态机阶段切换, 阶段参数随状态切换"),
]

# ── 状态空间模型 feature 清单 (Z700 数学化主线) ──
# 每项: (特征名, 描述, 对应接口, 工程映射)
STATE_SPACE_FEATURES = [
    ("F1 物理世界建模",
     "7 轴臂质量/惯量/自由度逐关节建模, 物理参数可标定",
     "CFG",
     "物理参数面板 (双击🌍节点) → physical_world_params.html; 参数源 execution.py"),
    ("F2 状态空间方程",
     "ẋ=Ax+Bu, y=Cx+Du 系统级数学表达, 阶数=7 轴动力学",
     "IN/OUT",
     "flows json + 六层源码 + node_logic 注册; 数学化主线"),
    ("F3 前馈 PD 双通道校正",
     "前馈 F 回路外补偿 + 状态机 P/动作 D 串联 C, 静差削减",
     "CFG/OUT",
     "ff_pd_top.json (双击标定); 纯规则可解析, 不改特征根"),
    ("F4 增益调度",
     "5 阶段 Kp/Kd 切换 (接近/抓取/抬起/转移/插入), 特征根随阶段跳跃",
     "CFG",
     "stab_5stage.py 根轨迹: Kp 20→500, 肩关节 j1 为速度瓶颈"),
    ("F5 状态机作业编排",
     "6 阶段作业流程调度, 阶段参数随状态切换",
     "SCHED",
     "插拔流程: 接近→抓取→抬起→转移→插入; 每阶段一组增益"),
    ("F6 稳定性保证",
     "闭环特征根全负实部 (李雅普诺夫判据), 5 阶段全部稳定",
     "EVAL",
     "tools/stab_7dof.py STABLE; 根轨迹图 reports/stab_5stage.png"),
    ("F7 仿真验证",
     "真仿真生成 距离/前馈/残差/接触概率 波形曲线",
     "EVAL",
     "state_space_sim.py 真仿真 (非玩具); 📊 仿真波形节点"),
    ("F8 触觉力控",
     "4D 触觉输入, 力控插拔保护模块金手指与壳体",
     "IN",
     "58D=45+触觉4+CoT9; 力控插拔场景验收"),
    ("F9 可解释决策",
     "9 维思维链 (CoT) 推理, 决策过程可追溯",
     "MON",
     "大屏监督: 成功率/节拍/力值/决策链实时展示"),
    ("F10 端侧实时推理",
     "轻量化端侧决策 (0.64M 参数级), 机端本地实时",
     "DEPLOY",
     "Orin 端侧部署; 模型热更新 (safetensors 监听自动拉取)"),
]


def current_model_key(module):
    """当前画布 → 模型 key: 状态空间画布 → state_space; 否则 None (后续扩展)"""
    try:
        nodes = getattr(module, "nodes", []) or []
        if any(n.get("params", {}).get("state_space") for n in nodes):
            return "state_space"
    except Exception:
        pass
    return None


def build_model_feature_item(module):
    """构建数据字典树的「🧩 模型 Feature」顶级节点 (当前模型)"""
    key = current_model_key(module)
    if key != "state_space":
        return None  # 2026-08-19: 状态空间先行, 其他模型后续补 feature 定义
    name = "🧩 模型 Feature · 状态空间模型 (当前)"
    root = QTreeWidgetItem([name, ""])
    root.setData(0, Qt.UserRole, None)

    # 📦 标准接口层
    iface = QTreeWidgetItem(["📦 标准接口 ModelSpec (第三方可替换)", ""])
    iface.setData(0, Qt.UserRole, None)
    root.addChild(iface)
    for iname, idesc in MODEL_INTERFACES:
        it = QTreeWidgetItem([iname, idesc])
        it.setData(0, Qt.UserRole, None)
        iface.addChild(it)

    # ✨ 模型特征层
    feats = QTreeWidgetItem([f"✨ 模型特征 ({len(STATE_SPACE_FEATURES)} 项)", ""])
    feats.setData(0, Qt.UserRole, None)
    root.addChild(feats)
    for fname, fdesc, fiface, feng in STATE_SPACE_FEATURES:
        ft = QTreeWidgetItem([fname, fdesc])
        ft.setData(0, Qt.UserRole, None)
        feats.addChild(ft)
        QTreeWidgetItem(ft, ["接口", f"对应 {fiface}"])
        QTreeWidgetItem(ft, ["工程映射", feng])

    # 🔄 可替换机制
    repl = QTreeWidgetItem(["🔄 可替换机制 (模块化)", ""])
    repl.setData(0, Qt.UserRole, None)
    root.addChild(repl)
    QTreeWidgetItem(repl, ["接入标准", "第三方模型实现 ModelSpec 8 接口 (适配器) 即可换装"])
    QTreeWidgetItem(repl, ["当前实现", "状态空间模型 (Z700 数学化主线)"])
    QTreeWidgetItem(repl, ["换装路径", "注册 model_feature.py + 画布模型引擎选择 → 同接口运行"])
    return root
