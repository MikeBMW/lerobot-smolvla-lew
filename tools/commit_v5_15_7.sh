#!/usr/bin/env bash
# 提交并推送 v5.15.7 (DDS 全局数据空间 + 服务修复 + 版本同步 + 交接单)
set -u
cd /home/ubuntu/zmax_rel || exit 1
git add VERSION.md docs/HANDOVER_20260926.md \
        dds/ss_types.py dds/zmax_node.py dds/zmax_types.py \
        tools/zmax_dds_ss_daemon.py tools/zmax_dds_ss_verify.py \
        tools/fix_services_to_main.sh tools/archive_release_5_15_7.sh \
        tools/gui/studio.py tools/gui/update_checker.py tools/gui/version_sync.py tools/gui/docs_sync.py
git -c user.name=ubuntu -c user.email=ubuntu@zmax commit -q -F - <<'EOF'
release(v5.15.7): 全局数据空间发布守护(6 类真实源→DDS, 受模式控制) + 9 类型/14 话题 + 6 服务启动依赖修复

① 全局数据空间发布守护 tools/zmax_dds_ss_daemon.py: ss_state/ss_action/ss_infer/ss_calib/ss_diag/ss_test
   六类真实数据源全接上 DDS, 受遥测模式控制 (prod 不 import cyclonedds 零开销), 过期帧只报诊断;
   取证 tools/zmax_dds_ss_verify.py 16/16; 常驻 zmax-dds-ss.service
② 类型补齐 SSCalib/SSDiag/SSTest (dds/ss_types.py) → 9 类型 / 14 话题 (三专项通道接通)
③ 修复: 共享检出被切到 mac-hw 分支致 6 个在役服务脚本缺失(重启即挂) → 重指 main worktree
   (tools/fix_services_to_main.sh), 复核 6/6 active, 真机只读帧龄 0s
④ 修 chain_health 巡检哨兵崩溃 (None.startswith)
⑤ 确认 DeepSeek: 账号可用 deepseek-flash = V4.1-Flash 最新版; 文本+视觉双路 200; 单次 ~122s → 异步旁路必留
⑥ 版本同步 6 处真源 → v5.15.7 + VERSION.md 新行
EOF
echo "commit rc=$?"
git log --oneline -1 | cat
timeout 180 git fetch origin -q && timeout 180 git rebase origin/main 2>&1 | tail -3
timeout 180 git push origin HEAD:main 2>&1 | tail -3
echo "push 后远端: $(git log --oneline -1 origin/main | cat)"
