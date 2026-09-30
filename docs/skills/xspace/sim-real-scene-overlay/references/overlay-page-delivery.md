# 叠加页"改了没生效"与交付链路取证（2026-09-27 实测）

## ⚠️ 最大陷阱: `/overlay` 发的是代码里写死的旧 HTML 副本
症状: 改了 `tools/web/scene-overlay.html`、刷新页面毫无变化。
真因: `cam_live_stream.py` 把那份 HTML **内嵌在 py 字符串里**（老字号），路由 `/overlay` 发内嵌副本，
      后面那条从 `tools/web/` 热读的 elif 被抢先命中成了**死代码**（`/app` 同病）。
判据: `curl -s http://127.0.0.1:8791/overlay | wc -c` 与 `wc -c tools/web/scene-overlay.html`
      **对不上**就是命中了内嵌副本（实测 9239B vs 25545B）。
修法: 让 `/overlay /overlay.html /live /scene /app /app.html /m` **全部按 mtime 热读同一份真源文件**，
      然后按 PID 精确重启 8791 服务（服务无 systemd 监管，必须手工重启并核 `/stats` 各路 fps 恢复、
      顺手确认 `/room` 没被带坏）。
**纪律**: 交付前先比"页面服务字节数 vs 磁盘文件字节数"，相等才算改对了。

## 取证的层次（别停在“已上传”）
1. 页面: `curl -o /dev/null -w '%{http_code} %{size_download}'` 对**局域网 8791** 和**公网 ECS** 各一遍。
2. APK 字节: 从**公网 URL** 下载回来 `sha256sum`，与**本地产物**逐字节比（不看页面上写的串）。
3. APK 体检: `aapt2 dump badging`（package/label/launchable-activity）+
   `apksigner verify --min-sdk-version 21 --verbose`（v1/v2/v3 全 true）+ `zipalign -c -v 4`。
4. 真浏览器（CDP）打开页面看每格是否都有真图、控制台是否 0 报错 —— 只看 curl 200 不够，
   图上可能仍是黑的。
5. 叠加真源: 读 `/scene.json` 的 `_overlay_info.<路>` 看 `drawn` 与 `origins`(sim/det/vlm 各几框)。

## 叠加的业务约束（实测行为，页面要如实反映）
- **仿真框只对做过手眼标定的那一路成立**（本次=臂上 D405）。笔记本内置/MAXHUB 点「仿真投影」会被
  **服务端如实拒绝** —— 这是对的，别为了“每格都有框”去假造。
- 点页面按钮真跑「仿真投影」会**重建整份 overlay_spec.json** ⇒ 会把其它相机那一路已有的
  大模型框冲掉（实测 local2 的 5 个 VLM 框被冲成 0）。要保留就分路存，别整份覆盖。
- 死掉的路（如 depth）按**运行时探测**（`/stats` 里 fps>0 才算活）渲染，未上线就在页面上如实标
  「未上线（不上屏、不当活的用）」，不写死成活的。

## 页面/APP 的地址与连接预算
- 相机是 http MJPEG ⇒ https 页里嵌会被内核按**混合内容**拦死（页面能开、画面永远黑，
  `usesCleartextTraffic`+`MIXED_CONTENT_ALWAYS_ALLOW` 也救不了）⇒ **实况页只能由工位机自己 http 提供**，
  APP 顶层直接 loadUrl 那个 http 页；公网页只做交付/安装说明，不放实时画面。
- 手机只有 **6 条** HTTP/1.1 连接 ⇒ 全看模式用**串行轮询单帧快照**，单看才开 1 路 MJPEG，
  永不同时开 N 路 MJPEG。
- APK 内**烧两个网口地址自动依次试**（如 192.168.23.50 与 10.163.146.78），IP 变了不用重装。
