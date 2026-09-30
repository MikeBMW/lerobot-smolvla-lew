#!/usr/bin/env bash
# 在 Orin 上恢复 rs_fast_node(带 ROS 环境) —— 通过 ssh bash -s 执行, 无引号问题
set -u
echo "-- 1) 原进程环境(留档, 防止再次丢环境) --"
OLD=$(pgrep -f "rs_fast""_node.py" | head -1)
echo "   原 PID: ${OLD:-无}"
if [ -n "${OLD:-}" ]; then
  tr '\0' '\n' < "/proc/$OLD/environ" 2>/dev/null | grep -E "^(ROS_|RMW_|AMENT|LD_LIBRARY|PYTHONPATH|FASTRTPS)" | head -8 | sed 's/^/     /'
  echo "   工作目录: $(readlink /proc/$OLD/cwd 2>/dev/null)"
fi

echo "-- 2) 停旧进程并确认真的没了 --"
for p in $(pgrep -f "rs_fast""_node.py"); do kill "$p" 2>/dev/null; done
sleep 3
for p in $(pgrep -f "rs_fast""_node.py"); do kill -9 "$p" 2>/dev/null; done
sleep 2
if pgrep -f "rs_fast""_node.py" >/dev/null 2>&1; then
  echo "   ✗ 还有残留:"; pgrep -af "rs_fast""_node.py" | sed 's/^/     /'
else
  echo "   ✓ 旧进程已清"
fi

echo "-- 3) 带 ROS 环境重新拉起(脱离会话) --"
cat > /tmp/rs_fast_launch.sh <<'EOS'
#!/usr/bin/env bash
source /opt/ros/humble/setup.bash
for ws in /home/tashan/0810/*/install/setup.bash; do [ -f "$ws" ] && source "$ws" && break; done
export ROS_DOMAIN_ID=0
exec python3 /tmp/rs_fast_node.py
EOS
chmod +x /tmp/rs_fast_launch.sh
setsid nohup /tmp/rs_fast_launch.sh > /tmp/rs_fast_node.log 2>&1 < /dev/null &
sleep 10

echo "-- 4) 状态两次采样(n 必须涨、age_s 必须回落) --"
curl -s --max-time 8 http://127.0.0.1:8792/st || echo "   (取不到)"
echo
sleep 5
curl -s --max-time 8 http://127.0.0.1:8792/st || echo "   (取不到)"
echo
echo "-- 5) /frame.jpg 两次 md5(必须不同 = 真在刷新) --"
curl -s --max-time 8 -o /tmp/a.jpg http://127.0.0.1:8792/frame.jpg && md5sum /tmp/a.jpg | awk '{print "     "$1}'
sleep 2
curl -s --max-time 8 -o /tmp/b.jpg http://127.0.0.1:8792/frame.jpg && md5sum /tmp/b.jpg | awk '{print "     "$1}'
echo "-- 6) 日志尾 --"
tail -4 /tmp/rs_fast_node.log | sed 's/^/     /'
exit 0
