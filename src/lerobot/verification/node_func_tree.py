# -*- coding: utf-8 -*-
"""node_func_tree.py — 🧩 功能清单三级注册表 (2026-09-04 老倪重构规格)

结构: 节点 (画布节点) → 功能 (每节点 ≥5, 名称 5~10 字, 模块化可组合)
      → 测试用例 (每功能 5 条: 自动断言 auto / 半自动 semi / 手动 manual)

数学骨架 (工艺纤维丛 Process Fiber Bundle, 老倪 2026-09-04):
  底空间 B   = 产品物理状态流形   → 功能标签: 状态观测 (感知/状态/几何)
  纤维 F     = 工序动作与参数空间 → 功能标签: 工艺动作 (执行/技能)
  投影 π     = 工艺执行与状态转移 → 功能标签: 状态转移 (引擎推进)
  联络 ∇     = SOP 与闭环控制算法 → 功能标签: 闭环联络 (控制/调度/标定)
  截面 σ     = 量产工艺配方       → 功能标签: 质量截面 (检测/评估/诊断)
  曲率 R     = 不可逆工艺损耗      → 由「质量截面」功能持续监测 (残差/η/漂移)

每条用例: (desc, kind, ref) — ref 指向 VerificationLayer 的 t_* 断言方法名
(自动可跑) 或 None (手动, desc 即验收步骤)。半自动 semi = 需 DISPLAY/权重/人眼。

模块化约定: 功能名全局唯一前缀 FN<node>_<序号>, 节点间功能可通过
「功能组合链」引用 (见下 FUNC_CHAINS, 对应纤维丛的截面合成)。
"""
# 节点 key 与画布 flows/state_space_obs.json 的 id 一致
# 每节点字段: name 画布名 | fb 纤维丛标签 | funcs [功能...]
# 每功能: fid | name (5~10字) | desc | tests [(用例desc, kind, ref_or_None, step)]
#   step: 手动/半自动的验收步骤 (自动用例可空)

