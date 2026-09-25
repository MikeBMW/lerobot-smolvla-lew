#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中版本迭代: v5.14.0 → v5.15.0 (老倪 2026-09-25「中版本迭代, 发布 windows mac 版本」)

只做三件事（可 review、可回滚）:
  ① studio.py 版本串 v5.14.0 → v5.15.0（3 处显示位）
  ② 在 v5.14.0 变更块之前插入 v5.15.0 变更块（与既有格式一致）
  ③ 校验: 替换处数、语法、changelog 连续性
"""
import ast
import io
import re
import sys

P = "tools/gui/studio.py"
OLD, NEW = "Z-MAX v5.14.0", "Z-MAX v5.15.0"   # ★ 精确到显示模式: 不碰历史变更块 "# v5.14.0:"

ENTRY = """# v5.15.0: 🌀 **流形引擎 + 阶段专家 MOE + 全系统训练/部署控制平台 (中版本)** — 老倪: 「训练的总目标是流形引擎，在APP的训练控制界面，我要看到模型训练的结构化流形」/「阶段专家MOE升级改造, 全系统模型微调」/「训练加部署控制，L2模型训练给小芳，L3以上微调训练给静静，Web你提供控制平台」/「同步仿真与实际环境，造数据，继续训练」/「中版本迭代, 发布windows mac版本」 ①**阶段专家 MOE (7 专家 × 硬先验路由)** `tools/stage_moe_backbone.py`: 共享 SigLIP 768d 冻结主干 + 7 个阶段专家(接近/对位/下降/抓取/抬起/转移/插入) + 门控; **学习式门控实测坍缩**(两版都坍缩: 单射性 4/7 与 1/7) ⇒ 改 **`--route prior` 硬先验路由**, 路由熵 **0.000**、**单射性 7/7**(每阶段 100% 专属专家)、有效专家 7/7; 判据同步加 **单射性**(旧判据"每行最大值"会假阳性 — 曾据此误报"6/7 分化成立"已撤回) ②**按阶段误差拆解** `tools/perstage_error_compare.py`: 三方同口径(n=3000) — **接触段动作误差**: 密集 0.0955 · 容量版(MOE-soft) 0.1157 · **分工版(MOE-prior) 0.0905 最优**; 插入段(n=254) 0.0225 → **优于密集 17%、优于容量版 44%** ⇒ **阶段分工的价值体现在接触段**(正是此前诊断出的瓶颈), 而容量堆叠只改善非接触段观测 ③**统一主干两阶段配方** `tools/joint_unified_backbone.py`: 几何增强训练(阶段1) → 短程无增强微调(阶段2) ⇒ **精度与鲁棒性兼得**(推翻此前"二者权衡"的错误结论); 最优档 **v13 留出 0.008/动作 0.047**, 几何不变性 **四杆全过**(平移 0.997/缩放 0.997/旋转 0.998/流形一致性 6.8%, 对照无增强基线 0.817/0.841/0.886/65.4%); 阶段2 长度实验(v13 600步 vs v14 4000步) ⇒ **阶段2 越短越好**(拉长只换 0.002 精度却把一致性从 6.8% 磨到 13.4%) ④**造数据 + 域随机化 + 训练增益** `tools/l5_plan_and_gen.py`: 补上缺失的 `skill_ctx` 字段(此前 l5_* 数据集无此列 → MOE 用不了的根因); L5 定方向造 **23,393 帧**(对位±20mm·高度±10mm·阶段组合·力档30/40/50·速度0.8/1.0/1.2); **新旧混合训练实测增益**: 留出观测 **0.013 → 0.010 (优 23%)** · 动作 0.050 → 0.049 ⑤**结构化流形视图** `tools/manifold_train_view.py`: **全部数值来自真实调用**(`su2.py` 群引擎 + 引擎 trace 实测数组, 缺项按 0 不编造); **纯数学自检 8/8**(单位元/θ=|rotvec|/U·U⁻¹=I/不可交换性/FS 自距离/L5未接→单位元/剥离残差); 过程中自查发现"(U·U⁻¹).θ=2.98e-08"是**我的阈值过严(1e-9)**而非代码 bug, 已按 float64 实际精度改为 1e-6 并复验; 引擎真跑 240 步: θ min 1.687/max 2.746/mean 1.870, **层间耦合 L3|L4 = 0.5618 最强**(状态调度↔认知, 符合物理直觉) · L2|L3 0.1424 · L2|L4 0.1142, **FS 测地距离** 首→中 0.323/首→末 0.671, 末帧各层 θ: L2 0.188(检测)/L3 0.846(调度)/L4 2.542(认知主导)/**L5 0.0(未接 LLM, 诚实标注)** ⑥**训练 + 部署 Web 控制平台** `tools/train_deploy_console.py`: **零依赖单文件**(标准库 http.server) → 可复制可运维; **分工硬编码为策略** — L2 检测层归**小芳(Mac 备份端)**、L3/L4/L5/MEM 归**静静(4060 工作端)**; L2 训练请求 → **生成"待小芳执行"处理单(不越权在本机跑)**; L3+ → 本机直接启动(实测 job+日志+审计); **部署控制**: 晋级默认档/回滚 带 **sha256 + prev 记录 + 审计流水**(`models/model_default.json` · `docs/deploy_audit.jsonl`); 管道状态与画布/CICD 控制台**同一真源**(`docs/PIPELINE_STATE.json`); **🌀 结构化流形面板**内嵌(θ(t) 测地演化曲线 / 各层 θ 条形 / 层间耦合矩阵 / L5=0 明标"未接 LLM") ⑦**全系统 Pipeline 训练编排器** `tools/system_train_orchestrator.py`: 每层做成统一 trainer 插件(`preflight/train/evaluate`), 状态落盘供画布轮询; 实测一次编排跑通 MEM→L4moe→L4 (2099s), **同口径 MOE 观测 0.0091 vs 密集 0.013(优 30%)** ⑧**L5 大模型层升级策略** `docs/L5-UPGRADE-STRATEGY.md`: 四条按投产比排序 — P1 结构化输出+三条硬校验(顺序合法/依赖满足/与观测一致) · P2 分级调用(高频本地<200ms/低频才调云端) · P3 视觉表征收口(L5 复用 L4 的 SigLIP 768d 特征, 免二次编码省 0.35GB) · P4 规划-预测联动(L5 出 K 候选 → L4 rollout 打分选优, MPC 思路); 明确不建议(换更大本地 VLM/端到端微调/每步调云端) ⑨**仿真↔真机同步 + 可复制交付**: `sim2real_bridge.py --check` 动力学/运动学/TCP/限幅已对齐(**FK 残差 3.518mm**), 3 个感知几何缺口待现场(T_base_cam/plane_z/示教点); **ECS 大包分片发布器**(绕 nginx 200m 限)+ **ECS 开机自检恢复**+ **主页访问白名单**(只允许静静4060 `103.114.194.13` + 小芳 Mac, 默认只锁主页不切中转链); 可复制交付 T1 包 391MB 已验(缺失0/不符0/冒烟✅) ⑩**重大环境发现** — Hermes 工具对每条命令的临时 scope 有 **~8GB 内存上限**(实测 OOM 时机器仍余 21GB): 定位靠 `dmesg | grep 'Memory cgroup out of memory'` 的 `CONSTRAINT_MEMCG` + `oom_memcg=.../hermes-worker-*.scope`; 对策已落进训练脚本(**按 MemAvailable 自动算缓存上限** + `--cache-gb` 显式开关 + **两个调用点都要传**(第一版只改一处仍照装大缓存 OOM — 同类"补丁只改一处"当日第三次) + page cache 清理 + 磁盘流式降级) ⑪**闭环任务诚实结论**: 统一主干在引擎闭环 **A/B n=10 与在役模型逐 seed 同生共死**(成功率 7/10 = 7/10, 深度差 ≤5mm) ⇒ **集成成功但无任务级提升**, 机理 = 融合权重仅 **w=0.30**(解析反馈占 70% 主导)且失败点同源在接触段; 待验证杠杆 = 提高 w 后重测\n"""


