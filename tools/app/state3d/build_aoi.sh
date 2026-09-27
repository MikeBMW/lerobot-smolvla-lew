#!/bin/bash
# 重打包 (新包名 com.zmax.state3d.aoi, 新应用名)
set -e
SDK=/home/ubuntu/android-sdk
BT=$SDK/build-tools/34.0.0
PLATFORM=$SDK/platforms/android-34/android.jar
PROJ=/home/ubuntu/state3d_app
OUT=$PROJ/build
rm -rf $OUT && mkdir -p $OUT/gen $OUT/obj $OUT/dex $OUT/apk

echo "=== 1. aapt2 === (仅编译新包名 res, 引用 @mipmap 图标)"
$BT/aapt2 compile --dir $PROJ/app/src/main/res -o $OUT/res.zip 2>/dev/null
$BT/aapt2 link -o $OUT/apk/app.apk -I $PLATFORM \
  --manifest $PROJ/app/src/main/AndroidManifest.xml --java $OUT/gen $OUT/res.zip

echo "=== 2. javac (aoi 包: 3D 全链 + 🧩场景叠加 两个入口) ==="
javac -source 8 -target 8 -bootclasspath $PLATFORM -d $OUT/obj \
  $PROJ/app/src/main/java/com/zmax/state3d/aoi/MainActivity.java \
  $PROJ/app/src/main/java/com/zmax/state3d/aoi/OverlayActivity.java

echo "=== 3. d8 ==="
$BT/d8 --release --lib $PLATFORM --output $OUT/dex $(find $OUT/obj -name '*.class')

echo "=== 4. dex 入 apk ==="
cd $OUT/dex && zip -q $OUT/apk/app.apk classes.dex

echo "=== 5. zipalign ==="
$BT/zipalign -f 4 $OUT/apk/app.apk $OUT/apk/app-aligned.apk

echo "=== 6. 签名 (新 keystore) ==="
# 旧包先留档 (改坏可回退); 用 if 而不是 `[ -f x ] && cp` —— set -e 下后者会直接中断脚本
if [ -f $PROJ/ZMAX-3D-AOI.apk ]; then cp -f $PROJ/ZMAX-3D-AOI.apk $OUT/prev_ZMAX-3D-AOI.apk; fi
if [ ! -f $PROJ/release2.keystore ]; then
  keytool -genkeypair -v -keystore $PROJ/release2.keystore \
    -alias zmaxaoi -keyalg RSA -keysize 2048 -validity 10000 \
    -storepass zmax2026 -keypass zmax2026 -dname "CN=Z-MAX AOI, OU=ZFCY, O=ZFCY, L=Shenzhen, ST=GD, C=CN"
fi
$BT/apksigner sign --ks $PROJ/release2.keystore --ks-pass pass:zmax2026 \
  --out $PROJ/ZMAX-3D-AOI.apk $OUT/apk/app-aligned.apk

echo "=== 7. 完成 ==="
ls -la $PROJ/ZMAX-3D-AOI.apk | awk '{print $5/1024"KB", $NF}'
$BT/aapt2 dump badging $PROJ/ZMAX-3D-AOI.apk 2>/dev/null | grep -E '^package|application-label|launchable-activity'
echo "--- 内含文件 ---"
unzip -l $PROJ/ZMAX-3D-AOI.apk | grep -E "classes.dex|ic_overlay|ic_launcher|resources.arsc" | awk '{print "  "$4"  "$1"B"}'
