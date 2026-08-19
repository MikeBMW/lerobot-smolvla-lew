# -*- coding: utf-8 -*-
"""🧩 Feature Registry · 特征库体系 (2026-08-19 老倪, 系统工程模块化设计)

══════ 设计思想 ══════
1. **数据流形态** — 状态空间只是众多形态中的一种数据流。数据流五环节:
   感知 → 决策 → 控制 → 执行。形态举例:
   - 状态向量流 (状态空间: 决策=线性动力学 ẋ=Ax+Bu)
   - 图像→动作流 (端到端: 视觉直接出动作)
   - 视频预测流 (世界模型: 预测未来帧/状态)
   - 感知专用流 (YOLO: 只做检测/位姿)
2. **特征库分层** (参考 LeRobot 生态标准: datasets/processor/policies/robots/
   envs + @register_subclass 注册机制) — 8 大类, 每条特征可**复用/增加/组合**:
   - 复用: 特征独立定义, 多模型共用 (A1 视觉检测, ACT 与状态空间都用)
   - 增加: 第三方模型带新能力 → 注册新特征条目 (库即插即用)
   - 组合: 模型 = feature 清单 (Manifest), 按需勾选
3. **模型组合** — 每个模型一份 Manifest (选用特征集合); 第三方模型:
   注册 Manifest + 实现缺失特征适配器 → 同接口进训练/评估/部署/监控管道
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QTreeWidgetItem

# ── 数据流形态 (用户核心观点: 状态空间只是形态之一) ──
DATAFLOW_STAGES = [
    ("感知 Perception", "原始传感 → 特征流 (视觉/触觉/状态)"),
    ("决策 Decision", "特征流 → 意图流 (策略/动力学/规则)"),
    ("控制 Control", "意图流 → 动作流 (调度/增益/限幅)"),
    ("执行 Execution", "动作流 → 硬件 (7轴臂/夹爪/力控)"),
]

# ── 特征库: 8 大类 × 条目 ──
# (类名, [(id, 名称, 简述, 接口, 工程映射, 适用模型)])
FEATURE_LIBRARY = [
    ("A 感知特征", [
        ("A1", "视觉目标检测", "YOLO 2D 检测, 定位工件/孔位", "IN",
         "yolo_3d/ 感知链 (ultralytics)", "YOLO / ACT / 端到端"),
        ("A2", "空间位姿估计", "2D→3D 深度, 抓取点/插孔位姿", "IN",
         "感知链 2D→3D 适配器", "ACT / 端到端"),
        ("A3", "触觉力觉感知", "4D 触觉, 接触/力值检测", "IN",
         "58D 观测含触觉 4D", "VLA-Touch / 状态空间"),
        ("A4", "观测状态编码", "关节角/末端位姿/相对向量编码", "IN/CFG",
         "39D/45D 观测, 坐标叠加主线", "全部"),
    ]),
    ("B 决策特征", [
        ("B1", "端到端动作策略", "图像+状态→动作, 行为克隆/扩散", "OUT",
         "ACT/扩散策略 (PretrainedPolicy)", "ACT / 端到端"),
        ("B2", "世界模型预测", "预测未来帧/状态, 旁路校正", "OUT",
         "LEW 世界模型旁路", "世界模型类"),
        ("B3", "状态空间动力学", "ẋ=Ax+Bu 线性化表达 (一种数据流形态)", "OUT",
         "六层源码 + flows json 注册", "状态空间"),
        ("B4", "规则前馈校正", "前馈 F 回路外 + PD 串联, 静差削减", "CFG/OUT",
         "ff_pd_top.json 双击标定", "状态空间 / MLP"),
        ("B5", "可解释推理链", "CoT 思维链, 决策过程可追溯", "MON",
         "CoT 9D 推理链", "端到端"),
    ]),
    ("C 控制特征", [
        ("C1", "作业状态机", "多阶段作业编排, 阶段切换", "SCHED",
         "接近/抓取/抬起/转移/插入", "全部"),
        ("C2", "增益调度", "分阶段 Kp/Kd, 特征根随阶段切换", "CFG",
         "stab_5stage.py 根轨迹", "状态空间"),
        ("C3", "力控插拔保护", "力反馈限幅, 保护金手指/壳体", "OUT/MON",
         "力控插拔场景验收", "全部"),
        ("C4", "动作限幅与平滑", "速度/加速度约束, 防抖动", "OUT",
         "动作限幅器", "全部"),
    ]),
    ("D 数据特征", [
        ("D1", "标准数据集格式", "视频帧+状态+动作, LeRobotDataset 标准", "TRAIN",
         "npz/lerobot 数据集 (生态标准)", "全部"),
        ("D2", "数据闭环", "采集→训练→部署 边学边练", "TRAIN",
         "Orin 采集→ECS 中转→GPU 训练", "全部"),
        ("D3", "数据追溯", "SN 绑定, 批次可查", "MON",
         "产线全流程追溯", "产线版"),
    ]),
    ("E 训练特征", [
        ("E1", "容器化训练", "GPU 容器一键训练, 配置版本化", "TRAIN",
         "zmax-std 容器 (torch+cu128)", "全部"),
        ("E2", "仿真评估", "metaworld rollout, 成功率/动作质量", "EVAL",
         "rollout_video.py 帧+曲线", "全部"),
        ("E3", "三阶段迁移", "冻结→零样本→真机微调渐进", "TRAIN",
         "S1 仿真 / S2 零样本 / S3 低lr微调", "ACT / 端到端"),
    ]),
    ("F 部署特征", [
        ("F1", "端侧推理", "机端本地实时, 不依赖云端", "DEPLOY",
         "Orin 端侧 (0.64M 轻量)", "全部"),
        ("F2", "模型热更新", "权重文件监听自动拉取生效", "DEPLOY",
         "safetensors → Orin 监听器", "全部"),
    ]),
    ("G 接口特征", [
        ("G1", "标准 I/O 接口", "输入观测/输出动作 契约 (ModelSpec)", "IN/OUT",
         "8 标准接口: IN/OUT/CFG/TRAIN/DEPLOY/EVAL/MON/SCHED", "全部"),
        ("G2", "监控上报接口", "指标 HTTP 上报大屏", "MON",
         "P3 指标树 + datadrive.world", "全部"),
        ("G3", "消息通知接口", "训练/视频/报告自动推飞书", "MON",
         "飞书机器人", "全部"),
    ]),
    ("H 工程特征", [
        ("H1", "参数标定", "数据字典双击写回画布节点", "CFG",
         "右侧标定面板 + 物理参数面板", "全部"),
        ("H2", "方案文档交付", "PDF 技术选型报告 + Feature List", "-",
         "报告管道 / 菜单 Feature List", "交付"),
        ("H3", "大屏监督", "网页端实时监控, 手机可访问", "MON",
         "datadrive.world 分页", "全部"),
    ]),
]

# ── 模型 Manifest (feature 组合) ──
# key: 显示名, 数据流形态, 选用特征 ID 集合
MODEL_MANIFESTS = {
    "state_space": {
        "name": "状态空间模型",
        "dataflow": "状态向量流 (决策=线性动力学 ẋ=Ax+Bu)",
        "features": {"A1", "A2", "A3", "A4", "B3", "B4", "C1", "C2", "C3", "C4",
                     "D1", "D2", "E1", "E2", "F1", "F2", "G1", "G2", "G3",
                     "H1", "H3"},
    },
    "act": {
        "name": "ACT",
        "dataflow": "图像+状态→动作流 (端到端行为克隆)",
        "features": {"A1", "A2", "A4", "B1", "C1", "C3", "C4", "D1", "D2",
                     "E1", "E2", "E3", "F1", "F2", "G1", "G2", "G3", "H1", "H3"},
    },
    "smolvla": {
        "name": "SmolVLA",
        "dataflow": "视觉语言动作流 (VLM 统一决策)",
        "features": {"A1", "A2", "A4", "B1", "B2", "C1", "C3", "C4", "D1", "D2",
                     "E1", "E2", "E3", "F1", "F2", "G1", "G2", "G3", "H1", "H3"},
    },
    "vla_touch": {
        "name": "VLA-Touch",
        "dataflow": "视觉+触觉→动作流 (力控端到端)",
        "features": {"A1", "A2", "A3", "A4", "B1", "B5", "C1", "C3", "C4",
                     "D1", "D2", "E1", "E2", "E3", "F1", "F2", "G1", "G2",
                     "G3", "H1", "H3"},
    },
    "yolo": {
        "name": "YOLO 感知",
        "dataflow": "感知专用流 (检测/位姿输出)",
        "features": {"A1", "A2", "G1"},
    },
}


def _match_model(text):
    """下拉文本/节点名 → manifest key (模糊匹配)"""
    if not text:
        return None
    t = text.lower()
    for key, m in MODEL_MANIFESTS.items():
        if key in t or m["name"].lower() in t:
            return key
    return None


def current_model_key(module):
    """当前画布 → 模型 key: 状态空间画布 → state_space; Model Zoo → cmb_model 匹配"""
    try:
        nodes = getattr(module, "nodes", []) or []
        if any(n.get("params", {}).get("state_space") for n in nodes):
            return "state_space"
        cmb = getattr(module, "cmb_model", None)
        if cmb is not None:
            k = _match_model(cmb.currentText())
            if k:
                return k
    except Exception:
        pass
    return None


def _feat_map():
    """id → (类名, 条目) 快速索引"""
    out = {}
    for cat, items in FEATURE_LIBRARY:
        for it in items:
            out[it[0]] = (cat, it)
    return out


def build_model_feature_item(module):
    """数据字典树顶级节点: 🧩 Feature Registry 特征库 + 当前模型组合"""
    _FM = _feat_map()
    key = current_model_key(module)
    manifest = MODEL_MANIFESTS.get(key)

    root = QTreeWidgetItem(["🧩 特征库 Feature Registry · 精细操作 (LeRobot 生态)", ""])
    root.setData(0, Qt.UserRole, None)

    # 🔄 数据流形态
    df = QTreeWidgetItem(["🔄 数据流形态 (状态空间=形态之一)", ""])
    df.setData(0, Qt.UserRole, None)
    root.addChild(df)
    for sname, sdesc in DATAFLOW_STAGES:
        QTreeWidgetItem(df, [sname, sdesc])
    if manifest:
        QTreeWidgetItem(df, ["当前形态", manifest["dataflow"]])

    # 📂 特征库 8 大类
    sel = manifest["features"] if manifest else set()
    for cat, items in FEATURE_LIBRARY:
        cn = QTreeWidgetItem([f"📂 {cat} ({len(items)})", ""])
        cn.setData(0, Qt.UserRole, None)
        root.addChild(cn)
        for fid, fname, fdesc, fiface, feng, fapp in items:
            mark = "✓ " if fid in sel else "○ "
            ft = QTreeWidgetItem([f"{mark}{fid} {fname}", fdesc])
            ft.setData(0, Qt.UserRole, None)
            cn.addChild(ft)
            QTreeWidgetItem(ft, ["接口", f"对应 {fiface}"])
            QTreeWidgetItem(ft, ["工程映射", feng])
            QTreeWidgetItem(ft, ["适用", fapp])

    # 📦 当前模型组合 (Manifest)
    if manifest:
        mf = QTreeWidgetItem([f"📦 当前模型 · {manifest['name']} ({manifest['dataflow']})", ""])
        mf.setData(0, Qt.UserRole, None)
        root.addChild(mf)
        ids_sel = sorted(sel, key=lambda x: x)
        ids_all = {it[0] for _, items in FEATURE_LIBRARY for it in items}
        QTreeWidgetItem(mf, ["选用特征", f"{len(sel)} 项: " + " ".join(ids_sel)])
        QTreeWidgetItem(mf, ["未选用", " ".join(sorted(ids_all - sel))])
        repl = QTreeWidgetItem(["🔄 可替换机制 (模块化)", ""])
        repl.setData(0, Qt.UserRole, None)
        mf.addChild(repl)
        QTreeWidgetItem(repl, ["接入标准", "第三方模型注册 Manifest + 缺失特征适配器 → 同接口运行"])
        QTreeWidgetItem(repl, ["复用机制", "特征库可复用/可增加/可组合 (参考 LeRobot @register_subclass)"])
        QTreeWidgetItem(repl, ["生态标准", "PretrainedPolicy 接口 · LeRobotDataset 格式 · ProcessorStep 管道"])
    return root
