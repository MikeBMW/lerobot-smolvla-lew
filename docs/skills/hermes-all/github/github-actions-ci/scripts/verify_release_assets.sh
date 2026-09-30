#!/usr/bin/env bash
# 验证 GitHub Release 资产: 拉 digest(API 元数据) + 8 并发 Range 分块下载(browser_download_url) + sha256 对照
# 用法: bash verify_release_assets.sh <owner> <repo> <tag> <asset...>
# 例:   bash verify_release_assets.sh MikeBMW lerobot-smolvla-lew v3.2.1 Z-MAX_Console.exe Z-MAX_Console-macOS.zip
# 背景(2026-08-26 实测): api.github.com 的 releases/assets/{id} 下载端点带 token 会被 WAF 拒
#   (HTTP 400 "Whoa there!" / curl 43 "Failed sending HTTP request"); browser_download_url 无需 token
#   直连通畅且支持 Range; 单连接 50~130KB/s 时 8 并发分块能压到 ~1MB/s。
set -u
OWNER="${1:?owner}"; REPO="${2:?repo}"; TAG="${3:?tag}"; shift 3
[ $# -ge 1 ] || { echo "至少给一个资产名"; exit 2; }
CHUNK=8388608   # 8MB
CONC=8
WORK="${TMPDIR:-/tmp}/relassets_${TAG}"
mkdir -p "$WORK"; cd "$WORK" || exit 1
BASE="https://github.com/$OWNER/$REPO/releases/download/$TAG"

# ⚠️ .git-credentials 可能有多行重复 token, 必须 head -1 (全取 → header 含换行 → ValueError)
TOKEN=$(grep -oP 'https://[^:]+:\K[^@]+' ~/.git-credentials | head -1)

# 1) digest 从 API 拿 (元数据端点不被 WAF 拦)
OWNER="$OWNER" REPO="$REPO" TAG="$TAG" TOKEN="$TOKEN" python3 <<'PYEOF'
import json, os, urllib.request
owner, repo, tag, token = os.environ["OWNER"], os.environ["REPO"], os.environ["TAG"], os.environ["TOKEN"]
req = urllib.request.Request(
    f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}",
    headers={"Authorization": f"token {token}"})
rel = json.loads(urllib.request.urlopen(req, timeout=30).read())
out = {}
for a in rel.get("assets", []):
    d = a.get("digest", "").replace("sha256:", "")
    out[a["name"]] = d
    print(f"{a['name']} {a['size']//1024//1024}MB digest={d[:16]}...")
json.dump(out, open("digests.json", "w"))
PYEOF
[ -f digests.json ] || { echo "!! digest 拉取失败"; exit 1; }

dl_file() {
  local name="$1" total n i j start end
  total=$(curl -sIL --http1.1 "$BASE/$name" | grep -i '^content-length' | tail -1 | tr -d '\r' | awk '{print $2}')
  [ -n "$total" ] || { echo "!! 拿不到 $name 大小"; return 1; }
  echo "== $name $total bytes"
  n=$(( (total + CHUNK - 1) / CHUNK ))
  for ((i=0; i<n; i+=CONC)); do
    local pids=()
    for ((j=i; j<n && j<i+CONC; j++)); do
      start=$(( j * CHUNK )); end=$(( start + CHUNK - 1 ))
      [ $end -ge $total ] && end=$(( total - 1 ))
      # ⚠️ 必须带 -L: 302 不跟随 → 每块 0 字节 → 拼接后整文件 0 字节 (本会话踩过)
      curl -sL --http1.1 --retry 6 --retry-delay 3 --retry-all-errors \
        -H "Range: bytes=$start-$end" -o "${name}.part.${j}" "$BASE/$name" &
      pids+=($!)
    done
    for p in "${pids[@]}"; do wait "$p"; done
    echo "  chunk $i-$((i+CONC-1)) done"
  done
  : > "$name"
  for ((j=0; j<n; j++)); do cat "${name}.part.${j}" >> "$name"; rm -f "${name}.part.${j}"; done
  echo "== $name 拼接完成 $(stat -c%s "$name") bytes"
}

for a in "$@"; do dl_file "$a"; done

echo "=== sha256 校验 ==="
python3 <<'PYEOF'
import hashlib, json
dig = json.load(open("digests.json"))
ok_all = True
for name, expect in dig.items():
    try:
        h = hashlib.sha256(open(name, "rb").read()).hexdigest()
        ok = h == expect
        ok_all &= ok
        print(f"{name}: {h[:16]}... {'✅MATCH' if ok else '❌MISMATCH'}")
    except FileNotFoundError:
        print(f"{name}: 文件缺失!")
        ok_all = False
print("ALL_MATCH" if ok_all else "HAS_FAILURE")
PYEOF
