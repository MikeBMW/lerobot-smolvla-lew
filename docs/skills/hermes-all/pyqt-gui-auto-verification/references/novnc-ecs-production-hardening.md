# noVNC/x11vnc 生产加固 — ECS 公网 + nginx 前置 (2026-09-06 全踩过)

补 remote-desktop-x11vnc-novnc.md 与 websockify-broken-vnc-bridge.md 的**生产部署尾段**。
纯 WS bridge (自写 asyncio) 已跑通本地后, 走 ECS 公网还有四个必踩坑:

## 1. nginx 426 Upgrade Required (vnc.html 都打不开)
症状: 页面 curl 返回 **426** (不是 200), noVNC UI 起不来。
根因: 把整个 `location ^~ /novnc/` 都 proxy_pass 给纯 WS bridge → nginx 把**普通 GET
(vnc.html 静态页) 也当 WebSocket 升级**要求。旧 websockify 带 `--web` 同时服务静态文件所以
没这问题; 自写 bridge 只做 WS 代理 → 必须拆分。
修复: **静态文件 nginx 直服务, 只有 websockify 端点走代理**:
```nginx
location ^~ /novnc/ {
    alias /www/wwwroot/<site>/novnc/;     # 静态文件直出
    index vnc.html;
    try_files $uri $uri/ /novnc/vnc.html;
    location /novnc/websockify {           # 内嵌: 仅 WS 端点代理
        proxy_pass http://127.0.0.1:6080/websockify;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header Origin $http_origin;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```
另需根路径 `location = /websockify` (noVNC 默认连 `/websockify` 根, 不带 /novnc 前缀 — 旧文档
URL 若只给 vnc.html 不带参数, 浏览器默认 path=websockify 相对当前目录)。

## 2. Origin "multiple values" 400
症状: WS 握手 400 `invalid Origin header: multiple values` (websockets>=16 严格校验),
本地直连 bridge 带 Origin 却正常 → 断点在 nginx 转发。
根因: nginx HTTP/2→后端 HTTP/1.1 转换时 Origin 头可能多值/重复。
修复: bridge 侧 `origins=None` **不够** → nginx 侧显式归一化:
`proxy_set_header Origin $http_origin;` 才真正修好。
(注意 heredoc 写 nginx conf 时 `\$http_upgrade` 会被转义成字面 `\$` → 值变空 → 404; 用
不带转义的 heredoc 或落盘文件。)

## 3. 去密码流程 (老倪 "不要密码")
两层密码都要去:
- nginx: 删 `auth_basic "realm";` + `auth_basic_user_file ...;` 两行 → reload
- x11vnc: 改 `-nopw` 启动 (去掉 `-rfbauth ~/.vnc/zmax.pass`)
坑:
- ECS 无 htpasswd 命令 → 用 `openssl passwd -apr1 <pw>` 生成 hash 写 `zmax:$hash`
- **密码文件权限必须 644**: 600 root 时 nginx worker (www 用户) 读不了 →
  公网返回 **500 Internal Server Error** (error log: Permission denied), 不是 401!

## 4. 手机适配 (老倪手机操作)
noVNC URL 加参数: `?autoconnect=1&resize=scale&reconnect=1`
- autoconnect=1 打开即连; resize=scale 自动缩放适配手机屏; reconnect=1 断线重连
- 仍不缩放: 页面左侧 ⚙️ 设置 → Scaling Mode → **Local Scaling**
- noVNC 1.3 UI 是 ES module (`type="module"` src=app/ui.js) — 若静态资源 404 会整页白屏;
  验证所有 core/ app/ 资源 200 再交付

## 5. 服务端自测 (交付前, 别让用户当测试员)
见 websockify-broken-vnc-bridge.md 验证节 — RFB 首帧 + 安全类型两段都收到才算通;
只收到 RFB 首帧就宣称成功 = websockify 当年栽的误判。
额外: noVNC 页面资源逐个 curl 200 (vnc.html/app/ui.js/core/rfb.js/core/websock.js 等)。

## ECS 部署状态注记 (非长期事实)
- datadrive.world: systemd 服务 `vncbridge` (自写 asyncio bridge, Restart=always) 监听
  127.0.0.1:6080 → 127.0.0.1:5900 (reverse SSH 隧道 ← 本机 x11vnc)
- nginx extension: novnc.conf + novnc_root.conf (静态直服务 + WS 代理, 无 auth_basic)
- 隧道重建: 杀旧 `ssh -R 5900` 进程 → ECS 上清 5900 占用 (sshd 转发残留占端口, 新隧道
  `remote port forwarding failed` 就是它) → `sshpass ssh -N -R 5900:localhost:5900 root@datadrive.world`
- 老倪"不要密码"已落地: nginx 无 basic auth + x11vnc -nopw, 打开 URL 即连
