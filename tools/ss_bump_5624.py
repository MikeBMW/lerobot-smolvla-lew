#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小版本迭代 v5.6.23 → v5.6.24: 五处版本号 + changelog 摘要前缀 (带断言, 不猜)"""
import ast
import os

REPO = "/home/ubuntu/lerobot-smolvla-lew"
os.chdir(REPO)
NEW, OLD = "v5.6.24", "v5.6.23"
SUMMARY = (
    f"# {NEW}: 🏷 **真机 YOLO 标定工位打通 (拖框/选中间步/删除) + 真机位姿真值记录 + 机器人动作自动标注设计** — 老倪: "
    "「左键拖不出框 / 改选中的类别不好使 / 标号的数据在哪里 / 加两个删除按钮 / 记录光模块 x y z 对齐 metaworld / "
    "设计用机器人实际动作自动标注」。①**修两个真 bug (均 offscreen 取证)**: (a)**拖框锚点被每帧鼠标移动覆盖** "
    "(`_edit_drag` 写 `(\"new\", start, pt)` 而非 anchor) ⇒ 松开时只剩最后一小段位移(<4px)被当误点丢弃 → 「左键拖不出框」; "
    "修后显示(100,100)-(260,220) → 原帧框 (50,50,130,110) 正确, 旋转窗 180° 同测 (189,129,269,189) 自动换算回原始坐标。"
    "(b)**两窗只同步框集合、不同步选中项** ⇒ 在旋转窗(相机翻转时最常用)点选后「🏷改选中类别/🗑删选中/↩撤销」取不到选中 → "
    "看着像按钮坏了; 修: selectionChanged 互相同步 + 这几个键改走 `_active_pane()`。②**类别口径纠正**: 真机类名必须 `peg` "
    "(不是默认 `optical_module`) —— 依据唯一口径源 `yolo_3d/frame_source.py:40 CLASS_MAP{{peg→光模块}}` 与下游 "
    "`real_yolo_perceive.py` 的 `det3d[\"光模块\"]/[\"hole\"]` 取值; 且 `save_sample` 对未知类名会**自动追加进 classes.txt** ⇒ "
    "旧名会污染类别表(id 顺序乱); 已把 classes.txt/DEFAULT_CLASSES/GUI 兜底全部改 `peg` 并救回已存 3 张的标签 (id1→id0)。"
    "③**数据管理**: 窗口新增「🗑 丢弃当前帧」「🗑 清空本会话」(图+标注**成对删**, 绝不留孤儿) + CLI `--clean`(清孤儿标注)/"
    "`--reset --yes`(清空重来, 保留类别表+审计流水); 实测临时根: 孤儿标注删/孤儿图保留/配对不动、reset 19 文件清空 classes.txt 保留。"
    "④**真机位姿真值 (单一来源 `tools/real_truth.py`)**: 读采集容器落盘的 state jsonl 末行(尾部64KB反扫)/status.json → TCP+四元数+关节+"
    "新鲜度; 保存样本时写入 `annotations.jsonl.truth` + 侧车 `sessions/<会>/truth.jsonl`, `--build` 聚合 `dataset/truth.jsonl`; "
    "**按 metaworld 39D 段位对齐** ([0:3]hand=[TCP真值], [4:7]光模块=TCP+R·夹具偏移, [7:11]peg_quat, [36:39]hole=示教goal) —— "
    "夹具偏移/示教几何未标定时**填 null + 原因, 不编造**; 窗口加 1Hz 真值行 (实测 TCP=[0.43678,0.32978,0.222018] base_link, age 0.02s)。"
    "⑤**机器人动作自动标注 (设计+数学核)**: `docs/design/real_autolabel_by_robot_motion.md` — 机器人自己当标定物: 探针运动(夹着模块走9~12位姿, "
    "图像差分取运动域中心当模块像素, 配对用**两帧TCP中点**消除半采样周期偏置) → DLT 解 3x4 投影矩阵 P(=K·[R|t], 已含手眼外参) → 批量把 "
    "真值投影成 YOLO 框; `tools/real_autolabel.py --selftest` 全绿 (rms 1.4e-13 · 还原内参 fx610.000/fy607.000/cx318/cy242 · "
    "1px噪声→0.811px · 薄片绕光轴转90°框 14.5x37.5→37.7x14.4 正确互换); 诚实边界: 模块尺寸/夹具偏移/孔口点需现场量或示教, 自动标注**不得当 val**。"
    "⑥**模型引擎页一键训 YOLO**: 新增「🚀 YOLO 训练」节点 (policy=yolo · 步数=epoch · 与 🚀 ACT 训练 同列对齐) —— 原来 "
    "`_train_yolo_detector()` 写了却没有节点传 policy=\"yolo\", 从界面到不了; 同时修该函数: 解释器自动选带 ultralytics 的 gui-venv311"
    "(旧写死 ~/lerobot-venv 实测没装 → 一点就报错), 数据源优先**真机标注** data/yolo_annot/dataset (走 yolo_annot_train.py --base auto 域适应微调, "
    "imgsz640) 否则回退仿真 data/yolo_peg, 仿真分支真用 GPU; 踩坑: match_node 取最长关键字, 裸 \"YOLO\"(4字) 会抢走 \"训练\"(2字) → "
    "「🚀 YOLO 训练」被派去跑目标检测, 故单独注册 train_yolo(\"YOLO 训练\"); 另 edges 源索引是 3(YOLO检测)不是 2(共享🧩定义被跳过) 否则连线被静默丢弃。"
    "⑦**运维**: `zmax-studio` `Restart=on-failure→no` (journal 实证 11:51 X11 connection broke → 退出码1 → 5s 又拉起 = 反复重启, 老倪「别自动重启」); "
    "**采集容器 DDS 假死**(长跑后 jsonl 在长但所有话题收包恒 0, 新建容器同话题立刻 49.6Hz ⇒ 启动撞上 NTP 拨钟致 RTPS 发现不自愈) → `docker restart` 即恢复; "
    "标定工具写出路径与采集器读取路径**口径对齐**($SS_OUT/real_cell_geometry.json), 否则示教完 tap 仍报「无示教几何」。"
    "⑧全程零回退取证: 模型引擎 65 节点/101 连线 vs 基线 64/100 —— 旧 64 节点索引→名字逐条不变、旧 100 连线一条不少、布局仅第0行第10列新增。"
)

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
print("全部完成")
