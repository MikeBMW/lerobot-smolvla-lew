#!/bin/bash
# LeRobot Studio 启动脚本

cd /home/admin/xspace/lerobot-smolvla-lew/tools/gui

# PyQt5 只在 Python 3.10 下完整安装，3.12 缺少 PyQt5-Qt5（~80MB，下载超时）
python3.10 le_robot_studio.py
