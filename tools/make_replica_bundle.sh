#!/usr/bin/env bash
# 📦 生成可传的 T1 交付包 (工作端执行)
# 产出: ~/zmax_replica_T1.tar.zst (或 .tar.gz 回退) + 内含 manifest/SOP/校验脚本
set -euo pipefail
REPO=/home/ubuntu/lerobot-smolvla-lew
SWM=/home/ubuntu/stable-wm-cache
STAGE=/tmp/zmax_replica
OUT=$HOME/zmax_replica_T1

echo "═══ ① 生成分级清单 (含 sha256) ═══"
python3 "$REPO/tools/replicate_manifest.py" --hash 1 --out /tmp/replica_manifest.json > /tmp/manifest.log 2>&1 || true
tail -6 /tmp/manifest.log

echo "═══ ② 组包 (只装 T1) ═══"
rm -rf "$STAGE"; mkdir -p "$STAGE/lerobot-smolvla-lew" "$STAGE/checkpoints"

for d in tools src/lerobot/policies src/lerobot/manifold flows config; do
  mkdir -p "$STAGE/lerobot-smolvla-lew/$(dirname $d)"
  cp -r "$REPO/$d" "$STAGE/lerobot-smolvla-lew/$(dirname $d)/" 2>/dev/null || true
done
mkdir -p "$STAGE/lerobot-smolvla-lew/data" "$STAGE/lerobot-smolvla-lew/docs"
cp "$REPO/data/memory_layers.json" "$STAGE/lerobot-smolvla-lew/data/" 2>/dev/null || true
cp "$REPO/docs/PIPELINE_STATE.json" "$STAGE/lerobot-smolvla-lew/docs/" 2>/dev/null || true

# 关键权重 (含 config.json)
for ck in backbone_cont unified_aug intact_l4_current joint_v5; do
  [ -d "$SWM/checkpoints/$ck" ] && cp -r "$SWM/checkpoints/$ck" "$STAGE/checkpoints/" 2>/dev/null || true
done

cp /tmp/replica_manifest.json "$STAGE/" 2>/dev/null || true
[ -f "$REPO/docs/REPLICA_SOP.md" ] && cp "$REPO/docs/REPLICA_SOP.md" "$STAGE/" || true

# 清 __pycache__
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

echo "   组包体积: $(du -sh $STAGE | cut -f1)"

echo "═══ ③ 压缩 ═══"
if command -v zstd >/dev/null 2>&1; then
  tar -C /tmp -I 'zstd -3 -T0' -cf "${OUT}.tar.zst" zmax_replica
  echo "✅ ${OUT}.tar.zst  $(du -h ${OUT}.tar.zst | cut -f1)"
else
  tar -C /tmp -czf "${OUT}.tar.gz" zmax_replica
  echo "✅ ${OUT}.tar.gz   $(du -h ${OUT}.tar.gz | cut -f1)"
fi
echo "   校验: sha256sum 已存 ${OUT}.sha256"
( cd "$(dirname ${OUT})" && sha256sum "$(basename ${OUT})".tar.* > "${OUT}.sha256" 2>/dev/null || true )

echo "═══ ④ 冒烟: 用打包内容自校验 ═══"
python3 "$STAGE/lerobot-smolvla-lew/tools/replica_verify.py" --root "$STAGE" --manifest replica_manifest.json 2>&1 | tail -12 || true
