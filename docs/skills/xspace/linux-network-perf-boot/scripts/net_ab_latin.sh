#!/usr/bin/env bash
# net_ab_latin.sh — 网络旋钮 交错 A/B 实测模板 (Latin-square 轮转 + 中位 + 胜率 + 噪声带)
#
# 为什么这样写: "先全 A 再全 B" 会因首测偏低(CDN 冷启/首包/无线退避)造出假提升 (实测 +19% 假象)。
# 用法: 编辑 c_A / c_B / measure, 然后 `timeout 570 bash net_ab_latin.sh 6`
set -u
ROUNDS=${1:-6}
D=/tmp/net_ab_latin_detail.txt; : > "$D"

# ── ① 两组配置 (A=出厂/对照, B=候选) ─────────────────────────────
c_A() {
  sudo sysctl -qw net.ipv4.tcp_congestion_control=cubic \
    net.core.rmem_max=212992 net.core.wmem_max=212992 \
    net.ipv4.tcp_rmem="4096 131072 33554432" net.ipv4.tcp_wmem="4096 16384 4194304" \
    net.ipv4.tcp_slow_start_after_idle=1 net.ipv4.tcp_fastopen=1 net.ipv4.tcp_mtu_probing=0
}
c_B() {
  sudo modprobe tcp_bbr 2>/dev/null || true
  sudo sysctl -qw net.core.rmem_max=33554432 net.core.wmem_max=16777216 \
    net.ipv4.tcp_rmem="4096 262144 33554432" net.ipv4.tcp_wmem="4096 65536 16777216" \
    net.ipv4.tcp_slow_start_after_idle=0 net.ipv4.tcp_fastopen=3 net.ipv4.tcp_mtu_probing=1 \
    net.ipv4.tcp_congestion_control=bbr
}
# ── ② 被测指标 (远端单流下载; 换成 npmmirror/并发/TTFB 也可) ────────
measure() {
  curl -sL -o /dev/null -m 12 -w "%{speed_download}" \
    "https://codeload.github.com/git/git/tar.gz/refs/tags/v2.47.0"
}

CFGS=(A B)
for r in $(seq 1 "$ROUNDS"); do
  if [ $((r % 2)) -eq 1 ]; then ORD="A B"; else ORD="B A"; fi      # 奇偶交替 = 消位置效应
  for cfg in $ORD; do
    c_$cfg; sleep 1
    v=$(measure); echo "r$r $cfg $v" | tee -a "$D"
  done
done
python3 - <<'PY'
import statistics as st
rows=[l.split() for l in open('/tmp/net_ab_latin_detail.txt') if len(l.split())==3]
d={}
for _,c,v in rows: d.setdefault(c,[]).append(float(v))
A=d['A']; B=d['B']
print("A 中位 %8.2f MB/s  (噪声带 %.2f~%.2f = ±%.0f%%)" % (
    st.median(A)/1048576, min(A)/1048576, max(A)/1048576, (max(A)-min(A))/2/st.median(A)*100))
print("B 中位 %8.2f MB/s  相对 A %+.1f%%  胜率 %d/%d" % (
    st.median(B)/1048576, (st.median(B)/st.median(A)-1)*100,
    sum(1 for i in range(min(len(A),len(B))) if B[i]>A[i]), len(A)))
print("判据: 胜率>=5/6 且中位增益 > 噪声带 → 才可写'有提升'; 否则写'无可测收益'")
PY
c_A   # 测完恢复对照态, 不留半优化
echo "已回滚到 A: cc=$(sysctl -n net.ipv4.tcp_congestion_control) rmem_max=$(sysctl -n net.core.rmem_max)"
