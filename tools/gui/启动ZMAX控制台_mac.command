#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Z-MAX 控制台启动 (macOS 快捷方式) — 2026-08-26 静静 → 小芳
# 解决: exe 版黑屏 → 改源码模式启动 (可控 + 可诊断)
# 用法: 双击本文件 (首次 chmod +x), 或终端: bash ~/Desktop/启动ZMAX控制台.command
# ═══════════════════════════════════════════════════════════════

# 仓库根 (改这里指向你的 clone 路径)
REPO="$HOME/lerobot-smolvla-lew"
export ZMAX_REPO_ROOT="$REPO"

# 进入仓库
cd "$REPO" || { echo "❌ 仓库不存在: $REPO"; echo "请先: git clone https://github.com/MikeBMW/lerobot-smolvla-lew.git"; read -p "按回车退出"; exit 1; }

# ── 找 Python (优先 venv, 其次系统) ──
PY=""
for cand in "$REPO/gui-venv311/bin/python3" "$REPO/.venv/bin/python3" "$REPO/lerobot-venv/bin/python3" "/usr/bin/python3"; do
  if [ -x "$cand" ]; then PY="$cand"; break; fi
done
[ -z "$PY" ] && { echo "❌ 未找到 Python"; read -p "按回车退出"; exit 1; }
echo "✅ Python: $PY"

# ── OpenGL 兜底 (黑屏根因排查: 3D 视图 GLViewWidget 需要 OpenGL) ──
# 注释掉任一行可切换渲染模式, 排查黑屏:
export QT_OPENGL=software          # 软件渲染 (最稳, 3D 慢但绝不黑)
# export QT_OPENGL=desktop         # 桌面 OpenGL (3D 快, 若黑屏换 software)
# export QT_OPENGL=dynamic         # 动态选择
export LIBGL_ALWAYS_SOFTWARE=1     # Mesa 软件渲染兜底
# 高分屏缩放 (Mac Retina 必须, 禁 QT_SCALE_FACTOR 手设)
unset QT_SCALE_FACTOR

# ── 启动日志 (黑屏时看这里) ──
LOG="$HOME/zmax_console.log"
echo "🚀 启动 Z-MAX 控制台 (源码模式) ... 日志: $LOG"
echo "[$(date '+%H:%M:%S')] 启动: PY=$PY REPO=$REPO QT_OPENGL=$QT_OPENGL" >> "$LOG"

# 启动 (Mac .command 双击自带 Terminal)
"$PY" "$REPO/tools/gui/studio.py" 2>&1 | tee -a "$LOG"

echo ""
echo "⚠️ 控制台已退出。若黑屏, 把 $LOG 最后 30 行发群里给静静。"
read -p "按回车关闭"
