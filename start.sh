#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Z-MAX Studio — 一键启动脚本
# 用法: bash start.sh  或  ./start.sh
# 支持: WSL2 (WSLg) / 标准 Linux / Windows (通过 wsl.exe)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
set -e

# ── 自动定位项目根目录 ──
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "╔══════════════════════════════════════════════╗"
echo "║   Z-MAX Studio                              ║"
echo "║   多模态动作专家 · 具身智能开发环境           ║"
echo "║   v1.0.2 | Z700 轮式双臂机器人               ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── 检测运行环境 ──
if grep -qi microsoft /proc/version 2>/dev/null; then
    echo "🖥️  检测到 WSL 环境"
    IS_WSL=true
else
    echo "🐧 检测到标准 Linux 环境"
    IS_WSL=false
fi

# ── WSL: 修复 DISPLAY ──
if [ "$IS_WSL" = true ]; then
    export DISPLAY=:0
    echo "🔧 WSLg: DISPLAY 已设为 :0 (Unix socket)"
fi

# ── 找到 Python ──
PYTHON=""
CONDA_PYTHON="$HOME/miniconda3/envs/lerobot/bin/python"

if [ -x "$CONDA_PYTHON" ]; then
    if "$CONDA_PYTHON" -c "from PyQt5.QtWidgets import QApplication" 2>/dev/null; then
        PYTHON="$CONDA_PYTHON"
        echo "🐍 Python: conda lerobot ($($PYTHON --version 2>&1))"
    fi
fi

if [ -z "$PYTHON" ]; then
    for py in python3 python3.12 python3.11 python3.10; do
        if command -v "$py" >/dev/null 2>&1; then
            if "$py" -c "from PyQt5.QtWidgets import QApplication" 2>/dev/null; then
                PYTHON="$py"
                echo "🐍 Python: $PYTHON ($($PYTHON --version 2>&1))"
                break
            fi
        fi
    done
fi

if [ -z "$PYTHON" ]; then
    echo "❌ 未找到带 PyQt5 的 Python 环境"
    echo "   请先创建 conda 环境: conda create -n lerobot python=3.12 -y"
    echo "   然后安装依赖: conda activate lerobot && pip install -e ."
    exit 1
fi

# ── 检查是否在项目根目录 ──
if [ ! -f "tools/gui/studio.py" ]; then
    echo "❌ 未找到 tools/gui/studio.py，请在项目根目录运行此脚本"
    exit 1
fi

# ── 启动！ ──
echo "🚀 启动 XSpace Studio..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

cd tools/gui
exec $PYTHON studio.py
