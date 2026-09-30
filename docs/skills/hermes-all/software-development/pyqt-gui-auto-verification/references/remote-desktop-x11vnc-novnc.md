# Linux 真机 GUI 远程看屏/遥控 — x11vnc + noVNC (2026-09-06 实测)

触发: 用户不在真机旁, 要"看到 agent 在电脑上的实际操作"或"开放远程控制窗口"。
参考 mutter-window-map-debug.md — 窗口 X 层不 map 时 QWidget.grab() 取证照常, 本文件是"让用户实时看/操作真机桌面"的落地通道。

## 方案层次 (按用户需求强度)
1. 截图 MEDIA 推送 (已有): 每步操作 scrot + MEDIA: 发飞书; 或 cron every 1m 定时截屏。够"看动作"。
2. **x11vnc + noVNC 网页远程桌面** (用户选"远程桌面"时用): 浏览器打开网页实时看+操作整屏 (含控制台)。零客户端。

## x11vnc + noVNC 安装与启动 (Ubuntu 24.04)
```bash
sudo apt-get install -y x11vnc novnc websockify

# 1) x11vnc: 共享 DISPLAY=:0, 密码认证
mkdir -p ~/.vnc
echo "zmax2026" | x11vnc -storepasswd /dev/stdin ~/.vnc/zmax.pass   # 或用 -storepasswd 交互
# 关键: 从 gnome-shell 进程取 XAUTHORITY (root/agent 启动时必需, 否则 Couldn't open display)
XAUTH=$(tr '\0' '\n' < /proc/$(pgrep -f gnome-shell | head -1)/environ | grep '^XAUTHORITY' | cut -d= -f2-)
DISPLAY=:0 nohup x11vnc -display :0 -rfbauth ~/.vnc/zmax.pass \
  -forever -shared -noxdamage -ncache 10 -bg -o /tmp/x11vnc.log

# 2) websockify: 网页 6080 → VNC 5900
nohup websockify --web=/usr/share/novnc 0.0.0.0:6080 localhost:5900 > /tmp/novnc.log 2>&1 &
```
验证: `ss -tln | grep -E '5900|6080'` 双端口 LISTEN; `curl -s -o /dev/null -w '%{http_code}' http://localhost:6080/vnc.html` = 200。

## 用户连接
- 网页版 (推荐): `http://<IP>:6080/vnc.html` → Connect → 密码
- VNC 客户端: `<IP>:5900` 同密码

## 网络要点 (最容易卡)
- `hostname -I` 查本机 IP; 内网 IP (192.168.x) 仅同网可达 → 用户连不上先问网络环境, 需路由器端口转发 5900/6080 或 VPN/frp
- `sudo ufw status` inactive 则端口已通; IPv6 公网地址存在但未必可路由
- 密码明文在命令里, 交付后提醒用户可改 (~/.vnc/zmax.pass)

## 用户偏好 (老倪, 本会话明确纠正)
- **"不要再发桌面的截屏了, 我要看控制台的截屏"** — 桌面 scrot 不是交付物; 要 GUI 取证发 **QWidget.grab() 截控件本身** (控制台窗口内容, 2900x1800), 或 3D 窗口 grab (241-257KB/张)
- "操纵控制台, 自动测试, 我要看控制台的实际操作截屏" — 自动测试套件 (ZMAX_AUTO_TEST=1 → auto_test_suite.py) 每用例 QWidget.grab 截图, 逐张 MEDIA 发群即交付
- 3D 全流程视频 (接近→插入 8 阶段): grab 逐帧 + ffmpeg 合成 (见 pyqt-gui-auto-verification SKILL.md 坑), 发 mp4

## 会话状态注记 (不要当作长期事实)
- 本机 (09-06) x11vnc PID + noVNC 已启动于 192.168.1.5:6080/5900, 密码 zmax2026 — 服务重启后需重新执行上面命令
