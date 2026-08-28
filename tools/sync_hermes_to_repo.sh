#!/usr/bin/env bash
# ============================================================
# sync_hermes_to_repo.sh — 静静技能+记忆 完整同步到 GitHub 仓库
# 老倪要求 (2026-08-28): 技能完整镜像到 docs/skills/, 记忆一点不能丢, 每次都要备份
#
# 功能:
#   1. zmax-console 全家 (SKILL.md + references/ + scripts/ + templates/) 镜像到 docs/skills/xspace/zmax-console/
#   2. 其他关键技能 (mlops 训练类 + github 工作流类) 镜像到 docs/skills/xspace/
#   3. 记忆文件 (MEMORY.md + USER.md) 备份到 docs/memory/hermes-jingjing-{日期}.md + 最新副本
#   4. 更新 manifest.json (技能数/最后同步时间)
#   5. commit + push (带 sslVerify=false, 走 ghproxy)
#
# 用法:
#   bash tools/sync_hermes_to_repo.sh          # 同步+提交+推送
#   bash tools/sync_hermes_to_repo.sh --no-push  # 只同步+提交, 不推送
# ============================================================
set -e
cd "$(dirname "$0")/.."   # 仓库根目录
REPO_ROOT=$(pwd)
SKILLS_SRC="$HOME/.hermes/skills"
MEM_SRC="$HOME/.hermes/memories"
DEST_SKILLS="$REPO_ROOT/docs/skills/xspace"
DEST_MEM="$REPO_ROOT/docs/memory"
TODAY=$(date +%Y-%m-%d)
NOW=$(date +"%Y-%m-%d %H:%M:%S")
NO_PUSH=0
[ "$1" = "--no-push" ] && NO_PUSH=1

echo "📦 同步 Hermes → 仓库 (${TODAY})"
mkdir -p "$DEST_SKILLS" "$DEST_MEM"

# ── 1. zmax-console 全家 (最重要, 214 文件) ──
echo "  → zmax-console 全家镜像..."
rm -rf "$DEST_SKILLS/zmax-console"
mkdir -p "$DEST_SKILLS/zmax-console"
cp -r "$SKILLS_SRC/software-development/zmax-console/." "$DEST_SKILLS/zmax-console/"
echo "    zmax-console: $(find "$DEST_SKILLS/zmax-console" -type f | wc -l) 文件"

# ── 2. 其他关键技能 (按需扩展: 训练类/工作流类) ──
# 规则: 技能体积 < 3M 且属于关键路径才同步 (完整 27M 全同步会让仓库膨胀)
SYNC_LIST=(
  "mlops/lerobot-act-training"
  "mlops/lerobot-dataset-engineering"
  "mlops/robot-policy-eval"
  "mlops/robot-policy-eval-rollout"
  "mlops/zmax-cicd"
  "mlops/zmax-cicd-pipeline"
  "mlops/zmax-data-closed-loop"
  "mlops/zmax-data-pipeline"
  "mlops/zmax-left-right-policy"
  "mlops/zmax-model-compare-report"
  "mlops/zmax-policy-training-eval"
  "mlops/zmax-scene-engineering"
  "mlops/zmax-state-space-training"
  "mlops/hf-weight-download"
  "mlops/hf-dataset-subset"
  "mlops/docker-gpu-training"
  "github/github-issue-to-pr"
  "github/github-pr-workflow"
  "github/github-actions-ci"
  "devops/http-relay-service"
)
for rel in "${SYNC_LIST[@]}"; do
  src="$SKILLS_SRC/$rel"
  [ -d "$src" ] || { echo "    (跳过缺失: $rel)"; continue; }
  sz=$(du -sk "$src" | cut -f1)
  if [ "$sz" -gt 3072 ]; then
    echo "    (跳过超大: $rel ${sz}KB)"
    continue
  fi
  name=$(basename "$rel")
  rm -rf "$DEST_SKILLS/$name"
  mkdir -p "$DEST_SKILLS/$name"
  cp -r "$src/." "$DEST_SKILLS/$name/"
  echo "    ✓ $rel (${sz}KB)"
