#!/bin/bash
# post_lora_merge.sh — LoRA 训练产物"可部署化"收尾 (2026-09-23 老倪: 训练完必须能真加载/真对比)
#   1) 把包装键 (xxx.lora_A/.lora_B/.base.*) merge 回原始命名 (W = W_base + (alpha/r)·B@A)
#   2) 建"稳定指针目录" checkpoints/<policy> = config.json + 唯一 weights.pt 软链 (与在役 intact_l4_current 同构)
#   3) 用 tools/intact_worker.py 发 {"cmd":"hello"} 自证 trained=True/action_dim=8 (不过关就退非 0)
# 用法: bash tools/post_lora_merge.sh <训练产物目录名> [指针目录名] [r] [alpha]
#   例: bash tools/post_lora_merge.sh intact_goal_optical_insert_v6lora_200 intact_l4_v6lora_200 8 16
set -u
SWM=/home/ubuntu/stable-wm-cache
ART_DIR=$SWM/checkpoints/${1:?用法: post_lora_merge.sh <产物目录名> [指针名] [r] [alpha]}
POLICY=${2:-intact_l4_${1}}
R=${3:-8}
ALPHA=${4:-16}
IVENV=/home/ubuntu/INTACT-JEPA/.venv/bin/python
REPO=/home/ubuntu/lerobot-smolvla-lew

LATEST=$(ls -t $ART_DIR/weights_epoch_*.pt 2>/dev/null | head -1)
[ -z "$LATEST" ] && { echo "❌ $ART_DIR 里没有 weights_epoch_*.pt"; exit 2; }
echo "产物目录: $ART_DIR"
echo "最新权重: $(basename $LATEST)"

$IVENV $REPO/tools/merge_lora_ckpt.py --in "$LATEST" \
      --out "$ART_DIR/weights_merged_clean.pt" --r "$R" --alpha "$ALPHA" || exit 3

PTR=$SWM/checkpoints/$POLICY
mkdir -p "$PTR"
cp -f "$ART_DIR/config.json" "$PTR/config.json"
rm -f "$PTR/weights.pt"
ln -sfn "$ART_DIR/weights_merged_clean.pt" "$PTR/weights.pt"
rm -f "$ART_DIR/weights.pt"          # 产物目录不留多余软链 (官方加载器要求"恰好一个 .pt")
echo "指针目录: $PTR"; ls -l "$PTR"

echo "== 自证 (引擎口径: task=pusht + INTACT_POLICY=$POLICY) =="
STABLEWM_HOME=$SWM LOCAL_DATASET_DIR=$SWM INTACT_DEVICE=cpu INTACT_RUNTIME=root HF_HUB_OFFLINE=1 \
MUJOCO_GL=egl INTACT_POLICY=$POLICY $IVENV - <<PY
import json, subprocess, os
p = subprocess.Popen(["/home/ubuntu/INTACT-JEPA/.venv/bin/python",
                      "/home/ubuntu/lerobot-smolvla-lew/tools/intact_worker.py",
                      "--repo", "/home/ubuntu/INTACT-JEPA", "--task", "pusht",
                      "--hf-repo", "INTACT-JEPA/INTACT", "--hf-rev", "paper-e5-goal-v1",
                      "--policy", "direct", "--policy-name", os.environ["INTACT_POLICY"],
                      "--device", "cpu", "--runtime", "root"],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                     text=True, bufsize=1, env={**os.environ})
p.stdin.write('{"cmd":"hello"}\n'); p.stdin.flush()
for _ in range(400):
    ln = p.stdout.readline()
    if not ln:
        break
    try:
        j = json.loads(ln)
    except Exception:
        continue
    print("hello:", json.dumps({k: j.get(k) for k in ("trained", "dims", "reason")}, ensure_ascii=False)[:300])
    p.kill()
    raise SystemExit(0 if j.get("trained") else 4)
p.kill(); raise SystemExit(5)
PY
