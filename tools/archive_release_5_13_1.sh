#!/usr/bin/env bash
# 归档 v5.13.1 当日产物到 ~/zmax_data (单一目录 + MANIFEST/sha256), 供备份/复盘
# 口径同 archive_release_5_13_0.sh: 只放**真实产物+改动文件**, 大文件(权重/整库)不进归档
set -u
REPO=/home/ubuntu/lerobot-smolvla-lew
DST=$HOME/zmax_data/release_5.13.1_$(date +%Y%m%d)
mkdir -p "$DST"/{canvas,canvas/backups_older,tools,reports,docs,src}
cd "$REPO" || exit 1

# ① 画布真源 + 改前/改后快照
cp -f flows/state_space_obs.json "$DST/canvas/"
cp -f flows/state_space_obs.json.bak_pre_fusionloc_* "$DST/canvas/" 2>/dev/null
cp -f flows/state_space_obs.json.bak_post_fusionloc_* "$DST/canvas/" 2>/dev/null
# ② 历史快照移出仓库工作树 (清理: 只留最近 2 个在仓库, 其余进归档)
ls -t flows/state_space_obs.json.bak_2026* 2>/dev/null | tail -n +3 | while read -r f; do
  mv -f "$f" "$DST/canvas/backups_older/" 2>/dev/null && echo "  移出工作树: $(basename "$f")"
done
# ③ 本轮改动的运行时映射 + 工具 (节点名=数据总线通道名, 9 处同步)
cp -f tools/gui/data_world.py tools/gui/simulink_module.py tools/gui/state_space_sim.py \
      tools/gui/state_space_sim_real.py tools/gui/node_logic.py tools/gui/auto_test_suite.py \
      tools/gui/ss_dreamview.py "$DST/tools/" 2>/dev/null
cp -f src/lerobot/verification/node_func_tree.py "$DST/src/" 2>/dev/null
cp -f tools/bump_version.py tools/studio_ctl.sh "$DST/tools/" 2>/dev/null
# ④ 证据报告 (档位级审计最新两份)
ls -t reports/canvas_level_audit_*.md 2>/dev/null | head -2 | xargs -r -I{} cp -f {} "$DST/reports/"
ls -t reports/canvas_level_audit_*.json 2>/dev/null | head -2 | xargs -r -I{} cp -f {} "$DST/reports/"
# ⑤ 文档
cp -f VERSION.md docs/TASK_LEDGER_20260924.md "$DST/docs/" 2>/dev/null
cp -f docs/design/canvas_layout_forward_20260924.md "$DST/docs/" 2>/dev/null
# ⑥ 哨兵清单留档 (清理前后对照: 删 9 条, 留 9 条)
cp -f "$HOME/.hermes/cron.yaml" "$DST/docs/cron_after_cleanup.yaml" 2>/dev/null

cd "$DST" || exit 1
{
  echo "# v5.13.1 归档 MANIFEST ($(date '+%F'))"
  echo
  echo "- 仓库: MikeBMW/lerobot-smolvla-lew @ $(cd "$REPO" && git rev-parse --short HEAD)"
  echo "- 生成: $(date '+%F %T %Z')"
  echo "- 内容: 画布真源(融合定位重构) + 9 处运行时映射 + 档位级审计证据 + 版本文件"
  echo
  echo "| 文件 | 字节 | sha256(前16) |"
  echo "|---|---|---|"
  find . -type f ! -name MANIFEST.md -printf '%P\n' | sort | while read -r f; do
    printf '| %s | %s | %s |\n' "$f" "$(stat -c%s "$f")" "$(sha256sum "$f" | cut -c1-16)"
  done
} > MANIFEST.md
echo "归档目录: $DST"
echo "文件数: $(find . -type f | wc -l) · 总大小: $(du -sh . | cut -f1)"
head -10 MANIFEST.md
echo "ARCHIVE_DONE"
