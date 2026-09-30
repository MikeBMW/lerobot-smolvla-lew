#!/usr/bin/env bash
# sys_efficiency.sh — 效率项落地 (skill linux-host-maintenance §6 四项) + docker/snap 安全清理
set -u
LOG=/tmp/sys_eff.log; : > "$LOG"
say() { echo "$*" | tee -a "$LOG"; }
B=$(df -m / | awk 'NR==2{print $3}')

say "═══ ① GPU persistence mode (反复起停 CUDA 省驱动重初始化) ═══"
say "  前: $(nvidia-smi --query-gpu=persistence_mode --format=csv,noheader)"
sudo nvidia-smi -pm 1 >/dev/null 2>&1 || true
say "  后: $(nvidia-smi --query-gpu=persistence_mode --format=csv,noheader)"

say "═══ ② NVMe TRIM 定时器 ═══"
sudo systemctl enable --now fstrim.timer >/dev/null 2>&1 || true
say "  fstrim.timer: $(systemctl is-enabled fstrim.timer 2>/dev/null)/$(systemctl is-active fstrim.timer 2>/dev/null)"
sudo fstrim -v / 2>&1 | tail -1 | tee -a "$LOG"

say "═══ ③ 桌面索引器 (tracker-miner 后台扫描) ═══"
systemctl --user mask --now tracker-miner-fs-3.service >/dev/null 2>&1 || true
tracker3 daemon -k >/dev/null 2>&1 || true
say "  tracker-miner-fs-3: $(systemctl --user is-enabled tracker-miner-fs-3.service 2>/dev/null)/$(systemctl --user is-active tracker-miner-fs-3.service 2>/dev/null)"

say "═══ ④ docker 安全清理 (只动 dangling 镜像 + 构建缓存, 不动在役镜像/容器) ═══"
say "  在役容器: $(docker ps --format '{{.Names}}' 2>/dev/null | tr '\n' ' ')"
D_B=$(docker system df --format '{{.Type}} {{.Size}}' 2>/dev/null | tr '\n' ' | ')
say "  前: $D_B"
D_BR=$(docker system df 2>/dev/null | awk '/Build Cache|Images|Local Volumes/{print $4}' | paste -sd+ | bc 2>/dev/null || echo 0)
docker container prune -f >/dev/null 2>&1 || true
docker image prune -f >/dev/null 2>&1 || true
docker builder prune -f >/dev/null 2>&1 || true
say "  后: $(docker system df --format '{{.Type}} {{.Size}}' 2>/dev/null | tr '\n' ' | ')"
say "  在役容器 (清理后): $(docker ps --format '{{.Names}}' 2>/dev/null | tr '\n' ' ')"

say "═══ ⑤ snap 旧版本 ═══"
snap list --all 2>/dev/null | awk '/disabled/{print $1, $3}' | while read -r n v; do
  say "  删除旧 revision: $n $v"; sudo snap remove "$n" --revision="$v" >/dev/null 2>&1 || true
done
say "  当前 snap: $(snap list 2>/dev/null | tail -n +2 | wc -l) 个"

say "═══ ⑥ 大文件扫描 (只列 TOP, 不删) ═══"
say "  /tmp 前 5:"; ls -Sl /tmp 2>/dev/null | head -6 | tail -5 | awk '{printf "    %s %s\n", $5, $9}' | tee -a "$LOG"
say "  /var/log 合计: $(du -sm /var/log 2>/dev/null | cut -f1)MB"
say "  ~/.cache 合计: $(du -sm /home/ubuntu/.cache 2>/dev/null | cut -f1)MB"

A=$(df -m / | awk 'NR==2{print $3}')
say "═══ ⑦ 磁盘: used ${B}MB → ${A}MB (本轮释放 $(( B - A ))MB, 负值=期间有新写入) ==="
say "  df: $(df -h / | awk 'NR==2{print $3" used / "$4" free / "$5}')"
say "  GPU 状态: $(nvidia-smi --query-gpu=utilization.gpu,memory.used,persistence_mode --format=csv,noheader)"
