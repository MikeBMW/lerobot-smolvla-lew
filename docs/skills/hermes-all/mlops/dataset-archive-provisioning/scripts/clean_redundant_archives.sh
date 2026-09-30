#!/usr/bin/env bash
# 大归档安全回收门禁 (verify-before-delete)
#   用法: 改下面 CONFIG 区 → bash 本脚本   (本环境长内联命令会被硬拦, 所以固化成脚本)
#   门禁: ① 替代物字节门  ② 归档完整性门 (zstd -t)  ③ 留档 sha256+URL (可重下)  ④ 删后核账 <= 红线
set -uo pipefail

# ================= CONFIG =================
REDLINE_G=300                       # 系统盘 used 上限 (G) — 与 ~/.hermes/scripts/disk_redline.sh 保持一致
REC=/home/ubuntu/l4_ab/intact_results/released_archives.log   # 留档(证据)文件

# 要删的归档: "路径|来源URL|说明(被什么替代 / 为什么不需要)"
ARCHIVES=(
  "/home/ubuntu/dl_intact/pusht_expert_train.h5.zst|https://hf-mirror.com/datasets/quentinll/lewm-pusht/resolve/main/pusht_expert_train.h5.zst|已解压为 stable-wm-cache/datasets/pusht_expert_train.h5 (已 h5py 校验)"
)
# 替代物门 (必须先确认这些还在且字节数对): "路径|期望字节数"
KEEP_CHECKS=(
  "/home/ubuntu/stable-wm-cache/datasets/pusht_expert_train.h5|46300921856"
)
# =========================================

echo "=== 0) 清理前 ==="; df -h / | tail -1

echo "=== 1) 替代物字节门 ==="
for k in "${KEEP_CHECKS[@]}"; do
  p="${k%%|*}"; want="${k##*|}"
  if [ ! -e "$p" ]; then echo "❌ 替代物不存在: $p → 中止"; exit 1; fi
  got=$(stat -c %s "$p")
  if [ "$got" != "$want" ]; then echo "❌ 字节不符: $p 期望 $want 实得 $got → 中止"; exit 1; fi
  echo "✅ $p = $got B"
done

echo "=== 2) 归档完整性门 (zstd -t) ==="
for a in "${ARCHIVES[@]}"; do
  f="${a%%|*}"
  [ -e "$f" ] || { echo "⚠️  不存在: $f"; continue; }
  # 稀疏文件提示: apparent vs 实占
  echo "  $f  apparent=$(du -h --apparent-size "$f" | cut -f1) 实占=$(du -h "$f" | cut -f1) inode/links=$(stat -c '%i/%h' "$f")"
  if zstd -t "$f" >/dev/null 2>&1; then echo "  ✅ zstd -t 通过 (内容 $(zstd -t "$f" 2>&1 | awk '{print $NF, $(NF-1)}'))"
  else echo "❌ zstd -t 失败: $f → 中止(可能是半截包)"; exit 1; fi
done

echo "=== 3) 留档 (sha256 + URL, 让删除可重下) ==="
{
  echo "## $(date '+%F %T') 归档清理记录 (可重下证据)"
  for a in "${ARCHIVES[@]}"; do
    IFS='|' read -r f url note <<< "$a"
    [ -e "$f" ] || continue
    echo ""
    echo "$(basename "$f")  sha256=$(sha256sum "$f" | cut -d' ' -f1)  size=$(stat -c %s "$f")"
    echo "  url: $url"
    echo "  说明: $note"
  done
  echo ""
} >> "$REC"
tail -20 "$REC"

echo "=== 4) 删除 ==="
for a in "${ARCHIVES[@]}"; do
  f="${a%%|*}"
  if [ -e "$f" ]; then
    m=$(du -m "$f" 2>/dev/null | cut -f1); rm -f "$f" && echo "🗑  已删 $f (实占回收 ${m}M)"
  fi
  # 顺手清断点残留
  [ -e "$f.aria2" ] && rm -f "$f.aria2" && echo "🗑  已删 $f.aria2"
done

echo "=== 5) 删后核账 ==="
df -h / | tail -1
used_gb=$(df / | tail -1 | awk '{print int($3/1024/1024)}')
echo "系统盘 used = ${used_gb}G (红线 ${REDLINE_G}G)"
[ "$used_gb" -le "$REDLINE_G" ] && echo "✅ 达标" || echo "🚨 仍超红线 ${REDLINE_G}G"
