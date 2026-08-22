#!/bin/bash
# Z-MAX 全量容器训练 (2026-08-08 老倪: 模型引擎强制容器) — v2 带时间戳
# 7 模型串行: ACT → SmolVLA → SmolVLA+LEW → VLA-Touch → AWE → MLP蒸馏 → 官方专家基准
cd /home/xspace/lerobot-smolvla-lew
ROOT=$(pwd)
IMG=zmax-std:1.0
LOG=/tmp/container_all_train2.log
echo "=== 全量容器训练开始 $(date +%H:%M:%S) ===" > $LOG

run_train() {
  local name=$1; shift
  echo "=== [$name] $(date +%H:%M:%S) 开始 ===" >> $LOG
  sudo -n docker run --rm --gpus all -v $ROOT:/app -w /app \
    -e PYTHONPATH=/app/src --entrypoint python $IMG "$@" >> $LOG 2>&1
  echo "=== [$name] $(date +%H:%M:%S) 完成 EXIT=$? ===" >> $LOG
}

mkcfg() {
  # $1=模板 $2=输出目录前缀: 生成 /app/config_<prefix>_ct.yaml (时间戳 output_dir)
  local tpl=$1 prefix=$2 ts=$(date +%Y%m%d_%H%M%S)
  python3 -c "
import re, sys
s = open('$tpl').read()
s = re.sub(r'(output_dir:\s*).*', 'output_dir: outputs/train/${prefix}_${ts}', s, count=1)
s = re.sub(r'(root:\s*).*', 'root: /app/data/metaworld_peg_grab6', s, count=1)
open('config_${prefix}_ct.yaml', 'w').write(s)
"
  echo "/app/config_${prefix}_ct.yaml"
}

# 1. ACT (grab6 + 无VAE)
CFG=$(mkcfg configs/policies/act/config_act_metaworld.yaml act)
run_train "ACT" -u -m lerobot.scripts.lerobot_train --config_path $CFG
# 2. SmolVLA
CFG=$(mkcfg configs/policies/smolvla/config_smolvla_metaworld.yaml smolvla)
run_train "SmolVLA" -u -m lerobot.scripts.lerobot_train --config_path $CFG
# 3. SmolVLA+LEW
CFG=$(mkcfg configs/policies/smolvla_lew/config_smolvla_lew_metaworld.yaml smolvla_lew)
run_train "SmolVLA+LEW" -u -m lerobot.scripts.lerobot_train --config_path $CFG
# 4. VLA-Touch
run_train "VLA-Touch" -u /app/tools/train_vla_touch.py --steps 2000 --data-root /app/data/metaworld_peg_grab6
# 5. AWE
run_train "AWE" -u /app/tools/train_awe_zflow.py --steps 2000 --data-root /app/data/metaworld_peg_grab6 --max-frames 6040

echo "=== 全量容器训练完成 $(date +%H:%M:%S) ===" >> $LOG
