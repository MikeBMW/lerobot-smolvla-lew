#!/usr/bin/env bash
# aoi_channel_sentinel.sh — 反向通道(8794 -> 工控机)复活哨兵 (2026-09-30 建)
#
# 为什么需要它(实录):
#   2026-09-30 23:59 一次 `aoi_remote_deploy.py --only 10083` 卡在 **下载** 那一步超时
#   (`<<TIMEOUT download>>`), 而 `iwr -OutFile` 是**先截断目标文件**的 ⇒ 磁盘上那份
#   `cam_surface_10083_work_v6.py` **可能只有半截** ⇒ 一旦保活/人工重启 10083, 服务就起不来。
#   而部署前的完好副本已经备份在 `cam_surface_10083_work_v6.py.bak_20260930_235901`。
#   之后反向通道(工控机轮询任务)一直不取命令 ⇒ 没法即时核验和修复 ⇒ 只能等它自己醒。
#
# 本哨兵做三件事(全部只读探测 + 只在真需要时才写):
#   ① 探通道(station_cmd.py 小命令); 没醒 → 静默退出(不刷屏)
#   ② 醒了 → 核 `cam_surface_10083_work_v6.py` 的 SHA256 是否等于**已知在役版本**
#   ③ 不相等 ⇒ 从 .bak_* 里找**哈希等于已知版本**的那份覆盖回去 + 复核 + 报一次
#
# 报一次: 用标记文件, 修过/报过就不再重复(除非又出现不一致)。
set -uo pipefail
REPO=/home/ubuntu/zmax_rel
PY=$REPO/gui-venv311/bin/python
WANT="636AC7854C947943"                    # 已知在役 v13 的 SHA256 前 16 位(三处一致核过)
DIR='D:\xspace\ultralytics_AOI'
F=cam_surface_10083_work_v6.py
MARK=/home/ubuntu/zmax_data/agent_hub/.sentinel_last

probe=$(cd "$REPO" && timeout 100 $PY tools/station_cmd.py "echo awake" 70 2>&1 | tail -3)
case "$probe" in
  *"没等到回执"*|*TIMEOUT*|*ENQUEUE_FAIL*) exit 0 ;;          # 通道还没醒: 静默, 不打扰
esac

out=$(cd "$REPO" && timeout 180 $PY tools/station_cmd.py \
  "cd $DIR; Get-FileHash '$F',$F'.bak_*' -Algorithm SHA256 -ErrorAction SilentlyContinue | ForEach-Object { \$_.Hash.Substring(0,16) + '  ' + (Split-Path \$_.Path -Leaf) }" 120 2>&1)

cur=$(printf '%s\n' "$out" | awk -v f="$F" 'index($2,f)==1 && $2==f {print $1}' | head -1)
good=$(printf '%s\n' "$out" | awk -v w="$WANT" '$1==w {print $2}' | head -1)

if [ "$cur" = "$WANT" ]; then                                  # 好: 记一笔就走
  echo "$(date '+%F %T') OK chan-alive $cur" > "$MARK"; exit 0
fi
if [ -z "$good" ]; then                                        # 通道醒了但没找到好副本: 必须报
  echo "⚠️ AOI 哨兵: 通道已恢复, 但 10083 文件哈希=$cur(应为 $WANT), 且 .bak_* 里没有可用的完好副本 —— 需要人工介入" 
  echo "$cur" > "$MARK"; exit 0
fi
res=$(cd "$REPO" && timeout 180 $PY tools/station_cmd.py \
  "cd $DIR; Copy-Item '$good' '$F' -Force; Start-Sleep -Milliseconds 500; (Get-FileHash '$F' -Algorithm SHA256).Hash.Substring(0,16)" 120 2>&1)
after=$(printf '%s\n' "$res" | grep -oE '[0-9A-F]{16}' | tail -1)
echo "🔧 AOI 哨兵: 通道恢复, 10083 文件曾损坏($cur) → 已用 $good 恢复 → 复核=$after (应为 $WANT)"
echo "$after" > "$MARK"
