#!/usr/bin/env python3
"""生成 L4 演示定制场景 XML: 桌面加 ①来料转台(干扰机构, 光模块放台上被外力水平旋转90°)
②光耦合压电定位台(参照芯明天压电陶瓷: 底座+叠堆+载物台+光纤头)。
写入 metaworld 包 assets/sawyer_xyz/ (同目录 include 相对路径全部有效), 不影响原环境文件。
"""
import os, sys, shutil

# 🐛 2026-09-11 (Windows CI/EXE 实测): Windows 控制台默认 cp1252 → print("✅ 写入: ...")
#   抛 UnicodeEncodeError 直接 exit 1 (CI「Generate L4 demo scene XML」步骤实测失败); GUI
#   子进程捕获输出同理。统一 UTF-8, 不可用则 replace 降级 — 绝不因日志编码崩掉任务。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _mw_assets_dir():
    """metaworld 包 assets 目录多候选探测 — 🐛 2026-09-11 根因修复:
    原硬编码 ~/lerobot-smolvla-lew/gui-venv311/lib/python3.11/site-packages/...
    → CI (mac/win runner) 与 PyInstaller frozen 环境一律找不到该路径 →
    L4 场景 XML 生成失败 (静默) = 打包版 L4 没有转台/耦合台设备 = 开机就没有干扰机构,
    与"L4 看不到干扰旋转"直接相关。改为按 metaworld 包实际位置解析。"""
    cands = []
    try:
        import metaworld as _mw
        cands.append(os.path.join(os.path.dirname(os.path.abspath(_mw.__file__)), "assets"))
    except Exception:
        pass
    _mp = getattr(sys, "_MEIPASS", None)          # frozen: metaworld 在 _MEIPASS/metaworld
    if _mp:
        cands.append(os.path.join(_mp, "metaworld", "assets"))
    cands.append(os.path.expanduser(
        "~/lerobot-smolvla-lew/gui-venv311/lib/python3.11/site-packages/metaworld/assets"))
    cands.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "gui-venv311/lib/python3.11/site-packages/metaworld/assets"))
    for c in cands:
        if os.path.isfile(os.path.join(c, "sawyer_xyz", "sawyer_peg_insertion_side.xml")):
            return c
    return cands[0]


MW_ASSETS = _mw_assets_dir()
SRC = os.path.join(MW_ASSETS, "sawyer_xyz", "sawyer_peg_insertion_side.xml")
DST = os.path.join(MW_ASSETS, "sawyer_xyz", "sawyer_peg_insertion_side_l4.xml")

EXTRA = """
  <!-- 🎯 L4 演示 (2026-09-09 老倪: 抗干扰=来料被外力旋转90°; 光耦合精密操作=精细交互):
       ① 来料转台 turntable — 光模块放台上, 转台绕z转90° = "桌面被外力水平旋转90°"
          (治具携带; 演示固定落点盘中心)。盘面深灰 + 白十字刻度线随盘转, 转角肉眼可见。
          ⚠️ 2026-09-09 布局修正: (0.10,0.60)→(0.30,0.30) — 原位与 3D AOI 设备视觉区 (0.12,0.62) 重合。
          ② 光耦合压电定位台 coupler — 参照芯明天压电陶瓷: 金属底座 + 黄色压电叠堆 +
          x/y 压电微动载物台 (slide ±2mm) + 光纤头基准 (cp_ref)。放桌面空白(右前),
          承载面摩擦 5 可稳定携带光模块微动; 光模块头(pegHead) 对准光纤头 = 耦合基准。 -->
          <body name="turntable" pos="0.42 0.60 0">
    <joint name="tt_yaw" type="hinge" axis="0 0 1" limited="false" damping="0.02"/>
    <inertial pos="0 0 0.005" mass="0.35" diaginertia="0.0005 0.0005 0.001"/>
    <geom name="tt_disc" type="cylinder" size="0.075 0.005" pos="0 0 0.005" rgba="0.30 0.32 0.38 1"
          contype="1" conaffinity="1" friction="2.0 0.02 0.002"/>
    <geom name="tt_ring" type="cylinder" size="0.075 0.0052" pos="0 0 0.0055" rgba="0.55 0.58 0.65 0.5"
          contype="0" conaffinity="0"/>
    <geom name="tt_mark1" type="box" size="0.062 0.0025 0.0005" pos="0 0 0.0104" rgba="0.9 0.92 0.95 0.9"
          contype="0" conaffinity="0"/>
    <geom name="tt_mark2" type="box" size="0.0025 0.062 0.0005" pos="0 0 0.0104" rgba="0.9 0.92 0.95 0.9"
          contype="0" conaffinity="0"/>
  </body>

  <body name="coupler" pos="0.55 0.42 0">
    <geom name="cp_base" type="box" size="0.17 0.055 0.010" pos="0 0 0.010" rgba="0.42 0.44 0.50 1"
          contype="1" conaffinity="1"/>
    <geom name="cp_pzt_a" type="box" size="0.06 0.008 0.010" pos="-0.07 0 0.030" rgba="0.82 0.70 0.15 1"
          contype="0" conaffinity="0"/>
    <geom name="cp_pzt_b" type="box" size="0.06 0.008 0.010" pos="0.07 0 0.030" rgba="0.78 0.66 0.12 1"
          contype="0" conaffinity="0"/>
    <!-- 光纤头 (固定基准, 指向台上光模块头) -->
    <geom name="cp_fiber" type="cylinder" size="0.0035 0.016" pos="-0.13 0 0.067" euler="0 1.57 0"
          rgba="0.85 0.87 0.9 1" contype="0" conaffinity="0"/>
    <site name="cp_ref" pos="-0.13 0 0.067" size="0.004" rgba="1 0.3 0.3 1"/>
  </body>

  <!-- x/y 压电微动载物台 (free 须 worldbody 顶级实锤): 每步 qpos 强钉 = 压电位置闭环等效,
       与治具转台同机制实测稳定; 行程 ±2mm 由脚本限; 与 coupler 底座坐标对齐 (0.55,0.42) -->
  <body name="cp_stage_b" pos="0.55 0.42 0.044">
    <joint type="free" damping="0.05"/>
    <inertial pos="0 0 0" mass="0.5" diaginertia="0.0002 0.0002 0.0002"/>
    <geom name="cp_stage" type="box" size="0.17 0.055 0.004" pos="0 0 0.004" rgba="0.22 0.25 0.32 1"
          contype="1" conaffinity="1" friction="5 0.02 0.002"/>
    <geom name="cp_scale" type="box" size="0.15 0.002 0.001" pos="0 0 0.009" rgba="0.65 0.7 0.78 0.8"
          contype="0" conaffinity="0"/>
    <site name="cp_stage_top" pos="0 0 0.008" size="0.004"/>
  </body>
"""

