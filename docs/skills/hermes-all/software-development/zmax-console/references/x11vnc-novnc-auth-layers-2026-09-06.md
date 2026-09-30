# x11vnc/noVNC 两层认证 + VNC 密码坑 (2026-09-06 实测)

触发: 用户/群里报 noVNC 连不上 — 401 / password check failed 是**两层不同认证**的报错,
别混为一谈。本文件是 remote-desktop-x11vnc-novnc.md 的认证专项补充。

## 报错 → 层的对照表 (先判层再动手)
| 报错 | 层 | 查什么 |
|---|---|---|
| `401` (浏览器弹窗, 进不了页面) | nginx HTTP Basic Auth | nginx `.htpasswd`/`.novnc_passwd` 账号; 浏览器缓存旧密码 (隐身窗口重试) |
| `password check failed` (页面能开, noVNC 红字) | **x11vnc VNC 密码** (RFB auth) | `~/.vnc/zmax.pass` 内容 + x11vnc 是否加载了正确密码; 日志 `/tmp/x11vnc.log` 同刻应有 `rfbAuthProcessClientMessage: password check failed` |

## VNC 密码文件坑 (2026-09-06 实锤)
- **`x11vnc -storepasswd /dev/stdin file` 是错的**: 第一参数被当**明文密码本身**,
  存进去的是字面量 `/dev/stdi` (VNC 密码只取前 8 字符) → 所有持正确密码的人全被拒,
  x11vnc 日志反复 `password check failed`。看起来像"从 stdin 读"实则是陷阱写法。
- **正确**: `x11vnc -storepasswd zmax2026 ~/.vnc/zmax.pass` (明文作第一参数, 直接写文件)。
- **改密码必须重启 x11vnc** — 密码启动时读入内存, 不重启不生效:
  `kill <x11vnc_pid>` → `x11vnc -display :0 -rfbauth ~/.vnc/zmax.pass -forever -shared -noxdamage -ncache 10 -bg -o /tmp/x11vnc.log`
- VNC 密码 ≤8 字符 (超出静默截断); 系统无 vncpasswd 很正常 (别装, 用下面的实测脚本)。

## 验证 = RFB 挑战应答实测 (唯一权威, 别做字节对比)
**字节对比加密文件会骗人**: 若系统无 vncpasswd, `printf pw | vncpasswd -f > f` 实际
command not found (被 `2>/dev/null` 掩盖) → f 是空文件 → `cmp` 空 vs 空 输出"一致"、
空 vs 非空 输出"不一致" — 全是假象。**认证唯一可靠验证 = 真连一次走挑战应答**:

```bash
python3 scripts/rfb_auth_test.py zmax2026     # 期望 PASS (exit 0)
python3 scripts/rfb_auth_test.py wrongpass    # 负对照, 期望 FAIL (exit 2) — 证明测试不是啥都放行
```
(脚本: RFB 3.8 握手 + VNC Auth DES 挑战应答, 依赖 pycryptodome; 支持
`<pw> [host] [port]`, 默认 127.0.0.1:5900 — 隧道入口在 ECS 时连 ECS 侧端口同法验证全链路。)

## noVNC 密码免输 URL
noVNC `vnc.html` 支持 URL `password=` 参数 → 自动填 VNC 密码, 用户只手输一次 nginx 弹窗:
```
https://datadrive.world/novnc/vnc.html?host=datadrive.world&port=443&path=novnc/websockify&password=zmax2026&autoconnect=1
```
⚠️ URL 含明文密码会留在群记录/浏览器历史 — 只在需要时发, 别常驻文档/公告。

## 链路各环节健康速查 (报障时按序实测)
1. 本机: `pgrep -af x11vnc` + `ss -tln | grep 5900` (x11vnc 活 + 监听)
2. 隧道: 本机 `pgrep -af 'ssh.*5900'` / ECS `ss -tln | grep 5900`
3. ECS websockify: ECS 上 `pgrep -af websockify` (6080)
4. nginx 层: `curl -u 'zmax:zmax2026' https://datadrive.world/novnc/vnc.html` → 200
5. VNC 层: `python3 scripts/rfb_auth_test.py zmax2026` (ECS 侧 5900 端口直测可验隧道+VNC 全通)
