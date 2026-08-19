# -*- coding: utf-8 -*-
"""🧩 Feature Registry · 能力特征库 (2026-08-19 老倪, 系统工程模块化设计)

══════ 设计思想 ══════
1. **能力视角** — feature 从「模型能做什么」定义, 不写算法/技术实现
   (无 YOLO/ẋ=Ax+Bu/Kp/Kd/PD/CoT/行为克隆 等技术词)。每个模型都有能力,
   能力清单描述模型的能力边界, 而非实现细节。
2. **数据流形态** — 状态空间只是众多形态中的一种数据流。数据流五环节:
   感知 → 决策 → 控制 → 执行。形态举例:
   - 状态向量流 (状态空间: 决策=运动规律建模)
   - 图像→动作流 (端到端: 视觉直接出动作)
   - 视频预测流 (预判型: 预测后续过程)
   - 感知专用流 (感知类: 只做识别定位)
3. **特征库分层** (参考 LeRobot 生态标准) — 8 大类, 每条能力可**复用/增加/组合**:
   - 复用: 能力独立定义, 多模型共用 (A1 目标识别定位, 各模型都用)
   - 增加: 第三方模型带新能力 → 注册新能力条目 (库即插即用)
   - 组合: 模型 = 能力清单 (Manifest), 按需勾选
4. **能力定义四要素** (老倪要求): 每条能力含
   - explain 能力解释 (能做什么)
   - io      输入输出信号 (接口契约: IN → OUT)
   - scene   使用场景 (何时启用/用在哪)
   - eng     工程落点 (内部实现定位)
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QTreeWidgetItem

# ── 数据流形态 (状态空间只是形态之一) ──
DATAFLOW_STAGES = [
    ("感知 Perception", "现场信息 → 目标/状态认知 (识别/定位/触感)"),
    ("决策 Decision", "认知 → 作业意图 (动作规划/预判/建模)"),
    ("控制 Control", "意图 → 动作指令 (分步编排/力度调节/平稳)"),
    ("执行 Execution", "动作指令 → 机械作业 (7轴臂/夹爪/保护)"),
]

# ── 能力特征库: 8 大类 × 条目 ──
# 条目: {id, name(能力名), desc(简述), explain(能力解释), io(输入输出信号),
#        scene(使用场景), iface(接口), eng(工程落点), app(能力归属)}
FEATURE_LIBRARY = [
    ("A 感知能力", [
        {"id": "A1", "name": "目标识别定位",
         "desc": "识别工件/孔位/托盘等目标并给出位置",
         "explain": "能自动识别作业环境中的工件、孔位、托盘等目标, 并给出它们的位置信息, "
                    "是「看得见」的基础能力",
         "io": "IN: 现场图像 → OUT: 目标类别与位置",
         "scene": "抓取前找工件 · 插拔前找孔位 · 上下料认托盘",
         "iface": "IN", "eng": "感知链模块 (yolo_3d/)",
         "app": "感知（例YOLO）· 端到端动作（例ACT）"},
        {"id": "A2", "name": "空间位姿感知",
         "desc": "感知目标的三维位置与朝向",
         "explain": "能把识别到的目标放到三维空间中理解, 知道它在哪、朝向哪, "
                    "支撑抓取点计算与插拔对准",
         "io": "IN: 目标识别结果 + 现场信息 → OUT: 三维位置与朝向",
         "scene": "抓取点计算 · 插拔对准 · 放置规划",
         "iface": "IN", "eng": "感知链 2D→3D 适配",
         "app": "端到端动作（例ACT）"},
        {"id": "A3", "name": "触感感知",
         "desc": "感知接触状态与力度大小",
         "explain": "能感知末端与物体的接触, 以及接触力的大小, 知道「碰到了」「用力多少」, "
                    "是力保护与精细操作的基础",
         "io": "IN: 触感原始信号 → OUT: 接触状态与力度",
         "scene": "插拔接触判断 · 抓取力度控制 · 防损伤",
         "iface": "IN", "eng": "触觉感知通道",
         "app": "触觉力控（例VLA-Touch）· 状态空间（例状态空间模型）"},
        {"id": "A4", "name": "自身状态感知",
         "desc": "感知机械臂各关节与末端状态",
         "explain": "能感知自身各关节角度、末端位置姿态等状态, 知道自己「手在哪儿、姿态如何」, "
                    "是所有作业动作的公共前提",
         "io": "IN: 关节编码/运动状态 → OUT: 关节与末端状态",
         "scene": "全模型共用 · 位置闭环 · 状态上报",
         "iface": "IN/CFG", "eng": "观测状态组装",
         "app": "全模型通用"},
    ]),
    ("B 决策能力", [
        {"id": "B1", "name": "完整作业执行",
         "desc": "学习并执行完整作业动作序列",
         "explain": "能通过学习掌握一套完整作业动作（从看到做）, 独立完成抓取-搬运-插拔等任务, "
                    "不需要人工编写每一步",
         "io": "IN: 现场观测 → OUT: 完整动作序列",
         "scene": "插拔/搬运/对准等完整任务 · 数据充分的任务",
         "iface": "OUT", "eng": "端到端动作策略",
         "app": "端到端动作（例ACT）"},
        {"id": "B2", "name": "过程预判",
         "desc": "预判后续过程走向, 提前调整",
         "explain": "能根据当前过程预判下一步走向, 提前调整动作, 让作业更连贯、更少返工",
         "io": "IN: 当前过程观测 → OUT: 预判结果",
         "scene": "长时序作业 · 异常预警 · 动作预演",
         "iface": "OUT", "eng": "预判旁路模块",
         "app": "世界模型（例LEW）"},
        {"id": "B3", "name": "运动规律建模",
         "desc": "建立运动规律模型, 支撑分析预测",
         "explain": "能建立自身运动规律模型, 用于分析作业表现、预测结果、指导参数调整 "
                    "(状态空间是其中一种数据流形态)",
         "io": "IN: 历史过程数据 → OUT: 运动规律模型",
         "scene": "稳定性分析 · 控制参数设计 · 表现预测",
         "iface": "OUT", "eng": "运动规律建模层",
         "app": "状态空间（例状态空间模型）"},
        {"id": "B4", "name": "精准到位",
         "desc": "快速平稳到达目标位置, 消除偏差",
         "explain": "能快速平稳地把末端送到目标位置, 并消除到位偏差, 保证位置精度, "
                    "作业又快又准",
         "io": "IN: 目标位置 + 当前状态 → OUT: 到位控制指令",
         "scene": "高精度定位 · 低偏差插拔 · 快速换位",
         "iface": "CFG/OUT", "eng": "到位校正模块",
         "app": "状态空间（例状态空间模型）· 轻量决策（例MLP）"},
        {"id": "B5", "name": "决策说明",
         "desc": "说明当前决策的依据, 过程可查",
         "explain": "能说明每一步决策的理由, 作业过程可解释、可回溯, 方便监督与问题归因",
         "io": "IN: 当前观测与决策 → OUT: 决策依据说明",
         "scene": "运行监督 · 异常归因 · 评审验收",
         "iface": "MON", "eng": "决策说明通道",
         "app": "端到端动作（例ACT）"},
    ]),
    ("C 作业控制能力", [
        {"id": "C1", "name": "分步作业编排",
         "desc": "将作业分解为多阶段逐步完成",
         "explain": "能把复杂作业分解为多个阶段（如接近、抓取、插入）, 分阶段管控、逐段完成, "
                    "每阶段独立管理",
         "io": "IN: 阶段完成条件 → OUT: 阶段切换指令",
         "scene": "插拔流程编排 · 多工序流转 · 异常回退",
         "iface": "SCHED", "eng": "作业阶段编排",
         "app": "全模型通用"},
        {"id": "C2", "name": "阶段力度调节",
         "desc": "不同作业阶段自动调节控制力度",
         "explain": "能根据不同作业阶段自动调整控制力度（接近时柔和、插入时稳准）, "
                    "让每个阶段都有合适的作业手感",
         "io": "IN: 当前阶段 → OUT: 控制力度参数",
         "scene": "分阶段作业 · 接近/抓取/插入差异化",
         "iface": "CFG", "eng": "阶段参数调度",
         "app": "状态空间（例状态空间模型）"},
        {"id": "C3", "name": "作业保护",
         "desc": "插拔/压合过程防损伤工件",
         "explain": "能在插拔/压合过程中感知力的大小并自动保护, 超限即调整或停止, "
                    "防止损伤模块金手指与壳体",
         "io": "IN: 力度反馈 → OUT: 保护性调整/停止",
         "scene": "模块插拔 · 金手指保护 · 压合保护",
         "iface": "OUT/MON", "eng": "力保护执行器",
         "app": "全模型通用"},
        {"id": "C4", "name": "平稳运行",
         "desc": "动作平滑无抖动冲击",
         "explain": "能输出平稳顺滑的动作指令, 避免抖动与冲击, 让精密操作更稳、工件更安全",
         "io": "IN: 原始动作指令 → OUT: 平滑后动作指令",
         "scene": "高速作业 · 精密操作 · 大惯量切换",
         "iface": "OUT", "eng": "动作平滑模块",
         "app": "全模型通用"},
    ]),
    ("D 数据能力", [
        {"id": "D1", "name": "标准数据采集",
         "desc": "按行业标准格式采集与交换训练数据",
         "explain": "能按行业标准格式采集与组织训练数据（现场画面+状态+动作）, "
                    "数据可与外部工具/第三方模型互通",
         "io": "IN: 现场采集 → OUT: 标准格式数据",
         "scene": "训练数据准备 · 数据交换 · 第三方模型复用",
         "iface": "TRAIN", "eng": "标准数据集 (生态格式)",
         "app": "全模型通用"},
        {"id": "D2", "name": "边学边练",
         "desc": "现场作业中持续学习提升能力",
         "explain": "能在现场作业中持续采集数据、更新能力, 越用越强, "
                    "产线数据不断反哺模型成长",
         "io": "IN: 现场作业数据 → OUT: 更新后的能力",
         "scene": "产线持续优化 · 新工位快速适配",
         "iface": "TRAIN", "eng": "采集→训练→部署闭环",
         "app": "全模型通用"},
        {"id": "D3", "name": "作业追溯",
         "desc": "每件工件作业过程可查可审计",
         "explain": "能为每件工件记录作业过程与结果, 支持质量追溯与审计, "
                    "满足产线质量管理要求",
         "io": "IN: 工件编号 + 作业记录 → OUT: 追溯档案",
         "scene": "产线验收 · 质量审计 · 异常批次定位",
         "iface": "MON", "eng": "作业记录归档",
         "app": "产线部署版"},
    ]),
    ("E 学习训练能力", [
        {"id": "E1", "name": "一键训练",
         "desc": "标准化配置即可完成训练",
         "explain": "提供标准化训练流程, 配置完成后一键完成训练, 同一套流程可训练多种能力模型",
         "io": "IN: 训练数据 + 配置 → OUT: 训练好的模型",
         "scene": "批量训练 · 多模型对比 · 配置复现",
         "iface": "TRAIN", "eng": "容器化训练环境",
         "app": "全模型通用"},
        {"id": "E2", "name": "上岗前考核",
         "desc": "正式作业前先经仿真考核验证能力",
         "explain": "正式上岗前先在仿真环境完成能力考核, 考核成功率与作业质量, "
                    "达标后才允许真机作业",
         "io": "IN: 待考核模型 → OUT: 考核成绩与结论",
         "scene": "模型选型 · 训练验收 · 版本对比",
         "iface": "EVAL", "eng": "仿真考核环境",
         "app": "全模型通用"},
        {"id": "E3", "name": "渐进式上岗",
         "desc": "从仿真到真机渐进迁移, 降低风险",
         "explain": "支持从仿真到真机的渐进式过渡: 先在仿真打磨, 再零风险试运行, "
                    "最后小步适配真机, 降低现场风险",
         "io": "IN: 仿真训练模型 + 现场数据 → OUT: 真机适配模型",
         "scene": "仿真到真机迁移 · 新产线快速部署",
         "iface": "TRAIN", "eng": "分阶段迁移流程",
         "app": "端到端动作（例ACT）"},
    ]),
    ("F 部署运行能力", [
        {"id": "F1", "name": "本地实时作业",
         "desc": "机端本地实时完成作业, 不依赖外部网络",
         "explain": "在机端本地实时完成感知-决策-作业全流程, 不依赖外部网络, "
                    "断网也能持续作业, 满足 24h 连续生产",
         "io": "IN: 现场观测 → OUT: 实时作业动作",
         "scene": "产线实时作业 · 断网可用 · 低延迟",
         "iface": "DEPLOY", "eng": "机端运行环境 (Orin)",
         "app": "全模型通用"},
        {"id": "F2", "name": "远程升级",
         "desc": "作业中可远程更新模型能力",
         "explain": "支持远程更新模型能力, 新模型文件到位后自动生效, 作业不停、升级不断",
         "io": "IN: 新模型文件 → OUT: 更新生效",
         "scene": "远程升级 · 不停机换模型 · 批量部署",
         "iface": "DEPLOY", "eng": "模型文件监听生效",
         "app": "全模型通用"},
    ]),
    ("G 对外协作能力", [
        {"id": "G1", "name": "标准模型接入",
         "desc": "按统一接口接入任意模型",
         "explain": "提供统一的模型接入标准, 任何第三方模型按标准即可接入, "
                    "接入后共享训练/评估/部署/监控全流程",
         "io": "IN: 标准观测 → OUT: 标准动作 (统一契约)",
         "scene": "第三方模型接入 · 模型替换 · 多模型对比",
         "iface": "IN/OUT", "eng": "统一接入契约 (8 接口)",
         "app": "全模型通用"},
        {"id": "G2", "name": "运行状态上报",
         "desc": "作业状态与结果实时上报",
         "explain": "作业状态、成功率、节拍等运行数据实时上报, 对接大屏与上位系统, "
                    "异常即时告警",
         "io": "IN: 运行数据 → OUT: 上报记录",
         "scene": "产线监控 · 指标验收 · 异常告警",
         "iface": "MON", "eng": "指标上报通道",
         "app": "全模型通用"},
        {"id": "G3", "name": "事件自动通知",
         "desc": "关键事件自动通知相关人员",
         "explain": "训练完成、作业异常、报告输出等关键事件自动通知相关人员, 无需盯屏",
         "io": "IN: 系统事件 → OUT: 通知消息",
         "scene": "远程协作 · 无人盯屏 · 交付同步",
         "iface": "MON", "eng": "消息通知通道",
         "app": "全模型通用"},
    ]),
    ("H 工程交付能力", [
        {"id": "H1", "name": "现场参数可调",
         "desc": "作业参数支持现场直接调整",
         "explain": "作业参数（力度、速度、位置阈值等）支持现场直接调整, 立即生效, "
                    "调试不用改代码",
         "io": "IN: 现场调参输入 → OUT: 生效参数",
         "scene": "现场调试 · 参数整定 · 快速适配",
         "iface": "CFG", "eng": "参数面板 + 数据字典",
         "app": "全模型通用"},
        {"id": "H2", "name": "方案文档交付",
         "desc": "一键生成方案与能力文档",
         "explain": "一键生成技术方案文档与能力清单, 交付口径统一, 客户评审有据可依",
         "io": "IN: 系统数据 → OUT: 交付文档",
         "scene": "客户交付 · 技术选型 · 评审材料",
         "iface": "-", "eng": "文档生成管道",
         "app": "交付"},
        {"id": "H3", "name": "远程查看",
         "desc": "手机/网页随时查看运行情况",
         "explain": "支持手机/网页远程查看运行状态, 管理者随时随地巡检, 展会现场可演示",
         "io": "IN: 运行状态 → OUT: 远程展示",
         "scene": "管理者监控 · 远程巡检 · 展会展示",
         "iface": "MON", "eng": "远程展示页面",
         "app": "全模型通用"},
    ]),
]

# ── 接口说明 (ModelSpec 8 接口, 每条特征标注对应接口及用途) ──
INTERFACE_DEFS = {
    "IN": "输入观测 · 现场信息接入 (图像/状态/触感)",
    "OUT": "动作输出 · 作业动作下发 (机械臂/夹爪)",
    "CFG": "参数配置 · 作业参数可调 (力度/速度/阈值), 运行期生效",
    "TRAIN": "训练接入 · 数据与训练流程对接, 产线数据可反哺",
    "DEPLOY": "部署接入 · 模型加载与更新生效, 作业不停机",
    "EVAL": "评估接入 · 能力考核与结果反馈 (上岗前考核)",
    "MON": "监控上报 · 运行数据对外上报 (状态/成功率/节拍)",
    "SCHED": "调度接入 · 分步作业编排与阶段切换",
}

# ── 模型能力组合 (Manifest) ──
MODEL_MANIFESTS = {
    "state_space": {
        "name": "状态空间模型",
        "abstract": "状态空间（例状态空间模型）",
        "dataflow": "状态向量流 (决策=运动规律建模)",
        "features": {"A1", "A2", "A3", "A4", "B3", "B4", "C1", "C2", "C3", "C4",
                     "D1", "D2", "E1", "E2", "F1", "F2", "G1", "G2", "G3",
                     "H1", "H3"},
    },
    "act": {
        "name": "ACT",
        "abstract": "端到端动作（例ACT）",
        "dataflow": "图像+状态→动作流 (完整作业执行)",
        "features": {"A1", "A2", "A4", "B1", "C1", "C3", "C4", "D1", "D2",
                     "E1", "E2", "E3", "F1", "F2", "G1", "G2", "G3", "H1", "H3"},
    },
    "smolvla": {
        "name": "SmolVLA",
        "abstract": "端到端动作（例SmolVLA）",
        "dataflow": "视觉语言动作流 (统一决策)",
        "features": {"A1", "A2", "A4", "B1", "B2", "C1", "C3", "C4", "D1", "D2",
                     "E1", "E2", "E3", "F1", "F2", "G1", "G2", "G3", "H1", "H3"},
    },
    "vla_touch": {
        "name": "VLA-Touch",
        "abstract": "触觉力控（例VLA-Touch）",
        "dataflow": "视觉+触感→动作流 (力控作业)",
        "features": {"A1", "A2", "A3", "A4", "B1", "B5", "C1", "C3", "C4",
                     "D1", "D2", "E1", "E2", "E3", "F1", "F2", "G1", "G2",
                     "G3", "H1", "H3"},
    },
    "yolo": {
        "name": "YOLO 感知",
        "abstract": "感知（例YOLO）",
        "dataflow": "感知专用流 (识别定位输出)",
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


def build_model_feature_item(module):
    """数据字典树顶级节点: 🧩 能力特征库 + 当前模型能力组合"""
    key = current_model_key(module)
    manifest = MODEL_MANIFESTS.get(key)

    root = QTreeWidgetItem(["🧩 能力特征库 Capability Registry · 精细操作", ""])
    root.setData(0, Qt.UserRole, None)

    # 🔄 数据流形态
    df = QTreeWidgetItem(["🔄 作业数据流 (状态空间=形态之一)", ""])
    df.setData(0, Qt.UserRole, None)
    root.addChild(df)
    for sname, sdesc in DATAFLOW_STAGES:
        QTreeWidgetItem(df, [sname, sdesc])
    if manifest:
        QTreeWidgetItem(df, ["当前形态", manifest["dataflow"]])

    # 📂 能力库 8 大类 (能力四要素: 解释/信号/场景/工程)
    sel = manifest["features"] if manifest else set()
    for cat, items in FEATURE_LIBRARY:
        cn = QTreeWidgetItem([f"📂 {cat} ({len(items)})", ""])
        cn.setData(0, Qt.UserRole, None)
        root.addChild(cn)
        for f in items:
            fid, fname, fdesc = f["id"], f["name"], f["desc"]
            mark = "✓ " if fid in sel else "○ "
            ft = QTreeWidgetItem([f"{mark}{fid} {fname}", fdesc])
            ft.setData(0, Qt.UserRole, None)
            cn.addChild(ft)
            QTreeWidgetItem(ft, ["能力", f["explain"]])
            QTreeWidgetItem(ft, ["信号", f["io"]])
            QTreeWidgetItem(ft, ["接口", f"对应 {f['iface']}"])
            QTreeWidgetItem(ft, ["接口说明",
                " / ".join(INTERFACE_DEFS.get(x.strip(), x.strip())
                           for x in f["iface"].split("/"))])
            QTreeWidgetItem(ft, ["场景", f["scene"]])
            QTreeWidgetItem(ft, ["工程", f["eng"]])
            QTreeWidgetItem(ft, ["归属", f["app"]])

    # 📦 当前模型能力组合 (Manifest)
    if manifest:
        mf = QTreeWidgetItem(
            [f"📦 当前模型 · {manifest['name']} ({manifest.get('abstract', '')} · {manifest['dataflow']})", ""])
        mf.setData(0, Qt.UserRole, None)
        root.addChild(mf)
        ids_sel = sorted(sel)
        ids_all = {f["id"] for _, items in FEATURE_LIBRARY for f in items}
        QTreeWidgetItem(mf, ["具备能力", f"{len(sel)} 项: " + " ".join(ids_sel)])
        QTreeWidgetItem(mf, ["不具备", " ".join(sorted(ids_all - sel))])
        repl = QTreeWidgetItem(["🔄 能力组合机制 (模块化)", ""])
        repl.setData(0, Qt.UserRole, None)
        mf.addChild(repl)
        QTreeWidgetItem(repl, ["接入标准", "第三方模型注册能力组合 + 补齐缺失能力 → 同流程运行"])
        QTreeWidgetItem(repl, ["复用机制", "能力库可复用/可增加/可组合 (参考生态注册机制)"])
        QTreeWidgetItem(repl, ["生态标准", "标准接入契约 · 标准数据格式 · 标准考核流程"])
    return root
