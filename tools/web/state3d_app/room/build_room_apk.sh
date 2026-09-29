#!/usr/bin/env bash
# ============================================================================
# 打包「Z-MAX 现场」(手机 APP · com.zmax.room) —— 纯 CLI, 无 Gradle
#
# ★ 签名姿势: 显式开 **v1+v2+v3 三种方案**(apksigner 在 minSdk>=24 时默认不签 v1)。
#   注意: 不开 v1 也**不是**装不上的原因 —— apksigner 的 --verbose 不带 --min-sdk-version
#   时会恒报 "v1: false", 那只是"该 minSdk 不需要它", 不是签名残缺(曾据此误判过一轮)。
#
# ★ 顺序铁律: 先 zipalign 再 apksigner (反过来会把签名搞失效)
# ★ 打完整包自动投递到 tools/web/dl/ —— 8791 的 /dl/ 路由只服务那个目录,
#   这样老倪那个链接(http://<ip>:8791/dl/ZMAX-Site.apk)始终是最新的。
# ============================================================================
set -e
SDK=/home/ubuntu/android-sdk
BT=$SDK/build-tools/34.0.0
PLATFORM=$SDK/platforms/android-34/android.jar
SRC=/home/ubuntu/state3d_app
PROJ=$SRC/room
BUILD=$PROJ/build
OUT=$PROJ/ZMAX-Site.apk
DL=/home/ubuntu/zmax_rel/tools/web/dl            # 8791 /dl/ 服务的唯一目录
KS=$SRC/release.keystore                          # 与其它 Z-MAX APP 同一把钥匙
cd "$PROJ"

echo "=== ① 资源/目录准备 ==="
mkdir -p src/main/res/values src/main/res/mipmap-{mdpi,hdpi,xhdpi,xxhdpi,xxxhdpi}
printf '<resources>\n  <string name="app_name">Z-MAX 现场</string>\n</resources>\n' > src/main/res/values/strings.xml
for d in mdpi hdpi xhdpi xxhdpi xxxhdpi; do
  cp -f "$SRC/app/src/main/res/mipmap-$d/ic_launcher.png" "src/main/res/mipmap-$d/ic_launcher.png"
done
echo "  图标数(需 5): $(ls src/main/res/mipmap-*/ic_launcher.png | wc -l)"

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
( cd "$BUILD/dex" && zip -q "$BUILD/unsigned.apk" classes.dex )
"$BT/zipalign" -f -p 4 "$BUILD/unsigned.apk" "$BUILD/aligned.apk"

echo "=== ⑦ 签名: v1 + v2 + v3 全开 (③ 步的修复点) ==="
if [ -f "$OUT" ]; then cp -f "$OUT" "$BUILD/prev_ZMAX-Site.apk"; fi
"$BT/apksigner" sign --ks "$KS" --ks-pass pass:zmax2026 --key-pass pass:zmax2026 \
  --v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled true \
  --min-sdk-version 24 --out "$OUT" "$BUILD/aligned.apk"
rm -f "$OUT.idsig"          # v4 的旁挂签名文件对安装没用, 别留在下载目录里混淆

echo "=== ⑧ 验收 (任一红就是没修好) ==="
# ⚠️ 判 v1 必须显式给 --min-sdk-version 21: apksigner 的 --verbose 只校验"该 minSdk 需要的方案",
#    而本包 manifest 里 minSdk=24 ⇒ 不带这个参数时 v1 恒显示 false, 那是"不需要"不是"残缺"。
#    (踩过: 曾据此误判"签名残缺导致华为装不上", 实际签名一直是好的)
V=$("$BT/apksigner" verify --min-sdk-version 21 --verbose "$OUT" 2>&1)
echo "$V" | grep -E "Verified using v[123]|Verifies" | sed 's/^/  /'
for s in 1 2 3; do
  echo "$V" | grep -q "Verified using v$s scheme.*: true" \
    || { echo "  ✗ v$s 校验未通过 —— 停, 不投递"; exit 1; }
done
echo "  ✓ v1 + v2 + v3 全部校验通过"
"$BT/zipalign" -c -v 4 "$OUT" >/dev/null 2>&1 && echo "  ✓ zipalign 4 字节对齐通过" || { echo "  ✗ zipalign 失败"; exit 1; }
"$BT/aapt2" dump badging "$OUT" | grep -E "^package|^sdkVersion|^targetSdk|^application-label|^launchable" | sed 's/^/  /'
echo "  烧进包里的地址: $(unzip -p "$OUT" classes.dex | strings | grep -o 'http://[0-9.]*:8791/room' | head -1)"

echo "=== ⑨ 投递到下载目录 (老倪那个链接直接生效) ==="
mkdir -p "$DL"
if [ -f "$DL/ZMAX-Site.apk" ]; then cp -f "$DL/ZMAX-Site.apk" "$DL/ZMAX-Site.apk.prev"; fi
cp -f "$OUT" "$DL/ZMAX-Site.apk"
ls -la "$OUT" "$DL/ZMAX-Site.apk" | awk '{printf "  %.1fKB  %s\n",$5/1024,$9}'
sha256sum "$OUT" "$DL/ZMAX-Site.apk" | awk '{print "  "$1"  "$2}'

echo "=== ⑩ 把哈希/体积写回现场页 (页面上的校验串必须与本次产物一致, 不然等于说谎) ==="
PAGE=/home/ubuntu/zmax_rel/tools/web/room.html
SHA=$(sha256sum "$OUT" | awk '{print $1}')
SZ=$(stat -c%s "$OUT" | awk '{printf "%.1fKB", $1/1024}')
python3 - "$PAGE" "$SHA" "$SZ" <<'PYEOF'
import re, sys
p, sha, sz = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(p, encoding="utf-8").read()
s = s.replace("__APK_SHA256__", sha).replace("__APK_SIZE__", sz)
open(p, "w", encoding="utf-8").write(s)
print("  写回 %s (%s)" % (sha[:24] + "…", sz))
PYEOF
LEFT=$(grep -c "__APK_SHA256__\|__APK_SIZE__" "$PAGE" || true)
echo "  页面残留占位符(应为 0): $LEFT"
[ "$LEFT" = "0" ] || { echo "  ✗ 占位符没替换干净"; exit 1; }
