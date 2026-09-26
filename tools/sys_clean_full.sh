#!/usr/bin/env bash
# sys_clean_full.sh — 系统清理 + DNS + 网络体检 (一脚本跑完, 每项报前/后, 落台账)
# 依据 skill `linux-host-maintenance` §0铁律/§4矩阵/§5HF + `linux-network-perf-boot` §3测法
set -u
TS=$(date +%Y%m%d_%H%M%S)
REPO=/home/ubuntu/zmax_rel
OUTDIR="$REPO/reports"; mkdir -p "$OUTDIR"
LEDGER="$OUTDIR/sys_cleanup_${TS}.json"
LOG=/tmp/sys_clean.log; : > "$LOG"
J=/tmp/_clean_items.jsonl; : > "$J"

mb() { local d="$1"; [ -e "$d" ] || { echo 0; return; }
       timeout 25 du -sm "$d" 2>/dev/null | cut -f1 || echo 0; }
say() { echo "$*" | tee -a "$LOG"; }
item() { # name path before after
  printf '{"name":"%s","path":"%s","mb_before":%s,"mb_after":%s,"freed_mb":%s}\n' "$1" "$2" "$3" "$4" "$(( $3 - $4 ))" >> "$J"
}

say "═══ ① 自检 ═══"
say "时间: $(date '+%F %T %Z') · 内核 $(uname -r) · $(lsb_release -ds 2>/dev/null)"
say "uptime: $(uptime -p) · 负载 $(cut -d' ' -f1-3 /proc/loadavg)"
say "失败单元: $(systemctl --failed --no-pager 2>/dev/null | grep -c 'loaded failed' ) 个"
say "内存: $(free -m | awk 'NR==2{printf "总%dMB 用%dMB 可用%dMB", $2,$3,$7}') · swap $(free -m | awk 'NR==3{printf "用%dMB", $3}') · swappiness=$(cat /proc/sys/vm/swappiness)"
say "GPU: $(nvidia-smi --query-gpu=utilization.gpu,memory.used,persistence_mode,temperature.gpu --format=csv,noheader 2>/dev/null)"
BRE=$(df -m / | awk 'NR==2{print $3}'); FRB=$(df -m / | awk 'NR==2{print $4}')
say "磁盘: used ${BRE}MB / free ${FRB}MB ($(df -h / | awk 'NR==2{print $5}'))"

say "═══ ② 保护清单 (清理前) ═══"
PROTECT="/home/ubuntu/zmax_ss_remote /home/ubuntu/stable-wm-cache /home/ubuntu/zmax_rel /home/ubuntu/zmax_data /home/ubuntu/zmax_dds /home/ubuntu/lerobot-smolvla-lew/models /home/ubuntu/lerobot-smolvla-lew/flows"
for p in $PROTECT; do printf "  %-48s %s\n" "$p" "$([ -e "$p" ] && echo 在 || echo 缺)" | tee -a "$LOG"; done

