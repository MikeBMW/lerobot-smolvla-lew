#!/bin/bash
# Hermes 随身包恢复脚本 v2 —— 一键安装 + 桌面图标
# 用法: bash hermes-restore.sh /path/to/hermes-portable.tar.gz
set -e

PKG="${1:-}"
# 没传参数时,自动找自己同目录(或家目录)的随身包 —— 双击即装,无需敲命令
if [ -z "$PKG" ]; then
  SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
  for cand in "$SELF_DIR/hermes-portable.tar.gz" "$HOME/hermes-portable.tar.gz"; do
    [ -f "$cand" ] && PKG="$cand" && break
  done
fi
[ -z "$PKG" ] && { echo "❌ 找不到 hermes-portable.tar.gz(请和本脚本放一起)"; sleep 3; exit 1; }
SRC_HOME="/home/xspace"

echo "==> 1/5 解包到 \$HOME ..."
tar xzf "$PKG" -C "$HOME" 2>/dev/null || true

# 路径修正:U盘系统用户名可能不是 xspace
if [ "$HOME" != "$SRC_HOME" ]; then
  echo "==> 2/5 修正路径 ($SRC_HOME -> $HOME) ..."
  sed -i "s|$SRC_HOME|$HOME|g" "$HOME/.local/bin/hermes" 2>/dev/null || true
  VENVPY="$HOME/.hermes/hermes-agent/venv/bin/python"
  if [ -L "$VENVPY" ]; then
    PY_BIN="$HOME/.local/share/uv/python/$(ls "$HOME/.local/share/uv/python/" 2>/dev/null | head -1)/bin/python3.11"
    [ -x "$PY_BIN" ] && ln -sf "$PY_BIN" "$VENVPY"
  fi
fi

echo "==> 3/5 配置 git 凭据 ..."
chmod 600 "$HOME/.git-credentials" 2>/dev/null || true
git config --global credential.helper store 2>/dev/null || true

echo "==> 4/5 创建桌面图标 ..."
# 找桌面目录(中英文系统都兼容)
DESKTOP_DIR=""
for d in "$HOME/Desktop" "$HOME/桌面" "$(xdg-user-dir DESKTOP 2>/dev/null)"; do
  [ -n "$d" ] && [ -d "$d" ] && DESKTOP_DIR="$d" && break
done
[ -z "$DESKTOP_DIR" ] && DESKTOP_DIR="$HOME/Desktop" && mkdir -p "$DESKTOP_DIR"

# 启动图标:双击直接进 Hermes
cat > "$DESKTOP_DIR/Hermes.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Hermes (静静)
Comment=启动 Hermes Agent
Exec=bash -lc 'export PATH="$HOME/.local/bin:\$PATH"; exec gnome-terminal -- bash -lc "hermes"'
Icon=utilities-terminal
Terminal=false
Categories=Development;
EOF
chmod +x "$DESKTOP_DIR/Hermes.desktop"
# 标记为可信,双击不再弹"未信任"警告
command -v gio >/dev/null && gio set "$DESKTOP_DIR/Hermes.desktop" metadata::trusted true 2>/dev/null || true

echo "==> 5/5 验证 ..."
export PATH="$HOME/.local/bin:$PATH"
if "$HOME/.local/bin/hermes" --version >/dev/null 2>&1; then
  echo ""
  echo "✅ 安装完成! 桌面上有 [Hermes (静静)] 图标,双击即用。"
  echo "   打开终端敲 hermes 也一样。"
  command -v zenity >/dev/null && zenity --info --title="Hermes 安装完成" --text="✅ Hermes 已装好\n桌面上有 [Hermes (静静)] 图标\n双击即可启动" 2>/dev/null || true
else
  echo "❌ 验证失败(venv 可能缺依赖)。把下面输出发给我:"
  "$HOME/.local/bin/hermes" --version 2>&1 || true
  echo "   可尝试: cd ~/.hermes/hermes-agent && uv sync 2>/dev/null || pip install -e ."
fi
