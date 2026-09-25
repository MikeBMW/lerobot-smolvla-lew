#!/usr/bin/env bash
# 归档 v5.15.6 当日产物 → ~/zmax_data (单一目录 + MANIFEST + sha256)
# ⚠️ 口径同 archive_release_5_13/5_14: 只放**真实产物+改动文件**, 大文件(权重/整库/rosbag)不进归档。
# ⚠️ 本次源 = worktree /home/ubuntu/zmax_rel (main 线); 另从共享检出的「活数据」补 live 审计文件。
set -u
REPO=/home/ubuntu/zmax_rel
LIVE=/home/ubuntu/lerobot-smolvla-lew
DST=$HOME/zmax_data/release_5.15.6_$(date +%Y%m%d)
mkdir -p "$DST"/{tools,src,docs,reports,live}
cd "$REPO" || exit 1

# ① 本轮新工具
cp -f tools/canvas_add_web_agent_node.py tools/verify_web_agent_node.py tools/ss_web_agent.py \
      tools/sim2real_preflight.py tools/zmax_net_optimize.sh tools/aoi_geom_parity.py \
      tools/studio_boot_start.sh tools/rollout_peg_check.py tools/rollout_video.py \
      tools/canvas_level_audit.py "$DST/tools/" 2>/dev/null
cp -f /etc/sysctl.d/99-zmax-net.conf "$DST/tools/" 2>/dev/null
cp -f /etc/systemd/system/zmax-web-agent-bridge.service /etc/systemd/system/zmax-net-optimize.service \
      /etc/systemd/system/aoi-feishu-push.service "$DST/tools/" 2>/dev/null
# ② 源码 (桥真源 + 能力清单 + 画布运行时注册)
cp -f src/lerobot/policies/left_right/state_space/web_agent_bridge.py "$DST/src/" 2>/dev/null
cp -f src/lerobot/verification/capability_levels.py "$DST/src/" 2>/dev/null
cp -f tools/gui/node_logic.py "$DST/src/" 2>/dev/null
cp -f flows/state_space_obs.json "$DST/docs/canvas_state_space_obs_snapshot.json" 2>/dev/null
# ③ 文档
cp -f VERSION.md docs/HANDOVER_20260926.md docs/TASK_LEDGER_20260925.md "$DST/docs/" 2>/dev/null
# ④ 证据 (本日报告/台账/预检)
cp -f reports/sys_maintenance_20260925.md reports/net_perf_optimize_20260925.md \
      reports/dns_net_maintenance_20260925.json reports/sys_maintenance_20260925.md "$DST/reports/" 2>/dev/null
ls -t reports/net_boot_optimize_*.jsonl reports/net_perf_ab_*.json reports/aoi_geom_parity_*.json 2>/dev/null | head -6 | xargs -r -I{} cp -f {} "$DST/reports/"
ls -t reports/sim2real_preflight_* 2>/dev/null | head -2 | xargs -r -I{} cp -f {} "$DST/reports/"
ls -t reports/verify_wa*.log /tmp/verify_wa2.log /tmp/preflight3.log 2>/dev/null | head -3 | xargs -r -I{} cp -f {} "$DST/reports/" 2>/dev/null
# ⑤ 活数据 (只存在于共享检出的: 桥审计/状态 + 记忆层阶梯)
cp -f "$LIVE/reports/web_agent_bridge_audit.jsonl" "$LIVE/reports/web_agent_bridge_state.json" "$DST/live/" 2>/dev/null
cp -r "$LIVE/reports/mem_ladder" "$DST/live/" 2>/dev/null

cd "$DST" || exit 1
{
  echo "# v5.15.6 归档 MANIFEST ($(date '+%F %T %Z'))"
  echo
  echo "- 仓库: MikeBMW/lerobot-smolvla-lew @ $(cd "$REPO" && git rev-parse --short HEAD) (源: worktree main)"
  echo "- 内容: L5 Web 智能体桥 (节点/通道/服务) · 网络性能优化 (sysctl+unit) · AOI 几何口径 · sim-to-real 预检 · 台账/交接单/live 审计"
  echo
  echo "## 文件清单"
  find . -type f | sort | sed 's|^\./||' | while read -r f; do printf -- "- %s (%s)\n" "$f" "$(du -h "$f" | cut -f1)"; done
  echo
  echo "## sha256"
  find . -type f ! -name sha256sums.txt -print0 | sort -z | xargs -0 sha256sum > sha256sums.txt
  echo '已写 sha256sums.txt'
} > MANIFEST.md
echo "归档目录: $DST"
echo "文件数: $(find "$DST" -type f | wc -l) · 总大小: $(du -sh "$DST" | cut -f1)"
ls "$DST"
