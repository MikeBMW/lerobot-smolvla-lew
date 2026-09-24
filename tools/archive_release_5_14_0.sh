#!/usr/bin/env bash
# 归档 v5.14.0 当日产物到 ~/zmax_data (单一目录 + MANIFEST/sha256), 供备份/复盘
# 口径同 archive_release_5_13_*.sh: 只放**真实产物+改动文件**, 大文件(权重/整库)不进归档
set -u
REPO=/home/ubuntu/lerobot-smolvla-lew
DST=$HOME/zmax_data/release_5.14.0_$(date +%Y%m%d)
mkdir -p "$DST"/{tools,src,docs,reports,capture,points}
cd "$REPO" || exit 1

# ① 本轮新工具 (相机客户端/任务头/窗口/示教点/过曝切除/飞书推图/四个取证脚本)
cp -f tools/opt_camera_client.py tools/aoi_feishu_push.py tools/aoi_teach_point.py \
      tools/aoi_exposure_fix.py tools/verify_opt_camera.py tools/verify_aoi_console.py \
      tools/verify_aoi_console_real.py tools/verify_teach_point.py "$DST/tools/" 2>/dev/null
cp -f tools/gui/aoi_inspect_console.py tools/bump_version.py tools/studio_ctl.sh "$DST/tools/" 2>/dev/null
# ② 源码 (质量检测任务头 + 工程记忆节点扩展)
cp -f src/lerobot/policies/yolo_3d/aoi_head.py "$DST/src/" 2>/dev/null
cp -f src/lerobot/memory/eng_memory.py "$DST/src/" 2>/dev/null
# ③ 文档 (版本历史/交接单/方案/两份现场补丁)
cp -f VERSION.md docs/HANDOVER_20260924_AOI.md docs/design/aoi_quality_head_and_console_20260924.md "$DST/docs/" 2>/dev/null
cp -f docs/patch/opt_surface_10083_add_picture_route.md docs/patch/opt_10082_gold_stretch_2x.md "$DST/docs/" 2>/dev/null
# ④ 证据 (验证 JSON + 半自动对照 + 交互动线图)
ls -t reports/opt_camera_verify_*.json 2>/dev/null | head -3 | xargs -r -I{} cp -f {} "$DST/reports/"
cp -f reports/teach_point_verify.json reports/aoi_console_state.json reports/aoi_roi.json \
      reports/opt_capture_log.jsonl reports/aoi_feishu_watch.log "$DST/reports/" 2>/dev/null
cp -r reports/aoi_compare_20260924_1851 "$DST/reports/" 2>/dev/null
# ⑤ 取图素材 (判据图/裁减图/推送图; 只留最近各 6 张, 大原图不进)
ls -t reports/opt_view/*.png 2>/dev/null | head -6 | xargs -r -I{} cp -f {} "$DST/capture/"
ls -t reports/feishu_push/*.png 2>/dev/null | head -6 | xargs -r -I{} cp -f {} "$DST/capture/"
# ⑥ 点位/技能库快照 (示教点+技能库+留痕)
cp -f data/skills/l2_atomic/taught_points.json "$DST/points/taught_points_snapshot.json" 2>/dev/null
cp -f data/skills/l2_atomic/registry.json "$DST/points/registry_snapshot.json" 2>/dev/null
cp -r reports/aoi_points "$DST/points/" 2>/dev/null

cd "$DST" || exit 1
{
  echo "# v5.14.0 归档 MANIFEST ($(date '+%F'))"
  echo
  echo "- 仓库: MikeBMW/lerobot-smolvla-lew @ $(cd "$REPO" && git rev-parse --short HEAD)"
  echo "- 生成: $(date '+%F %T %Z')"
  echo "- 内容: 外观质量检测线 (OPT 相机→任务头→窗口→飞书) 工具/源码/证据/点位快照/两份现场补丁"
  echo
  echo "| 文件 | 字节 | sha256(前16) |"
  echo "|---|---|---|"
  find . -type f ! -name MANIFEST.md -printf '%P\n' | sort | while read -r f; do
    printf '| %s | %s | %s |\n' "$f" "$(stat -c%s "$f")" "$(sha256sum "$f" | cut -c1-16)"
  done
} > MANIFEST.md
echo "归档目录: $DST"
echo "文件数: $(find . -type f | wc -l) · 总大小: $(du -sh . | cut -f1)"
echo "ARCHIVE_DONE"