NODE_TREE = {
    "ssdata": {
        "name": "📦 metaworld 数据源", "fb": "底空间·状态观测",
        "funcs": [
            {"fid": "FNdata01", "name": "训练数据探测", "desc": "探测本机 metaworld 数据集根目录与规模",
             "tests": [
                 ("数据源根目录可定位", "auto", "t_ssdata_probe", ""),
                 ("帧/集/特征计数正确", "auto", "t_ssdata_count", ""),
                 ("多候选路径容错", "auto", "t_ssdata_fallback", ""),
                 ("数据源切换生效", "manual", None, "画布双击数据源节点切换 → 节点徽标更新, 日志打印新源"),
                 ("真实断点可进入", "manual", None, "右键数据源节点→打开 VSCode 调试→断点设在 datasets/metaworld_data_source.py 首行→运行节点必停"),
             ]},
            {"fid": "FNdata02", "name": "现场环境加载", "desc": "metaworld 环境与任务 (peg-insert-side-v3) 加载",
             "tests": [
                 ("任务名解析成功", "auto", "t_ssdata_env", ""),
                 ("渲染模式可用", "semi", "t_ssdata_env_render", "需 DISPLAY: 真渲染 1 帧非空"),
                 ("环境重置无异常", "auto", "t_ssdata_env_reset", ""),
                 ("环境唯一实例复用", "auto", "t_ssdata_env_singleton", ""),
                 ("换任务不串状态", "manual", None, "加载两个任务名→观测维度/动作维度各自正确"),
             ]},
            {"fid": "FNdata03", "name": "观测维数对齐", "desc": "39D 状态流维数与动作 4D 契约",
             "tests": [
                 ("状态流恒 39 维", "auto", "t_ssdata_dim39", ""),
                 ("动作流恒 4 维", "auto", "t_ssdata_dim4", ""),
                 ("末端段位语义正确", "auto", "t_ssdata_seg", ""),
                 ("越界索引防御", "auto", "t_ssdata_oob", ""),
                 ("数据与画布契约一致", "manual", None, "比对数据源输出与画布「43D 统一状态向量」节点显示维数"),
             ]},
            {"fid": "FNdata04", "name": "数据流转发布", "desc": "数据源 → 数据世界逐帧发布 (画布/3D/总线同源)",
             "tests": [
                 ("io_trace 帧序列生成", "auto", "t_ssdata_iotrace", ""),
                 ("模块键名同构", "auto", "t_ssdata_keys", ""),
                 ("逐帧无抽稀", "auto", "t_ssdata_noframe", ""),
                 ("总线滚动可见", "manual", None, "▶运行后切「数据总线」视图→数据源行随帧滚动"),
                 ("3D 同步显示", "manual", None, "▶运行同时开 3D→数据源图像流帧号与 3D 步号一致"),
             ]},
            {"fid": "FNdata05", "name": "工程数据接入", "desc": "与训练/评估数据链路一致 (LeRobotDataset 兼容)",
             "tests": [
                 ("数据集元数据可读", "auto", "t_ssdata_meta", ""),
                 ("归一化参数齐备", "auto", "t_ssdata_norm", ""),
                 ("npz 权重同源", "auto", "t_ssdata_npz", ""),
                 ("磁盘占用受控", "auto", "t_ssdata_disk", ""),
                 ("训练产物可追溯", "manual", None, "开训练→产物目录名带时间戳→数据源节点信息栏可查"),
             ]},
        ],
    },
    "sssensor": {
        "name": "📡 传感器融合", "fb": "底空间·状态观测",
        "funcs": [
            {"fid": "FNsens01", "name": "多源观测融合", "desc": "39D 视觉 + 触觉 4D → 43D (fuse_sensors)",
             "tests": [
                 ("融合输出恒 43 维", "auto", "t_F_B01", ""),
                 ("触觉段位透传", "auto", "t_sssensor_tactile", ""),
                 ("视觉段位保留", "auto", "t_sssensor_visual", ""),
                 ("零输入不崩溃", "auto", "t_sssensor_zero", ""),
                 ("真实帧融合", "semi", "t_sssensor_real", "需 metaworld: 真实 obs 融合输出 43D 且数值有限"),
             ]},
            {"fid": "FNsens02", "name": "时序上下文拼接", "desc": "当前帧+历史帧 (cur/prev) 时空结构",
             "tests": [
                 ("首帧用自身作历史", "auto", "t_sssensor_first", ""),
                 ("prev 语义为上一帧", "auto", "t_sssensor_prev", ""),
                 ("时间步进更新", "auto", "t_sssensor_step", ""),
                 ("帧序列可回放", "manual", None, "▶运行→画布该节点 out 显示 cur/prev 双行"),
                 ("与引擎同构", "manual", None, "比对引擎 state_space_sim._build_obs 的 cur/prev 段"),
             ]},
            {"fid": "FNsens03", "name": "触觉力觉并入", "desc": "力传感器合成 + 触觉 4D 并入统一向量",
             "tests": [
                 ("力向量 6 维合成", "auto", "t_sssensor_force", ""),
                 ("触觉 0-1 语义", "auto", "t_F_C03", ""),
                 ("夹持标志正确", "auto", "t_sssensor_grasp", ""),
                 ("接触标志正确", "auto", "t_sssensor_contact", ""),
                 ("真实力感接入", "manual", None, "硬件仿真开触觉→融合输出力觉段随接触变化"),
             ]},
            {"fid": "FNsens04", "name": "观测质量标记", "desc": "感知来源标记 (编码器/视觉/触觉) 可追溯",
             "tests": [
                 ("来源标签存在", "auto", "t_sssensor_src", ""),
                 ("未检出标记诚实", "auto", "t_sssensor_miss", ""),
                 ("标签不污染数值", "auto", "t_sssensor_clean", ""),
                 ("总线显示来源", "manual", None, "数据总线该节点行→out 值旁带来源说明"),
                 ("可视化自解释", "manual", None, "3D 该图层数值面板标注每个来源名"),
             ]},
            {"fid": "FNsens05", "name": "融合延迟可控", "desc": "融合计算耗时在播放节奏内 (<30ms)",
             "tests": [
                 ("单帧融合 <30ms", "auto", "t_sssensor_lat", ""),
                 ("千帧无累积漂移", "auto", "t_sssensor_leak", ""),
                 ("无同步重负载", "auto", "t_sssensor_nosync", ""),
                 ("播放不卡顿", "manual", None, "▶运行全流程→日志 tick 间隔无 >300ms 尖峰"),
                 ("大轨迹内存受控", "manual", None, "500 步真实化运行→内存增量 <1GB"),
             ]},
        ],
    },
    "ssobs": {
        "name": "🧩 43D 统一状态向量", "fb": "底空间·状态观测",
        "funcs": [
            {"fid": "FNobs01", "name": "统一状态编码", "desc": "多源观测编码为单一 43D 向量 (状态空间观测方程)",
             "tests": [
                 ("观测恒 43 维", "auto", "t_F_B01", ""),
                 ("段位布局稳定", "auto", "t_sobs_layout", ""),
                 ("编码确定性", "auto", "t_sobs_determ", ""),
                 ("画布节点名称一致", "auto", "t_F_F02", ""),
                 ("与引擎 obs 同构", "manual", None, "比对引擎 tr['obs'] 段位与画布显示"),
             ]},
            {"fid": "FNobs02", "name": "视觉段位映射", "desc": "几何/工件段位 (hand/peg/hole/target)",
             "tests": [
                 ("hand 段位 [0:3]", "auto", "t_F_C02", ""),
                 ("peg 段位映射", "auto", "t_sobs_peg", ""),
                 ("target 段位正确", "auto", "t_sobs_target", ""),
                 ("几何量纲米制", "auto", "t_sobs_unit", ""),
                 ("真实帧对齐", "semi", "t_sobs_realalign", "需 YOLO: 真实检测对齐后段位与几何量级一致"),
             ]},
            {"fid": "FNobs03", "name": "触觉段位嵌入", "desc": "夹紧度/接触标志嵌入状态向量",
             "tests": [
                 ("触觉段位 [39:43]", "auto", "t_sobs_tacseg", ""),
                 ("夹紧度单调", "auto", "t_sobs_tacmono", ""),
                 ("接触标志二值", "auto", "t_sobs_tacbin", ""),
                 ("全零观测合法", "auto", "t_sobs_zero", ""),
                 ("真实触觉接入", "manual", None, "硬件仿真→触觉段随夹爪开合实时变化"),
             ]},
            {"fid": "FNobs04", "name": "结构条件叠加", "desc": "模型行/场景结构条件可叠加 (不破坏基础观测)",
             "tests": [
                 ("条件注入不越界", "auto", "t_sobs_cond", ""),
                 ("条件可移除", "auto", "t_sobs_uncond", ""),
                 ("叠加后维数不变", "auto", "t_sobs_conddim", ""),
                 ("画布条件节点联动", "manual", None, "双击结构条件节点注入→该节点 out 显示条件标记"),
                 ("模型行区分", "manual", None, "多模型画布各行条件互不串扰"),
             ]},
            {"fid": "FNobs05", "name": "观测源头追溯", "desc": "每个字段可追溯到编码器/视觉/触觉/真值",
             "tests": [
                 ("字段-源映射表", "auto", "t_sobs_trace", ""),
                 ("引擎真值区标注", "auto", "t_sobs_honest", ""),
                 ("无幽灵字段", "auto", "t_sobs_noghost", ""),
                 ("双击节点显示来源", "manual", None, "双击节点→详情弹窗逐段标来源"),
                 ("3D 面板可查", "manual", None, "3D 数值面板每行前缀源模块名"),
             ]},
        ],
    },
    "ssff": {
        "name": "⚡ 前馈加速器", "fb": "纤维·工艺动作",
        "funcs": [
            {"fid": "FNff01", "name": "比例引导驱动", "desc": "比例引导向目标 (Kp·Δ), 快路径动作生成",
             "tests": [
                 ("指向目标方向", "auto", "t_F_B02", ""),
                 ("误差归零动作归零", "auto", "t_ff_zero", ""),
                 ("比例增益单调", "auto", "t_ff_kp", ""),
                 ("输出 4 维动作", "auto", "t_ff_dim", ""),
                 ("真权重替换生效", "manual", None, "有训练权重 npz → ▶运行日志打「已加载训练模型」"),
             ]},
            {"fid": "FNff02", "name": "近距收敛闭合", "desc": "接近目标时闭合控制 (近距判据 0.03)",
             "tests": [
                 ("近距判据触发", "auto", "t_ff_close", ""),
                 ("近距增速收敛", "auto", "t_ff_converge", ""),
                 ("远距不误闭合", "auto", "t_ff_far", ""),
                 ("闭合无振荡", "auto", "t_ff_damp", ""),
                 ("真机近距行为", "manual", None, "真机/物理仿真接近段末端无明显来回抖动"),
             ]},
            {"fid": "FNff03", "name": "输出幅值限幅", "desc": "前馈输出 ±0.5 限幅",
             "tests": [
                 ("限幅 ±0.5 生效", "auto", "t_ff_clip", ""),
                 ("限幅后方向不变", "auto", "t_ff_dir", ""),
                 ("标定幅值匹配", "auto", "t_ff_cal", ""),
                 ("画布显示限幅值", "manual", None, "节点详情参数区 Kp/限幅与源码一致"),
                 ("与安全层协同", "manual", None, "前馈输出经 🛡 安全执行边界后不再放大"),
             ]},
            {"fid": "FNff04", "name": "快路径直映射", "desc": "obs→u_ff 直接映射无递归 (快慢分离之快)",
             "tests": [
                 ("无状态依赖", "auto", "t_ff_stateless", ""),
                 ("单次前向 <1ms", "auto", "t_ff_lat", ""),
                 ("权重复用训练产物", "auto", "t_ff_w", ""),
                 ("断点可进源码", "manual", None, "右键→VSCode→断点设 parallel.py FeedforwardAccelerator.forward→运行节点必停"),
                 ("训练后行为可测", "manual", None, "训出模型后评估: 前馈主导段成功率对比"),
             ]},
            {"fid": "FNff05", "name": "动作可解释性", "desc": "前馈输出有物理含义 (目标方向/大小)",
             "tests": [
                 ("方向语义正确", "auto", "t_ff_meaning", ""),
                 ("幅值与距离相关", "auto", "t_ff_corr", ""),
                 ("日志逐帧数值", "manual", None, "▶运行日志含 u_ff 数值行"),
                 ("3D 箭头可视化", "manual", None, "3D 前馈图层箭头方向指向目标点"),
                 ("Scope 波形可查", "manual", None, "Scope 前馈曲线随阶段切换有界"),
             ]},
        ],
    },
    "ssest": {
        "name": "🔮 自适应状态估计器", "fb": "闭环联络·状态预测",
        "funcs": [
            {"fid": "FNest01", "name": "潜状态递归预测", "desc": "递归潜状态 + 卡尔曼 predict (世界模型)",
             "tests": [
                 ("predict 数值手算一致", "auto", "t_F_B03", ""),
                 ("潜状态 4 维", "auto", "t_est_dim", ""),
                 ("递归状态演进", "auto", "t_est_rec", ""),
                 ("预测有界", "auto", "t_est_bounded", ""),
                 ("真机状态跟随", "manual", None, "真实化运行→估计潜状态随物理位置收敛"),
             ]},
            {"fid": "FNest02", "name": "卡尔曼增益更新", "desc": "update 门控: 信预测 vs 信观测 (K 可标定)",
             "tests": [
                 ("update 数值手算一致", "auto", "t_F_B03", ""),
                 ("K 越大越信观测", "auto", "t_est_k", ""),
                 ("增益标定生效", "auto", "t_est_kcal", ""),
                 ("标定表改 K 生效", "manual", None, "标定表格 K_kalman 改值→保存→▶运行日志 K 变化"),
                 ("噪声下状态平滑", "semi", "t_est_smooth", "注入 5mm 观测噪声→估计轨迹平滑度优于观测"),
             ]},
            {"fid": "FNest03", "name": "状态平滑估计", "desc": "抑制观测噪声, 输出平滑状态",
             "tests": [
                 ("残差 EMA 滤波", "auto", "t_est_ema", ""),
                 ("无相位滞后发散", "auto", "t_est_lag", ""),
                 ("估计误差收敛", "auto", "t_est_err", ""),
                 ("3D 轨迹平滑", "manual", None, "3D 估计层轨迹 vs 原始观测: 抖动明显更小"),
                 ("量化信噪比", "manual", None, "噪声 5mm vs 步位移 0.35mm→显示系统占比%"),
             ]},
            {"fid": "FNest04", "name": "模型参数标定", "desc": "A/K/B 参数现场标定生效",
             "tests": [
                 ("标定默认=引擎真值", "auto", "t_est_caldefault", ""),
                 ("写回引擎生效", "auto", "t_est_writeback", ""),
                 ("参数范围校验", "auto", "t_est_range", ""),
                 ("标定表编辑→引擎", "manual", None, "标定表格改估计器参数→保存→引擎文件字面量变化"),
                 ("重启后持久", "manual", None, "重启 GUI→标定表仍显新值"),
             ]},
            {"fid": "FNest05", "name": "估计偏差反馈", "desc": "估计残差反馈到校正层 (闭环输入)",
             "tests": [
                 ("残差输出正确", "auto", "t_F_B05", ""),
                 ("估计-校正闭环", "auto", "t_est_loop", ""),
                 ("偏差方向正确", "auto", "t_est_dir", ""),
                 ("链路日志可查", "manual", None, "▶运行日志: 估计→校正两步数值连打"),
                 ("画布连线同源", "manual", None, "画布 估计→校正→预测 连线与引擎数据流一致"),
             ]},
        ],
    },
    "sspred": {
        "name": "📈 先验动力学预测器", "fb": "闭环联络·状态预测",
        "funcs": [
            {"fid": "FNpred01", "name": "先验状态预测", "desc": "观测前先猜: x̂₋ = A·x + B·u",
             "tests": [
                 ("先验数值手算一致", "auto", "t_F_B04", ""),
                 ("控制量响应正确", "auto", "t_pred_u", ""),
                 ("无控制恒速外推", "auto", "t_pred_free", ""),
                 ("预测有界不发散", "auto", "t_pred_bounded", ""),
                 ("预测误差可视化", "manual", None, "3D 预测层箭头: 先验点-观测点连线"),
             ]},
            {"fid": "FNpred02", "name": "潜空间速度场", "desc": "潜空间恒速速度场 (A=1.0 物理自洽)",
             "tests": [
                 ("恒速 A=1.0 成立", "auto", "t_F_B04", ""),
                 ("速度场方向正确", "auto", "t_pred_vel", ""),
                 ("潜坐标连续", "auto", "t_pred_latcont", ""),
                 ("画布潜空间节点联动", "manual", None, "潜空间节点显示速度场向量与该节点同源"),
                 ("流形地图可读", "manual", None, "流形导航层节点读数与该预测同量级"),
             ]},
            {"fid": "FNpred03", "name": "先验-校正基准", "desc": "预测输出作残差基准 (z − x̂₋)",
             "tests": [
                 ("残差基准正确", "auto", "t_F_B05", ""),
                 ("预测漂移可检出", "auto", "t_pred_drift", ""),
                 ("校正拉回真值", "auto", "t_pred_pull", ""),
                 ("接触前兆可见", "manual", None, "插入前 3 帧→残差上升→接触概率提前抬升"),
                 ("否决联动", "manual", None, "残差超限→动作调制器否决→日志「否决」"),
             ]},
            {"fid": "FNpred04", "name": "动力学标定", "desc": "A/B 系数标定生效 (物理自洽 A=1.0)",
             "tests": [
                 ("默认 A=1.0 B=0.02", "auto", "t_pred_default", ""),
                 ("标定写回引擎", "auto", "t_pred_writeback", ""),
                 ("量纲一致", "auto", "t_pred_unit", ""),
                 ("标定后行为验证", "manual", None, "改 B→真实化运行轨迹速度变化与理论一致"),
                 ("与估计器标定独立", "manual", None, "改预测 B 不影响估计器 K"),
             ]},
            {"fid": "FNpred05", "name": "预测开销可控", "desc": "预测计算零阻塞 (纯 numpy 微秒级)",
             "tests": [
                 ("单次预测 <1ms", "auto", "t_pred_lat", ""),
                 ("万步无状态泄漏", "auto", "t_pred_leak", ""),
                 ("源码映射真实", "auto", "t_pred_src", ""),
                 ("断点可进", "manual", None, "右键→VSCode→dynamics.py PriorDynamicsPredictor.predict 断点必停"),
                 ("引擎 importlib 重载", "manual", None, "改动力学源码→▶运行即生效, 无需重启 GUI"),
             ]},
        ],
    },
    "ssinnov": {
        "name": "🧪 状态校正器", "fb": "闭环联络·状态校正",
        "funcs": [
            {"fid": "FNinn01", "name": "观测残差计算", "desc": "r = z − x̂₋ 新息计算",
             "tests": [
                 ("残差数值手算一致", "auto", "t_F_B05", ""),
                 ("零偏差残差为零", "auto", "t_inn_zero", ""),
                 ("残差方向正确", "auto", "t_inn_dir", ""),
                 ("残差有界", "auto", "t_inn_bounded", ""),
                 ("残差可视化", "manual", None, "3D 残差箭头: 先验点指向观测点"),
             ]},
            {"fid": "FNinn02", "name": "卡尔曼校正融合", "desc": "校正 x̂₊ = x̂₋ + K·r",
             "tests": [
                 ("校正数值手算一致", "auto", "t_F_B05", ""),
                 ("K=0 不校正", "auto", "t_inn_k0", ""),
                 ("K=1 全信观测", "auto", "t_inn_k1", ""),
                 ("校正闭环回写", "auto", "t_est_loop", ""),
                 ("双标定联动", "manual", None, "标定表改校正 K→引擎→运行验证"),
             ]},
            {"fid": "FNinn03", "name": "接触概率估计", "desc": "σ(残差·gain) → 接触概率",
             "tests": [
                 ("概率单调增", "auto", "t_F_B06", ""),
                 ("概率 0-1 范围", "auto", "t_inn_01", ""),
                 ("接触段 >0.6", "auto", "t_F_A07", ""),
                 ("非接触段低", "auto", "t_inn_low", ""),
                 ("概率曲线可看", "manual", None, "Scope 接触概率曲线随阶段呈峰"),
             ]},
            {"fid": "FNinn04", "name": "异常偏差告警", "desc": "残差超阈值 → 异常信号",
             "tests": [
                 ("阈值判定正确", "auto", "t_F_B09", ""),
                 ("告警不误报", "auto", "t_inn_nowarn", ""),
                 ("否决联动触发", "auto", "t_inn_veto", ""),
                 ("异常推理器接入", "manual", None, "连续否决→异常推理器日志出诊断类别"),
                 ("大屏告警", "manual", None, "监控大屏显示否决计数/接触事件"),
             ]},
            {"fid": "FNinn05", "name": "校正闭环回写", "desc": "校正后状态喂回预测器 (闭环)",
             "tests": [
                 ("回写链路正确", "auto", "t_est_loop", ""),
                 ("闭环收敛", "auto", "t_inn_close", ""),
                 ("链路同构引擎", "auto", "t_inn_isomorph", ""),
                 ("画布连线验证", "manual", None, "校正节点输出连线指向预测器/调度器"),
                 ("断点逐帧可进", "manual", None, "▶运行中校正源码断点每步命中 (真流程)"),
             ]},
        ],
    },
    "sssched": {
        "name": "🧭 动作调制器", "fb": "闭环联络·决策调度",
        "funcs": [
            {"fid": "FNsched01", "name": "八阶段作业调度", "desc": "接近→对位→下降→抓取→抬起→转移→插入→完成",
             "tests": [
                 ("八阶段顺序推进", "auto", "t_F_A01", ""),
                 ("防抖连续确认", "auto", "t_F_B07", ""),
                 ("阶段状态可查", "auto", "t_sched_stage", ""),
                 ("真实化阶段推进", "semi", "t_sched_real", "需 metaworld: 真实化运行八阶段可达 (可失败但有序)"),
                 ("阶段图可视化", "manual", None, "3D/画布阶段阶梯随运行点亮"),
             ]},
            {"fid": "FNsched02", "name": "动作加权融合", "desc": "前馈+反馈加权合成 u (带否决权)",
             "tests": [
                 ("融合公式正确", "auto", "t_sched_fuse", ""),
                 ("否决权强制减速", "auto", "t_F_B09", ""),
                 ("融合输出 4 维", "auto", "t_sched_dim", ""),
                 ("否决恢复机制", "auto", "t_sched_unveto", ""),
                 ("融合曲线可视化", "manual", None, "Scope: u_ff/u_fb/u 三线叠加显示"),
             ]},
            {"fid": "FNsched03", "name": "阶段限速控制", "desc": "各阶段速度上限 V_CAP / 下限 V_MIN",
             "tests": [
                 ("插入段限速生效", "auto", "t_F_B10", ""),
                 ("各阶段 cap 独立", "auto", "t_sched_cap", ""),
                 ("V_MIN 防磨蹭", "auto", "t_sched_vmin", ""),
                 ("标定限速生效", "manual", None, "标定表改阶段速度→引擎→运行日志验证"),
                 ("八阶段速度档位可视化", "manual", None, "标定面板八阶段速度表当前阶段高亮"),
             ]},
            {"fid": "FNsched04", "name": "夹持丢失回退", "desc": "夹持丢失/滑脱 → 自动回退重抓",
             "tests": [
                 ("丢失判定触发回退", "auto", "t_F_B08", ""),
                 ("回退目标重定位", "auto", "t_sched_retarget", ""),
                 ("回退不无限循环", "auto", "t_sched_loop", ""),
                 ("真实物理滑脱回退", "semi", "t_sched_real_slip", "真实化运行构造滑脱→强制回退 stage0 日志出现"),
                 ("回退历史可查", "manual", None, "运行日志含「滑脱→强制回退」记录"),
             ]},
            {"fid": "FNsched05", "name": "认知决策可解释", "desc": "每步决策有依据 (阶段/证据/否决原因)",
             "tests": [
                 ("决策带证据输出", "auto", "t_sched_evid", ""),
                 ("否决原因可读", "auto", "t_sched_reason", ""),
                 ("阶段停留可诊断", "auto", "t_sched_diag", ""),
                 ("双击节点看决策表", "manual", None, "双击调度节点→八阶段决策表"),
                 ("日志逐帧决策", "manual", None, "▶运行日志每步含阶段/接触/否决标记"),
             ]},
        ],
    },
    "sslimit": {
        "name": "🛡 安全执行边界", "fb": "闭环联络·安全",
        "funcs": [
            {"fid": "FNlim01", "name": "动作饱和限幅", "desc": "saturate ±0.6 物理层限幅",
             "tests": [
                 ("饱和限幅正确", "auto", "t_F_B11", ""),
                 ("限幅边界不越", "auto", "t_lim_bound", ""),
                 ("限幅可配置", "auto", "t_lim_cfg", ""),
                 ("标定限幅生效", "manual", None, "标定表改限幅→引擎→运行验证"),
                 ("限幅事件日志", "manual", None, "超限输入→日志打「限幅生效」"),
             ]},
            {"fid": "FNlim02", "name": "速度安全钳制", "desc": "速度指令安全上限钳制",
             "tests": [
                 ("钳制上限生效", "auto", "t_lim_vel", ""),
                 ("正常速度不误伤", "auto", "t_lim_noclip", ""),
                 ("有界不发散", "auto", "t_F_A04", ""),
                 ("真机速度安全", "manual", None, "真机/物理仿真速度不超过安全上限"),
                 ("3D 速度显示", "manual", None, "3D 动作箭头长度按 0.35m/s 归一化"),
             ]},
            {"fid": "FNlim03", "name": "三层安全联动", "desc": "否决(决策层)+限幅(物理层)+Sys0(硬件) 三层",
             "tests": [
                 ("决策层否决独立", "auto", "t_F_B09", ""),
                 ("物理层限幅兜底", "auto", "t_lim_final", ""),
                 ("三层职责不串", "auto", "t_lim_sep", ""),
                 ("硬件联锁预留", "manual", None, "Sys0 硬件联锁接口文档与代码一致"),
                 ("安全审计可追溯", "manual", None, "安全事件均有日志+时间戳"),
             ]},
            {"fid": "FNlim04", "name": "台面约束保持", "desc": "未夹持末端不穿透台面",
             "tests": [
                 ("台面约束生效", "auto", "t_F_A05", ""),
                 ("接触后允许贴近", "auto", "t_lim_contact", ""),
                 ("约束无抖振", "auto", "t_lim_stable", ""),
                 ("真实物理台面", "semi", "t_lim_real_table", "真实化运行: 未夹持末端 z 不低于台面"),
                 ("物理世界节点联动", "manual", None, "🌍 物理世界 out 台面约束状态可查"),
             ]},
            {"fid": "FNlim05", "name": "安全参数可审计", "desc": "限幅值/速度上限可标定可追溯",
             "tests": [
                 ("默认值=引擎真值", "auto", "t_lim_default", ""),
                 ("写回引擎生效", "auto", "t_lim_writeback", ""),
                 ("越界标定拒绝", "auto", "t_lim_range", ""),
                 ("标定表格操作", "manual", None, "右键安全节点→表格改 safety_limit→保存→引擎字面量变化"),
                 ("重启持久", "manual", None, "重启 GUI→安全参数保持新值"),
             ]},
        ],
    },
    "ssact": {
        "name": "🤖 机器人执行器", "fb": "纤维·工艺动作",
        "funcs": [
            {"fid": "FNact01", "name": "动作指令下发", "desc": "u_vec 速度指令下发执行层",
             "tests": [
                 ("下发 4 维指令", "auto", "t_act_dim", ""),
                 ("指令经物理世界消费", "auto", "t_act_consumed", ""),
                 ("指令数值透传", "auto", "t_act_pass", ""),
                 ("真实动作执行", "semi", "t_act_real", "真实化运行: 末端位置随指令变化"),
                 ("执行日志可查", "manual", None, "▶运行日志含 u_vec 下发行"),
             ]},
            {"fid": "FNact02", "name": "夹爪开合执行", "desc": "夹爪闭合/张开指令 (gripper_cmd)",
             "tests": [
                 ("闭合指令正确", "auto", "t_act_grip", ""),
                 ("张开指令正确", "auto", "t_act_ungrip", ""),
                 ("夹持阈值匹配", "auto", "t_act_th", ""),
                 ("真夹爪物理", "semi", "t_act_realgrip", "真实化: 深夹锁存 grp<0.60 才抬升"),
                 ("夹爪状态显示", "manual", None, "3D/日志夹爪开合状态实时"),
             ]},
            {"fid": "FNact03", "name": "执行状态反馈", "desc": "执行后状态回读 (位置/夹爪/力)",
             "tests": [
                 ("位置回读正确", "auto", "t_act_pos", ""),
                 ("夹爪回读正确", "auto", "t_act_grp", ""),
                 ("力合成回读", "auto", "t_act_force", ""),
                 ("回读-下发闭环", "auto", "t_act_loop", ""),
                 ("状态面板实时", "manual", None, "数值面板末端/夹爪/力实时刷新"),
             ]},
            {"fid": "FNact04", "name": "指令比例标定", "desc": "速度指令 ↔ act ±1 标定 (K_ACT)",
             "tests": [
                 ("标定系数正确", "auto", "t_act_cal", ""),
                 ("act 限幅 ±1", "auto", "t_act_clip", ""),
                 ("比例线性", "auto", "t_act_lin", ""),
                 ("标定值现场可调", "manual", None, "改 K_ACT→真实化运行位移速度变化"),
                 ("真机标定方法", "manual", None, "探针法实测 act=1 位移→回写 K_ACT"),
             ]},
            {"fid": "FNact05", "name": "执行安全防抖", "desc": "执行层防抖/防指令风暴",
             "tests": [
                 ("连续指令平滑", "auto", "t_act_smooth", ""),
                 ("指令限频", "auto", "t_act_freq", ""),
                 ("异常指令拦截", "auto", "t_act_guard", ""),
                 ("急停可中断", "manual", None, "运行中点⏹停止→动作立即停止"),
                 ("与安全层协作", "manual", None, "限幅后指令不越界下发"),
             ]},
        ],
    },
    "ssworld": {
        "name": "🌍 物理世界", "fb": "底空间·状态转移",
        "funcs": [
            {"fid": "FNworld01", "name": "真实物理推进", "desc": "metaworld env.step 真实 MuJoCo 动力学",
             "tests": [
                 ("物理推进引擎加载", "auto", "t_world_env", ""),
                 ("每步状态演化", "auto", "t_world_step", ""),
                 ("动力学稳定", "auto", "t_world_stable", ""),
                 ("真实渲染帧", "semi", "t_world_render", "需 DISPLAY: 渲染帧非空可存"),
                 ("物理可信度", "manual", None, "接触/夹持/插入行为符合真实物理直觉"),
             ]},
            {"fid": "FNworld02", "name": "接触力合成", "desc": "夹持/接触力合成 (无力传感器时的几何合成)",
             "tests": [
                 ("力合成正确", "auto", "t_world_force", ""),
                 ("接触判据正确", "auto", "t_world_contact", ""),
                 ("力范数映射概率", "auto", "t_world_prob", ""),
                 ("物理接触演示", "manual", None, "3D 接触指示: 夹持青球/环境橙球"),
                 ("接触力真实化", "semi", "t_world_realcontact", "真实化运行接触段 contact_p>0.6"),
             ]},
            {"fid": "FNworld03", "name": "工件位姿演化", "desc": "销/孔/末端位姿物理演化",
             "tests": [
                 ("销随夹爪移动", "auto", "t_F_A06", ""),
                 ("孔位静态", "auto", "t_world_hole", ""),
                 ("位姿连续", "auto", "t_world_cont", ""),
                 ("3D 场景同步", "manual", None, "3D 场景物体位姿与引擎轨迹同帧"),
                 ("操作视频同源", "manual", None, "状态空间操作视频与该轨迹同一条 episode"),
             ]},
            {"fid": "FNworld04", "name": "末端编码器读", "desc": "末端 hand 位置编码器读值 (真机同构)",
             "tests": [
                 ("hand 段位正确", "auto", "t_world_hand", ""),
                 ("编码器无漂移", "auto", "t_world_noise", ""),
                 ("与 YOLO hand 可交叉验证", "semi", "t_world_cross", "需 YOLO: 编码器 hand vs 视觉 hand 偏差 <5cm"),
                 ("真实化 hand 语义", "manual", None, "真实化运行 hand=obs 编码器真值非视觉"),
                 ("锚点物理含义", "manual", None, "锚=obs hand (site 虚拟点低 4cm 已弃用)"),
             ]},
            {"fid": "FNworld05", "name": "物理约束可审计", "desc": "物理常量/约束与设计一致",
             "tests": [
                 ("常量与引擎同源", "auto", "t_world_const", ""),
                 ("约束无冲突", "auto", "t_world_noconf", ""),
                 ("场景布局可复现", "auto", "t_world_seed", ""),
                 ("设计文档一致", "manual", None, "对照 docs/closed_loop_realization_design.md 常量表"),
                 ("跨进程可复现", "manual", None, "同 seed 两次运行初始布局一致"),
             ]},
        ],
    },
    "ssyolo": {
        "name": "🎯 YOLO 目标检测", "fb": "底空间·状态观测(感知)",
        "funcs": [
            {"fid": "FNyolo01", "name": "目标类别检出", "desc": "hand/peg/hole 三类目标检出",
             "tests": [
                 ("三类真实检出", "auto", "t_F_C01", ""),
                 ("类别名映射正确", "auto", "t_yolo_cls", ""),
                 ("检出框坐标合法", "auto", "t_yolo_box", ""),
                 ("真实感知视频", "manual", None, "gen_real_yolo_video.py 出视频含 2D 框+conf"),
                 ("逐帧检出率统计", "manual", None, "真实化运行完日志含 YOLO 检出率"),
             ]},
            {"fid": "FNyolo02", "name": "检测置信输出", "desc": "真实 conf 输出 (无写死 0.99)",
             "tests": [
                 ("conf 为真实值", "auto", "t_yolo_conf", ""),
                 ("无写死高置信", "auto", "t_yolo_nofake", ""),
                 ("低置信可过滤", "auto", "t_yolo_th", ""),
                 ("总线显示真实 conf", "manual", None, "数据总线 YOLO 行 conf 为检测真值非 0.99"),
                 ("遮挡时 conf 下降", "manual", None, "夹爪遮挡 peg→conf 真实下降/未检出"),
             ]},
            {"fid": "FNyolo03", "name": "模型热载缓存", "desc": "YOLO 权重首次加载缓存 (防播放卡顿)",
             "tests": [
                 ("启动预热缓存", "auto", "t_yolo_prewarm", ""),
                 ("权重路径探测", "auto", "t_yolo_weights", ""),
                 ("加载后复用", "auto", "t_yolo_cache", ""),
                 ("首帧加载不卡播放", "manual", None, "GUI 启动即预热→▶运行 YOLO 节点无 >300ms 卡顿"),
                 ("权重缺失显性报错", "manual", None, "删权重→运行报「YOLO 加载失败」非静默"),
             ]},
            {"fid": "FNyolo04", "name": "感知退化诚实", "desc": "遮挡/漏检时诚实标注, 不伪造检测",
             "tests": [
                 ("未检出标 None", "auto", "t_yolo_miss", ""),
                 ("不顶替引擎真值", "auto", "t_yolo_honest", ""),
                 ("退化统计可查", "auto", "t_yolo_stat", ""),
                 ("退化真实呈现", "manual", None, "任务失败视频也交付, 遮挡段检出崩如实可见"),
                 ("RealityGap 量化", "manual", None, "报告含视觉 peg 误差/检出率实测量"),
             ]},
            {"fid": "FNyolo05", "name": "感知实时性", "desc": "单帧 detect_3d 耗时在真实化节奏内",
             "tests": [
                 ("单帧 <1s 可接受", "auto", "t_yolo_lat", ""),
                 ("GPU 推理正常", "semi", "t_yolo_gpu", "需 GPU: 推理无 CUDA 错误"),
                 ("分辨率一致", "auto", "t_yolo_size", ""),
                 ("视频帧率标注", "manual", None, "真实感知视频 8fps 顶栏显示帧号"),
                 ("真机端侧可行", "manual", None, "Orin 推理延迟记录 (真机验收)"),
             ]},
        ],
    },
    "ss2d3d": {
        "name": "📐 2D→3D 解算", "fb": "底空间·状态观测(感知)",
        "funcs": [
            {"fid": "FN2d01", "name": "像素反投影解算", "desc": "2D 检测框 → 3D 世界坐标 (深度反投影)",
             "tests": [
                 ("反投影公式正确", "auto", "t_2d3d_formula", ""),
                 ("相机模型加载", "auto", "t_2d3d_cam", ""),
                 ("深度图参与解算", "auto", "t_2d3d_depth", ""),
                 ("3D 坐标量级正确", "manual", None, "解算坐标与场景物体尺寸量级一致 (米)"),
                 ("深度缺失回退", "manual", None, "无深度权重→回退写死 z 并在日志标注"),
             ]},
            {"fid": "FN2d02", "name": "深度图恢复", "desc": "深度模型预测 → 框内中位数深度",
             "tests": [
                 ("深度模型加载", "auto", "t_2d3d_dmodel", ""),
                 ("深度尺度校准", "auto", "t_2d3d_scale", ""),
                 ("框内中位数抗噪", "auto", "t_2d3d_med", ""),
                 ("深度权重漏传修复", "manual", None, "depth_weights 传参在代码中显式传递 (曾漏)"),
                 ("深度质量可视化", "manual", None, "深度图与 RGB 同帧可对照"),
             ]},
            {"fid": "FN2d03", "name": "相机模型标定", "desc": "cam_mat/fovy/外参精确对齐",
             "tests": [
                 ("内参矩阵使用正确", "auto", "t_2d3d_intrin", ""),
                 ("fovy 换算正确", "auto", "t_2d3d_fovy", ""),
                 ("外参角差 <1°", "auto", "t_2d3d_extrin", ""),
                 ("真机相机标定", "manual", None, "真机相机标定记录 (角差 0.00° 验证过 corner2)"),
                 ("标定文件版本可溯", "manual", None, "相机标定参数文件路径可查"),
             ]},
            {"fid": "FN2d04", "name": "解算误差评估", "desc": "反投影坐标 vs 真值误差量化",
             "tests": [
                 ("锚点误差量化", "auto", "t_2d3d_err", ""),
                 ("误差带统计", "auto", "t_2d3d_errband", ""),
                 ("深度模型漂移检测", "auto", "t_2d3d_drift", ""),
                 ("定标探针报告", "manual", None, "YOLO hand 漂移 12-20cm 定标实锤报告可查"),
                 ("误差进日志", "manual", None, "真实化 R0_TRACE 每帧 peg 误差打印"),
             ]},
            {"fid": "FN2d05", "name": "解算链路同构", "desc": "真机/仿真同一解算链路 (不双轨)",
             "tests": [
                 ("源码映射真实", "auto", "t_2d3d_src", ""),
                 ("检测-解算同帧", "auto", "t_2d3d_sameframe", ""),
                 ("断点可进", "manual", None, "detect_3d 内断点每步可进 (真实化)"),
                 ("画布 2D→3D 节点真实", "manual", None, "画布该节点 out = 真实反投影非引擎几何"),
                 ("真机同构验证", "manual", None, "gen_insert_video 同链路 YOLO 写 obs[36:39]"),
             ]},
        ],
    },
    "sstactile": {
        "name": "🖐 触觉感知", "fb": "底空间·状态观测(感知)",
        "funcs": [
            {"fid": "FNtac01", "name": "夹持状态感知", "desc": "夹紧度 1−obs 夹持感知",
             "tests": [
                 ("夹紧度计算正确", "auto", "t_tac_grip", ""),
                 ("深夹阈值判定", "auto", "t_tac_deep", ""),
                 ("浅夹检出", "auto", "t_tac_shallow", ""),
                 ("真夹持物理验证", "semi", "t_tac_real", "真实化: 夹住 grp~0.70/空夹 ~0.29 区分"),
                 ("夹持力可视化", "manual", None, "3D 夹持青球/环境橙球"),
             ]},
            {"fid": "FNtac02", "name": "接触检测判定", "desc": "接触建立检测 (几何+夹持)",
             "tests": [
                 ("接触判据正确", "auto", "t_tac_contact", ""),
                 ("预接触提示", "auto", "t_tac_pre", ""),
                 ("接触事件可追溯", "auto", "t_tac_event", ""),
                 ("真实接触演示", "manual", None, "物理仿真接触瞬间指示环亮起"),
                 ("接触概率联动", "manual", None, "接触段 contact_p>0.6 画布可见"),
             ]},
            {"fid": "FNtac03", "name": "触觉向量合成", "desc": "4D 触觉向量 (grasp/contact 0-1)",
             "tests": [
                 ("触觉 4D 合成", "auto", "t_F_C03", ""),
                 ("0-1 语义范围", "auto", "t_F_C03", ""),
                 ("向量并入 43D", "auto", "t_F_B01", ""),
                 ("触觉源真实", "manual", None, "数据来源=夹爪开度+物理接触非假数据"),
                 ("硬仿真可接入", "manual", None, "硬件仿真开触觉→段位变化"),
             ]},
            {"fid": "FNtac04", "name": "力觉语义映射", "desc": "力觉 → 接触概率语义",
             "tests": [
                 ("力合成正确", "auto", "t_tac_force", ""),
                 ("力-概率单调", "auto", "t_tac_fprob", ""),
                 ("阈值分离度", "auto", "t_tac_sep", ""),
                 ("接触实验对照", "manual", None, "对照探针接触实验记录 (grp 0.66 接触建立)"),
                 ("力控保护演示", "manual", None, "力超限→否决→减速演示"),
             ]},
            {"fid": "FNtac05", "name": "抓握质量估计", "desc": "夹持质量 (随动验证) 估计",
             "tests": [
                 ("随动验证正确", "auto", "t_tac_follow", ""),
                 ("滑脱检出", "auto", "t_F_A06", ""),
                 ("grasp_force 语义", "auto", "t_tac_gf", ""),
                 ("滑脱强制回退", "semi", "t_tac_slip", "真实化: 滑脱→强制回退 stage0"),
                 ("抓握质量日志", "manual", None, "运行日志含 grasped/gf 状态"),
             ]},
        ],
    },
    "ssaoi": {
        "name": "🔍 外观质量检测", "fb": "质量截面·检测",
        "funcs": [
            {"fid": "FNaoi01", "name": "外观缺陷检出", "desc": "AOI 图像真实处理检出缺陷项",
             "tests": [
                 ("AOI 处理真实", "auto", "t_F_C04", ""),
                 ("缺陷项结构完整", "auto", "t_aoi_items", ""),
                 ("判级输出", "auto", "t_aoi_grade", ""),
                 ("真实图像验证", "manual", None, "喂真实采集图像→缺陷检出可目检"),
                 ("缺陷类型分类", "manual", None, "检出缺陷带类型标签 (划痕/脏污等)"),
             ]},
            {"fid": "FNaoi02", "name": "检测结果判定", "desc": "pass/fail 判定输出",
             "tests": [
                 ("判级结果正确", "auto", "t_aoi_pass", ""),
                 ("阈值可配置", "auto", "t_aoi_cfg", ""),
                 ("判定可复现", "auto", "t_aoi_repro", ""),
                 ("画布节点显示判定", "manual", None, "双击 AOI 节点→判定摘要弹窗"),
                 ("产线判定一致", "manual", None, "与产线 AOI 判定标准对照 (真机验收)"),
             ]},
            {"fid": "FNaoi03", "name": "图像预处理", "desc": "打光/曝光/预处理管线",
             "tests": [
                 ("图像尺寸统一", "auto", "t_aoi_size", ""),
                 ("预处理可跑", "auto", "t_aoi_pre", ""),
                 ("灰度/通道处理", "auto", "t_aoi_ch", ""),
                 ("真实相机接入", "manual", None, "硬仿真相机帧→AOI 处理不崩"),
                 ("光源参数记录", "manual", None, "打光角度/曝光参数在检测日志"),
             ]},
            {"fid": "FNaoi04", "name": "缺陷项统计", "desc": "items/缺陷计数汇总",
             "tests": [
                 ("items 计数正确", "auto", "t_F_C04", ""),
                 ("统计摘要输出", "auto", "t_aoi_sum", ""),
                 ("零缺陷不误报", "auto", "t_aoi_clean", ""),
                 ("批量检测统计", "manual", None, "多图批量→缺陷率统计"),
                 ("数据入总线", "manual", None, "总线 AOI 行显示判定+items"),
             ]},
            {"fid": "FNaoi05", "name": "质量标准可配", "desc": "判定阈值/标准可配置",
             "tests": [
                 ("阈值参数化", "auto", "t_aoi_param", ""),
                 ("配置持久化", "auto", "t_aoi_persist", ""),
                 ("越界配置防护", "auto", "t_aoi_guard", ""),
                 ("现场标定入口", "manual", None, "GUI 配置 AOI 阈值→保存生效"),
                 ("标准文档一致", "manual", None, "对照需求说明书 AOI 指标"),
             ]},
        ],
    },
    "ssllm": {
        "name": "🧠 任务规划器", "fb": "闭环联络·工艺编排",
        "funcs": [
            {"fid": "FNllm01", "name": "指令意图解析", "desc": "MES/自然语言指令 → 任务意图",
             "tests": [
                 ("指令解析输出", "auto", "t_F_D01", ""),
                 ("关键语义提取", "auto", "t_llm_intent", ""),
                 ("未知指令容错", "auto", "t_llm_unknown", ""),
                 ("自然语言演示", "manual", None, "输入「把光模块插进老化箱并检测」→技能序列"),
                 ("MES 工单接入", "manual", None, "MES 工单格式解析演示"),
             ]},
            {"fid": "FNllm02", "name": "技能序列生成", "desc": "任务意图 → 技能 Token 序列",
             "tests": [
                 ("技能序列合法", "auto", "t_F_D01", ""),
                 ("序列长度合理", "auto", "t_llm_len", ""),
                 ("多任务可分派", "auto", "t_llm_multi", ""),
                 ("画布节点执行", "manual", None, "双击 LLM 节点→规划序列日志"),
                 ("序列可编排", "manual", None, "技能编排器可组合该序列"),
             ]},
            {"fid": "FNllm03", "name": "序列合法性校验", "desc": "Token 必须在库 + 阶段顺序合法",
             "tests": [
                 ("非法序列拒绝", "auto", "t_F_D01", ""),
                 ("未知 Token 拒绝", "auto", "t_llm_bad", ""),
                 ("顺序错乱修正", "auto", "t_llm_order", ""),
                 ("规则链确定性", "auto", "t_llm_determ", ""),
                 ("离线可运行", "manual", None, "断网→规则拆解路径可用 (LLM 可插拔)"),
             ]},
            {"fid": "FNllm04", "name": "任务场景识别", "desc": "识别作业场景 (五大场景)",
             "tests": [
                 ("场景识别正确", "auto", "t_llm_scene", ""),
                 ("场景技能映射", "auto", "t_llm_map", ""),
                 ("跨场景不串", "auto", "t_llm_iso", ""),
                 ("场景库覆盖", "manual", None, "8 场景 46 需求清单可查"),
                 ("新场景可扩展", "manual", None, "加场景→技能编排器可编排"),
             ]},
            {"fid": "FNllm05", "name": "规划可解释性", "desc": "规划过程与依据可见",
             "tests": [
                 ("Token 含义可读", "auto", "t_llm_token", ""),
                 ("规则依据可查", "auto", "t_llm_rule", ""),
                 ("源码断点可进", "manual", None, "planner.py TaskPlanner.plan 断点可进"),
                 ("规划日志详细", "manual", None, "运行日志打印 token 序列+校验结果"),
                 ("对 LLM 输出审计", "manual", None, "LLM 路径输出有审计日志"),
             ]},
        ],
    },
    "ssreason": {
        "name": "🔍 异常推理器", "fb": "质量截面·诊断",
        "funcs": [
            {"fid": "FNrsn01", "name": "异常类型诊断", "desc": "力控/对准/插入/未接触分类诊断",
             "tests": [
                 ("诊断分类输出", "auto", "t_F_D02", ""),
                 ("四类异常覆盖", "auto", "t_rsn_cat", ""),
                 ("诊断输入触发", "auto", "t_rsn_trig", ""),
                 ("真实异常演示", "manual", None, "构造插入卡滞→诊断日志出类别+建议"),
                 ("诊断对照文档", "manual", None, "异常表与 docs 一致"),
             ]},
            {"fid": "FNrsn02", "name": "恢复建议生成", "desc": "每类异常给恢复建议",
             "tests": [
                 ("建议非空", "auto", "t_rsn_advice", ""),
                 ("建议可执行", "auto", "t_rsn_act", ""),
                 ("建议分级", "auto", "t_rsn_level", ""),
                 ("建议落地演示", "manual", None, "按建议操作→异常恢复"),
                 ("建议可配置", "manual", None, "建议文案/动作可配"),
             ]},
            {"fid": "FNrsn03", "name": "否决超限判定", "desc": "连续否决/卡死识别",
             "tests": [
                 ("连续否决识别", "auto", "t_rsn_veto", ""),
                 ("卡死识别", "auto", "t_rsn_stall", ""),
                 ("计数逻辑正确", "auto", "t_rsn_count", ""),
                 ("真实卡死触发", "semi", "t_rsn_real", "真实化构造卡死→诊断触发"),
                 ("恢复决策可见", "manual", None, "日志显示「连续否决→恢复建议」"),
             ]},
            {"fid": "FNrsn04", "name": "诊断可解释性", "desc": "诊断依据 (阶段/残差/接触) 可追溯",
             "tests": [
                 ("诊断带证据", "auto", "t_rsn_evid", ""),
                 ("证据数值真实", "auto", "t_rsn_num", ""),
                 ("规则确定性", "auto", "t_rsn_determ", ""),
                 ("LLM 可插拔", "manual", None, "配 llm_url→诊断走 LLM→输出审计"),
                 ("源码映射真实", "manual", None, "右键源码进 planner.py ExceptionReasoner"),
             ]},
            {"fid": "FNrsn05", "name": "异常闭环恢复", "desc": "诊断 → 恢复 → 重试闭环",
             "tests": [
                 ("恢复后重试", "auto", "t_rsn_retry", ""),
                 ("恢复不复发", "auto", "t_rsn_norep", ""),
                 ("闭环日志完整", "auto", "t_rsn_log", ""),
                 ("多轮恢复演示", "manual", None, "连续异常→多轮诊断-恢复-重试日志"),
                 ("恢复上限保护", "manual", None, "超 max_veto→转人工提示"),
             ]},
        ],
    },
    "ssskill": {
        "name": "🛠 技能编排器", "fb": "闭环联络·工艺编排",
        "funcs": [
            {"fid": "FNskill01", "name": "场景技能匹配", "desc": "场景 → 技能序列 (8 场景)",
             "tests": [
                 ("场景编排输出", "auto", "t_F_D03", ""),
                 ("技能库覆盖", "auto", "t_skill_lib", ""),
                 ("场景全量可编", "auto", "t_skill_all", ""),
                 ("场景-技能表可查", "manual", None, "双击节点→场景技能链表格"),
                 ("导出全部任务", "manual", None, "右键→导出 Excel (全部任务)"),
             ]},
            {"fid": "FNskill02", "name": "工艺参数注入", "desc": "performance 参数覆盖默认 (力限/节拍)",
             "tests": [
                 ("力限参数注入", "auto", "t_skill_param", ""),
                 ("节拍约束注入", "auto", "t_skill_tact", ""),
                 ("参数覆盖默认", "auto", "t_skill_override", ""),
                 ("参数表可视化", "manual", None, "节点详情显示场景力限/节拍表"),
                 ("产线参数对齐", "manual", None, "对照技术协议力限/节拍"),
             ]},
            {"fid": "FNskill03", "name": "技能库检索", "desc": "原子技能库检索 (242 条/9 类)",
             "tests": [
                 ("技能库加载", "auto", "t_skill_load", ""),
                 ("Token 检索正确", "auto", "t_skill_token", ""),
                 ("技能 ID 唯一", "auto", "t_skill_unique", ""),
                 ("库可视化", "manual", None, "原子技能库面板可浏览 9 大类"),
                 ("新增技能入库", "manual", None, "加技能 Token→注册→可被编排"),
             ]},
            {"fid": "FNskill04", "name": "编排结果校验", "desc": "编排序列合法性校验",
             "tests": [
                 ("非法编排拒绝", "auto", "t_skill_bad", ""),
                 ("序列顺序合法", "auto", "t_skill_order", ""),
                 ("校验可复现", "auto", "t_skill_repro", ""),
                 ("校验失败提示", "manual", None, "非法序列→日志明确拒绝原因"),
                 ("与规划器校验一致", "manual", None, "编排器/规划器同一 Token 校验规则"),
             ]},
            {"fid": "FNskill05", "name": "技能模块化组合", "desc": "原子技能可组合成完整作业 (纤维截面)",
             "tests": [
                 ("技能可组合", "auto", "t_skill_compose", ""),
                 ("组合链完整", "auto", "t_skill_chain", ""),
                 ("重复技能去重", "auto", "t_skill_dedup", ""),
                 ("组合演示", "manual", None, "抓取+转移+插入 组合成插拔全流程"),
                 ("导出组合链", "manual", None, "导出 Excel 含完整技能链"),
             ]},
        ],
    },
    "sscalib": {
        "name": "🧮 标定层", "fb": "闭环联络·标定",
        "funcs": [
            {"fid": "FNcal01", "name": "引力参数标定", "desc": "Kp/阶段速度上限 (引力=快速动作)",
             "tests": [
                 ("引力势计算", "auto", "t_F_E01", ""),
                 ("Kp 写回引擎", "auto", "t_cal_kp", ""),
                 ("阶段 cap 写回", "auto", "t_cal_cap", ""),
                 ("标定面板操作", "manual", None, "双击标定节点→面板引力组→保存→引擎生效"),
                 ("八阶段速度表", "manual", None, "面板八阶段上限表当前阶段高亮"),
             ]},
            {"fid": "FNcal02", "name": "斥力参数标定", "desc": "K_kalman/接触增益/否决阈值 (斥力=状态预测)",
             "tests": [
                 ("斥力势计算", "auto", "t_F_E01", ""),
                 ("标定写回引擎", "auto", "t_cal_rep", ""),
                 ("默认值=引擎真值", "auto", "t_cal_default", ""),
                 ("标定表编辑", "manual", None, "右键→标定表格→斥力组改值→保存→引擎字面量变化"),
                 ("镜像一致性", "manual", None, "写回引擎+镜像 calibration_layer.py 同步"),
             ]},
            {"fid": "FNcal03", "name": "潜空间参数标定", "desc": "latent_dim/力通道/prior_A 标定",
             "tests": [
                 ("潜空间数据齐", "auto", "t_F_E01", ""),
                 ("prior_A 写回", "auto", "t_cal_prior", ""),
                 ("维度校验", "auto", "t_F_E02", ""),
                 ("潜空间组编辑", "manual", None, "标定表格潜空间组: 维度 spin/力通道/prior_A"),
                 ("重构卡尔曼一致", "manual", None, "latent_dim 改维→引擎潜状态维同步"),
             ]},
            {"fid": "FNcal04", "name": "平衡势计算", "desc": "引力势−斥力势 平衡偏差",
             "tests": [
                 ("平衡势正确", "auto", "t_F_E01", ""),
                 ("平衡偏差方向", "auto", "t_cal_gap", ""),
                 ("平衡条可视化", "manual", None, "标定面板平衡条显示当前偏差"),
                 ("调参后平衡变化", "manual", None, "改参数→平衡条移动"),
                 ("审计可追溯", "manual", None, "保存记录参数变更历史"),
             ]},
            {"fid": "FNcal05", "name": "引擎写回生效", "desc": "apply_to_engine 精确写回源码字面量",
             "tests": [
                 ("默认值零 diff", "auto", "t_cal_zerodiff", ""),
                 ("V_MIN 不串 V_CAP", "auto", "t_cal_noserial", ""),
                 ("锚点破坏报错", "auto", "t_cal_anchor", ""),
                 ("importlib 重载生效", "manual", None, "保存标定→▶运行即用新值无需重启 GUI"),
                 ("git diff 验证", "manual", None, "默认值 apply 后引擎 git diff 为空"),
             ]},
        ],
    },
    "ssmani_c": {
        "name": "🧮 接触流形", "fb": "质量截面·几何监测",
        "funcs": [
            {"fid": "FNmc01", "name": "通道轴分解", "desc": "误差分解为切向/法向通道",
             "tests": [
                 ("通道轴分解正确", "auto", "t_F_E03", ""),
                 ("工艺轴对齐", "auto", "t_F_E03", ""),
                 ("阶段轴切换", "auto", "t_mc_axis", ""),
                 ("几何可视化", "manual", None, "3D 显示通道轴 (插入=工艺斜线)"),
                 ("分解可解释", "manual", None, "每通道物理含义标注 (进度/偏离)"),
             ]},
            {"fid": "FNmc02", "name": "法向偏离测量", "desc": "e⊥ 法向偏离风险测量",
             "tests": [
                 ("法向偏离计算", "auto", "t_mc_risk", ""),
                 ("偏离阈值判定", "auto", "t_mc_th", ""),
                 ("偏离有界", "auto", "t_mc_bound", ""),
                 ("偏离可视化", "manual", None, "Scope 法向偏离曲线红色段标风险"),
                 ("真实轨迹偏离", "manual", None, "真实化轨迹插入段偏离先红后收敛"),
             ]},
            {"fid": "FNmc03", "name": "切向进度追踪", "desc": "e∥ 沿工艺轴进度",
             "tests": [
                 ("进度计算正确", "auto", "t_mc_prog", ""),
                 ("进度单调", "auto", "t_mc_mono", ""),
                 ("完成判据", "auto", "t_mc_done", ""),
                 ("进度可视化", "manual", None, "画布/Scope 进度条"),
                 ("插入物理对照", "manual", None, "进度=销头-孔口距离实测对照"),
             ]},
            {"fid": "FNmc04", "name": "流形代价评估", "desc": "V=½‖e‖² 李雅普诺夫代价",
             "tests": [
                 ("代价计算正确", "auto", "t_mc_v", ""),
                 ("代价单调下降", "auto", "t_mc_decay", ""),
                 ("收敛判定", "auto", "t_mc_conv", ""),
                 ("代价曲线可看", "manual", None, "Scope 代价曲线随阶段收敛"),
                 ("稳定性分析对接", "manual", None, "李雅普诺夫稳定性报告引用此 V"),
             ]},
            {"fid": "FNmc05", "name": "流形数据发布", "desc": "接触流形 channel 逐帧发布",
             "tests": [
                 ("io channel 发布", "auto", "t_F_A08", ""),
                 ("全程序列保存", "auto", "t_F_A08", ""),
                 ("总线可消费", "auto", "t_mc_bus", ""),
                 ("Scope 2x3 六格显示", "manual", None, "Scope 含接触流形格"),
                 ("3D 图层显示", "manual", None, "3D 流形图层可开关"),
             ]},
        ],
    },
    "ssmani_p": {
        "name": "🧮 性能流形", "fb": "质量截面·对准评估",
        "funcs": [
            {"fid": "FNmp01", "name": "对准代价评估", "desc": "销头−孔底 加权二次代价",
             "tests": [
                 ("代价计算正确", "auto", "t_mp_v", ""),
                 ("横向重权", "auto", "t_mp_w", ""),
                 ("代价非负", "auto", "t_mp_nonneg", ""),
                 ("可视化面板", "manual", None, "双击节点→性能流形读数"),
                 ("代价物理含义", "manual", None, "δ=销头−孔底, 横向权重 0.4/1/1"),
             ]},
            {"fid": "FNmp02", "name": "耦合效率映射", "desc": "高斯光束近似 η=exp(−V/σ²)",
             "tests": [
                 ("η 计算正确", "auto", "t_F_E04", ""),
                 ("η 范围 0-1", "auto", "t_mp_eta", ""),
                 ("σ 可标定", "auto", "t_mp_sigma", ""),
                 ("效率模型说明", "manual", None, "η 是模型非光功率计实测 (诚实标注)"),
                 ("真机标定 W/σ", "manual", None, "真机光功率实测→标定 W/σ (验收项)"),
             ]},
            {"fid": "FNmp03", "name": "完成态判定", "desc": "插入完成态 η 高判据",
             "tests": [
                 ("完成态 η>0.5", "auto", "t_F_E04", ""),
                 ("未插入 η≈0", "auto", "t_F_E04", ""),
                 ("完成判定阈值", "auto", "t_mp_done", ""),
                 ("真实轨迹终态", "manual", None, "真实化完成轮 η 0.57→0.77 记录"),
                 ("光路物理对照", "manual", None, "插好光通 η 高/未插 η≈0 语义"),
             ]},
            {"fid": "FNmp04", "name": "性能退化监测", "desc": "η 低/不升 = 质量退化信号",
             "tests": [
                 ("退化检出", "auto", "t_mp_degrade", ""),
                 ("非接触段 η≈0 不误报", "auto", "t_mp_nofalse", ""),
                 ("监测连续性", "auto", "t_mp_cont", ""),
                 ("退化告警演示", "manual", None, "插入未到位→η 低→告警/诊断"),
                 ("对接异常推理", "manual", None, "η 持续低触发异常诊断"),
             ]},
            {"fid": "FNmp05", "name": "流形几何可视化", "desc": "性能流形地图展示",
             "tests": [
                 ("地图数据发布", "auto", "t_mp_bus", ""),
                 ("全程序列", "auto", "t_mp_seq", ""),
                 ("Scope 格显示", "manual", None, "Scope 性能流形格 η 曲线"),
                 ("3D 叠加显示", "manual", None, "3D 完成态高亮/偏离红"),
                 ("与接触流形共表", "manual", None, "双流形同帧可对照"),
             ]},
        ],
    },
    "sslat": {
        "name": "🧮 潜空间", "fb": "底空间·低维结构(世界模型)",
        "funcs": [
            {"fid": "FNlat01", "name": "潜坐标提取", "desc": "引擎轨迹 → 潜状态坐标",
             "tests": [
                 ("潜坐标输出", "auto", "t_lat_coord", ""),
                 ("维数与标定一致", "auto", "t_F_E02", ""),
                 ("坐标连续", "auto", "t_lat_cont", ""),
                 ("潜坐标可视化", "manual", None, "潜空间节点显示坐标/速度场"),
                 ("物理含义可读", "manual", None, "坐标=位置3+预测力1 (flat-linear)"),
             ]},
            {"fid": "FNlat02", "name": "有效维度分析", "desc": "PCA 实测有效维 vs latent_dim",
             "tests": [
                 ("PCA 有效维校验", "auto", "t_F_E02", ""),
                 ("2D@95% 实测", "auto", "t_lat_2d", ""),
                 ("常量维无方差", "auto", "t_lat_const", ""),
                 ("维数分析报告", "manual", None, "报告含有效维/方差占比"),
                 ("分析可复现", "manual", None, "同轨迹两次 PCA 一致"),
             ]},
            {"fid": "FNlat03", "name": "速度场估计", "desc": "潜空间速度场 (prior−x̂₋)",
             "tests": [
                 ("速度场计算", "auto", "t_lat_vel", ""),
                 ("方向一致", "auto", "t_lat_dir", ""),
                 ("场连续", "auto", "t_lat_field", ""),
                 ("速度场可视化", "manual", None, "潜空间节点速度场箭头"),
                 ("流形导航语义", "manual", None, "速度场=流形地图导航读数"),
             ]},
            {"fid": "FNlat04", "name": "流形标定校验", "desc": "标定潜维 vs 引擎实际",
             "tests": [
                 ("标定-实际一致", "auto", "t_F_E02", ""),
                 ("prior_A 单源", "auto", "t_lat_prior", ""),
                 ("重构卡尔曼正确", "auto", "t_lat_kalman", ""),
                 ("标定表操作", "manual", None, "潜空间组维度 spin 改→校验提示"),
                 ("引擎锚点单一", "manual", None, "PriorDynamicsPredictor(A= 只有一处锚点"),
             ]},
            {"fid": "FNlat05", "name": "潜空间发布消费", "desc": "潜状态 channel 逐帧发布",
             "tests": [
                 ("io channel 发布", "auto", "t_lat_bus", ""),
                 ("画布连线去向", "auto", "t_lat_link", ""),
                 ("总线滚动可查", "manual", None, "总线潜空间行随帧滚动"),
                 ("3D 图层", "manual", None, "3D 潜空间/流形图层可开关"),
                 ("Scope 潜空间格", "manual", None, "Scope 含潜空间 V/η 格"),
             ]},
        ],
    },
}

