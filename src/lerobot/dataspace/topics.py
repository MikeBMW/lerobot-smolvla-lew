#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌐 Z-MAX 全局数据空间 (Global Data Space) —— **权威映射表 · 单一真源**

老倪 2026-09-29: 「构建全局数据空间的映射关系, 要有数据闭环流程 …… 应用 DDS 技术,
全面数据质量管理, 做到全链路 topic 可视化」

本文件 = 全局数据空间的**映射表本身**(不是文档): 谁发什么/谁消费/频率/QoS/质量判据,
以及数据闭环每一环节的入口·产物·质量门·证据来源。控制台(DreamView 风格)、守护进程、
巡检脚本、网页都从**这一处**读, 不许再各写一份。

三层映射 (老倪的分层口径):
  ① 物理层  话题 ↔ IDL 类型 ↔ QoS ↔ 频率      → TOPICS
  ② 语义层  话题 ↔ 生产者/消费者 ↔ 画布节点   → TOPICS[*]["producer"/"consumers"] + node 字段
  ③ 闭环层  环节 ↔ 输入/产物 ↔ 质量门         → CLOSED_LOOP

规矩:
  · 缺测 = -1.0, **不许用 0 冒充**(0 是合法实测值)  —— 全空间统一
  · 每个字段必须能追到真实来源; 追不到的不许进表(标 unverified 并写明为什么)
  · prod 模式 = 量产零开销(不建 DDS 参与者); diag/calib/test = 各自话题子集
