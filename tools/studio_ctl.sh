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
  stop)
    P=$(pids)
    if [ -n "$P" ]; then kill $P; sleep 4; echo "stopped: $P"; else echo "already stopped"; fi
    ;;
  start)
    [ -n "$(pids)" ] && { echo "already running: $(pids)"; exit 0; }
    cd "$GUI_DIR" && DISPLAY=:0 setsid bash launch_studio.sh >/tmp/studio_launch.log 2>&1 < /dev/null &
    sleep 25; echo "started: $(pids)"
    ;;
  restart)
    bash "$0" stop; bash "$0" start
    ;;
  *) echo "用法: $0 {status|stop|start|restart}"; exit 2 ;;
esac
