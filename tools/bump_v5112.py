#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小版本迭代 v5.11.1 → v5.11.2: 六处版本号 + changelog 摘要前缀 (带断言, 不猜)"""
import ast
import os

REPO = "/home/ubuntu/lerobot-smolvla-lew"
os.chdir(REPO)
OLD, NEW = "v5.11.1", "v5.11.2"
SUMMARY = (
    f"# {NEW}: 🎯 **金手指 AOI v4 — 模板法规整截取 + 区域检测/视觉伺服对准 + 自动对焦 + 状态空间接线** — "
    "老倪: 「之前的代码把金手指截取的歪歪扭扭，不合格；你来用模板的方式截取规整的金手指部分」→「下方还有一个厚厚的边沿，"
    "不是金手指，也要去掉，只保留金手指部分；而且金手指纵向太短了，要拉长到符合 YOLO v8 检测的比例」。"
    "①**歪斜根因(实测)**: 固定窗 [[400,1000],[2000,1000],[2000,1250],[400,1250]] 与实际条位置对不上(条中心 y 在 1008~1450 漂 ~400px, "
    "条自身还带 0.6~1.0° 倾角), 且 `out_w=None→out_w=img_w` 把 1600x250 的窗静默拉成原图 2448x2048(纵向 8.2x 拉伸) = 又歪又拉长。"
    "②**v4 模板法**: 参考真图去倾斜 ROI 做模板(居中存放) → 运行期 1/4 尺度多角度粗搜 → 1/1 局部窗精修(角度+尺度) → "
    "**角度扫描: 直接以「实心金带核心行(行密度≥95%峰值)质心线斜率」为目标度量取最小**(不猜符号) → 单次仿射映射到规范化画布; "
    "兜底链 模板失败→HSV 条带→中心窗(明确标记)。"
    "③**现场两轮目检后的几何**: 只保留**焊盘排**(离散, |gx|≥18) = 金手指本身 **1455x70**, 下方实心金带(覆盖64%/|gx|8.3)与塑料本体亮边沿(亮度冲 255)一律不进画布; "
    "金手指只占 21:1 太扁 → 纵向拉伸到 **960x960 方图**(与 yolo_detector/config.yaml imgsz=960 对齐, 不 letterbox/不上采样), 另存原比例版供目检。"
    "④**接口**(工控机 10082): `/picture`=原始图 2448x2048 · `?kind=crop`=拉长 960x960 · `?kind=natural`=原比例 1455x70 · `/crop_info`=score/残余倾角/线残差/金覆盖/高亮占比 · "
    "**新增 `/region`=原始图坐标系金手指区域(定向框+四边形+外接框)+对焦清晰度 focus(Laplacian 方差)**。"
    "⑤**视觉伺服 tools/aoi_gold_servo.py**(注册 L2.aoi_gold_align): 区域偏差→`Δarm=-M·e`(符号实测, 标定雅可比) + 沿光轴退火爬坡对焦(0.8→0.4→0.2mm, focus 峰值即停) + "
    "**四级闸**(默认 dry-run / 检测不可靠否决 / 单步2mm·单轴15mm·25次 / 实测位移 vs 雅可比预期 >3x 立即停); 一次 `teach` 基准 + 一次 `calibrate` 雅可比。"
    "⑥**技能清单 UI**: 图片预览区加「来源」下拉(金手指拉长960 / 原图 / 原比例), 默认拉长版 —— 原来写死 /picture 而那个口现在是原图, 所以看不到拉长后的金手指。"
    "⑦**实测证据**: 5 张真图 条 **1454~1462 x 70~72 跨帧一致** · score 0.933~0.938 · **残余倾角 -0.94~0.61 px/1000**(v3 现状 0.87~1.02 且整幅残差 98px) · "
    "桩相机全链 5/5 · 真 Flask+HTTP 端到端 8/8(含解码校验 2448x2048 / 960x960 / 1455x70) · 伺服离线 5/5(收敛/限幅/否决/对焦/dry-run)。"
    "⑧**数据**: tools/aoi_gold_region_label.py 用模板法几何**自动标** YOLO 区域数据集(低可信 score<0.90 或覆盖<0.45 自动挑出人工复核), 缺的是现场图片量。"
)

# ── 1) studio.py: 三处版本号 + changelog 摘要 (先吃锚点再整体替换)
p = "tools/gui/studio.py"
s = open(p, encoding="utf-8").read()
old_head = f"# {OLD}: "
assert s.count(old_head) == 1, f"changelog 锚点数={s.count(old_head)}"
s = s.replace(old_head, SUMMARY + f" | {OLD}: ", 1)
n = s.count(f"Z-MAX {OLD}")
assert n == 3, f"Z-MAX 版本号处数={n} (期望 3)"
s = s.replace(f"Z-MAX {OLD}", f"Z-MAX {NEW}")
assert s.count(f"Z-MAX {NEW}") == 3, "三处 Z-MAX 版本号替换失败"
assert s.count(f"# {NEW}: ") == 1
open(p, "w", encoding="utf-8").write(s)
ast.parse(s)
print("studio.py OK: 版本号 x3 + 摘要前缀")

# ── 2~4) 其余三文件
JOBS = [
    ("tools/gui/update_checker.py", [(f'CURRENT_VERSION = "{OLD}"', f'CURRENT_VERSION = "{NEW}"')]),
    ("tools/gui/version_sync.py", [(f'zmax_ver = "{OLD[1:]}"', f'zmax_ver = "{NEW[1:]}"')]),
    ("tools/gui/docs_sync.py", [(f'"version": "{OLD}"', f'"version": "{NEW}"'),
                                (f'"zmax_version": "{OLD}"', f'"zmax_version": "{NEW}"')]),
]
for p, pairs in JOBS:
    s = open(p, encoding="utf-8").read()
    for a, b in pairs:
        assert a in s, f"{p} 缺锚点: {a}"
        s = s.replace(a, b)
    open(p, "w", encoding="utf-8").write(s)
    print(f"{p} OK: {len(pairs)} 处")
print("全部完成:", OLD, "→", NEW)
