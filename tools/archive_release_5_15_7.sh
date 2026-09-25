#!/usr/bin/env bash
# 归档 v5.15.7 产物 (DDS 全局数据空间 + 服务修复 + DeepSeek 确认) → ~/zmax_data
set -u
REPO=/home/ubuntu/zmax_rel
DST=$HOME/zmax_data/release_5.15.7_$(date +%Y%m%d)
mkdir -p "$DST"/{tools,dds,docs,reports}
cd "$REPO" || exit 1

# ① DDS 件 (类型真源 + 节点 + 发布守护 + 取证)
cp -f dds/ss_types.py dds/zmax_node.py dds/zmax_types.py dds/README.md "$DST/dds/" 2>/dev/null
cp -f /home/ubuntu/zmax_dds/cyclonedds_unicast.xml "$DST/dds/" 2>/dev/null
cp -f tools/zmax_dds_ss_daemon.py tools/zmax_dds_ss_verify.py tools/fix_services_to_main.sh "$DST/tools/" 2>/dev/null
cp -f /etc/systemd/system/zmax-dds-ss.service "$DST/tools/" 2>/dev/null
# ② 证据
cp -f /tmp/ss_verify4.log "$DST/reports/dds_ss_verify_16of16.log" 2>/dev/null
cp -f /tmp/zmax_dds_ss.log "$DST/reports/zmax_dds_ss_daemon.log" 2>/dev/null
cp -f /tmp/check_deepseek_latest.py /tmp/probe_deepseek_vision.py "$DST/reports/" 2>/dev/null
cp -f /tmp/dds_services_after_fix.txt "$DST/reports/" 2>/dev/null
# ③ 文档
cp -f VERSION.md docs/DDS-TELEMETRY-ARCHITECTURE.md docs/HANDOVER_20260926.md docs/TASK_LEDGER_20260925.md "$DST/docs/" 2>/dev/null

cd "$DST" || exit 1
{
  echo "# v5.15.7 归档 MANIFEST ($(date '+%F %T %Z'))"
  echo
  echo "- 仓库: MikeBMW/lerobot-smolvla-lew @ $(cd "$REPO" && git rev-parse --short HEAD) (worktree main)"
  echo "- 内容: 全局数据空间发布守护 (6 类真实源→DDS, 受模式控制) + 9 类型/14 话题 + 6 服务启动依赖修复 + DeepSeek 确认"
  echo
  echo "## 文件清单"
  find . -type f ! -name MANIFEST.md ! -name sha256sums.txt -printf "%s\t%p\n" | sort -k2 | awk -F'\t' '{printf "- %s (%.0fKB)\n", substr($2,3), $1/1024}'
  echo
  echo "## sha256"
  find . -type f ! -name MANIFEST.md ! -name sha256sums.txt -print0 | sort -z | xargs -0 sha256sum > sha256sums.txt
  echo "见 sha256sums.txt ($(wc -l < sha256sums.txt) 条)"
} > MANIFEST.md
echo "归档: $DST · 文件 $(find "$DST" -type f | wc -l) · 大小 $(du -sh "$DST" | cut -f1)"
