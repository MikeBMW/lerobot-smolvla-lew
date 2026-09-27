# 📱 Z-MAX 实况 (com.zmax.live) — 交付与复现 (2026-09-27)

老倪口径：把「场景叠加 + 所有视频流」做成手机可用的现场控制页，打包成安卓 APK，发布到 ECS 并给下载链接。

## 交付件

| 项 | 值 |
|---|---|
| 实况页（局域网）| `http://192.168.23.50:8791/overlay`（真源 = `tools/web/scene-overlay.html`，改完**不用重启**服务）|
| 公网交付页 | `https://datadrive.world/zmax-live.html`（首页已挂「📱 现场实况」入口）|
| APK（公网）| `https://datadrive.world/dl/ZMAX-Live.apk` |
| APK（局域网）| `http://192.168.23.50:8791/dl/ZMAX-Live.apk`（页面内「📲 装 APP」也有入口）|
| 包名 / 标签 | `com.zmax.live` / **Z-MAX 实况** / launchable-activity `com.zmax.live.MainActivity` |
| 签名 | 复用 `state3d_app/release.keystore`（与「Z-MAX 现场」同一把钥匙），v1+v2+v3 全绿 |
| 顶层加载 | `http://192.168.23.50:8791/overlay`（**http 同源**，不越混合内容红线）；长按屏幕可改地址 |

## 工程与构建

```
src/main/AndroidManifest.xml                      # com.zmax.live · 竖屏 · 全屏 · usesCleartextTraffic
src/main/java/com/zmax/live/MainActivity.java     # WebView 壳(顶层 http) + 长按改地址(SharedPreferences)
tools/app/live/build_live_apk.sh                  # 7 步纯 CLI 构建(无 Gradle) → 投递 /dl/ + 回写页面 sha256
```

**真正的构建工程在 `/home/ubuntu/state3d_app/live/`**；本目录（`tools/app/live/`）是归档副本 + 构建脚本。
脚本会自动：① 编译链接签名 ② apksigner(带 `--min-sdk-version 21`) 三方案校验 ③ zipalign 校验
④ 投递到 `tools/web/dl/` ⑤ 把 sha256/体积写回 `tools/web/scene-overlay.html`（页面校验串与产物强一致）。

```bash
bash tools/app/live/build_live_apk.sh
ZMAX_ECS_PW='<密码>' python tools/deploy_zmax_live.py     # 发布公网交付页 + APK, 并回读逐字节核对
```

## 页面侧硬纪律（实测）

1. **手机只有 6 条 HTTP/1.1 连接** ⇒ 全看 = 全局 **1 条**串行取帧（fetch→blob），单看 = **1 条** MJPEG；
   永不同时开多路 MJPEG（会把连接吃干、整页卡死，按钮也点不动）。
2. **https 页面里嵌 http MJPEG 会被内核按页面源拦死**（页面能开、画面永远黑，`usesCleartextTraffic`
   也救不了）⇒ 页面必须由工位机自己 http 提供，App 顶层直接 loadUrl。
3. **在线判据用源侧 fps**（`/stats` 的 `fps>0.1`），**不写死哪几路是活的**；掉线的路如实标「未上线、
   不上屏」，掉线提示每次轮询都重绘（只在瓦片重建时写会被下一轮清空擦掉 —— 踩过）。
4. 每格必须标 **帧龄 + 拍照时间**（拍照时间 = 本机时钟 − 帧龄），导出 CSV/JSON 也带这两列。
5. **服务路由坑**：`/app` 曾被 room.html 那条分支抢先命中（死代码），`/overlay` 发的是 py 内嵌旧副本
   ⇒ 改 html 不生效。现在 `/overlay` `/overlay.html` `/live` `/scene` `/app` `/app.html` `/m` 全部发
   `tools/web/scene-overlay.html`（按 mtime 热读），`/room` 仍发 room.html。