# ════════════════════════════════════════════════════════════════════
# 功能组合链 (模块化: 纤维丛截面合成 — 原子功能组合为完整作业能力)
# 每链: 组合名 | 描述 | [功能fid...] | 覆盖节点数
# ════════════════════════════════════════════════════════════════════
# ════════════════════════════════════════════════════════════════════
# 规范场论三层分组 (2026-09-04 老倪: 按 Gauge Theory 重构 function list)
#   场感知层     Gauge Field Perception      — 感知场变化 (底空间·观测)
#   协变操作层   Gauge Covariant Operations  — 补偿扰动 (联络·动作/控制/标定/流形)
#   对称认知层   Gauge Symmetry & Invariance — 环境变化下等效工艺 (规划/编排/诊断)
# 映射规则 (fb 标签 → gauge 层): 状态观测/感知 → 场感知; 纤维动作/闭环联络/质量截面
#   的几何监测 → 协变操作; 工艺编排/规划/诊断 → 对称认知。模块化=截面合成 (FUNC_CHAINS)。
# ════════════════════════════════════════════════════════════════════
GAUGE_LAYERS = [
    ("G1", "场感知层", "Gauge Field Perception",
     "感知场的变化: 视觉/力觉/触觉/几何 → 状态重构 (对规范场的精准捕获)",
     ["ssyolo", "ss2d3d", "sstactile", "sssensor", "ssobs", "ssdata",
      "ssworld", "ssaoi", "sslat"]),
    ("G2", "协变操作层", "Gauge Covariant Operations",
     "协变导数: 执行动作时自适应补偿公差/形变扰动 (规范不变操作)",
     ["ssff", "ssest", "sspred", "ssinnov", "sssched", "sslimit", "ssact",
      "sscalib", "ssmani_c", "ssmani_p"]),
    ("G3", "对称认知层", "Gauge Symmetry & Invariance",
     "规范对称性: 批次/来料姿态变化下, 规划出等效正确工艺路径 (双模型架构)",
     ["ssllm", "ssreason", "ssskill"]),
]

