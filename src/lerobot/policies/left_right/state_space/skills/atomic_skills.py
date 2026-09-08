#!/usr/bin/env python3
"""atomic_skills.py — Z-MAX 原子技能库 (真实源码, 2026-09-08 老倪: 集中到 src/lerobot)

🧩 原子技能层: 决策层 (动作调制器状态机经安全边界) 选定当前技能 → 复制技能模板
实例化 → 快速执行 → 输出执行指令给 🤖执行器。

本文件 = 原子技能模板的**权威定义源** (SK01-08 = 插装任务 8 阶段模板)。
画布 SK01-08 节点 (sssk1-8) 右键源码指向本文件的技能类; node_logic 播放展示
读本文件模板 + 引擎轨迹当前帧 (stage=当前技能 / target=决策赋值 / u_exec_vec=实际下发)。

⚠️ 数值同源契约 (勿改单边): 模板参数与引擎执行常量保持一致 —
  简化引擎 tools/gui/state_space_sim.py · 真实化 tools/gui/state_space_sim_real.py
  (STAGE_* / cognition.py ActionModulator.STAGE_V_CAP / insert_depth / grasp_th)。
  改技能参数 = 同步引擎常量 (或后续把引擎改为直接 import 本文件, 本文件即唯一真源)。

夹爪语义契约: 引擎/3D: 0=张开 1=夹紧; metaworld obs 反 (1=张开 0=闭合), 记录层 1−obs。
任务链: SK01-08 = 插装 8 段 (mode=insert); mode=full 追加 拔出/AOI转移/AOI检测/回程/放下
(13 段) — 新技能模板按同构扩展 (见 SKILL_ORDER 注释)。
"""


class AtomicSkill:
    """原子技能模板基类 — 一个技能 = 一段可实例化执行的固定轨迹模板。

    决策层"实时赋值" (阶段目标/速度) 后复制实例化; 字段:
      code    技能编号 (SK01-08)
      stage   对应状态机阶段名 (cognition.ActionModulator.STAGES)
      goal    目标语义 (锚=光模块头/夹爪, 与 _stage_target 同语义)
      params  关键模板参数 (数值同源引擎常量, 见顶部契约)
      evidence 本技能完成的推进证据 (状态机 advance 判据)
      ctrl    控制语义 (夹爪/限速)
      source  数值来源引擎常量 (溯源)
    """

    code = "SK--"
    stage = ""
    name = ""
    desc = ""
    goal = ""
    params = {}
    evidence = ""
    ctrl = {}
    source = ""


class SK01Approach(AtomicSkill):
    """① 接近 — 从初始位移动到光模块抓握点正上方 (悬停, 不触碰)"""
    code = "SK01"
    stage = "接近"
    name = "① 接近"
    desc = "夹爪移动到光模块抓握点正上方悬停 (水平粗对准)"
    goal = "光模块头 → peg + (0, 0, 0.09) 上方 (水平 xy 追 peg, z 悬停)"
    params = {"hover_h": 0.09}            # STAGE_APPROACH_H (sim_real)
    evidence = "手-光模块水平距离 < 0.06 (align_xy_coarse) → 对位"
    ctrl = {"gripper": "张开", "v_cap": 0.35, "v_min": 0.12}
    source = "state_space_sim_real.STAGE_APPROACH_H / cognition.STAGE_V_CAP"


class SK02Align(AtomicSkill):
    """② 对位 — 光模块上方精对位 (更低悬停, 准备垂直下刀)"""
    code = "SK02"
    stage = "对位"
    name = "② 对位"
    desc = "降到光模块上方精对位高度, 消除水平残差"
    goal = "光模块头 → peg + (0, 0, 0.05) 上方"
    params = {"hover_h": 0.05}            # STAGE_ALIGN_H
    evidence = "手-光模块水平距离 < 0.02 (align_xy_fine) → 下降"
    ctrl = {"gripper": "张开", "v_cap": 0.12, "v_min": 0.04}
    source = "state_space_sim_real.STAGE_ALIGN_H"


class SK03Descend(AtomicSkill):
    """③ 下降 — 张爪垂直下刀包住光模块身 (触到即停)"""
    code = "SK03"
    stage = "下降"
    name = "③ 下降"
    desc = "张开的夹爪垂直下降到抓握点 (包住光模块两侧)"
    goal = "夹爪 → peg 抓握点 + (0, 0, 0.004) (贴到抓握点)"
    params = {"descend_h": 0.004,          # STAGE_DESCEND_H
              "z_stall_frames": 8}         # 下降停滞判据 (被销/台顶住)
    evidence = "接触概率 >0.6 (力觉) 或 到达抓握位姿 (几何+z停滞≥8帧) → 抓取"
    ctrl = {"gripper": "张开 (到位前不闭 — 状态锁存非比例)", "v_cap": 0.09}
    source = "state_space_sim_real.STAGE_DESCEND_H / _z_stall"


