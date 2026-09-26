#!/usr/bin/env bash
# net_tw_ab.sh — tcp_tw_reuse 是否真有收益 (交错 A/B, 反例就回滚) — skill linux-network-perf-boot §0 铁律
# 负载: 8790 推理服务短连接 (本机实测 9Hz 短连接 → TIME_WAIT 631 条的唯一来源)
set -u
run() {  # 200 次短连接总耗时(ms) + 期间新建 TIME_WAIT 增量
  local t0 tw0 t1 tw1
  tw0=$(ss -tan 2>/dev/null | grep -c TIME-WAIT)
  t0=$(date +%s%N)
  for i in $(seq 1 200); do curl -s -o /dev/null -m 2 http://127.0.0.1:8790/health; done
  t1=$(date +%s%N); tw1=$(ss -tan 2>/dev/null | grep -c TIME-WAIT)
  echo "$(( (t1-t0)/1000000 )) $(( tw1-tw0 ))"
}
setv() { sudo sysctl -qw net.ipv4.tcp_tw_reuse=$1; }
echo "1: $(sysctl -n net.ipv4.tcp_tw_reuse)  (出厂)"
declare -a A B
for r in 1 2 3; do
  setv 0; read -r t w <<<"$(run)"; A+=("$t"); echo "  A(tw_reuse=0) 轮$r: ${t}ms · TIME_WAIT +${w}"
  setv 1; read -r t w <<<"$(run)"; B+=("$t"); echo "  B(tw_reuse=1) 轮$r: ${t}ms · TIME_WAIT +${w}"
done
med() { printf '%s\n' "$@" | sort -n | awk '{a[NR]=$1} END{print (NR%2)?a[(NR+1)/2]:int((a[NR/2]+a[NR/2+1])/2)}'; }
MA=$(med "${A[@]}"); MB=$(med "${B[@]}")
echo "中位: A=${MA}ms  B=${MB}ms  差=$(( MB - MA ))ms"
case $(echo "$MB $MA" | awk '{print ($1<0.97*$2)?"B_FASTER":($1>1.03*$2?"A_FASTER":"NOISE")}') in
  B_FASTER) echo "→ B 快 ≥3%: 采纳 tcp_tw_reuse=1" ;;
  A_FASTER) echo "→ B 慢 ≥3%: 回滚" ; setv 0 ;;
  *)        echo "→ 差异在噪声内(±3%): 回滚 tcp_tw_reuse=0 (不留表演性设置)" ; setv 0 ;;
esac
echo "最终值: net.ipv4.tcp_tw_reuse=$(sysctl -n net.ipv4.tcp_tw_reuse)"