"""

# ─────────────────────── 元信息 ───────────────────────
VERSION = "1.0.0"
UPDATED = "2026-09-29"
DDS_PREFIX = "zmax/"          # 实际话题名 = DDS_PREFIX + key  (见 zmax_dds/zmax_node.py:95)

# 类型定义真源(当前在仓库外, 见 "收口计划")
TYPES_SRC = "/home/ubuntu/zmax_dds/ss_types.py"      # 9 个状态空间类型
TYPES_SRC_HW = "/home/ubuntu/zmax_dds/zmax_types.py"  # 4 个三端类型
TYPES_SRC_LINK = "tools/gui/dds_link_bus.py"          # link_value (画布连线值)

# ─────────────────────── ① 物理层: 话题表 ───────────────────────
# qos: state = RELIABLE·KEEP_LAST(1)·TRANSIENT_LOCAL(latch, 新订阅者立刻拿最新)
#      beat  = BEST_EFFORT·KEEP_LAST(1)          (丢帧无妨, 低延迟)
#      cmd   = RELIABLE·KEEP_ALL                 (一条都不许丢)
QOS_LABEL = {
    "state": "RELIABLE·KEEP_LAST(1)·TRANSIENT_LOCAL",
    "beat": "BEST_EFFORT·KEEP_LAST(1)",
    "cmd": "RELIABLE·KEEP_ALL",
}

TOPICS = {
    # ── 三端(4060/Orin/Mac/ECS) ──────────────────────────────────────────
    "hw_state": {
        "type": "zmax::HardwareState", "src": TYPES_SRC_HW, "rate_hz": 0.33, "qos": "state",
        "producer": "zmax_dds_publisher.py --interval 3 (zmax-dds-pub.service)",
        "consumers": ["zmax_dds_aggregator.py → JSON", "控制台 硬件页/数据空间页", "网页工位总览"],
        "modes": ["diag", "calib", "test"],
        "key_fields": ["node", "role", "backend", "util_pct", "mem_used_mb/mem_total_mb",
                       "temp_c", "power_w", "cpu_util_pct", "disk_free_gb", "train_steps_per_s"],
        "quality": ["freshness", "hz_tol", "no_zero_fake", "range", "unit"],
        "provenance": "nvidia-smi / /proc / torch.backends.mps",
    },
    "train_prog": {
        "type": "zmax::TrainProgress", "src": TYPES_SRC_HW, "rate_hz": 0.33, "qos": "state",
        "producer": "训练脚本写进度文件 → zmax_dds_publisher.py",
        "consumers": ["zmax_dds_aggregator.py → JSON", "控制台 训练/数据空间页"],
        "modes": ["diag", "test"],
        "key_fields": ["job", "layer", "step/total/pct", "loss", "best_obs", "best_act",
                       "gain_obs_pct", "gain_act_pct", "running"],
        "quality": ["freshness", "hz_tol", "loss_finite", "gain_reported", "monotonic_step"],
        "provenance": "训练进度文件(真实逐 N 步写出)",
    },
    "deploy_cmd": {
        "type": "zmax::DeployCommand", "src": TYPES_SRC_HW, "rate_hz": 0.0, "qos": "cmd",
        "producer": "ECS / 控制台(人工晋级)",
        "consumers": ["4060 部署执行", "Orin 部署执行"],
        "modes": ["test"],
        "key_fields": ["issuer", "layer", "artifact", "action(promote/rollback/stop_train)", "note"],
        "quality": ["audit_issuer", "artifact_exists"],
        "provenance": "人工/守护发起的晋级指令",
    },
    "heartbeat": {
        "type": "zmax::Heartbeat", "src": TYPES_SRC_HW, "rate_hz": 0.2, "qos": "beat",
        "producer": "各端守护", "consumers": ["zmax_dds_aggregator.py", "控制台节点灯"],
        "modes": ["diag", "calib", "test"],
        "key_fields": ["node", "role", "alive", "extra"],
        "quality": ["liveness", "freshness"],
        "provenance": "各端进程自身",
    },
    # ── 状态空间 ────────────────────────────────────────────────────────
    "ss_state": {
        "type": "zmax::SSState", "src": TYPES_SRC, "rate_hz": 10.0, "qos": "beat",
        "producer": "zmax_dds_ss_daemon.py ← 真机只读 tap ~/zmax_ss_remote/state_*.jsonl",
        "consumers": ["控制台 数据空间页/状态空间页", "备份端"],
        "modes": ["calib", "test"],
        "key_fields": ["ts", "layer", "stage", "vec/dim", "manifold_theta", "manifold_norm",
                       "pos_x/y/z", "lyap_v/lyap_dv", "source"],
        "quality": ["freshness", "hz_tol", "negative_age_reject", "dim_match", "no_zero_fake"],
        "provenance": "真机 tap(只读) / 引擎 / 仿真 —— source 字段自述",
    },
    "ss_action": {
        "type": "zmax::SSAction", "src": TYPES_SRC, "rate_hz": 10.0, "qos": "beat",
        "producer": "zmax_dds_ss_daemon.py ← tap proposal_*.jsonl (本机推理 8790 输出)",
        "consumers": ["控制台 数据空间页", "审计(动作必须可追闸门)"],
        "modes": ["calib", "test"],
        "key_fields": ["ts", "kind(joint/tcp/gripper/rt)", "joints", "tcp_pose", "gripper",
                       "speed", "gate_pass", "gate_reason", "source"],
        "quality": ["freshness", "hz_tol", "gate_audit", "dim_match", "no_zero_fake", "finite"],
        "provenance": "推理输出 / 真机下发记录",
    },
    "ss_infer": {
        "type": "zmax::SSInfer", "src": TYPES_SRC, "rate_hz": 0.5, "qos": "beat",
        "producer": "zmax_dds_ss_daemon.py ← http://127.0.0.1:8790/health",
        "consumers": ["控制台 推理页/数据空间页"],
        "modes": ["diag", "test"],
        "key_fields": ["ts", "model", "layer", "latency_ms", "device", "out_vec", "conf", "ok"],
        "quality": ["freshness", "hz_tol", "latency_budget", "no_zero_fake"],
        "provenance": "本机推理服务 /health(真实推理计数)",
    },
    "ss_canvas": {
        "type": "zmax::SSCanvasNode", "src": TYPES_SRC, "rate_hz": 0.5, "qos": "state",
        "producer": "画布/引擎节点状态上报",
        "consumers": ["控制台 画布页/数据空间页"],
        "modes": ["test"],
        "key_fields": ["ts", "node_id", "name", "layer", "status", "fps", "last_ms", "counter"],
        "quality": ["freshness", "hz_tol", "name_primary", "status_enum"],
        "provenance": "节点真实执行(每次 run 一行)",
    },
    "ss_macro": {
        "type": "zmax::SSMacro", "src": TYPES_SRC, "rate_hz": 0.2, "qos": "state",
        "producer": "五层记忆/宏观层(SS_MACRO)",
        "consumers": ["控制台 记忆页/数据空间页"],
        "modes": ["test"],
        "key_fields": ["ts", "layer_name", "intent", "plan", "progress", "recalled"],
        "quality": ["freshness", "hz_tol", "layer_enum", "progress_range"],
        "provenance": "总装 Qwen / 记忆层",
    },
    "ss_nodes": {
        "type": "zmax::SSNodes", "src": TYPES_SRC, "rate_hz": 0.2, "qos": "state",
        "producer": "数据空间自描述(谁在发什么)",
        "consumers": ["控制台 数据空间页(节点清单)"],
        "modes": ["test"],
        "key_fields": ["ts", "nodes", "topics", "publish_hz"],
        "quality": ["freshness", "hz_tol", "self_describe_match"],
        "provenance": "发布端自述 —— **必须与实测频率对账**, 否则是假自述",
    },
    "ss_calib": {
        "type": "zmax::SSCalib", "src": TYPES_SRC, "rate_hz": 0.2, "qos": "state",
        "producer": "zmax_dds_ss_daemon.py ← 标定真源文件(calib.json/handeye/align/gate)",
        "consumers": ["控制台 标定页/数据空间页", "现场核对(mm/deg 口径)"],
        "modes": ["calib", "test"],
        "key_fields": ["ts", "kind", "src_frame/dst_frame", "T(16)", "plane_z_mm", "tx/ty/tz",
                       "rx/ry/rz_deg", "rms_mm", "samples", "valid"],
        "quality": ["freshness", "valid_flag", "rms_budget", "no_zero_fake", "unit"],
        "provenance": "标定真源文件(与 zmax_params.py 同源)",
    },
    "ss_diag": {
        "type": "zmax::SSDiag", "src": TYPES_SRC, "rate_hz": 0.5, "qos": "beat",
        "producer": "zmax_dds_ss_daemon.py(延时/帧龄/吞吐/健康度)",
        "consumers": ["控制台 监控页/数据空间页", "运维告警"],
        "modes": ["diag", "calib", "test"],
        "key_fields": ["ts", "node", "kind", "latency_ms", "frame_age_s", "hz", "count",
                       "dropped", "queue", "health", "level", "msg"],
        "quality": ["freshness", "hz_tol", "negative_age_reject", "range", "level_enum"],
        "provenance": "实测(非估算)",
    },
    "ss_test": {
        "type": "zmax::SSTest", "src": TYPES_SRC, "rate_hz": 0.0, "qos": "state",
        "producer": "取证/回归脚本(verify_*.py / preflight)",
        "consumers": ["控制台 评估页/数据空间页"],
        "modes": ["test"],
        "key_fields": ["ts", "suite", "case", "passed", "dur_ms", "total", "failed", "detail"],
        "quality": ["counts_consistent(total = passed + failed)"],
        "provenance": "最近一次真跑的取证 JSON",
    },
    "link_value": {
        "type": "zmax::LinkValue", "src": TYPES_SRC_LINK, "rate_hz": 5.0, "qos": "beat",
        "producer": "画布连线总线(dds_link_bus)",
        "consumers": ["控制台 画布页(节点间传值可视化)"],
        "modes": ["calib", "test"],
        "key_fields": ["link", "value", "src_node", "dst_node"],
        "quality": ["freshness", "hz_tol", "finite"],
        "provenance": "画布上真实连线求值",
    },
}

# ─────────────────────── 遥测模式 → 允许话题 (口径与守护一致) ───────────────────────
# ⚠️ 真源当前是 /home/ubuntu/zmax_dds_ss_daemon.py:51 (MODE_TOPICS) 与
#    tools/gui/zmax_telemetry.py::MODE_TOPICS —— 两处手工同步, 收口后本表为准。
MODE_TOPICS = {
    "prod":  [],
    "diag":  ["hw_state", "heartbeat", "ss_infer", "train_prog", "ss_diag"],
    "calib": ["ss_state", "ss_action", "link_value", "hw_state", "heartbeat", "ss_calib", "ss_diag"],
    "test":  ["hw_state", "heartbeat", "train_prog", "deploy_cmd", "link_value", "ss_state",
              "ss_action", "ss_infer", "ss_canvas", "ss_macro", "ss_nodes", "ss_calib",
              "ss_diag", "ss_test"],
}
MODE_TOPICS["dev"] = MODE_TOPICS["test"]
MODE_DESC = {
    "prod":  "量产: 零开销 —— 不建 DDS 参与者、不开口、不 import cyclonedds",
    "diag":  "诊断: 只取性能/硬件类(不碰状态与标定)",
    "calib": "标定: 状态+动作+连线+标定量(现场核对用)",
    "test":  "测试: 全量 14 话题(取证/回归)",
    "dev":   "同 test",
}

# ─────────────────────── ② 语义层: 话题 ↔ 生产者/消费者 ───────────────────────
# 画面上的「节点」= 生产者进程 与 消费者进程; 中间是话题。画布节点与话题的绑定在
# TOPICS[*]["producer"] 里点名的脚本 → 脚本注册的画布节点(见 nodes/library.py)。
PRODUCERS = {
    "4060-硬件发布端": {"unit": "zmax-dds-pub.service", "path": "/home/ubuntu/zmax_dds_publisher.py",
                        "publishes": ["hw_state", "train_prog"]},
    "状态空间数据空间守护": {"unit": "zmax-dds-ss.service", "path": "/home/ubuntu/zmax_dds_ss_daemon.py",
                        "publishes": ["ss_state", "ss_action", "ss_infer", "ss_calib", "ss_diag",
                                      "ss_test", "ss_canvas", "ss_macro", "ss_nodes"]},
    "DDS→relay 汇聚器": {"unit": "zmax-dds-agg.service", "path": "/home/ubuntu/zmax_dds_aggregator.py",
                        "publishes": [], "subscribes": ["hw_state", "train_prog", "heartbeat"]},
    "画布连线总线": {"unit": None, "path": "tools/gui/dds_link_bus.py",
                        "publishes": ["link_value"]},
}

# ─────────────────────── ③ 闭环层: 数据闭环流程 ───────────────────────
# 每个环节: entry(入口命令) · produces(产物) · gate(质量门 + 判据) · evidence(证据来源) · owner
CLOSED_LOOP = [
    {
        "id": "S0", "name": "采数前自检",
        "entry": "现场核对: 标定 ss_calib.valid=1 · TCP 位姿新鲜(rokae_sdk/tcp_out/latest.json) · 相机帧龄≤1s",
        "produces": "—(门)", "owner": "人/静静",
        "gate": "全绿才许开采集: 手眼 rms≤2mm · TCP 非全 0 · 帧龄>0 且 <1s",
        "evidence": "ss_calib 话题 / latest.json / 8793 工位总览横幅",
        "why": "标定不对 ⇒ 采到的 3D 全是错的, 整轮数据作废(比采不到更贵)",
    },
    {
        "id": "S1", "name": "真机采集",
        "entry": "Orin 侧采集脚本(20s MCAP + 打标)", "owner": "现场/Orin",
        "produces": "数据包: observation.state(6) + action(6) + 图 + label + timestamp",
        "gate": "帧数≥20 · 维度一致(6D) · 图像有效帧率>0 · action≠state(恒等=无效)",
        "evidence": "包内 meta.frames / n_joint / n_action",
        "why": "action==state 的包会让训练学出恒等映射(历史上真踩过)",
    },
    {
        "id": "S2", "name": "上传中转",
        "entry": "POST https://datadrive.world/api/relay/upload", "owner": "Orin 侧",
        "produces": "ECS relay 队列(单包≤100M)", "gate": "上传回执 + 包内帧数/维度一致 + 校验和一致",
        "evidence": "GET /api/relay/status · /api/relay/peek",
        "why": "弹栈取走即删 ⇒ 必须留 peek 先验后取",
    },
    {
        "id": "S3", "name": "入库质量门",
        "entry": "本地弹栈 → 质检 → 构建 LeRobot 数据集(build_orin6d_dataset.py)", "owner": "静静",
        "produces": "LeRobot 数据集(parquet + mp4, 全局 frame_index/timestamp)",
        "gate": "帧数=视频帧数 · 时间戳单调(禁回拨) · float32 定长列表 · episodes 索引 int64",
        "evidence": "数据集 meta/info.json + 逐帧对账脚本",
        "why": "时间戳/索引不全局 ⇒ 训练 IndexError + 视频错位",
    },
    {
        "id": "S4", "name": "训练",
        "entry": "ACT 三阶段(S1 冻结→S2 零样本→S3 真机低 lr 微调, ensemble 必开)", "owner": "静静(4060)",
        "produces": "ckpt + 训练进度文件", "gate": "GPU 负载达标 · loss 有限且下降 · 每 N 步落进度",
        "evidence": "train_prog 话题 / 训练日志", "why": "掉载=每步 CPU 开销 > 计算",
    },
    {
        "id": "S5", "name": "评测",
        "entry": "同口径评测(训练同源预处理 + 留出集 + 平凡基线)", "owner": "静静",
        "produces": "评测 JSON(passed/total/成功率)", "gate": "**有提升**才放行(非仅不回退) · 平凡基线对照",
        "evidence": "ss_test 话题 / reports/*.json", "why": "loss 低≠有效; 不回退≠提升",
    },
    {
        "id": "S6", "name": "发布",
        "entry": "推静态 URL + sha256 + 版本号", "owner": "静静",
        "produces": "https://datadrive.world/models/<name>.safetensors (644)", "gate": "sha256 与本地一致 · HTTP 200 · 可匿名拉取",
        "evidence": "curl -sI 静态 URL", "why": "弹栈队列传模型丢过 4 次",
    },
    {
        "id": "S7", "name": "部署",
        "entry": "DeployCommand(issuer/layer/artifact/action) over DDS → Orin", "owner": "静静/人",
        "produces": "Orin 上的在役权重", "gate": "issuer 可追 · artifact 存在且 sha256 匹配 · 留旧版可回滚",
        "evidence": "deploy_cmd 话题 + 部署日志", "why": "部署是唯一不可逆动作 ⇒ 必须带审计与回滚点",
    },
    {
        "id": "S8", "name": "真实推理与回采",
        "entry": "Orin 真机推理(8790 / Orin 侧)", "owner": "现场",
        "produces": "推理计数 + 真实成功率 + 失败样本", "gate": "infer_count>0 · 成功率按任务口径统计 · 失败帧归档回采",
        "evidence": "ss_infer 话题 / /api/relay/orin/status",
        "why": "无回采 = 开环; 失败样本是下一轮数据的主料",
    },
]

# ─────────────────────── 全面数据质量: 判据(规则 id → 定义) ───────────────────────
QUALITY_RULES = {
    "freshness":        "帧龄 = now - ts, 超阈值(默认 5s) → 只报 diag、状态类降级",
    "negative_age_reject": "ts > now+1 ⇒ 拒用(本机 NTP 曾有 8h 回拨)",
    "no_zero_fake":     "未测量必须 -1.0; 统计字段里 0 的占比 ≈100% 判为假 0",
    "dim_match":        "vec 长度 == dim, 且与声明维度(6 关节/39 观测)一致",
    "monotonic_step":   "训练 step 单调不减; 回退 ⇒ 重启/覆盖, 要标记",
    "loss_finite":      "loss 为有限数(NaN/Inf 直接告警)",
    "gain_reported":    "提升必须带平凡基线对照的 %(缺 = 未证明)",
    "range":            "物理量在合理区间(利用率 0~100, 温度 -20~100)",
    "unit":             "单位与命名一致(util_pct / mem_mb / plane_z_mm / *_deg)",
    "latency_budget":   "推理延时 ≤ 预算(MoE 稳态 101ms, 冷启 6.7s 不算违规)",
    "liveness":         "心跳缺失 > 3×周期 ⇒ 节点掉线",
    "valid_flag":       "标定量 valid=1 才算数(缺测 valid=0/-1)",
    "rms_budget":       "手眼残差 ≤2mm(超 = 标定不合格, 不许用)",
    "audit_issuer":     "指令必须有 issuer(谁发的), 匿名指令拒收",
    "artifact_exists":  "指令里的产物路径必须真实存在",
    "self_describe_match": "自述话题/频率 vs 实测订阅/实测 Hz 对账",
    "counts_consistent": "total == passed + failed",
    "status_enum":      "状态取值必须在枚举内(pending/running/success/failed)",
    "layer_enum":       "层名必须在枚举内(L2/L3/L4/L5/meta)",
    "progress_range":   "进度 0..1",
    "gate_audit":       "动作必须带闸门判定(gate_pass≠-1)与原因",
    "finite":           "数值必须有限",
    "name_primary":     "以 name 为主键(id 重生会变)",
}


# ─────────────────────── 小工具 ───────────────────────
def full_name(key: str) -> str:
    """短名 → 真实话题名 (zmax/ss_state 等)"""
    return DDS_PREFIX + key


def topics_for_mode(mode: str):
    """该模式允许的话题 key 列表"""
    return list(MODE_TOPICS.get((mode or "prod").strip().lower(), []))


def summary():
    """给控制台/巡检用的一行摘要"""
    return {
        "version": VERSION, "updated": UPDATED,
        "n_topics": len(TOPICS), "n_rules": len(QUALITY_RULES),
        "n_stages": len(CLOSED_LOOP),
        "modes": {m: len(t) for m, t in MODE_TOPICS.items()},
    }


if __name__ == "__main__":
    import json
    print(json.dumps(summary(), ensure_ascii=False, indent=2))
    print("话题:", ", ".join(sorted(TOPICS)))
    for t, d in TOPICS.items():
        q = d["quality"] if isinstance(d["quality"], list) else [d["quality"]]
        print("  %-12s %-12s %5.2fHz  %-6s  质量规则 %d 条" % (t, d["type"], d["rate_hz"], d["qos"], len(q)))
