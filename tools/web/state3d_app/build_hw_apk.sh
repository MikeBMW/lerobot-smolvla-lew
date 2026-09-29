#!/usr/bin/env bash
# 打包 Z-MAX 硬件监控 APK（纯 CLI，无 Gradle）
set -e
SDK=/home/ubuntu/android-sdk
BT=$SDK/build-tools/34.0.0
PLATFORM=$SDK/platforms/android-34/android.jar
PROJ=/home/ubuntu/state3d_app/hw
SRC=/home/ubuntu/state3d_app
BUILD=$PROJ/build
cd "$PROJ"

echo "=== ① 准备资源目录 ==="
mkdir -p src/main/res/values src/main/res/mipmap-mdpi src/main/res/mipmap-hdpi \
         src/main/res/mipmap-xhdpi src/main/res/mipmap-xxhdpi src/main/res/mipmap-xxxhdpi
mkdir -p src/main/assets
cp -f /home/ubuntu/state3d_app/app/src/main/assets/index.html src/main/assets/index.html
[ -f src/main/res/values/strings.xml ] || printf '<resources>\n  <string name="app_name">Z-MAX 硬件</string>\n</resources>\n' > src/main/res/values/strings.xml

echo "=== ② 图标（复用既有工程的 5 个密度）==="
for d in mdpi hdpi xhdpi xxhdpi xxxhdpi; do
  if [ -f "$SRC/app/src/main/res/mipmap-$d/ic_launcher.png" ]; then
    cp -f "$SRC/app/src/main/res/mipmap-$d/ic_launcher.png" "src/main/res/mipmap-$d/ic_launcher.png"
  fi
done
ls src/main/res/mipmap-*/ic_launcher.png 2>/dev/null | wc -l | sed 's/^/  图标数: /'

echo "=== ③ aapt2 compile ==="
rm -rf "$BUILD"; mkdir -p "$BUILD/gen" "$BUILD/obj" "$BUILD/dex"
"$BT/aapt2" compile --dir src/main/res -o "$BUILD/res.zip"

echo "=== ④ aapt2 link ==="
"$BT/aapt2" link -o "$BUILD/app.apk" -I "$PLATFORM" \
  --manifest src/main/AndroidManifest.xml --java "$BUILD/gen" \
  -A src/main/assets "$BUILD/res.zip"

echo "=== ⑤ javac ==="
"$BT/../javac" -version >/dev/null 2>&1 || true
javac -source 8 -target 8 -bootclasspath "$PLATFORM" -d "$BUILD/obj" \
  $(find src/main/java "$BUILD/gen" -name '*.java') 2>&1 | grep -v '^Note:' | head -5 || true

echo "=== ⑥ d8 ==="
"$BT/d8" --release --lib "$PLATFORM" --output "$BUILD/dex" $(find "$BUILD/obj" -name '*.class')

echo "=== ⑦ 组包 + 对齐 ==="
cp -f "$BUILD/app.apk" "$BUILD/unsigned.apk"
cd "$BUILD/dex" && zip -q "$BUILD/unsigned.apk" classes.dex && cd "$PROJ"
"$BT/zipalign" -f 4 "$BUILD/unsigned.apk" "$BUILD/aligned.apk"

echo "=== ⑧ 签名 ==="
KS=$SRC/release.keystore
if [ ! -f "$KS" ]; then
  keytool -genkeypair -keystore "$KS" -alias zmax -keyalg RSA -keysize 2048 -validity 10000 \
    -storepass zmax2026 -keypass zmax2026 -dname "CN=ZMAX,OU=Robot,O=ZMAX,L=SZ,ST=GD,C=CN"
fi
"$BT/apksigner" sign --ks "$KS" --ks-pass pass:zmax2026 --key-pass pass:zmax2026 \
  --out "$PROJ/ZMAX-Hardware.apk" "$BUILD/aligned.apk"

echo "=== ⑨ 验证 ==="
"$BT/aapt2" dump badging "$PROJ/ZMAX-Hardware.apk" | head -3
ls -la "$PROJ/ZMAX-Hardware.apk" | awk '{print "  产物: "$5"B"}'
unzip -l "$PROJ/ZMAX-Hardware.apk" | grep -cE 'classes.dex|ic_launcher' | sed 's/^/  关键文件: /'
unzip -l "$PROJ/ZMAX-Hardware.apk" | grep -c 'assets/index.html' | sed 's/^/  内嵌页面: /'
