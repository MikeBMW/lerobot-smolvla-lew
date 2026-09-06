# 远程桌面交付通道: x11vnc(:0 直显) + ECS 反向隧道 + noVNC 网页 (2026-09-06 实测)

触发: 老倪要"真实控制, 点击控制台的按钮, 不只是截图, 要互动操作" → 选「远程桌面」。
本文件补 auto-test-stage-shots-2026-09-06.md 的悬空引用, 并记录**直接 :0 直显版**隧道链路
(区别于 gnome-x11-qt-iconic-minimize-2026-09-06.md 的 Xvfb :99 版)。

## 全链路 (本机 GNOME :0, 公网可达 = 交付给老倪)
```bash
# 1. 本机: x11vnc 直接共享真实 :0 (不要 -localhost, 隧道入口在 ECS 侧才需要 localhost)
# ⚠️ 密码写法: -storepasswd 第一参数 = 明文密码本身! 禁止管道 + /dev/stdin (会把字面量 '/dev/stdi' 存成密码 → 永远 password check failed)
mkdir -p ~/.vnc && x11vnc -storepasswd zmax2026 ~/.vnc/zmax.pass
x11vnc -display :0 -rfbauth ~/.vnc/zmax.pass -forever -shared -noxdamage -ncache 10 -bg -o /tmp/x11vnc.log
# 验证: ss -tln | grep 5900; 改密码后必须重启 x11vnc 才生效 (密码启动时读入内存)

# 2. ECS 侧 (datadrive.world, 密码见记忆 ECS条目): websockify + noVNC 目录已常驻
#    websockify --web=/www/wwwroot/datadrive.world/novnc 127.0.0.1:6080 127.0.0.1:5900
#    nginx 已配 /novnc/ 路径 + basic auth (账号 zmax)

# 3. 反向隧道 (本机→ECS): ECS 5900 转发回本机 5900
sshpass -p '<ECS密码>' ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -N \
  -R 5900:localhost:5900 root@datadrive.world
```

## 坑 (2026-09-06 实测)
- **`x11vnc -storepasswd /dev/stdin file` 会把字面量 `/dev/stdi`(前8字符) 存成密码** (2026-09-06 16:15 实锤):
  noVNC 连上后永远 "password check failed", x11vnc 日志同刻有 `rfbAuthProcessClientMessage: password check failed`。
  正确写法: `x11vnc -storepasswd zmax2026 ~/.vnc/zmax.pass` (明文作第一参数)。
  系统无 vncpasswd 时别用管道假想 — 直接明文参数最稳。改完**必须重启 x11vnc**。
  认证实测脚本: 无 vncpasswd 也可用 python3 + pycryptodome 走 RFB 3.8 挑战应答验密码 (见本会话 /tmp/rfb_auth_test.py 思路)。
- **ECS 5900 被僵尸 sshd 占用 → 隧道起不来** ("remote port forwarding failed for listen port 5900")。
  清理: 登录 ECS `ss -tlnp | grep ':5900 '` 找 pid (是 sshd 的转发监听) → kill → 再建隧道。
- 隧道建好验证: ECS `ss -tln | grep 5900` 有监听 = 隧道活; 本机隧道进程日志无 Error。
- 网页带认证: `curl -u 'zmax:zmax2026' https://datadrive.world/novnc/vnc.html` → 200;
  无认证 401 = nginx auth 正常挡着。
- **隧道断线自愈**: nohup ssh -N 会断; 后续可加 autossh 或 cron 心跳, 本会话未做 (交付时隧道活着即可)。

## 交付 URL (老倪要"打开什么网址" — 给一个干净可点击链接, 别给一长串带参数)
- 入口: `https://datadrive.world/novnc/vnc.html`  (账号 zmax / 密码 zmax2026)
- 带参数自动连版本 (之前交付过): ...?host=datadrive.world&port=443&path=novnc/websockify&autoconnect=1
- 老倪实际偏好: 飞书里问"打开什么网址" = 要**单个简洁链接 + 账号密码**, 不要技术细节堆叠。

## ⚠️ 直显 :0 的局限 (本会话暴露)
- Qt/Mutter Iconic bug 未根治时, :0 上控制台窗口不可见 → VNC 看到的是**桌面壁纸不是控制台**,
  老倪反馈"桌面壁纸，没有控制台，有终端"→ 又转回 QWidget.grab 截**控制台本身**交付。
- 因此: 远程桌面解决"互动操作", QWidget.grab 解决"看控制台内容" — 两者互补, 按用户当下诉求选。
- 用户两次纠正: "不要再发桌面的截屏了, 我要看控制台的截屏" (要 QWidget.grab 控件图, 非 scrot 全屏)。