def main():
    assert os.path.isfile(SRC), SRC
    s = open(SRC, encoding="utf-8").read()
    assert "<worldbody>" in s and "</worldbody>" in s
    assert "turntable" not in s, "目标 XML 已存在注入?"
    # peg 惯量双模式: --peg-real-inertia (演示出片: 夹持旋转需真实惯量, 大惯量下刚性锁相位错乱实锤)
    #   默认 100000 原值 (引擎插拔/回归链依赖防滚大惯量, 不回退红线; 引擎场景 90° 段用治具钉)
    import argparse as _ap
    _ap2 = _ap.ArgumentParser()
    _ap2.add_argument("--peg-real-inertia", action="store_true", help="peg 用真实盒惯量 (演示出片用)")
    _a2 = _ap2.parse_args()
    if _a2.peg_real_inertia:
        s = s.replace('<inertial pos="0 0 0" mass="0.1" diaginertia="100000 100000 100000"/>',
                      '<inertial pos="0 0 0" mass="0.1" diaginertia="0.000015 0.00049 0.00049"/>', 1)
    # 压电载物台惯性锁位 (100kg: 等效压电闭环刚度, 接触力推不动; 自由轻台被 peg 接触推开实锤;
    # 不用 actuator — 会破坏 metaworld nu=2 假设 do_simulation 校验实锤)
    # 夹持旋转回正需要高切向摩擦 (原 1.0 下滑脱实锤): peg 表面摩擦 5.0 (演示场景专用)
    s = s.replace('<geom name="peg" euler="0 1.57 0" size="0.015 0.015 0.12" type="box" mass=".1" rgba="0.3 1 0.3 1" conaffinity="1" contype="1" group="1"/>',
                  '<geom name="peg" euler="0 1.57 0" size="0.015 0.015 0.12" type="box" mass=".1" rgba="0.3 1 0.3 1" conaffinity="1" contype="1" group="1" friction="5 0.02 0.002"/>', 1)
    # 转台/压电台注入到 peg/box 定义之后 (worldbody 尾部、goal site 之前/后皆可)
    s = s.replace("</worldbody>", EXTRA + "\n    </worldbody>", 1)
    # 加 site 到 site 段? cp 已在 worldbody; goal site 不变
    shutil.copyfile(SRC, DST + ".orig_bak") if not os.path.exists(DST + ".orig_bak") else None
    open(DST, "w", encoding="utf-8").write(s)
    print("✅ 写入:", DST)
    print("   注入: turntable(来料转台) + coupler(压电光耦合台)")

if __name__ == "__main__":
    main()
