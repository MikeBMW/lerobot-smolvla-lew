#!/usr/bin/env bash
# 被墙环境把本地提交推上 GitHub (ghproxy 镜像) — 2026-09-13 实测通, 4 轮踩坑后的定版流程。
#
# 为什么不能直接 `git push origin main`:
#   ① github.com 直连被墙 (GnuTLS recv error -110)
#   ② 代理下 ~/.git-credentials (host=github.com) 匹配不到 ghproxy.net → git 交互式问密码 + 无 TTY → 永久挂起
#   ③ 提交体积 >几百 KB 会被代理拒绝: gh-proxy.com 回 HTTP 413, ghproxy.net 静默挂死 (无输出, rc=124)
#      → 所以本脚本先检查提交体积, 再推; 大图/PDF/权重一律不进库 (留本地 reports/)
#   ④ 被墙下 fetch 失败 → 本地 origin/main 永远陈旧, `git status -sb` 的 "ahead N" 不可信
#      → 成功判据只能是 ls-remote 的远端 SHA == 本地 HEAD
#
# 用法: bash scripts/push_via_ghproxy.sh [repo_dir]   (默认 ~/lerobot-smolvla-lew)
set -u
REPO="${1:-$HOME/lerobot-smolvla-lew}"
cd "$REPO" || { echo "❌ 仓库不存在: $REPO"; exit 1; }

echo "=== 待推提交 ==="
git log --oneline -3
echo "=== 提交体积检查 (>500KB 大概率被代理拒绝) ==="
BIG=$(git show --stat HEAD | tail -1)
echo "  $BIG"
git show --numstat HEAD | awk '{s+=$3} END {printf "  本提交新增 %d 字节\n", s}'
git diff --cached --quiet || echo "  ⚠️ 有未提交的暂存改动"

CRED=$(python3 - <<'PY'
import re, os
try:
    s = open(os.path.expanduser('~/.git-credentials')).read()
    m = re.search(r'https://([^/\s]+)@github\.com', s)
    print(m.group(1) if m else '')
except Exception:
    print('')
PY
)
if [ -z "$CRED" ]; then echo "❌ ~/.git-credentials 里没找到 github.com 凭证"; exit 1; fi
AUTH="Basic $(printf '%s' "$CRED" | base64 -w0)"
LOCAL=$(git rev-parse HEAD)

for M in https://ghproxy.net/ https://gh-proxy.com/ https://ghproxy.cc/; do
  URL="${M}https://github.com/MikeBMW/lerobot-smolvla-lew.git"
  echo "=== 尝试 $M ==="
  timeout 150 git -c http.sslVerify=false -c http.extraHeader="Authorization: $AUTH" \
      -c http.postBuffer=524288000 push "$URL" HEAD:main
  RC=$?                                # 单独取 rc: 别用 `| tail` (管道 rc 是 tail 的 0, 真失败被吞)
  echo "  push rc=$RC   (124=超时/体积墙 · 1 且带 413=代理拒绝体积)"
  if [ $RC -eq 0 ]; then
    REMOTE=$(timeout 45 git -c http.sslVerify=false -c http.extraHeader="Authorization: $AUTH" \
             ls-remote "$URL" refs/heads/main | cut -f1)
    echo "  远端 main = $REMOTE"
    echo "  本地 HEAD = $LOCAL"
    if [ "$REMOTE" = "$LOCAL" ]; then echo "✅ 推送成功且远端一致"; exit 0; fi
    echo "  ⚠️ rc=0 但远端不一致 → 继续换镜像"
  fi
done
echo "❌ 所有镜像都没推上去: 先确认提交体积 (去掉 PNG/PDF/权重再试), 再确认是否文件被 .gitignore 挡了"
exit 1