def main():
    src = io.open(P, encoding="utf-8").read()
    n_old = src.count(OLD)
    print("  ① 待替换版本串: %d 处 (期望 3)" % n_old)
    if n_old < 3:
        print("  ❌ 版本串少于 3 处, 停止（避免漏改）")
        return 2
    src2 = src.replace(OLD, NEW)
    # 插入 changelog（在 v5.14.0 变更块之前）
    anchor = "# v5.14.0:"   # 历史块锚点(替换后仍应存在)
    if anchor not in src2:
        print("  ❌ 找不到 v5.14.0 变更块锚点")
        return 2
    src2 = src2.replace(anchor, ENTRY + anchor, 1)
    io.open(P, "w", encoding="utf-8").write(src2)

    # 校验
    chk = io.open(P, encoding="utf-8").read()
    ok = []
    ok.append(("版本串已升到 %s (3 处)" % NEW, chk.count(NEW) >= 3))
    ok.append(("历史变更块 # v5.14.0: 仍在", "# v5.14.0:" in chk))
    ok.append(("显示位旧串残留 0", chk.count("Z-MAX v5.14.0") == 0))
    ok.append(("v5.15.0 变更块已插入", "# v5.15.0:" in chk))
    ok.append(("v5.14.0 变更块仍在", "# v5.14.0:" in chk))
    try:
        ast.parse(chk)
        ok.append(("Python 语法 OK", True))
    except SyntaxError as e:
        ok.append(("Python 语法 OK (%s)" % e, False))
    print("  ② 校验:")
    for nm, v in ok:
        print("     %s %s" % ("✅" if v else "❌", nm))
    return 0 if all(v for _, v in ok) else 2


if __name__ == "__main__":
    raise SystemExit(main())
