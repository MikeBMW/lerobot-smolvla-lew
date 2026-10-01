#!/usr/bin/env bash
# 手机远程操作 · 端到端往返实测 —— 走的就是手机页那条路:
#   手机 → POST /agent/prompt (ECS 中转) → 本机桥轮询取走 → 执行(只读白名单) → POST /agent/reply → 手机看到
# 老倪 2026-10-01「手机操作太慢, 反馈不及时」⇒ 用实测数字量化, 不靠感觉。
set -u
R="https://datadrive.world/api/relay"
TAG="hermes_latency_$(date +%s)"

echo "══ ① 中转读口是否通(拿当前游标) ══"
CUR=$(curl -s -m 8 "$R/agent/prompt?after=999999999" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('cursor') or d.get('pending') or 0)" 2>/dev/null)
echo "   读口 200 · cursor=$CUR"

echo "══ ② 发一条**只读**指令(状态) 并计时 ══"
T0=$(date +%s.%N)
RESP=$(curl -s -m 10 -X POST "$R/agent/prompt" -H 'Content-Type: application/json' \
        --data "{\"text\":\"状态\",\"from\":\"$TAG\"}" 2>&1)
echo "   POST 返回: $(echo "$RESP" | head -c 160)"
SEQ=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('seq',''))" 2>/dev/null)

echo "══ ③ 等回执(每 0.2s 查一次, 最多 30s) ══"
for i in $(seq 1 150); do
  RPY=$(curl -s -m 6 "$R/agent/reply?after=0" 2>/dev/null | python3 -c "
import sys,json
try: d=json.load(sys.stdin)
except Exception: sys.exit(0)
for it in (d.get('replies') or []):
    if it.get('prompt_seq') == $SEQ or '$TAG' in json.dumps(it): print(json.dumps(it,ensure_ascii=False)[:200]); break
" 2>/dev/null)
  if [ -n "$RPY" ]; then
    T1=$(date +%s.%N)
    echo "   ✅ 回执到达: $RPY"
    echo ""
    printf "   ★ 端到端往返(指令→回执可见) = %.2f 秒\n" "$(echo "$T1 - $T0" | bc)"
    exit 0
  fi
  sleep 0.2
done
echo "   ✗ 30s 内没等到回执(seq=$SEQ) ⇒ 需要查这道环节"
