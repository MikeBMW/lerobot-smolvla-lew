#!/usr/bin/env bash
# ============================================================================
# 打包「Z-MAX 实况」(手机 APP · com.zmax.live) —— 纯 CLI, 无 Gradle
#
# 这个包 = 现场实况页(http://<工位机>:8791/overlay)的手机入口。
# ★ 2026-09-27: 工位机两个网口(手机网段不一定) ⇒ MainActivity 改为
#   自动依次试 [WiFi 10.163.146.78 → 产线 192.168.23.50], 全不通才提示 + 长按手改。
#   旧版写死产线口 ⇒ 手机在 WiFi 时打开是空白页("用不了")。
#
# ★ 顺序铁律: 先 zipalign 再 apksigner; v1+v2+v3 全开。
# ★ 打完整包自动投递到 tools/web/dl/ 并把 sha256/体积**写回**实况页的 APP 卡,
#   页面上那个校验串因此不可能与实际文件不一致。
# ============================================================================
set -e
SDK=/home/ubuntu/android-sdk
BT=$SDK/build-tools/34.0.0
PLATFORM=$SDK/platforms/android-34/android.jar
SRC=/home/ubuntu/state3d_app
PROJ=$SRC/live
BUILD=$PROJ/build
OUT=$PROJ/ZMAX-Live.apk
DL=/home/ubuntu/zmax/tools/web/dl
PAGE=/home/ubuntu/zmax/tools/web/scene-overlay.html      # 8791 /overlay 与 /app 都是它
KS=$SRC/release.keystore
cd "$PROJ"

echo "=== ① aapt2 compile ==="
rm -rf "$BUILD"; mkdir -p "$BUILD/gen" "$BUILD/obj" "$BUILD/dex"
"$BT/aapt2" compile --dir src/main/res -o "$BUILD/res.zip"

echo "=== ② aapt2 link ==="
"$BT/aapt2" link -o "$BUILD/app.apk" -I "$PLATFORM" \
  --manifest src/main/AndroidManifest.xml --java "$BUILD/gen" "$BUILD/res.zip"

echo "=== ③ javac ==="
javac -source 8 -target 8 -bootclasspath "$PLATFORM" -d "$BUILD/obj" \
  $(find src/main/java "$BUILD/gen" -name '*.java')

echo "=== ④ d8 ==="
"$BT/d8" --release --lib "$PLATFORM" --output "$BUILD/dex" $(find "$BUILD/obj" -name '*.class')

echo "=== ⑤ 组包 + 对齐 ==="
cp -f "$BUILD/app.apk" "$BUILD/unsigned.apk"
( cd "$BUILD/dex" && zip -q "$BUILD/unsigned.apk" classes.dex )
"$BT/zipalign" -f -p 4 "$BUILD/unsigned.apk" "$BUILD/aligned.apk"

echo "=== ⑥ 签名: v1 + v2 + v3 全开 ==="
if [ -f "$OUT" ]; then cp -f "$OUT" "$BUILD/prev_ZMAX-Live.apk"; fi
"$BT/apksigner" sign --ks "$KS" --ks-pass pass:zmax2026 --key-pass pass:zmax2026 \
  --v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled true \
  --min-sdk-version 24 --out "$OUT" "$BUILD/aligned.apk"
rm -f "$OUT.idsig"

echo "=== ⑦ 验收 ==="
V=$("$BT/apksigner" verify --min-sdk-version 21 --verbose "$OUT" 2>&1)
echo "$V" | grep -E "Verified using v[123]" | sed 's/^/  /'
for s in 1 2 3; do
  echo "$V" | grep -q "Verified using v$s scheme.*: true" || { echo "  ✗ v$s 未过, 停"; exit 1; }
done
"$BT/zipalign" -c -v 4 "$OUT" >/dev/null 2>&1 && echo "  ✓ zipalign 通过" || { echo "  ✗ zipalign 失败"; exit 1; }
"$BT/aapt2" dump badging "$OUT" | grep -E "^package|^application-label|^launchable" | sed 's/^/  /'
echo "  包内候选地址 (http/https 都要看, 只 grep http 会漏掉 ECS 那条):"
unzip -p "$OUT" classes.dex | strings | grep -oE '(https?://[^ "]*/(overlay|live))' | sort -u | sed 's/^/    /'
N=$(unzip -p "$OUT" classes.dex | strings | grep -coE '(https?://[^ "]*/(overlay|live))')
echo "  候选口数量: $N (期望 3 = ECS 稳定口 + 双网)"
grep -q "datadrive.world/ov/overlay" <(unzip -p "$OUT" classes.dex | strings) \
  && echo "  ✓ ECS 稳定口已烧进包" || { echo "  ✗ 包里没有 ECS 稳定口"; exit 1; }

echo "=== ⑧ 投递下载目录 ==="
mkdir -p "$DL"
if [ -f "$DL/ZMAX-Live.apk" ]; then cp -f "$DL/ZMAX-Live.apk" "$DL/ZMAX-Live.apk.prev"; fi
cp -f "$OUT" "$DL/ZMAX-Live.apk"
SHA=$(sha256sum "$OUT" | awk '{print $1}')
SZ=$(stat -c%s "$OUT" | awk '{printf "%.1fKB", $1/1024}')
echo "  $SZ  sha256=$SHA"
sha256sum "$DL/ZMAX-Live.apk" | awk '{print "  下发件: "$1}'

echo "=== ⑨ 写回实况页的 APP 卡 (页面上那串必须等于本次产物) ==="
python3 - "$PAGE" "$SHA" "$SZ" <<'PYEOF'
import re, sys
p, sha, sz = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(p, encoding="utf-8").read()
s2 = re.sub(r'(<span id="apkSize">)[^<]*(</span>)', r'\g<1>' + sz + r'\g<2>', s)
s2 = re.sub(r'(<code id="apkSha">)[0-9a-fA-F]{64}(</code>)', r'\g<1>' + sha + r'\g<2>', s2)
open(p, "w", encoding="utf-8").write(s2)
print("  写入 %s (%s)" % (sha[:24] + "…", sz))
PYEOF
grep -oE '<code id="apkSha">[0-9a-f]+' "$PAGE" | sed 's/.*>//' | sed 's/^/  页面现在声明: /'
grep -oE '<span id="apkSize">[^<]*' "$PAGE" | sed 's/.*>//' | sed 's/^/  页面现在声明: /'
