#!/bin/bash
# 系统体检 + 缓存清理 + DNS + 网络 + 性能 (2026-09-27) — 只删可再生的, 保护清单不动
set -u
R=/home/ubuntu/zmax/reports
LEDGER=$R/sys_cleanup_$(date +%Y%m%d_%H%M%S).json
declare -a ITEMS
before_mb=$(df --output=used -m / | tail -1 | tr -d ' ')
echo "###### 1. 自检 ######"
date; uptime | tr -s ' '
echo "kernel: $(uname -r)"
echo "--- failed units (应为空) ---"; systemctl --failed --no-pager | head -4
echo "--- 内存 ---"; free -h | head -2
echo "--- 磁盘 ---"; df -h / | tail -1
echo "--- 时间同步 ---"; timedatectl | grep -E "synchronized|Time zone" | sed 's/^ *//'
echo "--- CPU 档位 ---"; echo "$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor) · $(nproc) 核 · swappiness=$(cat /proc/sys/vm/swappiness)"
echo "--- GPU ---"; nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,persistence_mode,temperature.gpu --format=csv,noheader 2>/dev/null || echo "无 GPU"
echo "--- CPU 占用前 6 (1 秒差分, 非 ps 生命周期均值) ---"
snap(){ for p in $(ps -eo pid --no-headers); do [ -r /proc/$p/stat ] || continue; awk '{print $14+$15}' /proc/$p/stat 2>/dev/null | xargs -I{} echo "$p {}"; done; }
snap > /tmp/_s1; sleep 1; snap > /tmp/_s2
join /tmp/_s1 /tmp/_s2 2>/dev/null | awk '{d=$3-$2; if(d>20) printf "%.0f%% %s\n", d/10, $1}' | sort -rn | head -6 | while read pc pid; do
  printf "  %-6s %s\n" "$pc" "$(ps -p $pid -o comm=,args= --no-headers 2>/dev/null | cut -c1-70)"; done

echo; echo "###### 2. DNS ######"
resolvectl status 2>/dev/null | grep -E "Current DNS|DNS Servers" | head -3 | sed 's/^/  /'
hs="www.baidu.com open.feishu.cn github.com registry.npmmirror.com hf-mirror.com pypi.org"
probe(){ for h in $hs; do s=$(date +%s%N); getent hosts $h >/dev/null 2>&1; e=$(date +%s%N); \
  printf "  %-26s %4d ms\n" "$h" $(( (e-s)/1000000 )); done; }
echo "--- 清前 ---"; probe
sudo resolvectl flush-caches >/dev/null 2>&1 && echo "  [resolvectl flush-caches 已执行]"
echo "--- 清后(首查=冷) ---"; probe
echo "--- 清后(再查=热) ---"; probe

echo; echo "###### 3. 网络 ######"
ip -br a 2>/dev/null | grep -v "lo " | head -5 | sed 's/^/  /'
GW=$(ip route | awk '/default/{print $3; exit}')
if [ -n "${GW:-}" ]; then echo "  网关 $GW: $(ping -c3 -W2 $GW 2>/dev/null | tail -1)"; else echo "  (无默认路由: 产线口 192.168.23.50/24 本来就没网关)"; fi
for t in 223.5.5.5 1.1.1.1; do echo "  $t: $(ping -c3 -W2 $t 2>/dev/null | tail -1)"; done
for t in 192.168.23.66 192.168.23.23; do echo "  现场 $t: $(ping -c2 -W2 $t 2>/dev/null | tail -1)"; done
echo "  socket: $(ss -s 2>/dev/null | grep -i "total:" | head -1 | tr -s ' ')"
echo "  TCP 旋钮: $(sysctl -n net.ipv4.tcp_congestion_control) / $(sysctl -n net.core.default_qdisc) / fastopen=$(sysctl -n net.ipv4.tcp_fastopen)"

