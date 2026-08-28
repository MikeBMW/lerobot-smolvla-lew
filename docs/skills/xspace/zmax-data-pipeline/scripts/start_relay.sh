#!/bin/bash
# Z-MAX 中转服务启动脚本 (ECS 39.102.211.79)
# 关键: 单独落盘执行, 不要把 pkill+nohup 塞进同一条 ssh 命令
pkill -f 'zmax_relay.py' 2>/dev/null
sleep 1
cd /root/zmax-relay
setsid nohup python3 zmax_relay.py > relay.log 2>&1 < /dev/null &
sleep 2
ps aux | grep zmax_relay | grep -v grep | head -1
tail -2 relay.log
