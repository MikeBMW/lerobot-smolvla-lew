#!/bin/bash
# 🐶 大文件下载看门狗: 卡住(5 分钟字节数不变)就重启 aria2c -c 续传; 一直盯到下完
#   背景: HF 直连/hf-mirror 大文件现在基本不动 (30s 0 字节), 只有常驻 aria2 能吃到 ~300KB/s;
#   两个数据集的下载必须能自愈, 否则过夜白等。
set -u
DL=/home/ubuntu/dl_intact
T=(
  "pusht_expert_train.h5.zst|https://hf-mirror.com/datasets/quentinll/lewm-pusht/resolve/main/pusht_expert_train.h5.zst|13140000000"
  "reacher.tar.zst|https://hf-mirror.com/datasets/quentinll/lewm-reacher/resolve/main/reacher.tar.zst|23750000000"
)
LOG=/tmp/dl_dog.log
exec >>"$LOG" 2>&1
echo "=== 看门狗启动 $(date '+%F %T') ==="
while :; do
  alldone=1
  for ent in "${T[@]}"; do
    IFS='|' read -r name url want <<<"$ent"
    case "$name" in
      reacher*) path=/home/ubuntu/stable-wm-cache/datasets/$name ;;
      *)        path=$DL/$name ;;
    esac
    if [ -f "$path" ] && [ "$(stat -c%s "$path")" -ge "$want" ]; then continue; fi
    alldone=0
    S1=$(stat -c%s "$path" 2>/dev/null || echo 0)
    sleep 300
    S2=$(stat -c%s "$path" 2>/dev/null || echo 0)
    if [ "$S2" -le "$S1" ]; then
      # 只在没有 aria2 在跑这个文件时才重启 (避免双写损坏)
      if ! pgrep -f "aria2c .*$name" >/dev/null; then
        echo "$(date '+%F %T') $name 卡住 (${S1}B), 重启续传"
        nohup aria2c -x 16 -s 16 -k 1M -c --file-allocation=none --max-tries=0 --retry-wait=10 \
          --console-log-level=warn --summary-interval=60 -d "$(dirname "$path")" -o "$(basename "$path")" \
          "$url" >>/tmp/dl_aria_single.log 2>&1 &
      else
        echo "$(date '+%F %T') $name 未增长但 aria2 在跑 (限速中), 继续等"
      fi
    fi
  done
  [ "$alldone" = "1" ] && { echo "$(date '+%F %T') 全部下载完成, 看门狗退出"; break; }
  sleep 60
done
