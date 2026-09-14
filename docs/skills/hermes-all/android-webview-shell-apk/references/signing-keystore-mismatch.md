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
