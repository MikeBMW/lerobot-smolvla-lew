#!/bin/bash
# XSpace Studio 启动脚本 (Z-MAX GUI)

cd /home/admin/xspace/lerobot-smolvla-lew/tools/gui

# PyQt5 在 Python 3.10 下完整可用，3.12 缺少 Qt5 二进制库
PYTHON="/usr/bin/python3.10"

if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

DISPLAY=:1 $PYTHON studio.py