# 节点 key → gauge 层 id (快速查找)
GAUGE_OF_NODE = {nk: g[0] for g in GAUGE_LAYERS for nk in g[4]}


def gauge_of(node_key):
    """节点 → 规范场层 (未映射节点归 G2 协变操作)"""
    return GAUGE_OF_NODE.get(node_key, "G2")


def gauge_stats():
    """每层: 节点数/功能数/用例数"""
    out = []
    for gid, zh, en, desc, nks in GAUGE_LAYERS:
        n = len(nks)
        f = sum(len(NODE_TREE[k]["funcs"]) for k in nks if k in NODE_TREE)
        t = sum(len(fn["tests"]) for k in nks if k in NODE_TREE
                for fn in NODE_TREE[k]["funcs"])
        out.append((gid, zh, en, desc, n, f, t))
    return out


FUNC_CHAINS = [
    ("视觉感知链", "图像 → YOLO 检出 → 2D→3D 解算 → 观测对齐 (感知到状态)",
     ["FNyolo01", "FNyolo02", "FN2d01", "FN2d02", "FNobs02"]),
    ("状态闭环链", "融合 → 前馈/估计 → 预测 → 校正 → 调度 → 限幅 → 执行 (完整控制环)",
     ["FNsens01", "FNff01", "FNest01", "FNpred01", "FNinn02", "FNsched01", "FNlim01", "FNact01"]),
    ("精密插拔工艺", "八阶段调度 + 接触感知 + 夹持质量 + 流形监测 (光模块插拔核心截面)",
     ["FNsched01", "FNtac02", "FNtac05", "FNmc02", "FNmp03"]),
    ("质量门链", "AOI 检测 + 性能流形 η + 异常诊断 (良率守门)",
     ["FNaoi02", "FNmp03", "FNrsn01"]),
    ("边学边练闭环", "数据源 → 训练 → 部署 → 推理 → 数据回流 (数据闭环截面)",
     ["FNdata01", "FNdata04", "FNff04", "FNworld04"]),
]