class SK04Grasp(AtomicSkill):
    """④ 抓取 — 闭合夹爪深夹 (夹持锁存, 抬起前随动验证)"""
    code = "SK04"
    stage = "抓取"
    name = "④ 抓取"
    desc = "夹爪闭合深夹光模块 → 锁存夹持偏移 (真机同构: 编码器锚定)"
    goal = "原地闭爪 (深夹: 夹紧度 1−obs 升到 ≥0.50, obs<0.50)"
    params = {"grasp_th": 0.50,            # 夹紧度阈值 (obs<0.50)
              "grasp_sat": 0.70}           # metaworld 夹住销饱和 (~0.70 obs)
    evidence = "夹紧度 >0.50 (深夹到位) → 抬起; 15 帧稳定+<8mm → 真值锚定"
    ctrl = {"gripper": "闭合锁存 (抓取及之后恒闭合)", "v_cap": 0.04}
    source = "cognition.ActionModulator(grasp_th=0.50) / GRASP_SAT"


class SK05Lift(AtomicSkill):
    """⑤ 抬起 — 垂直提起光模块离台 (随动验证夹持是否真建立)"""
    code = "SK05"
    stage = "抬起"
    name = "⑤ 抬起"
    desc = "垂直抬升光模块离台面到转移高度 (夹持质量由随动判定)"
    goal = "光模块 body z → peg_z0 + 0.16 (STAGE_LIFT, 高于孔口 0.13)"
    params = {"lift_h": 0.16}              # STAGE_LIFT (真实化; 销升 16cm)
    evidence = "提起高度 >0.08 (lift_h 判据) → 转移; 滑脱(off 漂移>8mm) → 回接近重抓"
    ctrl = {"gripper": "闭合保持", "v_cap": 0.30, "v_min": 0.10}
    source = "state_space_sim_real.STAGE_LIFT / GRASP_SLIP_MM"


class SK06Transfer(AtomicSkill):
    """⑥ 转移 — 持光模块平移至孔口上方 (悬高 2cm, 对准插孔)"""
    code = "SK06"
    stage = "转移"
    name = "⑥ 转移"
    desc = "夹持光模块水平转移到带孔盒孔口正上方 (工艺定位)"
    goal = "光模块头 → 孔口 + (0, 0, 0.02) (INSERT_HOVER 悬高)"
    params = {"hover": 0.02,               # INSERT_HOVER (孔口上方悬高)
              "align_th": 0.025}           # 头-孔口水平对准阈值
    evidence = "头-孔口水平 <0.025 且 peg 头悬孔口 2cm±1.2cm → 插入"
    ctrl = {"gripper": "闭合保持", "v_cap": 0.35, "v_min": 0.12}
    source = "cognition.INSERT_HOVER / sim_real align_th"


class SK07Insert(AtomicSkill):
    """⑦ 插入 — 毫米级解析伺服精插 (两段式: 垂直对心→水平推入孔底)"""
    code = "SK07"
    stage = "插入"
    name = "⑦ 插入"
    desc = "光模块头对心孔口 → 沿孔轴推入孔底 (接触段, 禁肌肉记忆快通道)"
    goal = "光模块头 → 孔底 goal (插深 < 6mm 判完成)"
    params = {"insert_depth": 0.006,       # 完成判据 (离孔底 6mm)
              "z_align_tol": 0.0012,       # 段① z 对心容差 (1.2mm, 防顶孔沿)
              "stall_backoff": "遇阻回撤 12帧≈15mm → 分级重试(转移/接近)"}
    evidence = "插深 <0.006 → 完成 (full 模式 → 拔出)"
    ctrl = {"gripper": "闭合保持 (力控推入)", "v_cap": 0.085, "v_min": 0.02}
    source = "sim_real insert_depth=0.006 / cognition.STAGE_V_MIN 插入"


class SK08Complete(AtomicSkill):
    """⑧ 完成 — 插入到位, 本轮任务结束 (mode=full 续拔出/AOI 链)"""
    code = "SK08"
    stage = "完成"
    name = "⑧ 完成"
    desc = "插入深度达标 → 任务完成 (mode=insert 终点; full 模式插入后进入拔出链)"
    goal = "保持 (已插到底)"
    params = {"done": "depth < insert_depth 连续确认", "mode_full_next": "拔出"}
    evidence = "阶段 == 完成 (done)"
    ctrl = {"gripper": "闭合保持", "v_cap": 0.02}
    source = "cognition.ActionModulator STAGES[完成]"


# ── 技能注册表 (插装 8 段; 顺序 = 状态机推进序) ──
SKILLS = [SK01Approach, SK02Align, SK03Descend, SK04Grasp,
          SK05Lift, SK06Transfer, SK07Insert, SK08Complete]

# stage → 技能 (状态机当前阶段 → 当前技能模板)
SKILL_BY_STAGE = {cls.stage: cls for cls in SKILLS}
# code → 技能
SKILL_BY_CODE = {cls.code: cls for cls in SKILLS}


def list_skills():
    """技能清单 (GUI/文档/测试复用)"""
    return [{"code": cls.code, "name": cls.name, "stage": cls.stage,
             "desc": cls.desc, "params": dict(cls.params),
             "evidence": cls.evidence, "ctrl": dict(cls.ctrl),
             "source": cls.source}
            for cls in SKILLS]


if __name__ == "__main__":
    print("=== Z-MAX 原子技能库 (SK01-08, 真实源) ===")
    for s in list_skills():
        print(f"  {s['code']} {s['name']} [{s['stage']}] {s['desc']}")
        print(f"      目标: {s['goal']}")
        print(f"      推进: {s['evidence']}")
        print(f"      参数: {s['params']}  ctrl: {s['ctrl']}")
