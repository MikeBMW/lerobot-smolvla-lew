#!/bin/bash
# 修 L4 新权重的"可用性": INTACT 官方加载器要求**目录里恰好一个 .pt**;
#   intact_goal_optical_insert_v6lora_200/ 里有 weights_epoch_1.pt + weights_merged.pt (+我加的软链) → Ambiguous → trained=False
# 纪律: 不动训练产物本身; 另建**指针目录**(只有 config.json + weights.pt 软链), 与在役 intact_l4_current 同构
set -e
SWM=/home/ubuntu/stable-wm-cache/checkpoints
ART=$SWM/intact_goal_optical_insert_v6lora_200
PTR=$SWM/intact_l4_v6lora_200

rm -f "$ART/weights.pt"                       # 还原产物目录原状 (不在产物里塞软链)
mkdir -p "$PTR"
cp -f "$ART/config.json" "$PTR/config.json"
ln -sfn "$ART/weights_epoch_1.pt" "$PTR/weights.pt"
echo "指针目录: $PTR"
ls -l "$PTR"

echo "== 用 worker 验证 trained/dims =="
INTACT_POLICY=intact_l4_v6lora_200 INTACT_DEVICE=cpu INTACT_RUNTIME=root \
STABLEWM_HOME=/home/ubuntu/stable-wm-cache LOCAL_DATASET_DIR=/home/ubuntu/stable-wm-cache \
HF_HUB_OFFLINE=1 MUJOCO_GL=egl /home/ubuntu/INTACT-JEPA/.venv/bin/python - <<'PY'
import json, subprocess, os
env = {**os.environ}
p = subprocess.Popen(["/home/ubuntu/INTACT-JEPA/.venv/bin/python",
                      "/home/ubuntu/lerobot-smolvla-lew/tools/intact_worker.py",
                      "--repo", "/home/ubuntu/INTACT-JEPA", "--task", "optical_insert",
                      "--hf-repo", "INTACT-JEPA/INTACT", "--hf-rev", "paper-e5-goal-v1",
                      "--policy", "direct", "--policy-name", "intact_l4_v6lora_200",
                      "--device", "cpu", "--runtime", "root"],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env=env)
p.stdin.write('{"cmd":"hello"}\n'); p.stdin.flush()
for _ in range(200):
    ln = p.stdout.readline()
    if not ln:
        break
    try:
        j = json.loads(ln); print("hello:", json.dumps(j, ensure_ascii=False)[:300]); break
    except Exception:
        continue
p.kill()
PY
