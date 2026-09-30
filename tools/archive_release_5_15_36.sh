#!/usr/bin/env bash
# 归档 v5.15.36 产物 → ~/zmax_data/release_5.15.36_YYYYMMDD
#   本轮内容: ① HIL 人机在环接进手机 APP(现场页 + 本地 HIL API + 装包)
#             ② 工位总览 10082/10083 改实时推流(有人看顶到 OPT 上限)
#             ③ 场景叠加按钮"点了什么都没打开"的根因修复(DBUS=disabled ⇒ snap chromium 静默退出)
#             ④ 工位总览找回 + 控制台入口按钮
# 约定沿用 archive_release_5_15_7.sh: 代码 + 装包 + 证据 + 文档 + 现场数据快照, 末尾 MANIFEST.md + sha256sums.txt
set -u
REPO=/home/ubuntu/zmax
APP=/home/ubuntu/state3d_app
DST=$HOME/zmax_data/release_5.15.36_$(date +%Y%m%d)
mkdir -p "$DST"/{tools,app,evidence,docs,reports}
cd "$REPO" || exit 1

echo "=== ① 本轮改动的代码 ==="
cp -f tools/web/room.html tools/hil_local_api.py tools/cam_live_stream.py "$DST/tools/" 2>/dev/null
cp -f tools/gui/simulink_module.py tools/gui/studio.py tools/gui/launch_studio.sh tools/gui/node_logic.py "$DST/tools/" 2>/dev/null
cp -f tools/verify_scene_overlay_button.py tools/verify_station_button.py "$DST/tools/" 2>/dev/null
cp -f tools/hil_bridge.py src/lerobot/policies/left_right/state_space/hil_bridge.py "$DST/tools/hil_bridge_core.py" 2>/dev/null
cp -f tools/agent_hub.py tools/aoi_remote_deploy.py "$DST/tools/" 2>/dev/null
ls "$DST/tools" | wc -l | sed 's/^/  代码文件: /'

echo "=== ② 手机 APP 装包 + 可重建源码 ==="
cp -f "$APP/room/ZMAX-Site.apk" "$DST/app/" 2>/dev/null
cp -f "$APP/build_room_apk.sh" "$DST/app/" 2>/dev/null
cp -f "$APP/room/src/main/AndroidManifest.xml" "$DST/app/AndroidManifest.room.xml" 2>/dev/null
cp -f "$APP/room/src/main/java/com/zmax/room/MainActivity.java" "$DST/app/MainActivity.room.java" 2>/dev/null
sha256sum "$DST/app/ZMAX-Site.apk" > "$DST/app/ZMAX-Site.apk.sha256" 2>/dev/null
cat "$DST/app/ZMAX-Site.apk.sha256" 2>/dev/null | cut -c1-24 | sed 's/^/  装包 sha256: /'

echo "=== ③ 实测证据 (截图 + 版本摘要 + 回读的下载件) ==="
cp -f /tmp/room_phone.png /tmp/station_win.png /tmp/station_now.png /tmp/p_row2.png "$DST/evidence/" 2>/dev/null \
  || cp -f /tmp/room_phone.png /tmp/station_win.png "$DST/evidence/" 2>/dev/null
cp -f /tmp/bump_summary_fix20.txt /tmp/bump_summary_fix21.txt /tmp/bump_summary_fix22.txt "$DST/evidence/" 2>/dev/null
cp -f /tmp/bump_summary_fix17.txt /tmp/bump_summary_fix18.txt /tmp/bump_summary_fix19.txt "$DST/evidence/" 2>/dev/null
cp -f /tmp/dl.apk "$DST/evidence/downloaded_ZMAX-Site.apk" 2>/dev/null
cp -f /tmp/hil_local.log "$DST/evidence/hil_local_api.log" 2>/dev/null
ls "$DST/evidence" | wc -l | sed 's/^/  证据文件: /'

echo "=== ④ 文档 ==="
cp -f VERSION.md docs/STATION_6PANEL_20260927.md "$DST/docs/" 2>/dev/null
cp -f /tmp/bump_summary_fix2[012].txt "$DST/docs/" 2>/dev/null

echo "=== ⑤ 现场数据快照 ==="
cp -f reports/hil_bridge_state.json reports/aoi_deploy_log.jsonl reports/canvas_level_audit_20260926_121651.md "$DST/reports/" 2>/dev/null
cp -f reports/hil_instructions.jsonl "$DST/reports/" 2>/dev/null

echo "=== ⑥ MANIFEST + sha256 ==="
cd "$DST" || exit 1
{
  echo "# v5.15.36 归档 MANIFEST ($(date '+%F %T %Z'))"
  echo
  echo "- 仓库: MikeBMW/lerobot-smolvla-lew @ $(cd "$REPO" && git rev-parse --short HEAD) (worktree main)"
  echo "- 主题: HIL 人机在环接进手机 APP + 10082/10083 实时推流 + 场景叠加按钮根因修复"
  echo "- 手机现场页: http://10.163.146.78:8791/room · 本地 HIL API: http://10.163.146.78:8795"
  echo "- 装包: http://10.163.146.78:8791/dl/ZMAX-Site.apk (com.zmax.room, 与现有 App 并存)"
  echo
  echo "## 文件清单"
  find . -type f ! -name MANIFEST.md ! -name sha256sums.txt -printf "%s\t%p\n" | sort -k2 \
    | awk -F'\t' '{printf "- %s (%.0f B)\n", $2, $1}'
  echo
  echo "## sha256"
  echo "见 sha256sums.txt"
} > MANIFEST.md
rm -f sha256sums.txt
find . -type f ! -name MANIFEST.md ! -name sha256sums.txt -print0 | sort -z | xargs -0 sha256sum > sha256sums.txt

echo "归档: $DST · 文件 $(find "$DST" -type f | wc -l) · 大小 $(du -sh "$DST" | cut -f1) · sha256 $(wc -l < sha256sums.txt) 条"
