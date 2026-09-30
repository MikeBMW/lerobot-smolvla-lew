#!/usr/bin/env bash
# check_unit_paths.sh — 扫"unit 里引用的本机路径是否还存在" (抓「指向已消失脚本」的服务)
#
# 为什么需要 (2026-09-26 实测): 多 agent 线共用一棵检出时, 另一条线 `git switch` 到别的分支
# → 那棵树里 main 线的脚本/画布目录整个消失 → 服务**重启即挂**且没人发现(老进程还活着)。
# 本脚本把"启动依赖"当资产清点: 路径不存在就报 ❌, 一眼看出哪些服务下次重启会死。
#
# 用法: bash scripts/check_unit_paths.sh [前缀]      # 默认只看 /home/ubuntu 下的引用
set -u
PREFIX="${1:-/home/ubuntu}"
bad=0; tot=0
for u in $(systemctl list-unit-files '*.service' --no-pager 2>/dev/null | awk '{print $1}'); do
  paths=$(systemctl cat "$u" 2>/dev/null | grep -oE "${PREFIX}[^ \"']*" | sort -u)
  [ -n "$paths" ] || continue
  for p in $paths; do
    tot=$((tot+1))
    if [ ! -e "$p" ]; then
      bad=$((bad+1)); printf '❌ %-28s 缺: %s\n' "$u" "$p"
    fi
  done
done
echo "---- 引用路径 $tot 个, 缺失 $bad 个 ----"
if [ "$bad" -gt 0 ]; then
  echo "提示: 指向被切走分支的检出时 → 把 unit 改指稳定 worktree (改完 systemctl daemon-reload + 逐个 restart 复核 is-active)"
  exit 3
fi
