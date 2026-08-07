#!/bin/bash
# 恢复 act/smolvla/smolvla_lew 曲线 — 复刻 GUI config 生成 + 训练 + 落盘 (2026-08-07)
# 后台串行: act(~1min) → smolvla → smolvla_lew (各 1000 步, 自动落盘 train_curve_*.json)
cd /home/xspace/lerobot-smolvla-lew
V=./.venv/bin/python
echo "[$(date +%H:%M)] 曲线恢复链启动 (act→smolvla→smolvla_lew)..."

train_one() {
    local policy=$1 cfg_src=$2
    local ts_dir="${policy}_$(date +%Y%m%d_%H%M%S)"
    local tmp_cfg="config_${policy}_restore.yaml"
    echo "[$(date +%H:%M)] ① $policy 1000 步..."
    # 生成 runtime config (复刻 GUI on_train: 改 output_dir/job_name/steps)
    $V - "$cfg_src" "$ts_dir" "$tmp_cfg" <<'EOF'
import re, sys
cfg_src, ts_dir, tmp_cfg = sys.argv[1], sys.argv[2], sys.argv[3]
cfg = open(cfg_src, encoding="utf-8").read()
cfg = re.sub(r"(output_dir:\s*).*", f"output_dir: outputs/train/{ts_dir}", cfg, count=1)
cfg = re.sub(r"(job_name:\s*).*", f"job_name: {ts_dir}", cfg, count=1)
cfg = re.sub(r"^steps:\s*.*", "steps: 1000", cfg, count=1, flags=re.M)
open(tmp_cfg, "w", encoding="utf-8").write(cfg)
print("cfg ok:", tmp_cfg)
EOF
    $V -m lerobot.scripts.lerobot_train --config_path "$tmp_cfg" > /tmp/restore_$policy.log 2>&1
    $V - "$policy" <<'EOF'
import re, json, os, time, sys
policy = sys.argv[1]
log = open(f"/tmp/restore_{policy}.log", encoding="utf-8").read()
# 🐛 2026-08-07: lerobot 日志 "step:1K" (1000 步) → 先展开 K 后缀, 避免 step=1 误解析
log = re.sub(r"step:(\d+)K\b", r"step:\1" + "000", log)
pts = []
for m in re.finditer(r"step[:=]?\s*(\d+)\b.*?loss[=:\s]+([\d.eE+-]+)", log):
    pts.append([int(m.group(1)), float(m.group(2))])
if not pts:
    for m in re.finditer(r"loss[=:\s]+([\d.eE+-]+).*?step[:=]?\s*(\d+)\b", log):
        pts.append([int(m.group(2)), float(m.group(1))])
seen, uniq = set(), []
for s, l in pts:
    if s not in seen:
        seen.add(s); uniq.append([s, l])
ms = re.search(r"([\d.]+) step/s", log)
json.dump({"policy": policy, "ts": time.strftime("%Y%m%d_%H%M%S"), "curve": sorted(uniq),
           "step_s": float(ms.group(1)) if ms else 0, "ckpt": f"outputs/train/{policy}_latest/checkpoints",
           "note": "1000 步恢复重训"}, open(f"reports/train_curve_{policy}.json", "w"), ensure_ascii=False)
print(f"  ✅ {policy}: {len(uniq)} 点")
EOF
}

train_one act config_act_metaworld.yaml
train_one smolvla config_smolvla_metaworld.yaml
train_one smolvla_lew config_smolvla_lew_metaworld.yaml
echo "[$(date +%H:%M)] 曲线恢复全部完成"
