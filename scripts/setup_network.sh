#!/bin/bash
# Z-MAX Mac 永久配网 · 运行一次，重启不丢
# 用法: sudo bash setup_network.sh
set -e

IP="192.168.23.1"
MASK="255.255.255.0"
SERVICE="Ethernet"

echo "=== 配置 Mac 永久静态IP ==="

# 方案1: 创建 LaunchDaemon (开机自启，最高可靠性)
PLIST="/Library/LaunchDaemons/com.zmax.setup-network.plist"

cat > /tmp/com.zmax.setup-network.plist << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.zmax.setup-network</string>
    <key>ProgramArguments</key>
    <array>
        <string>/sbin/ifconfig</string>
        <string>en0</string>
        <string>inet</string>
        <string>$IP</string>
        <string>netmask</string>
        <string>$MASK</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>
EOF

cp /tmp/com.zmax.setup-network.plist "$PLIST"
launchctl load "$PLIST" 2>/dev/null || true
echo "✅ LaunchDaemon 已安装: $PLIST"

# 方案2: 立即生效
/sbin/ifconfig en0 inet $IP netmask $MASK 2>/dev/null || \
    networksetup -setmanual "$SERVICE" $IP $MASK 2>/dev/null || true

echo "✅ 当前IP: $(ifconfig en0 | grep 'inet ' | awk '{print $2}')"
echo "✅ 下次重启自动配网"
