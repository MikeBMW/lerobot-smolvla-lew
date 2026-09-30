#!/bin/bash
# 续训链 v2: 5 模型微调续训 (加载 1000 步 checkpoint → 新目录 4000 步) — 插拔提升 (2026-08-07)
# 不用 resume 机制 (draccus resume 需 config_path 目录结构), 用 --policy.path=<ckpt> 微调续训
cd /home/xspace/lerobot-smolvla-lew
V=./.venv/bin/python
echo "[$(date +%H:%M)] 插拔续训链 v2 启动 (act→smolvla→smolvla_lew)..."

train_ft() {
    local policy=$1 cfg_src=$2 ckpt_dir=$3
    local ts_dir="${policy}_ft_$(date +%Y%m%d_%H%M%S)"
    echo "[$(date +%H:%M)] ① $policy 微调续训 (ckpt→4000步)..."
    $V - "$cfg_src" "$ts_dir" <<'EOF'
import re, sys
cfg_src, ts_dir = sys.argv[1], sys.argv[2]
cfg = open(cfg_src, encoding="utf-8").read()
cfg = re.sub(r"(output_dir:\s*).*", f"output_dir: outputs/train/{ts_dir}", cfg, count=1)
cfg = re.sub(r"(job_name:\s*).*", f"job_name: {ts_dir}", cfg, count=1)
cfg = re.sub(r"^steps:\s*.*", "steps: 4000", cfg, count=1, flags=re.M)
open(cfg_src.replace("_restore.yaml", "_ft.yaml"), "w", encoding="utf-8").write(cfg)
print("ft cfg ok")
EOF
    local rc="config_${policy}_ft.yaml"
    # --policy.path= 加载 1000 步 checkpoint 微调 (等号 CLI, 2026-08-07)
    $V -m lerobot.scripts.lerobot_train --config_path "$rc" \
        --policy.path="$ckpt_dir/checkpoints/$(ls $ckpt_dir/checkpoints | grep -E '^[0-9]+$' | sort -n | tail -1)/pretrained_model" \
        > /tmp/ft_$policy.log 2>&1
    if grep -qE "FileExistsError|Traceback \(most recent|Error:" /tmp/ft_$policy.log; then
        echo "  ❌ $policy 续训失败 (见 /tmp/ft_$policy.log)"; return 1
    fi
    # 合并曲线: 旧 1000 步 + 新 (step 偏移 +1000, 因为新训练从 0 开始)
    $V - "$policy" <<'EOF'
import re, json, os, time, sys
policy = sys.argv[1]
log = open(f"/tmp/ft_{policy}.log", encoding="utf-8").read()
log = re.sub(r"step:(\d+)K\b", r"step:\1" + "000", log)
pts = {}
for m in re.finditer(r"step[:=]?\s*(\d+)\b.*?loss[=:\s]+([\d.eE+-]+)", log):
    pts[1000 + int(m.group(1))] = float(m.group(2))  # 新训练步偏移 +1000
if not pts:
    for m in re.finditer(r"loss[=:\s]+([\d.eE+-]+).*?step[:=]?\s*(\d+)\b", log):
        pts[1000 + int(m.group(2))] = float(m.group(1))
old = json.load(open(f"reports/train_curve_{policy}.json"))
for s, l in old.get("curve", []):
    pts.setdefault(int(s), l)
curve = sorted(pts.items())
json.dump({"policy": policy, "ts": time.strftime("%Y%m%d_%H%M%S"), "curve": curve,
           "step_s": 0, "ckpt": f"outputs/train/{policy}_latest/checkpoints",
           "note": "微调续训至 4000 步 (插拔提升)"},
          open(f"reports/train_curve_{policy}.json", "w"), ensure_ascii=False)
print(f"  ✅ {policy}: {len(curve)} 点 尾={curve[-1]}")
EOF
}

train_ft act configs/policies/act/config_act_restore.yaml outputs/train/act_20260807_153646
train_ft smolvla configs/policies/smolvla/config_smolvla_restore.yaml outputs/train/smolvla_20260807_153759
train_ft smolvla_lew configs/policies/smolvla_lew/config_smolvla_lew_restore.yaml outputs/train/smolvla_lew_20260807_154617
echo "[$(date +%H:%M)] lerobot 系微调续训完成 (act/smolvla/lew)"
