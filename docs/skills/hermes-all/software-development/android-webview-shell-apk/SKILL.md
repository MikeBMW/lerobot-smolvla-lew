---
name: android-webview-shell-apk
description: Use when 要把网页包成安卓 APK 装手机 (WebView 套壳), 或需命令行打 APK 无 Gradle.
---

# Android WebView 套壳 APK (纯 CLI, 无 Gradle/Android Studio)

把一个 URL (如 datadrive.world 的 3D 页面) 包成全屏安卓 App。用户场景: 老倪手机(华为 Mate30) 装「Z-MAX 状态空间3D」看 3D 模型。更新网页内容 = App 自动更新, 无需重装。

## 环境准备 (一次性)
```bash
sudo apt-get install -y openjdk-17-jdk-headless
mkdir -p /home/ubuntu/android-sdk/cmdline-tools && cd /tmp
curl -sL -o android-cmd.zip 'https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip'
cd /home/ubuntu/android-sdk && unzip -q /tmp/android-cmd.zip -d cmdline-tools/
mv cmdline-tools/cmdline-tools cmdline-tools/latest
yes | cmdline-tools/latest/bin/sdkmanager --sdk_root=/home/ubuntu/android-sdk \
  "platform-tools" "platforms;android-34" "build-tools;34.0.0"
```
关键路径: `BT=$SDK/build-tools/34.0.0`, `PLATFORM=$SDK/platforms/android-34/android.jar`

## 工程骨架
```
app/src/main/AndroidManifest.xml
app/src/main/java/<pkg>/MainActivity.java   (包名如 com.zmax.state3d)
app/src/main/res/mipmap-{mdpi,hdpi,xhdpi,xxhdpi,xxxhdpi}/ic_launcher.png
```

**Manifest 要点**:
- `package=com.zmax.state3d` + `versionCode/versionName`
- 权限: `INTERNET` + `ACCESS_NETWORK_STATE`
- `<application android:label="..." android:icon="@mipmap/ic_launcher"
   android:usesCleartextTraffic="true"
   android:theme="@android:style/Theme.NoTitleBar.Fullscreen">` (全屏无标题)
- activity: `android:exported="true"` + `configChanges="orientation|screenSize|keyboardHidden|screenLayout|smallestScreenSize|uiMode"` (转屏不重建)

**MainActivity 要点**: 程序化 new WebView(不走 XML 布局省资源), setContentView(webView);
WebSettings: `setJavaScriptEnabled(true)`, `setDomStorageEnabled(true)`, `setMediaPlaybackRequiresUserGesture(false)`;
`setWebViewClient(new WebViewClient())` + `setWebChromeClient(new WebChromeClient())`;
`getWindow().addFlags(FLAG_KEEP_SCREEN_ON)`; loadUrl("https://..."); onBackPressed 里 canGoBack→goBack。

**图标**: PIL 生成 192px 主图 → resize 出 5 密度(48/72/96/144/192)。manifest 引用 `@mipmap/ic_launcher` 需各密度文件齐全, 否则 aapt2 link 报资源缺失。

## 构建 (见 scripts/build_apk.sh, 7 步)
1. `aapt2 compile --dir res -o res.zip` (先确保 res/ 存在, 至少 values/strings.xml)
2. `aapt2 link -o app.apk -I $PLATFORM --manifest AndroidManifest.xml --java gen/ res.zip`
   ⚠️ 必须带 `--java gen/` 且**不能把输出管道到 grep 吞掉错误** (否则 link 静默失败、资源丢失、APK 只剩 8-28KB)
3. `javac -source 8 -target 8 -bootclasspath $PLATFORM -d obj/ MainActivity.java`
4. `d8 --release --lib $PLATFORM --output dex/ $(find obj -name '*.class')`
5. `cd dex && zip -q app.apk classes.dex`
6. `zipalign -f 4 app.apk app-aligned.apk`
7. `keytool -genkeypair -keystore release.keystore -alias zmax -keyalg RSA -keysize 2048 -validity 10000 -storepass ...` 一次生成后复用
   `apksigner sign --ks release.keystore --ks-pass pass:... --out Final.apk app-aligned.apk`
   ⚠️ 顺序: 先 zipalign 再 apksigner (反向会导致签名失效)

