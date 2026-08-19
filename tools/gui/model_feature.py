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
3. **特征定义三要素** (老倪要求): 每条特征含
   - explain 解释 (功能定义)
   - io      输入输出信号 (接口契约: IN → OUT)
   - scene   使用场景 (何时启用/用在哪)
4. **模型组合** — 每个模型一份 Manifest (选用特征集合); 第三方模型:
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
# 条目: {id, name, desc(简述), explain(解释), io(输入输出信号),
#        scene(使用场景), iface(接口), eng(工程映射), app(适用模型)}
FEATURE_LIBRARY = [
    ("A 感知特征", [
        {"id": "A1", "name": "视觉目标检测",
         "desc": "2D 目标检测, 定位工件/孔位",
         "explain": "基于检测网络的 2D 目标检测, 实时定位工件/孔位/托盘/料盒等目标, "
                    "输出检测框+类别+置信度, 是感知链的第一环 (感知→State 适配)",
         "io": "IN: 相机图像 (RGB 640×480) → OUT: 检测框 (x,y,w,h) + 类别 + 置信度",
         "scene": "抓取前工件定位 · 插拔前孔位检测 · 上下料托盘/料盒识别",
         "iface": "IN", "eng": "yolo_3d/ 感知链 (ultralytics)",
         "app": "感知（例YOLO）· 端到端动作（例ACT）"},
        {"id": "A2", "name": "空间位姿估计",
         "desc": "2D→3D 深度, 抓取点/插孔位姿",
         "explain": "把 2D 检测结果投影到 3D 空间 (深度估计 + 相机标定), 得到目标的空间位姿, "
                    "供抓取点计算与插拔对准使用",
         "io": "IN: 检测框 + 深度/标定参数 → OUT: 3D 位姿 (x,y,z,roll,pitch,yaw)",
         "scene": "抓取点计算 · 插拔对准 · 放置位姿规划",
         "iface": "IN", "eng": "感知链 2D→3D 适配器",
         "app": "端到端动作（例ACT）"},
        {"id": "A3", "name": "触觉力觉感知",
         "desc": "4D 触觉, 接触/力值检测",
         "explain": "触觉传感器采集接触力/力矩, 检测接触事件与力值, 为力控插拔提供反馈信号",
         "io": "IN: 触觉原始信号 → OUT: 力/力矩 (4D) + 接触状态",
         "scene": "力控插拔 · 抓取力控制 · 防损伤保护",
         "iface": "IN", "eng": "58D 观测含触觉 4D",
         "app": "触觉力控（例VLA-Touch）· 状态空间（例状态空间模型）"},
        {"id": "A4", "name": "观测状态编码",
         "desc": "关节角/末端位姿/相对向量编码",
         "explain": "将关节编码器/运动学/末端位姿编码为标准观测向量 (39D/45D/58D), "
                    "作为全模型共用的观测输入, 坐标叠加为逻辑主线、图像为背景",
         "io": "IN: 关节编码器 + 运动学解算 → OUT: 观测向量 (39D/45D/58D)",
         "scene": "全模型共用观测 · 坐标叠加结构条件",
         "iface": "IN/CFG", "eng": "39D/45D 观测, 坐标叠加主线",
         "app": "全模型通用"},
    ]),
    ("B 决策特征", [
        {"id": "B1", "name": "端到端动作策略",
         "desc": "图像+状态→动作, 行为克隆/扩散",
         "explain": "图像+状态直接映射动作的行为克隆策略, 训练即学完整操作 (不显式建模动力学), "
                    "是端到端动作模型的核心决策特征",
         "io": "IN: 图像 + 观测向量 → OUT: 7 轴目标角 + 夹爪开合",
         "scene": "插拔/搬运/对准等完整操作任务 · 数据充分的任务",
         "iface": "OUT", "eng": "端到端动作策略 (PretrainedPolicy)",
         "app": "端到端动作（例ACT）"},
        {"id": "B2", "name": "世界模型预测",
         "desc": "预测未来帧/状态, 旁路校正",
         "explain": "学习环境动力学, 预测未来帧/未来状态, 作为旁路校正当前决策 "
                    "(输入视频帧+动作, 输出预测下一帧)",
         "io": "IN: 当前帧 + 动作历史 → OUT: 预测下一帧/下一状态",
         "scene": "长时序操作 · 异常预警 · 决策预演",
         "iface": "OUT", "eng": "世界模型旁路",
         "app": "世界模型（例LEW）"},
        {"id": "B3", "name": "状态空间动力学",
         "desc": "ẋ=Ax+Bu 线性化表达 (一种数据流形态)",
         "explain": "将系统线性化为 ẋ=Ax+Bu, y=Cx+Du, 解析可控性/可观测性/稳定性, "
                    "是状态向量流形态的决策表达 (状态空间只是众多数据流形态之一)",
         "io": "IN: 状态向量 + 控制输入 → OUT: 状态导数/下一状态",
         "scene": "稳定性分析 · 控制器设计 · 增益调度依据",
         "iface": "OUT", "eng": "六层源码 + flows json 注册",
         "app": "状态空间（例状态空间模型）"},
        {"id": "B4", "name": "规则前馈校正",
         "desc": "前馈 F 回路外 + PD 串联, 静差削减",
         "explain": "前馈 F 放在回路外补偿参考输入 + 状态机 P/动作 D 串联 C 的反馈通道, "
                    "静差大幅削减且不改特征根 (只移零点), 纯规则可解析",
         "io": "IN: 参考 r + 状态误差 e, ė → OUT: 前馈+PD 校正量 u",
         "scene": "高精度定位 · 低静差插拔 · 增益调度配套",
         "iface": "CFG/OUT", "eng": "ff_pd_top.json 双击标定",
         "app": "状态空间（例状态空间模型）· 轻量决策（例MLP）"},
        {"id": "B5", "name": "可解释推理链",
         "desc": "CoT 思维链, 决策过程可追溯",
         "explain": "9 维思维链 (CoT) 显式输出决策依据, 让端到端模型的决策过程可解释、可追溯、可归因",
         "io": "IN: 观测 + 任务上下文 → OUT: 推理链/决策依据 (9D)",
         "scene": "大屏监督 · 异常归因 · 验收评审",
         "iface": "MON", "eng": "CoT 9D 推理链",
         "app": "端到端动作（例ACT）"},
    ]),
    ("C 控制特征", [
        {"id": "C1", "name": "作业状态机",
         "desc": "多阶段作业编排, 阶段切换",
         "explain": "将作业分解为多阶段 (接近/抓取/抬起/转移/插入), 按完成条件切换阶段, "
                    "每阶段绑定独立参数组 (增益/限幅/阈值)",
         "io": "IN: 阶段完成信号/条件评估 → OUT: 阶段切换指令",
         "scene": "插拔流程编排 · 多工序流转 · 异常回退",
         "iface": "SCHED", "eng": "接近/抓取/抬起/转移/插入",
         "app": "全模型通用"},
        {"id": "C2", "name": "增益调度",
         "desc": "分阶段 Kp/Kd, 特征根随阶段切换",
         "explain": "各阶段使用不同 Kp/Kd 增益组, 闭环特征根随阶段在复平面跳跃 "
                    "(接近用小增益慢稳, 插入用大增益快准狠), 全部阶段根须在左半平面",
         "io": "IN: 当前阶段编号 → OUT: Kp/Kd 增益组",
         "scene": "状态空间控制器 · 分阶段动态特性差异化",
         "iface": "CFG", "eng": "stab_5stage.py 根轨迹",
         "app": "状态空间（例状态空间模型）"},
        {"id": "C3", "name": "力控插拔保护",
         "desc": "力反馈限幅, 保护金手指/壳体",
         "explain": "插拔过程实时监测力值, 超限即力控修正或停止, 保护模块金手指与壳体不损伤",
         "io": "IN: 力/力矩反馈 → OUT: 力控修正量/停止指令",
         "scene": "模块插拔 · 金手指保护 · 压合保护",
         "iface": "OUT/MON", "eng": "力控插拔场景验收",
         "app": "全模型通用"},
        {"id": "C4", "name": "动作限幅与平滑",
         "desc": "速度/加速度约束, 防抖动",
         "explain": "对原始动作指令做速度/加速度限幅与平滑滤波, 防止末端抖动与冲击",
         "io": "IN: 原始动作指令 → OUT: 限幅平滑后动作指令",
         "scene": "高速作业 · 精密操作 · 大惯量切换",
         "iface": "OUT", "eng": "动作限幅器",
         "app": "全模型通用"},
    ]),
    ("D 数据特征", [
        {"id": "D1", "name": "标准数据集格式",
         "desc": "视频帧+状态+动作, LeRobotDataset 标准",
         "explain": "按 LeRobotDataset 生态标准组织数据 (视频帧+状态+动作, 支持增量), "
                    "任何符合标准的模型/工具可直接消费, 是第三方模型复用的数据基础",
         "io": "IN: 采集原始流 (视频/编码器/动作) → OUT: 标准数据集 (npz/视频, 可增量)",
         "scene": "训练数据准备 · 第三方模型训练 · 数据交换",
         "iface": "TRAIN", "eng": "npz/lerobot 数据集 (生态标准)",
         "app": "全模型通用"},
        {"id": "D2", "name": "数据闭环",
         "desc": "采集→训练→部署 边学边练",
         "explain": "现场采集 (Orin) → 中转 (ECS) → GPU 训练 → 部署回机端, 形成边学边练闭环, "
                    "产线数据持续反哺模型能力",
         "io": "IN: 现场采集数据 → OUT: 新模型权重 (回部署)",
         "scene": "产线持续优化 · 新工位快速适配",
         "iface": "TRAIN", "eng": "Orin 采集→ECS 中转→GPU 训练",
         "app": "全模型通用"},
        {"id": "D3", "name": "数据追溯",
         "desc": "SN 绑定, 批次可查",
         "explain": "每件工件 SN 与操作记录绑定, 全流程可追溯, 满足产线质量审计要求",
         "io": "IN: 工件 SN + 操作记录 → OUT: 追溯记录 (可查询)",
         "scene": "产线验收 · 质量审计 · 异常批次定位",
         "iface": "MON", "eng": "产线全流程追溯",
         "app": "产线部署版"},
    ]),
    ("E 训练特征", [
        {"id": "E1", "name": "容器化训练",
         "desc": "GPU 容器一键训练, 配置版本化",
         "explain": "训练在标准 GPU 容器 (torch+cu128) 中一键执行, 训练配置版本化可复现, "
                    "同一套管道跑通多模型 (Model Zoo)",
         "io": "IN: 数据集 + 训练配置 → OUT: 训练权重 (safetensors)",
         "scene": "批量训练 · 多模型对比 · 配置复现",
         "iface": "TRAIN", "eng": "zmax-std 容器 (torch+cu128)",
         "app": "全模型通用"},
        {"id": "E2", "name": "仿真评估",
         "desc": "metaworld rollout, 成功率/动作质量",
         "explain": "在 metaworld 仿真环境做 rollout 评估, 输出成功率/动作幅度/耗时/视频, "
                    "是模型选型与验收的客观依据",
         "io": "IN: 模型权重 + 评估配置 → OUT: 成功率/动作σ/耗时 + rollout 视频",
         "scene": "模型选型 · 训练验收 · 版本对比",
         "iface": "EVAL", "eng": "rollout_video.py 帧+曲线",
         "app": "全模型通用"},
        {"id": "E3", "name": "三阶段迁移",
         "desc": "冻结→零样本→真机微调渐进",
         "explain": "S1 仿真训练冻结 backbone → S2 零样本测 RealityGap → S3 真机低 lr 微调 "
                    "(backbone 更低 + ensemble 必开), 渐进式控制迁移风险",
         "io": "IN: 预训练权重 + 真机数据 → OUT: 微调后权重",
         "scene": "仿真到真机迁移 · 新产线快速部署",
         "iface": "TRAIN", "eng": "S1 仿真 / S2 零样本 / S3 低lr微调",
         "app": "端到端动作（例ACT）"},
    ]),
    ("F 部署特征", [
        {"id": "F1", "name": "端侧推理",
         "desc": "机端本地实时, 不依赖云端",
         "explain": "模型在机端 (Orin) 本地实时推理, 不依赖云端网络, 满足产线 24h 连续作业与断网可用",
         "io": "IN: 机端观测 → OUT: 实时动作指令",
         "scene": "产线实时作业 · 断网可用 · 低延迟",
         "iface": "DEPLOY", "eng": "Orin 端侧 (0.64M 轻量)",
         "app": "全模型通用"},
        {"id": "F2", "name": "模型热更新",
         "desc": "权重文件监听自动拉取生效",
         "explain": "机端监听权重文件 (safetensors) 变化, 自动拉取新权重并生效, 远程升级不停机",
         "io": "IN: 新权重文件 → OUT: 生效模型 (运行中切换)",
         "scene": "远程升级 · 不停机换模型 · 批量部署",
         "iface": "DEPLOY", "eng": "safetensors → Orin 监听器",
         "app": "全模型通用"},
    ]),
    ("G 接口特征", [
        {"id": "G1", "name": "标准 I/O 接口",
         "desc": "输入观测/输出动作 契约 (ModelSpec)",
         "explain": "8 个标准接口 (IN/OUT/CFG/TRAIN/DEPLOY/EVAL/MON/SCHED) 构成模型接入契约, "
                    "第三方模型实现同接口即插即用 (参考生态 PretrainedPolicy 标准)",
         "io": "IN: 观测 (图像/状态/触觉) → OUT: 动作 (7轴+夹爪), 统一契约",
         "scene": "第三方模型接入 · 模型替换 · 多模型对比",
         "iface": "IN/OUT", "eng": "8 标准接口: IN/OUT/CFG/TRAIN/DEPLOY/EVAL/MON/SCHED",
         "app": "全模型通用"},
        {"id": "G2", "name": "监控上报接口",
         "desc": "指标 HTTP 上报大屏",
         "explain": "成功率/节拍/力值/状态等指标通过 HTTP 上报大屏 (P3 指标树), 异常即时告警",
         "io": "IN: 运行指标 → OUT: 大屏展示/告警 (HTTP)",
         "scene": "产线监控 · 指标树验收 · 异常告警",
         "iface": "MON", "eng": "P3 指标树 + datadrive.world",
         "app": "全模型通用"},
        {"id": "G3", "name": "消息通知接口",
         "desc": "训练/视频/报告自动推飞书",
         "explain": "训练完成/视频生成/报告输出等事件自动推送飞书, 产线人员无需盯屏",
         "io": "IN: 系统事件 → OUT: 飞书消息 (含附件)",
         "scene": "远程协作 · 无人盯屏 · 交付同步",
         "iface": "MON", "eng": "飞书机器人",
         "app": "全模型通用"},
    ]),
    ("H 工程特征", [
        {"id": "H1", "name": "参数标定",
         "desc": "数据字典双击写回画布节点",
         "explain": "数据字典/标定面板双击参数即可标定并写回画布节点, 物理参数/增益/阈值现场可调",
         "io": "IN: 标定输入值 → OUT: 画布节点参数 (运行期生效)",
         "scene": "现场调试 · 增益调参 · 参数整定",
         "iface": "CFG", "eng": "右侧标定面板 + 物理参数面板",
         "app": "全模型通用"},
        {"id": "H2", "name": "方案文档交付",
         "desc": "PDF 技术选型报告 + Feature List",
         "explain": "一键生成技术选型 PDF 报告与 Feature List 特征清单, 交付口径统一 "
                    "(符合 5 场景具身方案技术协议)",
         "io": "IN: 系统数据 (画布/评估/指标) → OUT: PDF/特征清单文档",
         "scene": "客户交付 · 技术选型 · 评审材料",
         "iface": "-", "eng": "报告管道 / 菜单 Feature List",
         "app": "交付"},
        {"id": "H3", "name": "大屏监督",
         "desc": "网页端实时监控, 手机可访问",
         "explain": "datadrive.world 网页端实时展示运行状态与指标, 手机可访问, 管理者随时巡检",
         "io": "IN: 运行状态/指标 → OUT: 网页展示 (多端)",
         "scene": "管理者监控 · 远程巡检 · 展会展示",
         "iface": "MON", "eng": "datadrive.world 分页",
         "app": "全模型通用"},
    ]),
]