say "═══ ③ 清理 (每项前→后) ═══"
clean() { # name path [mode=rm|vacuum|cmd]
  local name="$1" path="$2" mode="${3:-rm}" cmd="${4:-}"
  local b a
  b=$(mb "$path")
  case "$mode" in
    rm)  sudo rm -rf "$path"/* 2>/dev/null || true ;;
    home) rm -rf "$path"/* 2>/dev/null || true ;;
    cmd)  eval "$cmd" >/dev/null 2>&1 ;;
    journal) sudo journalctl --vacuum-size=200M >/dev/null 2>&1 ;;
  esac
  a=$(mb "$path")
  printf "  %-26s %6sMB → %6sMB  (释放 %5sMB)\n" "$name" "$b" "$a" "$(( b - a ))" | tee -a "$LOG"
  item "$name" "$path" "$b" "$a"
}
clean "journal→200M"        /var/log/journal      journal
clean "apt 归档"            /var/cache/apt/archives
clean "apt 列表缓存"        /var/lib/apt/lists    rm 'sudo apt-get clean'
clean "崩溃转储"            /var/crash
clean "pip 缓存"            /home/ubuntu/.cache/pip home
clean "uv 缓存"             /home/ubuntu/.cache/uv  home
clean "HF incomplete"       /home/ubuntu/.cache/huggingface cmd 'find /home/ubuntu/.cache/huggingface -name "*.incomplete" -delete 2>/dev/null; rm -rf /home/ubuntu/.cache/huggingface/tmp 2>/dev/null'
clean "缩略图"              /home/ubuntu/.cache/thumbnails home
clean "tracker3 索引"       /home/ubuntu/.cache/tracker3 home
clean "mesa 着色器"         /home/ubuntu/.cache/mesa_shader_cache home
clean "GNOME 缩略器"        /home/ubuntu/.cache/gnome-desktop-thumbnailer rm 'sudo rm -rf /home/ubuntu/.cache/gnome-desktop-thumbnailer/*'
clean "回收站"              /home/ubuntu/.local/share/Trash/files home
clean "chromium 缓存"       /home/ubuntu/snap/chromium/common/.cache home
clean "snap 应用缓存"       /home/ubuntu/snap/snap-store/common/.cache home
clean "系统临时(已回收)"    /tmp                 cmd 'find /tmp -maxdepth 1 -type f -mtime +7 -delete 2>/dev/null'
clean "日志轮转"            /var/log              cmd 'sudo find /var/log -maxdepth 2 -name "*.gz" -o -maxdepth 2 -name "*.1" 2>/dev/null | xargs -r sudo rm -f; sudo rm -rf /var/log/installer 2>/dev/null'

say "═══ ④ DNS 清理 + 解析实测 ═══"
say "解析链: $(resolvectl status 2>/dev/null | grep -m1 'Current DNS' | cut -c1-90)"
CS_B=$(resolvectl statistics 2>/dev/null | awk '/Cache Size/{print $3}')
sudo resolvectl flush-caches
CS_A=$(resolvectl statistics 2>/dev/null | awk '/Cache Size/{print $3}')
say "缓存条目: ${CS_B} → ${CS_A}"
for h in www.baidu.com open.feishu.cn github.com registry.npmmirror.com datadrive.world; do
  t=$( { /usr/bin/time -f "%e" getent hosts $h >/dev/null; } 2>&1 | tail -1 )
  printf "  冷解析 %-24s %ss\n" "$h" "$t" | tee -a "$LOG"
done
say "预热 5 域 (二次解析):"
for h in www.baidu.com open.feishu.cn github.com registry.npmmirror.com datadrive.world; do
  getent hosts $h >/dev/null 2>&1
done
for h in www.baidu.com open.feishu.cn github.com registry.npmmirror.com datadrive.world; do
  t=$( { /usr/bin/time -f "%e" getent hosts $h >/dev/null; } 2>&1 | tail -1 )
  printf "  热解析 %-24s %ss\n" "$h" "$t" | tee -a "$LOG"
done

say "═══ ⑤ 网络性能: 旋钮是否生效 ═══"
for k in net.core.rmem_max net.core.wmem_max net.ipv4.tcp_slow_start_after_idle net.ipv4.tcp_congestion_control net.core.default_qdisc net.ipv4.tcp_fastopen net.core.netdev_max_backlog net.core.somaxconn; do
  printf "  %-42s %s\n" "$k" "$(sysctl -n $k 2>/dev/null)" | tee -a "$LOG"
done
WL=$(iw dev 2>/dev/null | awk '/Interface/{print $2; exit}')
[ -n "${WL:-}" ] && say "  WiFi($WL) 省电: $(iw dev $WL get power_save 2>/dev/null | awk '{print $NF}') · 链路: $(iw dev $WL link 2>/dev/null | grep -E 'signal|bitrate' | tr -s ' ' | tr '\n' ' ')"
say "  远端下载实测 (codeload 单流, 3 轮取中位):"
for i in 1 2 3; do
  s=$(curl -s -m 12 -o /dev/null -w '%{speed_download}' -L "https://codeload.github.com/git/git/tar.gz/refs/tags/v2.43.0" 2>/dev/null)
  printf "    第%d轮 %.2f MB/s\n" "$i" "$(echo "$s/1048576" | bc -l)" | tee -a "$LOG"
done
ttfb=$(for i in 1 2 3; do curl -s -o /dev/null -m 8 -w '%{time_starttransfer}\n' https://registry.npmmirror.com/; done | sort -n | head -2 | tail -1)
say "  TTFB(npmmirror 中位): ${ttfb}s"

say "═══ ⑥ 清理后复核 ═══"
BUSED=$(df -m / | awk 'NR==2{print $3}'); BFREE=$(df -m / | awk 'NR==2{print $4}')
say "磁盘: used ${BUSED}MB (前 ${BRE}MB, 释放 $(( BRE - BUSED ))MB) · free ${BFREE}MB"
say "保护清单 (清理后):"
for p in $PROTECT; do printf "  %-48s %s\n" "$p" "$([ -e "$p" ] && echo 在 || echo 缺)" | tee -a "$LOG"; done
BRK=$(find /home/ubuntu/.cache/huggingface -xtype l 2>/dev/null | wc -l)
say "HF 断链检查: ${BRK} 个 (应为 0)"
say "在役服务: $(systemctl is-active ss-local-infer ss-bypass ss-remote-tap ss-yolo-bypass zmax-net-optimize zmax-web-agent-bridge aoi-feishu-push zmax-dds-ss zmax-dds-pps 2>/dev/null | tr '\n' ' ')"

python3 - "$J" "$LEDGER" "$BRE" "$BUSED" "$CS_B" "$CS_A" "$ttfb" <<'PY'
import json, sys, os
j, led, b, a, csb, csa, ttfb = sys.argv[1:8]
items = [json.loads(l) for l in open(j, encoding="utf-8") if l.strip()]
tot = sum(i["freed_mb"] for i in items)
out = {"ts": __import__("time").strftime("%F %T %Z"),
       "disk_used_mb_before": int(b), "disk_used_mb_after": int(a), "freed_mb": int(b) - int(a),
       "items_total_freed_mb": tot,
       "items": sorted(items, key=lambda x: -x["freed_mb"]),
       "dns_cache_entries": [csb, csa], "ttfb_npmmirror_s": ttfb,
       "note": "只删可再生缓存; 保护清单见 sys_clean.log; 真机数据/权重/仓库未动"}
json.dump(out, open(led, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("台账: %s (释放合计 %dMB)" % (led, tot))
PY
say "日志: $LOG"