## 验证
- `aapt2 dump badging Final.apk` → 应见 package/launchable-activity/application-icon
- `unzip -l` → 应含 classes.dex + 各密度 png + resources.arsc (纯 WebView 壳 ~28KB 正常)
- **签名校验必须显式给 minSdk**: `apksigner verify --min-sdk-version 21 --verbose Final.apk`。
  它只校验"该 minSdk 需要的方案" —— manifest 里 minSdk≥24 而又不传这个参数时, **v1 恒报 `false`**,
  那是"不需要 v1"而**不是签名残缺**(据此以为签名坏了会白查一整轮)。要三方案全绿就在签名时显式
  `--v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled true`。
- 交付: 飞书直接发 .apk 附件 (MEDIA:/path.apk), 手机提示未知来源→允许安装

## 加第二个桌面入口（同 APK 两个图标，不用新建工程）
常见需求："把这个新功能加到 APP"，但新页面在另一台机器/另一个域名上。
- manifest 里再加一个 `<activity>`：自己的 `android:label`（桌面显示名）+ `android:icon`
  （`@mipmap/ic_xxx`，**5 个密度 png 都要有**，缺一个 aapt2 link 报资源缺失）+ 同样的
  `MAIN`/`LAUNCHER` intent-filter + 同样的 `configChanges` + `exported="true"`。
- 构建脚本的 `javac` 必须把**两个 .java 都列上**（只编一个 ⇒ dex 里没有第二个类，装出来点不开）。
- 签名 keystore **复用同一个**（换 keystore ⇒ 手机认为是另一个 App，覆盖安装失败）。
- 验收：`aapt2 dump badging` 要列出**两条** `launchable-activity`；
  `unzip -p apk classes.dex | strings | grep 你的URL` 要能看到新入口的地址，
  且**旧入口的地址仍在**（证明没把原有入口打坏）。
- 想覆盖旧包先 `cp` 留档再签（`set -e` 下用 `if [ -f x ]; then …; fi`，`[ -f x ] && cp` 会中断脚本）。

## 手机 App 里要放**局域网 http 相机流/接口**时 (2026-09-27 实测, 做了「Z-MAX 现场」)
- 症状: 页面能开、画面永远黑 —— 外层页面是 https, 里面嵌的 http MJPEG 被混合内容拦死
  (`usesCleartextTraffic` + `setMixedContentMode(MIXED_CONTENT_ALWAYS_ALLOW)` 都设了也没用,
  内核按**页面源**判: https 页不许发 http 子请求)。
- 定式: **另开一个入口, 顶层直接加载那个 http 页**(页面与数据同源) —— 这次就是这条路:
  新工程用**新包名**(com.zmax.room) + **同一个 keystore**(⇒ 与现有 App **并存**, 用户不用先卸载,
  也不会把旧入口打坏) + activity 竖屏/全屏/常亮 + `loadUrl("http://<工位机IP>:8791/room")`。
