#!/usr/bin/env bash
# 关键对照实验: 去掉 UDP-only 强制(回到默认=可用共享内存) + BEST_EFFORT, 量帧率
set +u
PAT="rs_fast""_node.py"

echo "-- 0) 当前 SHM 端口占用情况(只读, 不删任何文件) --"
ls -l /dev/shm/ 2>/dev/null | grep -iE "fastrtps|rtps|sem" | head -5 | sed 's/^/     /'
echo "     SHM 总占用: $(df -h /dev/shm 2>/dev/null | tail -1)"

echo "-- 1) 把 launcher 里的 UDP-only 强制去掉(BEST_EFFORT 恢复) --"
sed -i 's/ReliabilityPolicy.RELIABLE/ReliabilityPolicy.BEST_EFFORT/' /tmp/rs_fast_node.py
cat > /tmp/rs_fast_launch.sh <<'EOS'
#!/usr/bin/env bash
source /opt/ros/humble/setup.bash
for ws in /home/tashan/0810/*/install/setup.bash; do [ -f "$ws" ] && source "$ws" && break; done
export ROS_DOMAIN_ID=0
# 不再设 FASTRTPS_DEFAULT_PROFILES_FILE ⇒ 用默认传输(UDPv4 + SHM)
exec python3 /tmp/rs_fast_node.py
EOS
chmod +x /tmp/rs_fast_launch.sh
grep -nE "ReliabilityPolicy|FASTRTPS" /tmp/rs_fast_node.py /tmp/rs_fast_launch.sh | sed 's/^/     /'

echo "-- 2) 重启桥 --"
for p in $(pgrep -f "$PAT"); do kill "$p" 2>/dev/null; done
sleep 3
for p in $(pgrep -f "$PAT"); do kill -9 "$p" 2>/dev/null; done
sleep 1
setsid nohup /tmp/rs_fast_launch.sh > /tmp/rs_fast_node.log 2>&1 < /dev/null &
sleep 12

echo "-- 3) 量 25 秒帧率 --"
n1=$(curl -s --max-time 6 http://127.0.0.1:8792/st | sed -E 's/.*"n":([0-9]+).*/\1/')
sleep 25
n2=$(curl -s --max-time 6 http://127.0.0.1:8792/st | sed -E 's/.*"n":([0-9]+).*/\1/')
echo "     n: $n1 → $n2   ⇒ 实测 $(echo "scale=2; ($n2-$n1)/25" | bc 2>/dev/null || echo "?") fps"
curl -s --max-time 6 http://127.0.0.1:8792/st | sed 's/^/     /'
echo
echo "-- 4) 日志(有没有 SHM 报错回来) --"
tail -5 /tmp/rs_fast_node.log | sed 's/^/     /'
exit 0
