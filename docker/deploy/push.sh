#!/bin/bash
# Z-MAX 标准容器 — 部署/推送脚本族 (2026-08-08 老倪: 一处构建 → 四处运行)
# 用法: ./deploy/push_remote.sh   推送远程 GPU 服务器 (训练)
#       ./deploy/push_mac.sh      推送 Mac M1 (arm64, 数据/推理)
#       ./deploy/push_orin.sh     推送 Orin (arm64, 真机推理)
# 原理: buildx 多平台构建 → docker save → scp → docker load (无 registry 环境)
# =============================================================================
set -e
IMG="${IMG:-zmax-std:1.0}"
TGT="${TARGET:-train}"   # train | infer
REMOTE_HOST="${REMOTE_HOST:-223.109.239.36}"
REMOTE_PORT="${REMOTE_PORT:-24424}"
REMOTE_USER="${REMOTE_USER:-root}"
REMOTE_PWD="${REMOTE_PWD:-da9eo7yo}"
ARCH="amd64"

build_target() {  # $1=arch
  echo "🔨 构建 $IMG ($1/$TGT)…"
  docker buildx build --platform "linux/$1" --target "$TGT" -t "$IMG" -f docker/Dockerfile . 2>&1 | tail -3
  docker buildx build --platform "linux/$1" --target "$TGT" -o "type=docker,dest=/tmp/${IMG}-${1}.tar" -f docker/Dockerfile .
  echo "✅ /tmp/${IMG}-${1}.tar ($(du -h /tmp/${IMG}-${1}.tar | cut -f1))"
}

push() {  # $1=host $2=port $3=user $4=pwd $5=tar
  echo "📤 推送 ${5} → ${1}:${2}…"
  sshpass -p "$4" scp -o StrictHostKeyChecking=no -o Port="$2" "$5" "$3@$1:/tmp/"
  sshpass -p "$4" ssh -o StrictHostKeyChecking=no -o Port="$2" "$3@$1" "docker load -i /tmp/$5 2>&1 | tail -1"
  echo "✅ 已加载: $1"
}

case "$1" in
  remote) build_target amd64; push "$REMOTE_HOST" "$REMOTE_PORT" "$REMOTE_USER" "$REMOTE_PWD" "${IMG}-amd64.tar" ;;
  mac)    build_target arm64; push "10.0.0.4" "22" "mike" "" "${IMG}-arm64.tar" ;;   # 小芳 Mac (填实际 IP)
  orin)   build_target arm64; push "192.168.1.100" "22" "orin" "" "${IMG}-arm64.tar" ;; # Orin (填实际 IP)
  *) echo "用法: $0 {remote|mac|orin}"; exit 1 ;;
esac
