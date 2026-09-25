#!/usr/bin/env bash
# zmax-net-optimize.sh — 开机网络性能优化 + 体检台账 (每次开机由 systemd 调用)
#
# 口径 (linux-host-maintenance §6 / 技能 linux-network-perf-boot):
#   · 只应用**实测有收益**的旋钮, 无收益的一律不启用 (防 cargo-cult)
#   · 每次开机落一份台账 JSON: 应用了什么 + 实测数字, 便于下次对比"是否真有提升"
#   · 全程只读+可逆, 不动服务; 单项失败不阻塞开机
#
# 用法: zmax-net-optimize.sh [--quick] [--no-throughput] [--json-only]
set -u
QUICK=0; NO_TPUT=0
for a in "$@"; do case "$a" in --quick|--no-throughput) NO_TPUT=1;; --json-only) QUICK=1; NO_TPUT=1;; esac; done

REPO=/home/ubuntu/lerobot-smolvla-lew
OUTDIR="$REPO/reports"
LOG=/var/log/zmax-net-optimize.log
JSON="$OUTDIR/net_boot_optimize_$(date +%Y%m%d).jsonl"
TS=$(date '+%F %T %Z')
mkdir -p "$OUTDIR" 2>/dev/null
say() { printf '%s %s\n' "$(date '+%F %T')" "$*" | tee -a "$LOG" ; }

say "=== 开机网络优化开始 (tput=$([ $NO_TPUT = 0 ] && echo on || echo off)) ==="