# ── 模型 Manifest (feature 组合) ──
MODEL_MANIFESTS = {
    "state_space": {
        "name": "状态空间模型",
        "abstract": "状态空间（例状态空间模型）",
        "dataflow": "状态向量流 (决策=线性动力学 ẋ=Ax+Bu)",
        "features": {"A1", "A2", "A3", "A4", "B3", "B4", "C1", "C2", "C3", "C4",
                     "D1", "D2", "E1", "E2", "F1", "F2", "G1", "G2", "G3",
                     "H1", "H3"},
    },
    "act": {
        "name": "ACT",
        "abstract": "端到端动作（例ACT）",
        "dataflow": "图像+状态→动作流 (端到端行为克隆)",
        "features": {"A1", "A2", "A4", "B1", "C1", "C3", "C4", "D1", "D2",
                     "E1", "E2", "E3", "F1", "F2", "G1", "G2", "G3", "H1", "H3"},
    },
    "smolvla": {
        "name": "SmolVLA",
        "abstract": "端到端动作（例SmolVLA）",
        "dataflow": "视觉语言动作流 (VLM 统一决策)",
        "features": {"A1", "A2", "A4", "B1", "B2", "C1", "C3", "C4", "D1", "D2",
                     "E1", "E2", "E3", "F1", "F2", "G1", "G2", "G3", "H1", "H3"},
    },
    "vla_touch": {
        "name": "VLA-Touch",
        "abstract": "触觉力控（例VLA-Touch）",
        "dataflow": "视觉+触觉→动作流 (力控端到端)",
        "features": {"A1", "A2", "A3", "A4", "B1", "B5", "C1", "C3", "C4",
                     "D1", "D2", "E1", "E2", "E3", "F1", "F2", "G1", "G2",
                     "G3", "H1", "H3"},
    },
    "yolo": {
        "name": "YOLO 感知",
        "abstract": "感知（例YOLO）",
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


def build_model_feature_item(module):
    """数据字典树顶级节点: 🧩 Feature Registry 特征库 + 当前模型组合"""
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

    # 📂 特征库 8 大类 (三要素: 解释/信号/场景)
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
            QTreeWidgetItem(ft, ["解释", f["explain"]])
            QTreeWidgetItem(ft, ["信号", f["io"]])
            QTreeWidgetItem(ft, ["接口", f"对应 {f['iface']}"])
            QTreeWidgetItem(ft, ["场景", f["scene"]])
            QTreeWidgetItem(ft, ["工程映射", f["eng"]])
            QTreeWidgetItem(ft, ["适用", f["app"]])

    # 📦 当前模型组合 (Manifest)
    if manifest:
        mf = QTreeWidgetItem(
            [f"📦 当前模型 · {manifest['name']} ({manifest.get('abstract', '')} · {manifest['dataflow']})", ""])
        mf.setData(0, Qt.UserRole, None)
        root.addChild(mf)
        ids_sel = sorted(sel)
        ids_all = {f["id"] for _, items in FEATURE_LIBRARY for f in items}
        QTreeWidgetItem(mf, ["选用特征", f"{len(sel)} 项: " + " ".join(ids_sel)])
        QTreeWidgetItem(mf, ["未选用", " ".join(sorted(ids_all - sel))])
        repl = QTreeWidgetItem(["🔄 可替换机制 (模块化)", ""])
        repl.setData(0, Qt.UserRole, None)
        mf.addChild(repl)
        QTreeWidgetItem(repl, ["接入标准", "第三方模型注册 Manifest + 缺失特征适配器 → 同接口运行"])
        QTreeWidgetItem(repl, ["复用机制", "特征库可复用/可增加/可组合 (参考 LeRobot @register_subclass)"])
        QTreeWidgetItem(repl, ["生态标准", "PretrainedPolicy 接口 · LeRobotDataset 格式 · ProcessorStep 管道"])
    return root
