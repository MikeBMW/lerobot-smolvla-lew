# 公网暴露闸门 · 隧道选型 · 窄通道推流（可抄的件）

用途：把"现场实时画面"送到办公网以外（手机 4G、云主机、别人的 App），**且不允许任何人远程动机器人**。

## 1. 闸门（`tools/tunnel_proxy.py`，systemd 常驻，绑定 127.0.0.1）

```
ALLOW(正则全匹配, 想加必须显式加)   /  /index.html  /overlay  /overlay/<name>  /app  /scene.json
                                    /stats  /robot_status  /motion  /ctl/status
                                    /snapshot/<name>.jpg  /<name>.mjpg  /wall.jpg  /wall.mjpg
                                    /live.json  /dl/<file>  /lib/<path>
DENY(点名, 优先于 ALLOW, 永不外放)   /ctl/arm  /ctl/move  (以及 /api/ctl/*)  /station*  /gen*  /tap*  /move*  /api/relay/*
方法                               只放 GET; POST/PUT/DELETE/PATCH 一律 403; HEAD 405
口令                               无 ?k=<token> 且无 cookie zmaxk=<token> ⇒ 403
                                  首次带 ?k= 命中 ⇒ 响应加 Set-Cookie: zmaxk=<token>; Path=/; SameSite=Lax
MJPEG                              multipart 响应边收边发(read 8KB→write→flush)，非流式响应补齐 Content-Length
```

要点
- `/ctl/status`、`/motion` 是**只读状态**，故意放行；`/ctl/arm`、`/ctl/move` 是动作，永久拒绝。
- 白名单按"页面实际请求的路径"定：先 `grep -oE "fetch\('[^']+|src=\"[^\"]+" <页面>` 把路径列出来，否则穿过去是残页。
- 本地合成的路径（拼图流/清单）在**白名单判定之后、转发上游之前**处理。
- 代理转发给上游时改 `Host: 127.0.0.1`，避免上游按 Host 做意外分支。

## 2. 真值表（`tools/verify_tunnel_gate.py`，14 条，缺一条都不放行）

| 请求 | 期望 |
|---|---|
| `GET /overlay?k=` · `/scene.json?k=` · `/stats?k=` | 200 |
| `GET /overlay`（无口令） | 403 |
| `GET /overlay`（带 cookie） | 200 |
| `GET /snapshot/arm.jpg?k=` · `/snapshot/overlay_arm.jpg?k=` | 200 + `image/jpeg` |
| **`POST /ctl/arm?k=`** · **`POST /ctl/move?k=`** | **403（带正确口令也拒）** |
| `GET /gen?kind=vlm&k=` | 403 |
| `GET /station?k=` · `/tap?k=` | 403 |
| `POST /api/relay/upload?k=` | 403 |
| `GET /etc/passwd?k=` | 403 |

判据写法：状态码**先转 int** 再比期望；表里留一条已知必过的控制项。`str(status) == 200` 这种写法会让整表假报 ✗。

## 3. 隧道选型（先探可达性再选，别照抄教程）

| 方案 | 本机实测 | 备注 |
|---|---|---|
| cloudflared quick tunnel | **边缘不通**，走不了 | 教程默认选项，本网不行 |
| localhost.run（ssh 隧道） | ✓ 通，免安装免账号，**自带 HTTPS** | 首选；`ssh -T -R 80:localhost:<闸门口> nokey@localhost.run` |
| bore.pub | ✓ 通 | 纯 TCP，无 TLS（https 页面里做子请求会被拦） |
| ngrok | 边缘通，但需账号 token | 次选 |
| serveo.net / localtunnel.me | ✗ 不通 | — |

- 探法：`timeout 6 bash -c "echo > /dev/tcp/<host>/<port>"` + 服务站点 `curl -o /dev/null -w '%{http_code}'`。
- **URL 每次重连都变**（免费档）⇒ 只当过渡；终态是域名侧 frp/nginx 的稳定地址。
- 分工：源侧只交 **`host:port`（=只读闸门）+ 清单地址**；域名侧拿它做转发与打包。

## 4. 吞吐实测与选码率

| 通道 | 快照单张 | MJPEG 吞吐 |
|---|---|---|
| 公网隧道 | 35.7KB / 2.92s | **21~66 KB/s ⇒ 0.8~1.5 fps** |
| 闸门（局域网） | 0.00s | 497 KB/s ⇒ 10.3 fps |
| 直连 8791（基准） | — | 491 KB/s ⇒ 10.2 fps |

⇒ 代理本身零损耗；瓶颈全在中转。按"实测吞吐 ÷ 每帧字节"定 fps 与分辨率，**不要先承诺流畅再降**。
拼图流参数（`/wall.mjpg?w=&q=&fps=&layout=h|v`）：400/q60/2fps ≈ 56KB/s；560/q72 竖排单张 ≈ 66KB；
每格 4:3 信箱 + 底部 16px 标签条（`路名 · HH:MM:SS · 帧龄N.Ns · Nfps`）。

## 5. `/live.json` 清单（给对方照单接线）

```json
{"ok":true,"who":"<源机>视频源推流端","token":"<token>",
 "streams":{"三相机拼图":{"mjpg":"/wall.mjpg?k=…","single_frame":"/wall.jpg?k=…",
            "params":"w=400 q=60 fps=2 layout=h|v","bytes":"~28KB/帧, 2fps≈56KB/s"},
            "单路原始":{"arm":"/arm.mjpg?k=…"},"单张快照":{"arm":"/snapshot/arm.jpg?k=…"},
            "场景契约":"/scene.json?k=…"},
 "fps_now":{"arm":30.0},"禁止":"POST 一律 403; /ctl/*(真机动) /gen(触发拍照) /station /tap 永不外放"}
```

## 6. systemd 两个 unit（重启闸门不该换隧道 URL）

- 闸门：`Type=simple` + `Restart=always` + `StandardOutput=append:/var/log/...`，ExecStart 指向仓库里的 `tools/tunnel_proxy.py`。
- 隧道：`After=network-online.target` + **`Wants=`（软依赖）**，**绝不用 `Requires=`** —— 硬依赖会让"重启闸门"连带重启隧道，
  公网 URL 随之换掉，已发出的链接与已烧进 App 的地址全部失效（症状：`/wall.jpg` 稳定 503 而本地 200）。
- 排查"公网某路径 503 但本地 200"时，**第一步读隧道日志里的当前 URL**（`grep -oE 'https://[a-z0-9]+\.lhr\.life' /var/log/<隧道日志>`），
  确认下游用的是不是旧地址，再怀疑代码。
