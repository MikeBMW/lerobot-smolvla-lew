#!/bin/bash
# 🛰 工位总览/叠加 推流服务 —— 稳定启动器 (2026-09-28)
#
# 为什么需要它: 控制台两个按钮(🛰工位总览 / 🧩场景叠加)起来的那条命令**设备号写死**过
#   (--local-dev 2 --local2-dev 0), 现场后果实测:
#     · /dev/video2 = 笔记本相机的 GREY(IR) 路 ⇒ 画面近黑(mean≈6/255) —— 老倪:「笔记本内置摄像头太黑了」
#     · /dev/video0 = 笔记本**彩色**路, 却被当成 MAXHUB ⇒ 两格串线 —— 老倪:「MAXHUB 的跟笔记本串线了」
#   本脚本一律按 **卡名+能力** 解析设备(tools/cam_dev_resolve.py), 换号/换机/重启都不会再错。
#
# 用法:
#   bash tools/start_station_stream.sh          # 换号重启(先停旧, 再按解析结果起新)
#   bash tools/start_station_stream.sh --check  # 只看: 当前进程用的哪两路 + 两格实测
set -u
ROOT=/home/ubuntu/zmax_rel
PY="$ROOT/gui-venv311/bin/python"
PORT=8791
STATION=8793
LOG=/tmp/zmax_scene_overlay.log
ORIN_HOST="${ZMAX_ORIN_HOST:-tashan@192.168.23.66}"; ORIN_HOST="${ORIN_HOST##*@}"

_ld=$(python3 "$ROOT/tools/cam_dev_resolve.py" 2>/dev/null | sed -n 's/^LOCAL=//p');  [ -n "$_ld" ] || _ld=0
_l2=$(python3 "$ROOT/tools/cam_dev_resolve.py" 2>/dev/null | sed -n 's/^LOCAL2=//p'); [ -n "$_l2" ] || _l2=-1
[ "$_l2" = "$_ld" ] && _l2=-1        # 绝不把两路指到同一台设备(独占会打不开)

_pid_by_port() { ss -tlnp 2>/dev/null | sed -n "s/.*:${1} .*pid=\([0-9]*\).*/\1/p" | head -1; }

if [ "${1:-}" = "--check" ]; then
  p=$(_pid_by_port $PORT)
  echo "=== 当前推流进程 ==="
  [ -n "$p" ] && ps -o pid,etimes,cmd -p "$p" --no-headers | cut -c1-220 | sed 's/^/  /' || echo "  (8791 没在监听)"
  echo "=== 解析结果 (此刻硬件) ==="
  python3 "$ROOT/tools/cam_dev_resolve.py" --json 2>/dev/null | sed -n '1,12p' | sed 's/^/  /'
  echo "=== 两格实测(真实取帧) ==="
  curl -s -m 12 "http://127.0.0.1:$PORT/stats" \
    | python3 -c "import sys,json;d=json.load(sys.stdin);[print('  %-8s %-40s frames=%s'%(k,d[k].get('label',''),d[k].get('frames_served'))) for k in ('local','local2') if k in d]" 2>/dev/null
  exit 0
fi

p=$(_pid_by_port $PORT)
if [ -n "$p" ]; then echo "  · 停旧推流 pid=$p (按端口找, 不用 pkill 名字 —— 会杀到自己)"; kill "$p"; sleep 3; fi

cd "$ROOT" || exit 1
echo "  · 相机映射: 笔记本彩色 /dev/video$_ld · MAXHUB 顶视 $([ "$_l2" -ge 0 ] && echo "/dev/video$_l2" || echo '(未找到)')"
# ── 2026-09-29 根治: 先抬 fd 上限 + 清掉从父进程继承来的 fd 表 ────────────────
# 事故: 22:47 那个实例"一出生 fd 表就是满的"(日志第 15 行即 Errno 24) —— 它继承了
#       父进程的 1024 个 fd + 1024 的软上限, 于是连 accept 都做不了, 整个服务僵死 7 小时。
#       这里 ulimit 抬上限, closerange 丢弃 3 号以上的继承 fd, setrlimit 顶到硬上限。
ulimit -n 65535 2>/dev/null || ulimit -n 4096 2>/dev/null || true
nohup "$PY" -c 'import os,sys,resource
try:
  _s,_h=resource.getrlimit(resource.RLIMIT_NOFILE)
  resource.setrlimit(resource.RLIMIT_NOFILE,(_h,_h))
except Exception:
  pass
os.closerange(3,65536)
os.execv(sys.argv[1], sys.argv[1:])' "$PY" tools/cam_live_stream.py --port $PORT --quality 72 --fps 30 \
  --arm-http "http://$ORIN_HOST:8792/frame.jpg" --arm-fps 30 \
  --local-dev "$_ld" --local2-dev "$_l2" \
  --depth-fps 4 --aoi-fps 0.25 --ctl-motion --station-port $STATION \
  --overlay --overlay-src all --overlay-fps 10 >> "$LOG" 2>&1 &

for i in $(seq 1 20); do
  curl -s -m 3 -o /dev/null "http://127.0.0.1:$PORT/stats" && break
  sleep 1
done
sleep 2
echo "  · 复核:"
curl -s -o /dev/null -w "    8793/station → %{http_code}\n" -m 8 "http://127.0.0.1:$STATION/station"
curl -s -m 8 "http://127.0.0.1:$PORT/stats" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);[print('    %-8s %s'%(k,d[k].get('label',''))) for k in ('local','local2','arm') if k in d]" 2>/dev/null
echo "  页面: http://10.163.146.78:$STATION/station"
