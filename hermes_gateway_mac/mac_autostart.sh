#!/bin/bash
# Hermes Gateway — Mac自动启动脚本
# 通电后自动启动所有守护进程
# 
# 安装: bash mac_autostart.sh install
# 卸载: bash mac_autostart.sh uninstall

set -e

APP_NAME="com.hermes.gateway"
PLIST_PATH="$HOME/Library/LaunchAgents/${APP_NAME}.plist"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

install() {
    echo "🟢 安装 Hermes Gateway 开机自启动..."

    # 1. 创建启动脚本
    cat > "$PROJECT_DIR/startup.sh" << 'STARTUP_SCRIPT'
#!/bin/bash
# Hermes Gateway 开机启动

LOG="$HOME/hermes_gateway_startup.log"
echo "=== $(date) ===" >> "$LOG"

# 防休眠
caffeinate -d -i -m -s &
echo "✅ caffeinate 已启动" >> "$LOG"

# 激活虚拟环境
cd "$(dirname "$0")"
source venv/bin/activate 2>/dev/null || true

# 启动 Gateway (先不带Orin, 等现场手动连接或SSH配置)
python3 gateway_pure.py --port 8080 >> "$LOG" 2>&1 &

echo "✅ Gateway 已启动 (PID: $!)" >> "$LOG"
echo "启动完成" >> "$LOG"
STARTUP_SCRIPT

    chmod +x "$PROJECT_DIR/startup.sh"

    # 2. 创建 LaunchAgent
    cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${APP_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${PROJECT_DIR}/startup.sh</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${HOME}/hermes_gateway_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>${HOME}/hermes_gateway_stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${HOME}/miniconda/bin:${HOME}/miniconda3/bin</string>
    </dict>
</dict>
</plist>
PLIST

    # 3. 加载
    launchctl load "$PLIST_PATH"
    echo "✅ LaunchAgent 已安装并加载"

    # 4. 防休眠设置 (立即生效, 重启后由caffeinate保证)
    sudo pmset -a displaysleep 0 sleep 0 2>/dev/null || true
    echo "✅ 防休眠已设置"

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "✅ Hermes Gateway 开机自启动已安装"
    echo ""
    echo "通电后自动:"
    echo "  1. 启动 caffeinate (防休眠)"
    echo "  2. 启动 Gateway API (:8080)"
    echo "  3. 守护进程 KeepAlive (崩溃自动重启)"
    echo ""
    echo "日志: $HOME/hermes_gateway_startup.log"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

uninstall() {
    echo "卸载..."
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    rm -f "$PLIST_PATH"
    rm -f "$PROJECT_DIR/startup.sh"
    echo "✅ 已卸载"
}

status() {
    if [ -f "$PLIST_PATH" ]; then
        echo "✅ 已安装"
        launchctl list | grep "$APP_NAME" && echo "✅ 运行中" || echo "⚠️ 未运行"
    else
        echo "❌ 未安装"
    fi
}

case "${1:-install}" in
    install) install ;;
    uninstall) uninstall ;;
    status) status ;;
    *) echo "用法: bash mac_autostart.sh [install|uninstall|status]" ;;
esac
