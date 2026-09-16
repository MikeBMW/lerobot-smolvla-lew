#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小版本迭代 v5.6.14 → v5.6.15: 五处版本号 + changelog 摘要前缀 (带断言, 不猜)"""
import ast
import os

REPO = "/home/ubuntu/lerobot-smolvla-lew"
os.chdir(REPO)
NEW, OLD = "v5.6.15", "v5.6.14"
SUMMARY = (
    f"# {NEW}: 🛰 **Orin 零程序 · 只转发感知 (红线整改 + 标定桥真口径)** — 老倪: 「不要在orin上增加新程序, "
    "orin是生产设备, 不能被干扰, 你先只是转发orin的感知信号」。①**Orin 侧全清**: 自研进程/自启项(crontab @reboot)/"
    "ss_edge·ss_shadow·ss_infer 文件全部移除, 生产 8765 网关与 18 节点不受影响 (实测 pgrep 空 / crontab 空 / 域内 zmax_ss 话题 0)。"
    "②**采集改走 4060 侧 Docker 远程只读订阅** (ros:humble-ros-base --network host, ROS_DOMAIN_ID=0): 跨机 DDS 直订 "
    "/robot/tcp_pose(49.8Hz 真值) + /real_joint_states(100.4Hz) → 落本机 jsonl; 节点自证 endpoint 仅 /parameter_events"
    "(rosout 已关) = **零数据发布**; 会写回 Orin 的 ss-bridge 停用禁用。③**标定桥真口径**: z7=[手/头−目标, 手/头−光模块, 夹持], "
    "手/头=真机 tcp_pose, 目标/光模块点由 tools/ss_geom_calib.py 现场示教 (可在 4060 容器内跑, 不动 Orin); "
    "**几何未示教 → z7=null 拒算, 绝不编造**, 推理 input_map 逐条落盘 (现为 placeholder_v0, 示教后自动切 tcp_pose_v1)。"
    "④tools/ss_archive_remote_data.py 一致性快照+MANIFEST (条数/坏行/时间跨度/sha256/口径), 数据不进库。"
    "⑤踩坑留档: /robot/force_torque 同名双类型 (WrenchStamped 建订阅报 invalid allocator → 只订 JointState)。"
)

# ── 1) studio.py: 三处版本号 + changelog 摘要 (先吃锚点再整体替换, 否则计数会被注释里的版本号污染)
p = "tools/gui/studio.py"
s = open(p, encoding="utf-8").read()
old_head = "# v5.6.14: "
assert s.count(old_head) == 1, f"changelog 锚点数={s.count(old_head)}"
s = s.replace(old_head, SUMMARY + " | v5.6.14: ", 1)
n = s.count(f"Z-MAX {OLD}")          # 只数 3 处真版本号 (变更摘要链里的 " | v5.6.14: " 不算)
assert n == 3, f"Z-MAX 版本号处数={n} (期望 3 = QLabel + 两处 setWindowTitle)"
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
print("全部完成")
