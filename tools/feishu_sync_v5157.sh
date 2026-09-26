#!/usr/bin/env bash
# 飞书同步: 任务 / 记忆 / 数据 (v5.15.7 收尾)
set -u
cd /home/ubuntu/zmax_rel
MSG1='【静静同步 · v5.15.7 收尾 2026-09-26】

一、本轮补完（老倪指派）
① 全局数据空间发布守护：6 类真实数据源全接上 DDS —— ss_state(真机只读 tap) / ss_action(推理服务对真机帧输出) / ss_infer(8790健康) / ss_calib(标定真源文件) / ss_diag(延时·帧龄·服务健康) / ss_test(取证结果)；受遥测模式控制（prod 不 import cyclonedds = 量产零开销）。取证 16/16（四档全测）。
② 类型补齐 SSCalib/SSDiag/SSTest → 状态空间 9 类型 / 14 话题（你审计表里三个 ❌ 专项通道全部接通）。
③ 修严重：共享检出被切到 APP 的 mac-hw 分支 → 6 个在役服务脚本在该目录不存在，重启即挂（真机只读采集链已断流）→ 已全部重指 main worktree，复核 6/6 active，帧龄回到 0s。若昨夜直接关机，今早这 6 个服务会全部起不来。
④ 修 chain_health 巡检哨兵每 30 分钟报错（None.startswith）。
⑤ DeepSeek 确认：账号可用 deepseek-flash / deepseek-v4-pro，仓库配的 deepseek-flash 就是 V4.1-Flash 最新版（无需切换）；文本+视觉双路 HTTP 200（视觉对真机判据图返回真实描述）；实测单次约 122s → 异步旁路 + 本地 smolvlm2 兜底必须保留。

二、同步内容
· 任务：台账 docs/TASK_LEDGER_20260925.md + 交接单 docs/HANDOVER_20260926.md（待现场 8 项在内）
· 记忆+技能：已同步到仓库并 push（52 技能 / 记忆备份 2026-09-26）
· 数据：归档 ~/zmax_data/release_5.15.6_20260926（138 文件 5.0M）+ release_5.15.7_20260926（19 文件 304K，含 DDS 类型/守护/取证日志），均带 MANIFEST + sha256
· 版本：v5.15.7（6 处真源同步），commit adb14eb2 已 push

三、待现场（你授权后当天可开工）
AOI 首轮标定（数据集 0 标注框）· 10083 /picture 补丁（仍 404）· 10082 拉长口径 · 2D→3D 采集 · T_base_cam/plane_z 实测 · ring_pose 示教 · 抓取五段计划 S0~S5 批准 · 动作授权'
python3 ~/.hermes/scripts/feishu_notify.py "$MSG1" 2>&1 | tail -4
