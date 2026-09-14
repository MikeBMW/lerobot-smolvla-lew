#!/bin/bash
# 手动构建 WebView 壳 APK (无 gradle) — 改 PROJ/SDK 即用
# 前置: openjdk-17 + android-sdk (cmdline-tools + platforms;android-34 + build-tools;34.0.0)
set -e
SDK=/home/ubuntu/android-sdk
BT=$SDK/build-tools/34.0.0
PLATFORM=$SDK/platforms/android-34/android.jar
PROJ=/tmp/state3d_app          # ← 改成你的工程目录
OUT=$PROJ/build
rm -rf $OUT && mkdir -p $OUT/gen $OUT/obj $OUT/dex $OUT/apk

echo "=== 1. aapt2 编译资源 ==="
# 先保证 res/ 存在 (至少 values/strings.xml 含 <resources/>)
$BT/aapt2 compile --dir $PROJ/app/src/main/res -o $OUT/res.zip 2>/dev/null
ls -la $OUT/res.zip | awk '{print "res.zip: "$5/1024"KB"}'
# 链接 (含资源 + R.java); ⚠️ 不要管道到 grep 吞错误 — link 失败会静默丢资源
$BT/aapt2 link -o $OUT/apk/app.apk \
  -I $PLATFORM \
  --manifest $PROJ/app/src/main/AndroidManifest.xml \
  --java $OUT/gen \
  $OUT/res.zip
ls -la $OUT/apk/app.apk | awk '{print "app.apk: "$5/1024"KB"}'

echo "=== 2. javac 编译 ==="
javac -source 8 -target 8 -bootclasspath $PLATFORM \
  -d $OUT/obj \
  $PROJ/app/src/main/java/com/zmax/state3d/MainActivity.java

echo "=== 3. d8 转 dex ==="
$BT/d8 --release --lib $PLATFORM --output $OUT/dex \
  $(find $OUT/obj -name '*.class')

echo "=== 4. 打包 classes.dex 进 apk ==="
cd $OUT/dex && zip -q $OUT/apk/app.apk classes.dex

echo "=== 5. zipalign ==="
$BT/zipalign -f 4 $OUT/apk/app.apk $OUT/apk/app-aligned.apk

echo "=== 6. 生成 keystore + 签名 ==="
if [ ! -f $PROJ/release.keystore ]; then
  keytool -genkeypair -v -keystore $PROJ/release.keystore \
    -alias zmax -keyalg RSA -keysize 2048 -validity 10000 \
    -storepass zmax2026 -keypass zmax2026 -dname "CN=Z-MAX, OU=ZFCY, O=ZFCY, L=Shenzhen, ST=GD, C=CN"
fi
# ⚠️ 顺序: 先 zipalign 再 apksigner (反了签名失效)
$BT/apksigner sign --ks $PROJ/release.keystore --ks-pass pass:zmax2026 \
  --out $PROJ/ZMAX-State3D.apk $OUT/apk/app-aligned.apk

echo "=== 7. 完成 ==="
ls -la $PROJ/ZMAX-State3D.apk | awk '{print $5/1024/1024"MB", $NF}'
# 验证
$BT/aapt2 dump badging $PROJ/ZMAX-State3D.apk 2>/dev/null | grep -E '^package|launchable' | head -2
