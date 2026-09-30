# 交付 web：场景叠加版 APK（ZMAX-State3D.apk）— 待检查 → 发布

来源：静静（4060 工作端）· 2026-09-27 · 老倪口径：「你把场景叠加的apk发给web检查，让web发布」

---

## 1. 交付件

| 项 | 值 |
|---|---|
| 文件名 | `ZMAX-State3D.apk`（与 `ZMAX-3D-AOI.apk` 是同一个包，改名而已） |
| 大小 | 38096 B |
| sha256 | `00e59a99f5a6500daba93bd7edfbea4c28a70c14a1ea9945447371c633706076` |
| 包名 | `com.zmax.state3d.aoi` |
| 版本 | versionCode 1 / versionName 1.0 |
| minSdk / targetSdk | 24 / 34 |
| 签名 | Z-MAX `release2.keystore`（v1 + v2 + v3 三种方案全部校验通过） |
| 取件 | ① 飞书附件 ② 局域网 `http://10.163.146.78:8791/dl/ZMAX-State3D.apk` |

## 2. 这版比上一版多什么

桌面**两个独立入口**（各有自己的图标，互不影响）：

| 图标 | Activity | 打开 |
|---|---|---|
| Z-MAX 3D 全链 | `MainActivity` | `https://datadrive.world/state-3d.html` |
| **Z-MAX 场景叠加** | `OverlayActivity` | `http://10.163.146.78:8791/app` |

第二个就是老倪要的「场景叠加进 APP」：手机桌面直接点开，看的到双路原始画面 + 叠加了仿真/VLM/检测框的画面。

## 3. ★ 发布前必须先知道的一条（架构约束，不是 bug）

站点是 **HTTPS**。页面里直接取 `http://` 的 MJPEG 会被浏览器内核按**混合内容**拦死 —— 表现是**页面能开、画面永远黑**。
所以叠加页**必须由视频源那台机器（4060）自己用 http 提供**（同端口 = 同源），APP 用**顶层跳转**过去（顶层跳转不受混合内容限制）。

**代价：手机要和 4060 在同一局域网（产线 WiFi）。**

⇒ 如果 web 要**对外发布**（不在产线 WiFi 也能用），需要 web 侧补一条 HTTPS 通道：
把 4060 的 8791 反代到站点某个 https 路径，或把视频流改走 https/wss。
那时只需改 **`OverlayActivity.java` 第 28 行的 `OVERLAY_URL`** —— 全包唯一硬编码地址。

## 4. 检查项（命令可直接跑）

```bash
sha256sum ZMAX-State3D.apk                                              # 应等于上表
"$BT/aapt2" dump badging ZMAX-State3D.apk                               # 应有 2 个 launchable-activity
"$BT/apksigner" verify --min-sdk-version 21 --verbose ZMAX-State3D.apk  # v1/v2/v3 全 true
"$BT/zipalign" -c -v 4 ZMAX-State3D.apk                                 # 应 successful
```

⚠️ **apksigner 不带 `--min-sdk-version` 时会恒报 `v1: false`** —— 那是「minSdk 24 不需要 v1」，
**不是签名残缺**，别据此判包不合格（我踩过这个坑）。

## 5. 发布要做的两件事

**① APK 发布** —— 把 `ZMAX-State3D.apk` 挂到站点下载位（如 `/www/wwwroot/datadrive.world/dl/`）或你们的发布页。

**② 站点页更新**（这步只有 web 能做：4060 没有 ECS 免密，密码不落盘）
把 `tools/web/state-3d.html` 传到 `/www/wwwroot/datadrive.world/` 根目录，`chmod 644`。
这份页面新增了 `🧩 场景叠加` 按钮（点击顶层跳转到 4060 的 `/app`）。

> 不部署 ② 也不影响新图标可用：APK 里 `Z-MAX 场景叠加` 入口是**直连 4060** 的，装完即用。

## 5b. 三个 Z-MAX 手机 APP 对照（别发错包）

| APK | 包名 | 装完打开 | 用途 |
|---|---|---|---|
| **ZMAX-Live.apk** | `com.zmax.live` | **现场实况页（=叠加页）** | ★ 本次要发布的：所有活着的相机流 + 仿真/检测叠加 |
| ZMAX-State3D.apk | `com.zmax.state3d.aoi` | 桌面两个图标：3D 全链 / 场景叠加 | 状态空间 3D 页 + 叠加页 |
| ZMAX-Site.apk | `com.zmax.room` | 现场页（多路相机 + HIL 遥控） | 现场总览 + 人机在环 |

**ZMAX-Live.apk v1.1（2026-09-27 修）**：MainActivity 的候选口 =
`[http://10.163.146.78:8791/overlay, http://192.168.23.50:8791/overlay]`，**自动依次试** ——
手机在哪个网段都能连（旧版只写产线口 ⇒ 老倪手机走 WiFi 时打开是空白页 = "用不了"）。
成功的口记进 SharedPreferences，下次先用；全不通才提示，长按屏幕仍可手改地址。
两个口实测都通（HTTP 200）。

> 各包**当前** sha256/体积以**页面上的 APP 卡**为准（打包脚本每出一版就把哈希写回页面，
> 页面声明因此永远等于实际下发件）。别把哈希抄进这份文档 —— 重打包后会过期。

## 6. 源码

本目录（已入库，`git pull` 即可）：
`AndroidManifest.xml`（双 LAUNCHER 入口）/ `OverlayActivity.java`（68 行）/ `MainActivity.java` / `build_aoi.sh`（45 行）

真正在用的工程在 4060 的 `/home/ubuntu/state3d_app/app/`；本目录是**归档副本**，便于 web 侧评审与追溯。

## 7. 回执

检查完 / 发布完，回一句到群里（或走 `agent_hub` 命令台 8794），我这边好对齐版本号与站点状态。

> **ZMAX-Live.apk 的源码**在 `tools/app/live/`（`MainActivity.java` 双网自动切换 / manifest /
> `build_live_apk.sh`）。真正在用的工程在 4060 的 `/home/ubuntu/state3d_app/live/`。
