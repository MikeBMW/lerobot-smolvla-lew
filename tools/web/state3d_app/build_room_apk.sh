#!/usr/bin/env bash
# 打包「Z-MAX 现场」(手机 APP · 人机在环) APK —— 纯 CLI, 无 Gradle
# 与既有 Z-MAX APK **同一个签名 keystore**, 但包名不同(com.zmax.room) ⇒ 可与现有 App 并存, 不用先卸载。
set -e
SDK=/home/ubuntu/android-sdk
BT=$SDK/build-tools/34.0.0
PLATFORM=$SDK/platforms/android-34/android.jar
SRC=/home/ubuntu/state3d_app
PROJ=$SRC/room
BUILD=$PROJ/build
OUT=$PROJ/ZMAX-Site.apk
cd "$PROJ"

echo "=== ① 资源/目录准备 ==="
mkdir -p src/main/res/values src/main/res/mipmap-mdpi src/main/res/mipmap-hdpi \
         src/main/res/mipmap-xhdpi src/main/res/mipmap-xxhdpi src/main/res/mipmap-xxxhdpi
printf '<resources>\n  <string name="app_name">Z-MAX 现场</string>\n</resources>\n' > src/main/res/values/strings.xml
for d in mdpi hdpi xhdpi xxhdpi xxxhdpi; do
  cp -f "$SRC/app/src/main/res/mipmap-$d/ic_launcher.png" "src/main/res/mipmap-$d/ic_launcher.png"
done
ls src/main/res/mipmap-*/ic_launcher.png | wc -l | sed 's/^/  图标数(需 5): /'

echo "=== ② aapt2 compile ==="
rm -rf "$BUILD"; mkdir -p "$BUILD/gen" "$BUILD/obj" "$BUILD/dex"
"$BT/aapt2" compile --dir src/main/res -o "$BUILD/res.zip"

echo "=== ③ aapt2 link (不带管道, 免得吞掉错误) ==="
"$BT/aapt2" link -o "$BUILD/app.apk" -I "$PLATFORM" \
  --manifest src/main/AndroidManifest.xml --java "$BUILD/gen" "$BUILD/res.zip"

echo "=== ④ javac ==="
javac -source 8 -target 8 -bootclasspath "$PLATFORM" -d "$BUILD/obj" \
  $(find src/main/java "$BUILD/gen" -name '*.java')

echo "=== ⑤ d8 ==="
"$BT/d8" --release --lib "$PLATFORM" --output "$BUILD/dex" $(find "$BUILD/obj" -name '*.class')

echo "=== ⑥ 组包 + 对齐 ==="
cp -f "$BUILD/app.apk" "$BUILD/unsigned.apk"
cd "$BUILD/dex" && zip -q "$BUILD/unsigned.apk" classes.dex && cd "$PROJ"
"$BT/zipalign" -f 4 "$BUILD/unsigned.apk" "$BUILD/aligned.apk"

echo "=== ⑦ 签名(复用 release.keystore) ==="
KS=$SRC/release.keystore
if [ -f "$OUT" ]; then cp -f "$OUT" "$BUILD/prev_$(basename "$OUT")"; fi   # 覆盖前留档
"$BT/apksigner" sign --ks "$KS" --ks-pass pass:zmax2026 --key-pass pass:zmax2026 \
  --out "$OUT" "$BUILD/aligned.apk"

echo "=== ⑧ 验证 ==="
"$BT/aapt2" dump badging "$OUT" | grep -E "^package|^application-label|launchable-activity" | sed 's/^/  /'
ls -la "$OUT" | awk '{print "  产物: "$5"B"}'
unzip -l "$OUT" | grep -cE 'classes\.dex|ic_launcher' | sed 's/^/  关键文件(应≥6): /'
echo -n "  烧进包里的地址: "; unzip -p "$OUT" classes.dex | strings | grep -o 'http://[0-9.]*:8791/room' | head -1
