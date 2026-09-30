#!/usr/bin/env bash
# live_run_triage.sh — 「我现在正在运行呢, 断点无反应」现场裁定 (只读, 不改任何状态)
#
# 用法:
#   scripts/live_run_triage.sh <入口脚本关键字> [adapter端口] [产物目录...]
# 例:
#   scripts/live_run_triage.sh studio.py 39777 reports/ outputs/
#
# 输出判读:
#   ① 子进程 ESTAB 到 adapter 端口  → 调试器 (pydevd 多进程) 已接上 ⇒ 子进程里断点**能进**
#      没有 ESTAB                    → 子进程没被调试 (或压根没起子进程), 断点自然不会进
#   ② STAT 含 t/T 的进程            → 有进程真停在断点 (此时"卡住"正常, 不是故障)
#      空                            → 一个都没停 ⇒ 不是"断点命中了没反应", 是没命中
#   ③ 产物 mtime + ffprobe          → 那个 run 是在跑 / 已跑完 / 产物大小帧数 (跑完但断点没进 ⇒ 链上没有那份代码)
set -u

PAT="${1:?用法: live_run_triage.sh <入口脚本关键字> [adapter端口] [产物目录...]}"
PORT="${2:-}"
shift 2 2>/dev/null || shift 1
DIRS=("$@")

hr() { printf '=%.0s' {1..72}; echo; }

hr; echo "① 进程树 (入口关键字: ${PAT})  [$(date '+%F %T')]"; hr
ps -eo pid,ppid,stat,etime,pcpu,cmd --no-headers \
  | grep -Ei "${PAT}|debugpy|pydevd" | grep -v grep | cut -c1-200

hr; echo "② 调试器接线 (adapter 端口: ${PORT:-<未给>})"; hr
if [ -n "${PORT}" ]; then
  echo "-- ESTAB 到 :${PORT} 的连接 (子进程 → adapter = 多进程调试已接) --"
  ss -tnp 2>/dev/null | grep ":${PORT}" || echo "   (无连接)"
  echo "-- 监听 :${PORT} 的进程 --"
  ss -ltnp 2>/dev/null | grep ":${PORT}" || echo "   (无人监听)"
else
  echo "   (跳过: 没给端口; 端口可从 pydevd 命令行里的 --port 取)"
fi

hr; echo "③ 有没有进程真停在断点 (STAT t/T)"; hr
_stopped=$(ps -eo pid,ppid,ppid,stat,etime,cmd --no-headers | awk '$4 ~ /^[tT]/ {print}' | cut -c1-180)
if [ -n "${_stopped}" ]; then printf '%s\n' "${_stopped}"; else echo "   (空 = 没有任何进程被断点停住 ⇒ 是"没命中", 不是"命中后无反应")"; fi

hr; echo "④ 运行产物 (证明那个 run 在写什么 / 跑完没有)"; hr
for d in "${DIRS[@]:-}"; do
  [ -e "$d" ] || continue
  ls -lat --time-style=+%m-%d_%H:%M:%S "$d" 2>/dev/null | head -8
done
for f in $(ls -t "${DIRS[@]:-}"/*.mp4 2>/dev/null | head -1); do
  echo "-- ffprobe $f --"
  ffprobe -v error -count_frames -select_streams v:0 \
          -show_entries stream=nb_read_frames,duration,width,height -of csv=p=0 "$f" 2>&1 | head -2
done

hr; echo "⑤ 这个 run 真正会执行的文件集 (静态判据: 断点文件在不在这里)"; hr
echo "   入口脚本里显式 import + importlib 动态加载点:"
for f in $(ps -eo cmd --no-headers | grep -E "${PAT}" | grep -v grep \
           | grep -oE '/[^ ]*\.py' | sort -u | head -3); do
  echo "   -- $f --"
  grep -nE "^\s*import |^\s*from |spec_from_file_location" "$f" 2>/dev/null | head -12
done
echo "   若你的断点模块名在上面一条都没出现 ⇒ 链上没有这份代码, 断点永远不会进 (先查这个, 别查调试器)"

hr; echo "提示: 想直接看活进程此刻在跑哪份代码: sudo <venv>/bin/py-spy dump --pid <pid>"
echo "      子进程若已跑完退出, py-spy 会报 'Failed to get process executable name' = 已退出, 不是探针坏。"
