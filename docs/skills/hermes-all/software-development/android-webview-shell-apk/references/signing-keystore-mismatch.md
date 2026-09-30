# 签名不一致 / keystore 丢失 / 新旧应用并存 — 2026-09-08 实测

## 症状
用户装新版 APK 报「更新包与已安装的包签名不一致, 安装失败」。

## 根因
APK 签名证书 (release.keystore) 决定应用身份。旧 v1.1 用旧 keystore 签名; 工程放 /tmp
被清理后 keystore 丢失 → 新打包用新生成的 keystore → 签名不同 → Android 禁止覆盖安装
(不同签名不能更新同一包名)。

## 解法 (二选一, 先问用户接受哪个)
1. **卸载旧应用再装新包** — 纯 WebView 壳无本地数据, 卸载零损失。最干净。
2. **换新包名 + 新应用名 = 新旧并存** — 用户不想删旧应用时用。改:
   - Manifest: `package="com.zmax.state3d"` → `com.zmax.state3d.aoi`; activity
     `android:name="com.zmax.state3d.aoi.MainActivity"` (全限定名); `android:label` 改名
     (桌面图标与旧版并列, 不冲突)。
   - MainActivity.java 移到 `app/src/main/java/com/zmax/state3d/aoi/` + 首行 package 改。
   - 换包名 = 全新应用, 可用新 keystore 签名 (与旧签名无关)。

## 铁律
- **keystore + APK 工程放持久目录** (如 ~/state3d_app/), 绝不放 /tmp。
- build_apk.sh 模板的 `PROJ=/tmp/state3d_app` 是坑 — 复制脚本后先改 PROJ 再构建。
- 先 zipalign 再 apksigner (反向签名失效); 图标 5 密度 (mipmap-mdpi..xxxhdpi) 齐全否则
  aapt2 link 报资源缺失。
- 验证: `aapt2 dump badging` 看 package/launchable-activity/application-label 三项确认
  包名与桌面名正确。

## 装不上 ⇒ 全项体检, 以及 apksigner 报数怎么读

用户说"装不了"时, **先把包体检完再动手改**. 六项检查各自的结论:

| 检查 | 命令 | 结论 |
|---|---|---|
| 身份/版本 | `aapt2 dump badging` | package / versionCode / versionName / label / minSdk / targetSdk |
| 组件合规 | `aapt2 dump xmltree --file AndroidManifest.xml` | 缺 `android:exported`(targetSdk≥31) 或带 `testOnly` ⇒ 直接拒装 |
| 签名 | `apksigner verify --min-sdk-version 21 --verbose` | v1 / v2 / v3 逐条 |
| 对齐 | `zipalign -c -v 4` | 必须 successful |
| 资源布局 | `unzip -v` 看 resources.arsc | targetSdk≥30 必须 **Stored**(未压缩); 压了 ⇒ "解析包错误" |
| 下发一致 | 从下载 URL 回读 `sha256sum` | 与磁盘产物逐字节一致 |

**最容易踩的读报数坑**: `apksigner verify --verbose` **不带 `--min-sdk-version`** 时, 若 manifest 的 minSdk≥24,
它会打印 `Verified using v1 scheme (JAR signing): false` —— 含义是"该 minSdk 不需要 v1, 所以没校验",
**不是签名残缺, 也不影响安装**。想确认 v1 到底好不好, 加 `--min-sdk-version 21` 复验。
(曾据这一行断定"签名残缺导致装不上", 白查一轮; 真正的卡点是交付页面里根本没有安装入口。)

**签名一致 ≠ 能装**: 包合格只说明"包没问题"。装不上还要看 ①交付路径上有没有安装入口
②OEM 是否拦(华为/鸿蒙 纯净模式、安装外部来源应用) ③同包名残留(报 "应用未安装" ⇒ 先卸载,
versionCode 升一版可覆盖) ④下载是否完整(报 "解析包错误" ⇒ 用 sha256 核对)。