# ── ① 内核旋钮 (真源: /etc/sysctl.d/99-zmax-net.conf, 这里只复核生效值) ──
APPLIED=""
for kv in "net.core.rmem_max=33554432" "net.core.wmem_max=16777216" \
          "net.ipv4.tcp_slow_start_after_idle=0" "net.ipv4.tcp_fastopen=3" \
          "net.ipv4.tcp_mtu_probing=1" "net.core.netdev_max_backlog=5000" \
          "net.core.somaxconn=8192" "net.ipv4.tcp_congestion_control=bbr" \
          "net.core.default_qdisc=fq"; do
  k=${kv%%=*}; v=${kv#*=}
  cur=$(sysctl -n "$k" 2>/dev/null)
  if [ "$cur" != "$v" ]; then sysctl -qw "$k=$v" 2>/dev/null && cur=$(sysctl -n "$k" 2>/dev/null); fi
  [ "$cur" = "$v" ] && APPLIED="$APPLIED $k=$v" || say "  ⚠️ $k 期望 $v 实际 $cur"
done
modprobe tcp_bbr 2>/dev/null || true
sysctl -qw net.ipv4.tcp_congestion_control=bbr 2>/dev/null || true
say "① 内核旋钮生效: cc=$(sysctl -n net.ipv4.tcp_congestion_control) rmem_max=$(sysctl -n net.core.rmem_max) ssai=$(sysctl -n net.ipv4.tcp_slow_start_after_idle) fastopen=$(sysctl -n net.ipv4.tcp_fastopen)"

# ── ② WiFi 省电关 (5GHz 抖动来源; 驱动默认 N, 这里显式断言) ──
WL=$(iw dev 2>/dev/null | awk '/Interface/{print $2; exit}')
if [ -n "${WL:-}" ]; then
  iw dev "$WL" set power_save off 2>/dev/null || true
  PS=$(iw dev "$WL" get power_save 2>/dev/null | awk -F': ' '{print $2}')
  say "② WiFi($WL) 省电: $PS"
else
  PS="<无wifi>"; say "② 无 WiFi 接口, 跳过"
fi

# ── ③ DNS: 清缓存 + 预热常用域 (开机首次解析不再等) ──
sudo -n true 2>/dev/null && resolvectl flush-caches 2>/dev/null || true
prewarm_ok=0
for h in open.feishu.cn github.com registry.npmmirror.com datadrive.world www.baidu.com; do
  getent hosts "$h" >/dev/null 2>&1 && prewarm_ok=$((prewarm_ok+1))
done
say "③ DNS 预热: $prewarm_ok/5 域已可解析 · 上游 $(resolvectl status 2>/dev/null | awk '/DNS Servers/{for(i=3;i<=NF;i++)printf "%s ",$i}' | head -1)"

# ── ④ 体检台账 (RTT / TTFB / 吞吐), 全带超时, 失败不影响开机 ──
GW=$(ip route | awk '/default/{print $3; exit}')
rtt() {
  # ⚠️ 别用 -F'[/ ]': ping 汇总行是 "rtt min/avg/max/mdev = a/b/c/d ms", 按 '=' 切再按 '/' 取 avg
  ping -c 5 -i 0.2 -W2 "$1" 2>/dev/null | tail -1 | awk -F'= ' '{split($2,a,"/"); print a[2]}'
}
ttfb() { curl -s -o /dev/null -m 8 -w "%{time_starttransfer}" "$1" 2>/dev/null; }
R_GW=$(rtt "${GW:-10.163.147.254}"); R_DNS=$(rtt "$(resolvectl status 2>/dev/null | awk '/DNS Servers/{print $3; exit}')")
R_PUB=$(rtt 1.1.1.1); R_IPC=$(rtt 192.168.23.23); R_ORIN=$(rtt 192.168.23.66)
T_FEISHU=$(ttfb https://open.feishu.cn/); T_GH=$(ttfb https://github.com/)
TPUT=""
if [ $NO_TPUT = 0 ]; then
  TPUT=$(curl -sL -o /dev/null -m 8 -w "%{speed_download}" "https://codeload.github.com/git/git/tar.gz/refs/tags/v2.47.0" 2>/dev/null)
fi
mbps() { awk -v v="${1:-0}" 'BEGIN{ if(v>=1048576) printf "%.2fMB/s", v/1048576; else printf "%.0fKB/s", v/1024 }'; }
say "④ 体检: 网关 ${R_GW}ms · DNS ${R_DNS}ms · 公网 ${R_PUB}ms · 工控机 ${R_IPC}ms · Orin ${R_ORIN}ms · TTFB feishu $(awk -v v=${T_FEISHU:-0} 'BEGIN{printf "%.0fms", v*1000}') github $(awk -v v=${T_GH:-0} 'BEGIN{printf "%.0fms", v*1000}') · 远端下载 $(mbps "${TPUT:-0}")"

# ── ⑤ 落台账 JSONL (一行一次开机, 便于跨天对比) ──
python3 - "$JSON" "$TS" "$APPLIED" "$PS" "$R_GW" "$R_DNS" "$R_PUB" "$R_IPC" "$R_ORIN" "$T_FEISHU" "$T_GH" "$TPUT" "$prewarm_ok" <<'PY' 2>/dev/null || true
import json, sys
(p, ts, applied, ps, rgw, rdns, rpub, ripc, rorin, tfs, tgh, tput, pre) = sys.argv[1:14]
def f(x):
    try: return float(x)
    except Exception: return None
rec = {"ts": ts, "event": "boot_net_optimize",
       "applied": applied.split(),
       "wifi_power_save": ps,
       "rtt_ms": {"gateway": f(rgw), "dns": f(rdns), "public_1.1.1.1": f(rpub),
                  "ipc_10082": f(ripc), "orin": f(rorin)},
       "ttfb_ms": {"feishu": (f(tfs) or 0)*1000, "github": (f(tgh) or 0)*1000},
       "far_download_Bps": f(tput),
       "dns_prewarm_ok": int(pre),
       "note": "远端下载基线: 默认(cubic/212992) 中位 4.30MB/s; 优化后 5.12MB/s (+19%, 5/6轮) — 见 reports/net_perf_ab_*.json"}
open(p, "a", encoding="utf-8").write(json.dumps(rec, ensure_ascii=False) + "\n")
PY
say "⑤ 台账: $JSON"
say "=== 完成 ==="
exit 0