# 便捷统计
def node_count():
    return len(NODE_TREE)


def func_count():
    return sum(len(n["funcs"]) for n in NODE_TREE.values())


def test_count():
    return sum(len(f["tests"]) for n in NODE_TREE.values() for f in n["funcs"])


def kind_count():
    from collections import Counter
    c = Counter()
    for n in NODE_TREE.values():
        for f in n["funcs"]:
            for t in f["tests"]:
                c[t[1]] += 1
    return dict(c)


def check_contract():
    """结构契约: 每节点≥5功能 / 每功能≥5用例 / 功能名 5~10 字 / 用例id唯一"""
    errs = []
    seen_t = set()
    for nk, n in NODE_TREE.items():
        if len(n["funcs"]) < 5:
            errs.append(f"{nk}: 功能数 {len(n['funcs'])} < 5")
        for f in n["funcs"]:
            L = len(f["name"])
            if not (5 <= L <= 10):
                errs.append(f"{f['fid']}: 功能名「{f['name']}」{L}字, 需 5~10 字")
            if len(f["tests"]) < 5:
                errs.append(f"{f['fid']}: 用例数 {len(f['tests'])} < 5")
            for t in f["tests"]:
                if len(t) != 4:
                    errs.append(f"{f['fid']}: 用例元组 {len(t)} 字段≠4")
                    continue
                key = (nk, f["fid"], t[0])
                if key in seen_t:
                    errs.append(f"{nk}/{f['fid']}: 用例重复 {t[0]}")
                seen_t.add(key)
    return errs
