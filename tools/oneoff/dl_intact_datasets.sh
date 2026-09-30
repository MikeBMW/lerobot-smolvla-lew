#!/bin/bash
# 下载 INTACT 官方评测所需的 pusht / reacher 数据集 (HF 镜像), 解压到 STABLEWM_HOME/datasets
set -u
cd /home/ubuntu/INTACT-JEPA || exit 1
export HF_ENDPOINT=https://hf-mirror.com
DL=/home/ubuntu/dl_intact
DS=/home/ubuntu/stable-wm-cache/datasets
mkdir -p "$DL" "$DS/dmc"
echo "=== 下载开始 $(date '+%F %T') ==="
.venv/bin/python - <<'PY'
from huggingface_hub import hf_hub_download
jobs = [("quentinll/lewm-pusht", "pusht_expert_train.h5.zst"),
        ("quentinll/lewm-reacher", "reacher.tar.zst")]
for repo, fn in jobs:
    try:
        p = hf_hub_download(repo_id=repo, filename=fn, repo_type="dataset",
                            local_dir="/home/ubuntu/dl_intact")
        print("OK", repo, fn, p, flush=True)
    except Exception as e:
        print("FAIL", repo, fn, type(e).__name__, e, flush=True)
PY
echo "=== 解压 ==="
cd "$DL" || exit 1
for f in *.zst; do
  [ -e "$f" ] || continue
  echo "--- $f"
  case "$f" in
    *.tar.zst) tar --use-compress-program=unzstd -xf "$f" && echo "  tar 解压完" ;;
    *.zst)     unzstd -f -k "$f" && echo "  zstd 解压完" ;;
  esac
done
echo "=== 落位到 datasets/ ==="
find "$DL" -name "*.h5" | while read -r h; do
  echo "  找到 $h"
  base=$(basename "$h")
  case "$base" in
    reacher*) cp -f "$h" "$DS/dmc/reacher_random.h5" && echo "   → datasets/dmc/reacher_random.h5" ;;
    pusht*)   cp -f "$h" "$DS/pusht_expert_train.h5" && echo "   → datasets/pusht_expert_train.h5" ;;
    *)        cp -f "$h" "$DS/$base" && echo "   → datasets/$base" ;;
  esac
done
ls -la "$DS" | head -12
echo "=== 完成 $(date '+%F %T') ==="