echo; echo "###### 4. 缓存清理 (可再生) ######"
sz(){ [ -e "$1" ] && sudo du -sm "$1" 2>/dev/null | awk '{print $1}' || echo 0; }
rec(){ ITEMS+=("{\"item\":\"$1\",\"freed_mb\":$2}"); printf "  %-22s %6s MB\n" "$1" "$2"; }
b=$(journalctl --disk-usage 2>/dev/null | grep -oE '[0-9.]+[MG]' | head -1)
journalctl --vacuum-size=200M >/dev/null 2>&1
a=$(journalctl --disk-usage 2>/dev/null | grep -oE '[0-9.]+[MG]' | head -1)
rec "journal($b→$a)" "0"

f=0; for d in /var/log/*.gz /var/log/*.1 /var/log/installer; do [ -e "$d" ] && { s=$(sz "$d"); sudo rm -rf "$d"; f=$((f+s)); }; done; rec "日志轮转" $f

f=0; [ -d /var/crash ] && { s=$(sz /var/crash); sudo rm -rf /var/crash/* 2>/dev/null; f=$s; }; rec "crash 转储" $f

s=$(sz /var/cache/apt/archives); sudo apt-get clean >/dev/null 2>&1; sudo apt-get autoclean >/dev/null 2>&1; rec "apt 包缓存" $s
s=$(sz /var/lib/apt/lists); sudo rm -f /var/lib/apt/lists/* 2>/dev/null; rec "apt 列表" $s

for u in "pip:$HOME/.cache/pip" "uv:$HOME/.cache/uv" "thumbnails:$HOME/.cache/thumbnails" "tracker3:$HOME/.cache/tracker3" "mesa:$HOME/.cache/mesa_shader_cache" "gnome-thumb:$HOME/.cache/gnome-desktop-thumbnailer"; do
  n=${u%%:*}; p=${u#*:}; s=$(sz "$p"); [ "$s" -gt 0 ] && { sudo rm -rf "$p"/* 2>/dev/null; rec "$n" $s; }; done

for c in firefox chromium snap-store thunderbird; do p="$HOME/snap/$c/common/.cache"; s=$(sz "$p"); [ "$s" -gt 1 ] && { rm -rf "$p"/* 2>/dev/null; rec "snap/$c" $s; }; done

s=$(sz "$HOME/.local/share/Trash/files"); [ "$s" -gt 0 ] && { ls "$HOME/.local/share/Trash/files" 2>/dev/null | head -3 | sed 's/^/     回收站: /'; }
rec "回收站" "0"
done_mb=$(df --output=used -m / | tail -1 | tr -d ' ')
echo "  ── 磁盘: ${before_mb}MB → ${done_mb}MB  (净释放 $((before_mb-done_mb))MB)"

echo; echo "###### 5. 性能项 ######"
sudo nvidia-smi -pm 1 >/dev/null 2>&1 && echo "  GPU persistence: $(nvidia-smi --query-gpu=persistence_mode --format=csv,noheader)"
systemctl --user mask --now tracker-miner-fs-3.service >/dev/null 2>&1; echo "  tracker-miner-fs-3: $(systemctl --user is-active tracker-miner-fs-3.service 2>/dev/null) (masked)"
if systemctl is-enabled fstrim.timer >/dev/null 2>&1; then
  echo "  fstrim.timer: $(systemctl is-active fstrim.timer)"; sudo fstrim -v / 2>/dev/null | sed 's/^/    /'
else sudo systemctl enable --now fstrim.timer >/dev/null 2>&1 && echo "  fstrim.timer 已启用"; fi

printf '{"ts":"%s","before_mb":%s,"after_mb":%s,"freed_mb":%s,"items":[%s]}\n' \
  "$(date -Is)" "$before_mb" "$done_mb" "$((before_mb-done_mb))" "$(IFS=,; echo "${ITEMS[*]:-}")" | sudo tee "$LEDGER" >/dev/null
echo; echo "台账: $LEDGER"