- **地址别写死死 —— 多网段要自动切换, 而不是只写一个 IP**。同一台机器常有两个网口
  (WiFi 10.163.x / 产线 192.168.x), 壳里写死其中一个 ⇒ 手机在另一个网段打开就是**空白页**,
  用户只会说「这 app 用不了」, 而包体检五道全过 —— **别再从包上找**。
  定式: `CANDIDATES[]` 依次试(上次成功的口 → WiFi 口 → 产线口); 成功时把该 URL 存
  SharedPreferences, 下次先用它; 全不通才 Toast 提示 + 长按弹 AlertDialog 手改。
  ⚠️ **`onPageFinished` 必须排除「刚报错的那个 URL」**: 有的 WebView 版本主框架加载失败后仍会回调
  `onPageFinished`, 在那里直接置 `landed=true` 会把错误页当成功 ⇒ **自动换口静默失效**。
  记一个 `lastErrUrl`, 在 `onPageFinished(url)` 里 `if (url.equals(lastErrUrl)) return;`。
  ⚠️ **每个候选口都要实测能通**(`curl -s -o /dev/null -w '%{http_code}' <口>`): 一个打不通的「备用」
  比没有备用更糟 —— 用户以为有兜底。
  ⚠️ **易失地址不能当唯一地址**：内网穿透的公网 URL 每次重连都会变（免费档），烧进包里 ⇒ 隧道一重启 App 就是空白页，
  而且**查包查不出问题**（地址确实在包里、签名也对）。定式（优先级）：**固定清单发现 > 稳定域名 > 内网口 > 易失地址**。
  · **固定清单发现（唯一能免重打包的做法）**：让 App 先读对方**固定域名**下的一个小清单（如 `/live.json`），
    里面写着当前流地址 ⇒ 易失地址变了只需发布方更新清单，App 永不用重装。发布方只在地址变化/心跳超时时推。
  · 易失地址只做最后一个兑底；候选表按「稳定 → 内网 → 易失」排；若只能拿它当唯一地址，地址轮换后
    必须重建包并把新哈希写回页面，同时告诉用户「长按屏幕可手改地址」。
  · 手机在蜂窝网时页面要落到**窄带档位**（多格同开要上百 KB/s，窄隧道上只会看起来像静态图）——
    带宽预算与档位选择见 `low-latency-camera-streaming` 的铁律 4。
  ⚠️ **构建脚本自己的断言要覆盖所有协议**：只 grep `http://[0-9.]*:<端口>` 的检查**看不见 https 候选**
  （实测报「候选口 2（期望 2）」而包里其实有 3 个地址）⇒ 漏烧地址它也报正常。改成逐条校验**已知主机名**，
  或统一用 `grep -oE 'https?://[^"]*(<端口>|overlay)'`。
  ⚠️ **叠加页自身的四个生成按钮在公网侧会被 403 是故意的**：它们会真触发拍照/大模型调用，
  只读闸门永久拒绝；交付时要把这条告诉用户（否则他会以为 App 坏了）。
  主框架加载失败用 `onReceivedError(WebView, WebResourceRequest, WebResourceError)` + `isForMainFrame()`
  弹 Toast(否则素材失败也会刷屏); `onReceivedSslError` 里 `h.proceed()` 兼容内网自签。
- 验收(缺一不可): ①`aapt2 dump badging` 看 package/label/launchable-activity;
  ②`unzip -p app.apk classes.dex | strings | grep -o 'http://[0-9.]*:8791/room'` —— **证明地址真烧进包里**;
  ③交付的下载链接**回读 sha256** 与本地构建逐字节一致(别只说“已上传”)。
- 页面侧配套(手机 WebView/浏览器只有 **6 条** HTTP/1.1 连接): 多路相机页**永远只开 1 条取流**
  (全看=串行轮询单帧快照 `fetch`→blob, 单看=1 路 MJPEG) + 1 条状态轮询; 同时开 6 路 MJPEG 会把
  连接吃干、整页卡死(实测过的老坑)。

## 交付给人装 —— 用户说「这个 app 我装不了」时的排查顺序
1. **先查"他手上的那条路径有没有入口", 别接着查包**: `grep -nE '下载|安装|apk' <他打开的那个页面>`。
   零命中 = 真卡点就在这儿(实测: 包五道体检全过、下发字节与产物逐字节一致, 而页面里一个"装"字都没有,
   给他链接也走不通流程)。**这一步零成本, 必须先做。**
2. 包体检(每条都能读出结论, 别靠感觉):
   ```bash
   $BT/aapt2 dump badging A.apk | grep -E "^package|sdkVersion|targetSdk|launchable"
   $BT/aapt2 dump xmltree --file AndroidManifest.xml A.apk | grep -E "exported|testOnly"  # 缺 exported / 带 testOnly = 直接拒装
   $BT/apksigner verify --min-sdk-version 21 --verbose A.apk   # v1/v2/v3 逐条都要 true
   $BT/zipalign -c -v 4 A.apk                                  # 4 字节对齐
   unzip -v A.apk | grep resources.arsc                        # targetSdk≥30 必须 Stored(未压缩), 压了就是"解析包错误"
   curl -s <下载URL> -o /tmp/x.apk && sha256sum /tmp/x.apk /path/产物.apk   # 下发字节与磁盘产物一致
   ```
