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
- 交付: 飞书直接发 .apk 附件 (MEDIA:/path.apk), 手机提示未知来源→允许安装

## Pitfalls
- **App 黑屏 (手机有图但网页渲染异常)**: ①manifest 必须加 `android:hardwareAccelerated="true"` (WebGL 必需, 缺失时 WebView 3D 黑屏); ②`<uses-sdk android:minSdkVersion="24" android:targetSdkVersion="34">` 必须显式 (缺失 targetSdk 导致兼容问题); ③MainActivity 加 `onReceivedError` Toast + `onConsoleMessage` 日志 (黑屏时能定位是加载失败还是 JS 错误); ④WebGL 检测: 网页里 try/catch `new WebGLRenderer` 失败时显示原因而非静默黑屏。
- **华为 Mate30 若仍黑屏**: 检查系统 WebView 更新 (设置→应用→WebView), 或网页降级 Canvas 2D 渲染。
- **APK 极小(8KB) = 资源没打进去**: aapt2 link 失败被管道吞了。去掉管道重跑, 确认 app.apk ~18KB(含图标)。
- **无 res 目录 aapt2 compile 报错**: 先建 `res/values/strings.xml` (空 `<resources/>`)。
- 华为/安卓 10+ 安装第三方 APK 需用户手动允许「未知来源」, 这是手机侧操作, 提示即可。

## 相关文件
- `scripts/build_apk.sh` — 完整 7 步构建脚本 (改 PROJ/SDK 变量即用)
- `templates/MainActivity.java` — WebView 壳 Activity 模板
- `templates/AndroidManifest.xml` — 全屏 WebView manifest 模板
