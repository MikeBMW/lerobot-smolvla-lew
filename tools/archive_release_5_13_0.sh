#!/usr/bin/env bash
# 归档 v5.13.0 当日产物到 ~/zmax_data (单一目录 + MANIFEST/sha256), 供离职/备份/复盘
set -u
REPO=/home/ubuntu/lerobot-smolvla-lew
DST=$HOME/zmax_data/release_5.13.0_20260924
mkdir -p "$DST"/{models,reports,web,docs,canvas,tools}
cd "$REPO" || exit 1

cp -f models/manifold_engine.npz "$DST/models/" 2>/dev/null
cp -f reports/moe_bypass_20260924.json reports/dense_bypass_20260924.json \
      reports/moe_holdout_vs_persist.json reports/dense_holdout_vs_persist.json \
      reports/obs_step_delta_engine_vs_h5.json reports/l2_guide_tactile_measured.json \
      reports/manifold_engine_bench.json "$DST/reports/" 2>/dev/null
cp -f reports/canvas_level_audit_*.md reports/canvas_level_audit_*.json "$DST/reports/" 2>/dev/null
cp -f reports/web/*.html reports/web/*.md "$DST/web/" 2>/dev/null
cp -f docs/design/manifold_engine_20260924.md docs/design/moe_dense_engine_bypass_20260924.md \
      docs/design/canvas_layout_forward_20260924.md docs/design/lora_align_ab_20260924.md \
      docs/TASK_LEDGER_20260924.md VERSION.md "$DST/docs/" 2>/dev/null
cp -f flows/state_space_obs.json "$DST/canvas/" 2>/dev/null
cp -f $(ls -t flows/state_space_obs.json.bak_* 2>/dev/null | head -2) "$DST/canvas/" 2>/dev/null
cp -f tools/moe_engine_bypass.py tools/moe_holdout_persistence.py tools/obs_step_delta.py \
      tools/canvas_level_audit.py tools/canvas_link_reconcile.py tools/canvas_add_manifold_engine.py \
      tools/canvas_update_verif_nodes.py tools/manifold_engine_bench.py tools/measure_l2_guide_tactile.py \
      tools/gen_l2_guide_tactile_page.py tools/studio_ctl.sh tools/bump_version.py "$DST/tools/" 2>/dev/null
cp -f src/lerobot/manifold/manifold_engine.py "$DST/tools/manifold_engine.py" 2>/dev/null

cd "$DST" || exit 1
{
  echo "# v5.13.0 归档 MANIFEST (2026-09-24)"
  echo
  echo "- 仓库: MikeBMW/lerobot-smolvla-lew @ $(cd "$REPO" && git rev-parse --short HEAD) (tag $(cd "$REPO" && git describe --tags --abbrev=0 2>/dev/null))"
  echo "- 生成: $(date '+%F %T %Z')"
  echo
  echo "| 文件 | 字节 | sha256(前16) |"
  echo "|---|---|---|"
  find . -type f ! -name MANIFEST.md -printf '%P\n' | sort | while read -r f; do
    printf '| %s | %s | %s |\n' "$f" "$(stat -c%s "$f")" "$(sha256sum "$f" | cut -c1-16)"
  done
} > MANIFEST.md
echo "归档目录: $DST"
echo "文件数: $(find . -type f | wc -l) · 总大小: $(du -sh . | cut -f1)"
echo "--- MANIFEST 摘要 (前 12 行) ---"
head -12 MANIFEST.md
echo "ARCHIVE_DONE"
