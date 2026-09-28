#!/usr/bin/env bash
# 🎛 studio_ctl.sh — 安全启停 zmax-studio (避免"pkill -f studio.py 杀自己")
#
# 为什么需要: 命令行里出现 "studio.py" 字样时, `pkill -f studio.py` / `ps|grep studio.py`
#   会匹配到**当前这个 shell 自身** → 自杀 (2026-09-24 实测 SIGTERM -15)。
#   本脚本按**解释器绝对路径**精确匹配 (arg0 = .../gui-venv311/bin/python), 且用 argv 数组比较,
#   不含自身命令行里的裸字符串 → 不会自杀。
#
# 用法: bash tools/studio_ctl.sh {status|stop|start|restart}
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GUI_DIR="$REPO/tools/gui"
# ⚠️ 坑: venv 在**仓库根** (launch_studio.sh 硬编码 $REPO/gui-venv311/bin/python),
#    不在 tools/gui/ 下 —— 按错的路径匹配会永远报 "stopped" (2026-09-24 实测踩到)
PY=""
for cand in "$REPO/gui-venv311/bin/python" "$GUI_DIR/gui-venv311/bin/python"; do
  [ -x "$cand" ] && PY="$cand" && break
done
[ -n "$PY" ] || { echo "❌ 找不到 gui-venv311 解释器"; exit 1; }

pids() {                       # 宽松精确匹配: cmdline 里同时含 'studio.py' 与 本工程 venv 解释器路径
  # ⚠️ 判断在**脚本文件里**做 (不是命令行), 所以不会像 `pkill -f studio.py` 那样匹配到自己
  python3 - "$PY" <<'PYEOF'
import os, sys, glob
target_dir = sys.argv[1].rsplit("/", 1)[0]          # .../gui-venv311/bin
out = []
for p in glob.glob("/proc/[0-9]*"):
    try:
        with open(os.path.join(p, "cmdline"), "rb") as f:
            argv = [a.decode(errors="ignore") for a in f.read().split(b"\0") if a]
    except Exception:
        continue
    if not argv:
        continue
    # 启动脚本会套 nice/setsid/env → 不假设 argv[1], 只要任一段是解释器且任一段是 studio.py
    if any(a == target_dir + "/python" or a.startswith(target_dir + "/python") for a in argv) \
            and any(a.endswith("studio.py") for a in argv):
        out.append(int(os.path.basename(p)))
print(" ".join(str(x) for x in out))
PYEOF
}

case "${1:-status}" in
  status)
    P=$(pids); [ -n "$P" ] && echo "running: $P" || echo "stopped"
    ;;
  stop|restart)
    # 🛑 2026-09-28 老倪两次问「控制台怎么自己重启呢」——真因不是自启(Restart=no, 无 cron 碰它),
    #   而是 **agent 改完代码就重启它**, 现场只看到窗口闪来闪去。加硬闸: 起不到 5 分钟的实例,
    #   stop/restart 一律拒绝, 要重启必须显式 --force; 每次动作都记进 /tmp/studio_ctl.log 可追溯。
    P=$(pids)
    if [ -n "$P" ]; then
      _age=$(ps -o etimes= -p $P 2>/dev/null | tr -d ' ')
      if [ -n "${_age:-}" ] && [ "$_age" -lt 300 ] && [ "${2:-}" != "--force" ] && [ "${2:-}" != "-f" ]; then
        echo "⛔ 拒绝: 控制台才起了 ${_age}s (<300s)。反复重启会让现场看到窗口闪来闪去 (老倪已投诉 2 次)。"
        echo "   确实要重启(比如必须加载新代码): bash $0 restart --force"
        echo "$(date '+%F %T') REFUSED stop pid=$P age=${_age}s arg=${1:-}" >> /tmp/studio_ctl.log
        exit 3
      fi
      echo "$(date '+%F %T') $1 pid=$P age=${_age:-?}s force=${2:-no}" >> /tmp/studio_ctl.log
      kill $P; sleep 4
    fi
    if [ "$1" = "restart" ]; then
      [ -n "$(pids)" ] && { echo "already running: $(pids)"; exit 0; }
      cd "$GUI_DIR" && DISPLAY=:0 setsid bash launch_studio.sh >/tmp/studio_launch.log 2>&1 < /dev/null &
      sleep 25; echo "started: $(pids)"
    else
      echo "stopped: ${P:-none}"
    fi
    ;;
  start)
    [ -n "$(pids)" ] && { echo "already running: $(pids)"; exit 0; }
    echo "$(date '+%F %T') start" >> /tmp/studio_ctl.log
    cd "$GUI_DIR" && DISPLAY=:0 setsid bash launch_studio.sh >/tmp/studio_launch.log 2>&1 < /dev/null &
    sleep 25; echo "started: $(pids)"
    ;;
  *) echo "用法: $0 {status|stop|start|restart} [--force]" ; exit 2 ;;
esac
