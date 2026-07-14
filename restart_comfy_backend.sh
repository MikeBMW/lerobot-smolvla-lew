#!/bin/bash
# ComfyUI Backend 安全重启脚本
PID=$(netstat -tlnp 2>/dev/null | grep 50054 | awk '{print $NF}' | cut -d'/' -f1)
[ -n "$PID" ] && kill -9 $PID 2>/dev/null && sleep 2
PORT_FREE=1
for i in 1 2 3 4 5; do
  if ! netstat -tlnp 2>/dev/null | grep -q 50054; then PORT_FREE=0; break; fi
  sleep 1
done
if [ $PORT_FREE -ne 0 ]; then echo "❌ Port 50054 still busy"; exit 1; fi
cd /root/lerobot-smolvla-lew
exec ~/.local/share/uv/python/cpython-3.12-linux-x86_64-gnu/bin/python3.12 comfyui_backend.py