done

# ── 3. 记忆备份 (一点不能丢) ──
echo "  → 记忆备份..."
if [ -f "$MEM_SRC/MEMORY.md" ]; then
  cp "$MEM_SRC/MEMORY.md" "$DEST_MEM/hermes-jingjing-memory-${TODAY}.md"
  cp "$MEM_SRC/MEMORY.md" "$DEST_MEM/hermes-jingjing-memory-latest.md"
  echo "    MEMORY.md → hermes-jingjing-memory-${TODAY}.md + latest"
fi
if [ -f "$MEM_SRC/USER.md" ]; then
  cp "$MEM_SRC/USER.md" "$DEST_MEM/hermes-jingjing-user-${TODAY}.md"
  cp "$MEM_SRC/USER.md" "$DEST_MEM/hermes-jingjing-user-latest.md"
  echo "    USER.md → hermes-jingjing-user-${TODAY}.md + latest"
fi

# ── 4. manifest.json 更新 ──
echo "  → manifest.json 更新..."
SKILL_COUNT=$(find "$DEST_SKILLS" -name SKILL.md | wc -l)
python3 - "$NOW" "$SKILL_COUNT" <<'PYEOF'
import json, sys, os
now, cnt = sys.argv[1], int(sys.argv[2])
p = "docs/skills/manifest.json"
m = {"updated": now[:10]}
if os.path.exists(p):
    try: m = json.load(open(p))
    except Exception: pass
# 🐛 2026-08-28: 幂等性 — last_sync 只记日期 (天级), 同一天重复跑 manifest 不变
#   → git diff 无变化 → 不产生重复 commit (cron 每 6h 跑也不会刷屏)
m["updated"] = now[:10]
m.setdefault("avatars", {}).setdefault("xspace", {})["environment"] = "Linux, RTX 4060, GUI工程"
m["avatars"]["xspace"]["total_skills"] = cnt
m["avatars"]["xspace"]["last_sync"] = now[:10]
m["last_sync"] = now[:10]
json.dump(m, open(p, "w"), ensure_ascii=False, indent=2)
print(f"    manifest: xspace {cnt} skills, synced {now[:10]}")
PYEOF

# ── 5. commit + push ──
cd "$REPO_ROOT"
git add docs/skills/ docs/memory/ 2>/dev/null || true
if git diff --cached --quiet; then
  echo "✅ 无变更 (技能/记忆与仓库一致)"
else
  git commit -m "sync: Hermes 技能+记忆同步 (${TODAY}) — zmax-console 全家 + 关键技能 + 记忆备份

- docs/skills/xspace/zmax-console/: zmax-console 技能全家 (SKILL.md + references + scripts + templates)
- docs/skills/xspace/: 关键 mlops/github/devops 技能镜像
- docs/memory/hermes-jingjing-*-${TODAY}.md: 记忆每日备份 (MEMORY.md + USER.md)
- manifest.json: xspace 技能数/同步时间更新" >/dev/null
  echo "  ✅ commit: $(git log --oneline -1)"
  if [ "$NO_PUSH" = "0" ]; then
    echo "  → push..."
    # 🐛 2026-08-28: 同步包大 (214+ 文件) 时 ghproxy 默认 postBuffer 断连 "hung up"
    #   → postBuffer 提到 512MB; 失败自动重试一次
    timeout 300 git -c http.sslVerify=false -c http.postBuffer=524288000 push origin main 2>&1 | tail -2 \
      || timeout 300 git -c http.sslVerify=false -c http.postBuffer=524288000 push origin main 2>&1 | tail -2
    echo "  ✅ push 完成"
  else
    echo "  ⏸ --no-push, 跳过推送"
  fi
fi
echo "🎉 同步完成"