3. 真因排序: **页面无安装入口** > **纯净模式/外部来源没放开** > **同包名残留**(报"应用未安装" ⇒ 先卸载;
   把 versionCode 升一版即可覆盖) > **下载没下完**(报"解析包错误" ⇒ 用哈希核对)。
4. 把安装流程**做进他已经在看的那个页面**(顶部一个 `📲 装 APP` 按钮 + 展开卡片): 下载按钮(指向 `/dl/xxx.apk`)
   + OEM 放开步骤 + **报错原文→做法**对照表 + sha256 校验串; 再加 `?inst=1|#install` 直开参数,
   这样"怎么装"可以一键转给别人。按钮用 inline `onclick` 就地 toggle, **别调页面底部才定义的函数**
   (声明前调用 = TDZ/未定义 ⇒ 整页脚本静默死)。
   卡片默认藏着的话再加一条: **手机浏览器打开时自动展开一次**(用户拿手机看这页, 就该直接看到下载入口);
   UA 判据 = 手机(`/Android|iPhone|iPad|Mobile/`)且**不在 App 里** —— App 内 WebView 的 UA 带 `wv`,
   看到 `wv` 就不展开(免得已经装过的人每次开都被弹), 展开过一次用 `sessionStorage` 记住。
   UA 分支没法真机跑时, 用 node 把三段真实 UA(桌面 Chrome / 安卓 Chrome / 安卓 WebView)过一遍真值表,
   几秒钟就能证明分支判对 —— 比"应该没问题"强。
5. **让构建脚本把产物 sha256/体积写回页面**(占位符 `__APK_SHA256__`/`__APK_SIZE__`): 页面上的校验串与本次
   产物强一致 ⇒ 页面不可能说谎; 手工填哈希的页面下次重打包就变成假信息。
6. 还装不上就问**报错原文**("应用未安装"/"解析包错误"/"已阻止安装" 三种做法完全不同), 比再打一版便宜。

## Pitfalls
- **App 黑屏 (手机有图但网页渲染异常)**: ①manifest 必须加 `android:hardwareAccelerated="true"` (WebGL 必需, 缺失时 WebView 3D 黑屏); ②`<uses-sdk android:minSdkVersion="24" android:targetSdkVersion="34">` 必须显式 (缺失 targetSdk 导致兼容问题); ③MainActivity 加 `onReceivedError` Toast + `onConsoleMessage` 日志 (黑屏时能定位是加载失败还是 JS 错误); ④WebGL 检测: 网页里 try/catch `new WebGLRenderer` 失败时显示原因而非静默黑屏。
- **华为 Mate30 若仍黑屏**: 检查系统 WebView 更新 (设置→应用→WebView), 或网页降级 Canvas 2D 渲染。
- **APK 极小(8KB) = 资源没打进去**: aapt2 link 失败被管道吞了。去掉管道重跑, 确认 app.apk ~18KB(含图标)。
- **无 res 目录 aapt2 compile 报错**: 先建 `res/values/strings.xml` (空 `<resources/>`)。
- **华为/鸿蒙 装不上多半不是包的问题**: ①系统「纯净模式」开着 ⇒ 只让装应用市场的包
  (设置→安全→更多安全设置→**关闭纯净模式**); ②同页「安装外部来源应用」要给浏览器/文件管理放开;
  ③风险提示要选「继续安装」。**这三步要写进交付页面**(见「交付给人装」章), 别只在会话里口头说。
- **页面取 http 视频流/接口而 App 页面是 https ⇒ 混合内容被拦死**(页面能开、画面永远黑)。
  两条路: ①让那个页面也由 http 源提供、App 顶层跳转过去; ②页面与数据同源。
  manifest `usesCleartextTraffic="true"` + `setMixedContentMode(MIXED_CONTENT_ALWAYS_ALLOW)` 是前提。

## 相关文件
- `scripts/build_apk.sh` — 完整 7 步构建脚本 (改 PROJ/SDK 变量即用)
- `references/signing-keystore-mismatch.md` — 签名/keystore 身份问题, 以及**装不上时的全项体检与 apksigner 报数怎么读**
- `templates/MainActivity.java` — WebView 壳 Activity 模板
- `templates/AndroidManifest.xml` — 全屏 WebView manifest 模板
