#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# XSpace Studio — Z-MAX 具身智能开发环境
# 启动方式: bash run_studio.sh 或 ./run_studio.sh
# 支持任意 clone 路径（不依赖固定目录）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 自动定位脚本所在目录（无论从哪里调用都正确）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || { echo "❌ 无法进入 $SCRIPT_DIR"; exit 1; }

echo "📂 工作目录: $SCRIPT_DIR"

# 自动检测可用 Python 版本（确保有 PyQt5）
find_python() {
    local py
    for py in python3 python3.10 python3.12 python3.11; do
        # 检查是否已安装
        if command -v "$py" >/dev/null 2>&1; then
            # 验证 PyQt5 可导入
            if "$py" -c "from PyQt5.QtWidgets import QApplication" 2>/dev/null; then
                echo "$py"
                return 0
            fi
        fi
    done
    return 1
}

PYTHON=$(find_python)
if [ -z "$PYTHON" ]; then
    echo "⚠️  未找到带 PyQt5 的 Python，尝试安装 PyQt5..."
    if command -v python3 >/dev/null 2>&1; then
        python3 -m pip install -q PyQt5 PyQt5-sip 2>/dev/null
        PYTHON="python3"
    fi
else
    echo "🐍 Python: $PYTHON ($($PYTHON --version 2>&1))"
fi

echo "🚀 启动 XSpace Studio..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
$PYTHON studio.py
