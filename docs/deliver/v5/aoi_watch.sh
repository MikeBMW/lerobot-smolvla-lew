#!/bin/bash
# AOI 两路看门狗 (4060 主节点侧) —— 2026-09-27
# 口径: 正常**一个字都不打**(老倪: 不要刷屏); 有问题才输出(并被 cron 投递到群)。
# 发现异常先自愈: 让工控机跑一次 ZMAX_AOI_KeepAlive 计划任务(它会缺哪个起哪个, 且能替掉没 /storage 面的冒充进程),
# 等 45s 复验; 仍异常才把结论打出来(带 /last_result 便于定位)。
LOG=/home/ubuntu/zmax_data/aoi_watch.log
cd /home/ubuntu/zmax || exit 0
PY=./gui-venv311/bin/python
probe() { curl -s -o /dev/null -m 8 -w '%{http_code}' "http://192.168.23.23:$1/storage"; }

bad=""
for p in 10082 10083; do
  c=$(probe $p)
  [ "$c" = "200" ] || bad="$bad $p($c)"
done
[ -z "$bad" ] && exit 0

echo "$(date '+%F %T') 首查异常:$bad → 触发自愈" >> "$LOG"
$PY tools/agent_hub.py --enqueue 'schtasks /run /tn ZMAX_AOI_KeepAlive' >/dev/null 2>&1
sleep 45

still=""
for p in 10082 10083; do
  c=$(probe $p)
  [ "$c" = "200" ] || still="$still $p($c)"
done
if [ -z "$still" ]; then
  echo "$(date '+%F %T') 自愈成功(首查$bad)" >> "$LOG"
  exit 0
fi

echo "$(date '+%F %T') 自愈失败: 首查$bad 仍异常$still" >> "$LOG"
echo "🚨 AOI 两路异常(已试自愈无效)"
echo "   首查:$bad"
echo "   自愈后:$still"
for p in 10082 10083; do
  echo "   $p /last_result: $(curl -s -m 8 "http://192.168.23.23:$p/last_result" | head -c 130)"
done
echo "   工控机侧日志: D:\\xspace\\ultralytics_AOI\\v5f.log / v5s.log / zmax_keepalive.log"
