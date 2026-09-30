# -*- coding: utf-8 -*-
"""档位视图 (by_level) —— 按 L2/L3/L4/L5 把节点逻辑索引出来 (自动生成, 勿手改)。

生成: `gui-venv311/bin/python tools/verify_engineering.py --regen-by-level`
真源: `..nodes.library` (逻辑) + `..registry` (key↔函数) + `..flows.state_space_obs.json` (画布) + `..levels` (档位归属)

用途: 一眼看清"这一档有哪些节点、每个节点落到哪个函数、函数在哪个文件" ——
GUI 只显示, 逻辑在包里, 这份索引就是把两边对上的那张表。
"""

LEVELS_INDEX = {
    "L2": [
        ("sssensor", "📡 融合定位", 'ss_sensor', "library.py", 'node_ss_s1'),
        ("ssobs", "🧩 SU(2) 统一状态空间 (二阶特殊酉群)", 'ss_obs', "library.py", 'node_ss_su2'),
        ("ssff", "⚡ 前馈加速器", 'ss_ff', "library.py", 'node_ss_s2'),
        ("ssest", "🔮 自适应状态估计器", 'ss_est', "library.py", 'node_ss_s2'),
        ("sspred", "📈 先验动力学预测器", 'ss_dyn', "library.py", 'node_ss_dyn'),
        ("ssinnov", "🧪 状态校正器", 'ss_correct', "library.py", 'node_ss_dyn'),
        ("sssched", "🧭 动作调制器", 'ss_sched', "library.py", 'node_ss_s3'),
        ("ssact", "🤖 机器人执行器", 'ss_act', "library.py", 'node_ss_exec'),
        ("ssworld", "🌍 物理世界", 'ss_world', "library.py", 'node_ss_exec'),
        ("ssyolo", "🎯 YOLO 目标检测", 'ss_yolo', "library.py", 'node_ss_yolo'),
        ("ss2d3d", "📐 2D→3D 解算", 'yolo_align', "library.py", 'node_yolo_align'),
        ("sstactile", "🖐 触觉感知", 'yolo_tactile', "library.py", 'node_yolo_tactile'),
        ("ssaoi", "🔍 外观质量检测", 'ss_aoi', "library.py", 'node_ss_aoi'),
        ("sssk2", "② 对位 · SK02", 'sssk2', "library.py", 'node_ss_atomic'),
        ("sssk3", "③ 下降 · SK03", 'sssk3', "library.py", 'node_ss_atomic'),
        ("sssk4", "④ 抓取 · SK04", 'sssk4', "library.py", 'node_ss_atomic'),
        ("sssk5", "⑤ 抬起 · SK05", 'sssk5', "library.py", 'node_ss_atomic'),
        ("sssk6", "⑥ 转移 · SK06", 'sssk6', "library.py", 'node_ss_atomic'),
        ("sssk7", "⑦ 插入 · SK07", 'sssk7', "library.py", 'node_ss_atomic'),
        ("sssk8", "⑧ 完成 · SK08", 'sssk8', "library.py", 'node_ss_atomic'),
        ("ss_mem_l2", "🔧 L2 · 肌肉记忆操作 (小脑 · 标杆回放)", 'ss_mem_l2', "mem_nodes.py", 'node_ss_mem_l2'),
        ("n_board_frame", "📐 板坐标系定位 (工序坐标系·免手眼)", 'n_board_frame', "library.py", 'node_n_board_frame'),
        ("n_l2_muscle", "💪 L2 肌肉记忆技能库 (光模块抓放循环)", 'n_l2_muscle', "library.py", 'node_n_l2_muscle'),
        ("ss_moe", "🧬 阶段专家 MOE · 7 专家 + 先验门控路由 (在役)", 'ss_moe', "library.py", 'node_ss_moe'),
        ("n_moveit", "🧭 MoveIt 运动规划 · SDK 直驱桥(Orin)", 'n_moveit', "library.py", 'node_moveit'),
        ("ss_seg", "🧩 开放词汇分割 (SAM3 分割anything)", 'ss_seg', "library.py", 'node_ss_seg'),
    ],
    "L3": [
        ("ssskill", "🛠 L3 技能序列编排", 'ss_skill', "library.py", 'node_ss_skill'),
        ("ssvlm", "🧠 VLM 通用视觉编码器 (SmolVLA)", 'ss_vlm', "library.py", 'node_ss_vlm'),
        ("ssdec", "🎯 Flow-Matching Action Head (DiT)", 'action_head', "library.py", 'node_action_head'),
        ("ss_mem_l3", "🚀 L3 · 长程序列规划 (记忆: 海马体)", 'ss_mem_l3', "mem_nodes.py", 'node_ss_mem_l3'),
        ("ss_lora_l3", "🎛 L3 · SmolVLA LoRA 微调 · 接入中", 'ss_lora_l3', "library.py", 'node_ss_lora_l3'),
    ],
    "L4": [
        ("sscalib", "🧮 标定层 · 引力-斥力-动作", 'ss_calib', "library.py", 'node_ss_calib'),
        ("ssmani_c", "🧮 接触流形 · 导航地图 (e∥进度/e⊥偏离)", 'ss_mani_c', "library.py", 'node_ss_mani'),
        ("ssmani_p", "🧮 性能流形 · 耦合代价 (V_p/η)", 'ss_mani_p', "library.py", 'node_ss_mani'),
        ("sslat", "🧮 潜空-流形", 'ss_lat', "library.py", 'node_ss_lat'),
        ("ssintact", "🎯 INTACT (L4) · 工作安全 + 物理世界导航", 'intact', "library.py", 'node_intact'),
        ("ssintact_dec", "🎯 INTACT 意图解码器 (L4 → L3 条件)", 'intact_dec', "library.py", 'node_intact_dec'),
        ("ssmani_exp", "🧠 流形专家预测器 (JEPA: 潜空间→流形→动作)", 'ss_pred', "library.py", 'node_ss_pred'),
        ("sscap", "🧭 能力档位", 'ss_cap', "library.py", 'node_ss_cap'),
        ("ss_mem_l4", "🏆 L4 · 工作安全 + 物理世界导航 (记忆: 前额叶)", 'ss_world', "library.py", 'node_ss_exec'),
        ("ss_mem_field", "🧲 总装机记忆 · 势场联络 (L2/L3/L4 势场 → 意图 −∇Φ)", 'ss_mem_field', "mem_nodes.py", 'node_ss_mem_field'),
        ("ss_mem_share", "🧠 总装记忆中枢 (前额叶总装 · 三层协同)", 'ss_mem_share', "mem_nodes.py", 'node_ss_mem_share'),
        ("n_intent_bundle", "🧠 意图丛 · 四槽语法", 'ss_intent_bundle', "mem_nodes.py", 'node_ss_intent_bundle'),
        ("n_intent_direct", "🔮 意图直读 · Direct", 'ss_intent_direct', "mem_nodes.py", 'node_ss_intent_direct'),
        ("swintact", "🎯 INTACT 插拔策略 · 光模块抓取插入 (本域微调 · 零搜索)", 'sw_intact', "library.py", 'node_sw_intact'),
        ("swworld", "🌍 Z-MAX 引擎 · 光模块插拔真物理 (模型动作真下发 env.step)", 'sw_world', "library.py", 'node_sw_world'),
        ("ss_lora_l4", "🎛 L4 · INTACT LoRA 微调 (r8/α16) · 接入中", 'ss_lora_l4', "library.py", 'node_ss_lora_l4'),
        ("ss_mani_eng", "🧮 流形引擎 (Manifold Engine · 编码→投影→度量→导航→反馈)", 'ss_mani_eng', "library.py", 'node_ss_mani_eng'),
        ("n_calib_mani", "🧮 流形引擎标定 · 主参数 M (状态空间结构参数 · 等效惯量)", 'n_calib_mani', "library.py", 'node_ss_calib_mani'),
    ],
    "L5": [
        ("ssllm_in", "📝 任务指令 · MES/自然语言", 'ss_llm_in', "library.py", 'node_ss_llm_in'),
        ("ssllm", "🧠 L3 长程序列规划器 (场景理解驱动)", 'ss_llm', "library.py", 'node_ss_llm'),
        ("ssreason", "🔍 异常推理器 (LLM)", 'ss_reason', "library.py", 'node_ss_reason'),
        ("n_skill_dict", "🧬 技能词典 · L2 动作基", 'ss_skill_dict', "mem_nodes.py", 'node_ss_skill_dict'),
        ("n_mem_links", "🔗 跨层连接 · 记忆图谱", 'ss_mem_links', "mem_nodes.py", 'node_ss_mem_links'),
        ("n_eng_mem", "📚 工程记忆 · 技能与经验库", 'n_eng_mem', "library.py", 'node_ss_eng_mem'),
        ("n_vlm_llm", "👁 视觉语言大模型 · 场景理解 (Qwen2.5/3-VL)", 'n_dsvl', "library.py", 'node_dsvl'),
        ("n_dsvl", "🧿 DeepSeek-V4-Flash · 场景理解 (L5 大模型主路)", 'n_dsvl', "library.py", 'node_dsvl'),
        ("n_web_agent", "🌐 Web 智能体桥 · 远程提示词", 'n_web_agent', "library.py", 'node_web_agent'),
        ("n_hil", "🙋 HIL 人机在环 · 状态↔指示", 'n_hil', "library.py", 'node_hil'),
        ("ss_l5", "🧿 L5 · 视觉语言自动标注 → L2/L3/L4 监督 → 自动训练", 'l5_loop', "library.py", 'node_l5_loop'),
    ],
    "meta": [
        ("ssvideo", "📊 仿真波形", 'ss_scope', "library.py", 'node_ss_scope'),
        ("ssvideo2", "🎥 操作视频", 'ss_video', "library.py", 'node_ss_video'),
        ("ssdata", "📦 metaworld 数据源", 'data', "library.py", 'node_metaworld_data'),
        ("ssmode", "🔀 训练/推理", 'mode_switch', "library.py", 'node_mode_switch'),
        ("ssfeat", "🧩 Feature 功能清单", 'ss_feature', "library.py", 'node_ss_feature'),
        ("ssff_hist", "🧠 前馈激活直方图", 'ss_ff_hist', "library.py", 'node_ss_ff_hist'),
        ("ss3d_view", "🧭 3D 视图", 'ss_3d_view', "library.py", 'node_ss_3d_view'),
        ("ssbypv", "📈 旁路实时可视化 (当前阶段/残差/接触概率)", 'ss_bypass_viz', "library.py", 'node_ss_bypass_viz'),
        ("ssz700", "🖥 Z700 真机信号 (全信号观测 · 物理世界输出)", 'ss_z700_signals', "library.py", 'node_ss_z700_signals'),
        ("swds", "🧪 光模块插拔 · 环境渲染图像源 (Z-MAX 引擎逐帧真图)", 'sw_ds', "library.py", 'node_sw_ds'),
        ("swvideo", "🎬 插拔渲染视频 (从 Z-MAX 引擎取出 · 实况窗)", 'sw_video', "library.py", 'node_sw_video'),
        ("n_realscene", "🎥 真实场景叠加 · 双眼 (sim2real)", 'n_realscene_live', "library.py", 'node_realscene_live'),
    ],
}


def keys_of(level):
    """该档位的逻辑 key 列表 (可执行/可查源码)"""
    return [r[2] for r in LEVELS_INDEX.get(level, []) if r[2]]


def funcs_of(level):
    """该档位 key → 真函数"""
    from ..registry import get
    return {k: (get(k) or {}).get("fn") for k in keys_of(level)}


def summary():
    return {lv: {"nodes": len(rows), "with_logic": len([r for r in rows if r[2]])}
            for lv, rows in LEVELS_INDEX.items()}


if __name__ == "__main__":
    import json as _j
    print(_j.dumps(summary(), ensure_ascii=False, indent=2))
