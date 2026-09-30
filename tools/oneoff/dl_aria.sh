#!/bin/bash
# 用 aria2c (16 连接 + 断点续传) 重下 INTACT 官方数据集 —— hf_hub 单连接下载已卡死 (pusht 停在 7.5/13.1GB,
# 半小时没动; reacher 归档也在别人那边卡在 22.67/23.75GB)。aria2c 多连接可绕开这种单流限速/卡死。
set -u
DL=/home/ubuntu/dl_intact
LOG=/tmp/dl_aria.log
exec >>"$LOG" 2>&1
mkdir -p "$DL"
echo "=== aria2 下载开始 $(date '+%F %T') ==="
M=https://hf-mirror.com/datasets
# ① pusht 13.14GB  ② reacher 23.75GB  (各自 8 连接, 并行两路)
aria2c -x 8 -s 8 -k 4M -c --file-allocation=none --auto-file-renaming=false \
  --console-log-level=warn --summary-interval=60 \
  -d "$DL" -o pusht_expert_train.h5.zst "$M/quentinll/lewm-pusht/resolve/main/pusht_expert_train.h5.zst"
echo "--- pusht 完成 rc=$? $(date '+%F %T') ---"
ls -la "$DL"
aria2c -x 8 -s 8 -k 4M -c --file-allocation=none --auto-file-renaming=false \
  --console-log-level=warn --summary-interval=60 \
  -d "$DL" -o reacher.tar.zst "$M/quentinll/lewm-reacher/resolve/main/reacher.tar.zst"
echo "--- reacher 完成 rc=$? $(date '+%F %T') ---"
ls -la "$DL"
echo "=== 下载结束 $(date '+%F %T') ==="
