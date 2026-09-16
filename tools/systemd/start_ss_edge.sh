#!/bin/bash
# Z-MAX 跨机闭环 · Orin 采集+闸门节点启动 (只读采集 + 闸门判决, 默认不执行任何动作)
export ROS_DOMAIN_ID=0
source /opt/ros/humble/setup.bash 2>/dev/null
export ZMAX_REPO_ROOT=/home/tashan/zmax_state_space
mkdir -p /home/tashan/.zmax/ss_link
# 默认: MIN 订阅 (关节+夹爪, 实测 10% 单核) + 10Hz 上行; 需要全量(含六维力/阶段)时 SS_EDGE_FULL=1
# 放权需显式 SS_GATE_ARM=1 (默认 disarmed: 只判不下发)
exec python3 /home/tashan/zmax_state_space/tools/ss_edge.py --rate 10 "$@"
