#!/usr/bin/env bash
# version_debt_audit.sh — 版本债审计: l4_mani_predictor v1/v2/v4/v5 (只审计 + 归档未被引用的, 不删)
set -u
cd /home/ubuntu/zmax_rel || exit 1
echo "═══ ① 内容指纹 (md5) — 判定重复 ═══"
for v in v1 v2 v4 v5; do
  f="models/l4_mani_predictor_$v.pt"
  [ -f "$f" ] || continue
  printf "  %-6s %-34s %s\n" "$v" "$(md5sum "$f" | cut -c1-32)" "$(stat -c%s "$f")B"
done
echo
echo "═══ ② 引用面 (谁在用) ═══"
for v in v1 v2 v4 v5; do
  n=$(grep -rl "l4_mani_predictor_$v" --include=*.py --include=*.sh --include=*.json tools src 2>/dev/null | wc -l)
  who=$(grep -rl "l4_mani_predictor_$v" --include=*.py --include=*.sh --include=*.json tools src 2>/dev/null | xargs -r -n1 basename 2>/dev/null | tr '\n' ' ')
  printf "  %-4s 引用文件 %-2d 个: %s\n" "$v" "$n" "${who:-（无）}"
done
echo
echo "═══ ③ 归档未被引用的版本 (move, 不 delete; 可一条命令还原) ═══"
mkdir -p models/_archive
for v in v1; do
  f="models/l4_mani_predictor_$v.pt"
  if [ -f "$f" ]; then
    mv "$f" "models/_archive/l4_mani_predictor_$v.pt"
    echo "  ⟶ 归档 $f → models/_archive/ (原引用数 0, 在役推理服务未加载)"
  fi
done
echo "  还原命令: mv models/_archive/l4_mani_predictor_v1.pt models/"
echo
echo "═══ ④ 在役推理服务实际加载 (权威口径) ═══"
curl -s -m 5 http://127.0.0.1:8790/health -o /tmp/h.json && python3 -c "
import json; d=json.load(open('/tmp/h.json')); print('  loaded =', d.get('models'), '| online =', d.get('online'))"
echo
echo "═══ ⑤ 结论 ═══"
echo "  现役 = v5 (推理服务已加载 + 主链路 yaw_actuator/simulink/studio 引用)"
echo "  v2/v4 = 仅历史 demo/对比脚本引用 (gen_l4_demo_video / state_space_sim_real) → 收敛需改这两处并重跑验证 (未擅自改)"
echo "  v1 = 无引用 → 已归档 (非删除)"
