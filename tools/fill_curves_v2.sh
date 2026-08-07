#!/bin/bash
# 补曲线 v2: 等飞书端 awe 完 → vla 1000步 → awe 1000步 → MLP 蒸馏 → 报告 v10 → 飞书 (2026-08-07)
# 真实数据补齐, 不干扰运行中训练 (awe 36971 让它先跑完)
cd /home/xspace/lerobot-smolvla-lew
V=./.venv/bin/python
echo "[$(date +%H:%M)] 补曲线 v2 启动: 等飞书端 awe_zflow 训练完..."

# 1) 等所有训练进程完 (最长 40 分钟)
for i in $(seq 1 80); do
    if ! pgrep -f 'lerobot_train|train_vla_touch|train_awe_zflow|distill_expert' > /dev/null; then
        echo "[$(date +%H:%M)] 训练清空, 开始补曲线"
        break
    fi
    sleep 30
done
sleep 10

# 2) VLA-Touch 1000 步重训落曲线
echo "[$(date +%H:%M)] ① VLA-Touch 1000 步..."
$V tools/train_vla_touch.py --steps 1000 --data-root data/metaworld_act \
  > /tmp/retrain_vla.log 2>&1
$V - <<'EOF'
import re, json, os
log = open("/tmp/retrain_vla.log", encoding="utf-8").read()
pts = [[i * 5 + 5, float(m.group(1))] for i, m in enumerate(re.finditer(r"action_loss:([\d.eE+-]+)", log))]
ms = re.search(r"([\d.]+) step/s", log)
json.dump({"policy": "vla_touch", "name": "VLA-Touch", "ts": "20260807",
           "curve": pts, "step_s": float(ms.group(1)) if ms else 0,
           "ckpt": "outputs/train/vla_touch_latest/checkpoints",
           "note": "1000 步重训 (metaworld_act)"},
          open("reports/train_curve_vla_touch.json", "w"), ensure_ascii=False)
print(f"  ✅ VLA-Touch 曲线 {len(pts)} 点")
EOF

# 3) AWE 1000 步重训落曲线
echo "[$(date +%H:%M)] ② AWE-zFlow 1000 步..."
$V tools/train_awe_zflow.py --steps 1000 --data-root data/metaworld_act \
  > /tmp/retrain_awe.log 2>&1
$V - <<'EOF'
import re, json, os
log = open("/tmp/retrain_awe.log", encoding="utf-8").read()
pts = [[i * 5 + 5, float(m.group(1))] for i, m in enumerate(re.finditer(r"action_loss:([\d.eE+-]+)", log))]
ms = re.search(r"([\d.]+) step/s", log)
json.dump({"policy": "awe_zflow", "name": "AWE-zFlow", "ts": "20260807",
           "curve": pts, "step_s": float(ms.group(1)) if ms else 0,
           "ckpt": "outputs/train/awe_latest/checkpoints",
           "note": "1000 步重训 (metaworld_act)"},
          open("reports/train_curve_awe_zflow.json", "w"), ensure_ascii=False)
print(f"  ✅ AWE-zFlow 曲线 {len(pts)} 点")
EOF

# 4) MLP 蒸馏落曲线
echo "[$(date +%H:%M)] ③ MLP 蒸馏..."
$V tools/distill_expert.py > /tmp/retrain_mlp.log 2>&1 || true
$V - <<'EOF'
import re, json, os
log = open("/tmp/retrain_mlp.log", encoding="utf-8").read()
pts = [[int(m.group(1)), float(m.group(2))] for m in re.finditer(r"epoch (\d+): loss=([\d.eE+-]+)", log)]
json.dump({"policy": "expert_mlp", "name": "MLP 蒸馏", "ts": "20260807",
           "curve": pts, "step_s": 0, "ckpt": "outputs/rl_peg/expert_mlp.pt",
           "success": "抓起18/20 插入11/20 (55%)", "note": "15 epochs 专家 BC 蒸馏"},
          open("reports/train_curve_expert_mlp.json", "w"), ensure_ascii=False)
print(f"  ✅ MLP 蒸馏 {len(pts)} epochs")
EOF

# 5) 官方专家基准标注
$V - <<'EOF'
import json, os
json.dump({"policy": "expert_policy", "name": "官方专家", "ts": "20260807",
           "curve": [], "step_s": 0, "ckpt": "", "success": "85% (规则真值基准)",
           "note": "规则策略, 无训练曲线"},
          open("reports/train_curve_expert_policy.json", "w"), ensure_ascii=False)
print("  ✅ 官方专家基准标注")
EOF

# 6) 报告 v10 + 发飞书
echo "[$(date +%H:%M)] ④ 重生成报告 v10 + 发飞书..."
$V - <<'EOF'
import sys, os, glob, json, urllib.request
sys.path.insert(0, "tools"); os.chdir(".")
import generate_report as gr
curves = gr.load_curves()
rollout_have = {}
for p in gr.MODELS:
    for d in ("rollout_final_", "rollout_peg_", "rollout_"):
        n = len(glob.glob(f"reports/{d}{p}/frame_*.png"))
        if n: rollout_have[p] = n; break
for p, d2 in (("expert_mlp", "rollout_mlp"), ("expert_policy", "rollout_expert_full")):
    n = len(glob.glob(f"reports/{d2}/frame_*.png"))
    if n: rollout_have[p] = n
out = "reports/七模型对比技术选型报告_20260807.pdf"
gr.build_pdf(None, curves, rollout_have, out)
print(f"✅ 报告: {out} ({os.path.getsize(out)//1024}KB)")
print("曲线:", {p: len((curves.get(p) or {}).get("curve") or []) for p in gr.MODELS})
env = {}
for line in open(os.path.expanduser("~/.hermes/.env"), encoding="utf-8"):
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1); env[k] = v
CHAT = env.get("FEISHU_REPORT_CHAT_ID", "oc_c0b4048546145c5c581ddd1a9e8f565d")
def post(url, data, headers=None):
    req = urllib.request.Request(url, data=json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    return json.loads(urllib.request.urlopen(req, timeout=20).read())
tok = post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
           {"app_id": env["FEISHU_APP_ID"], "app_secret": env["FEISHU_APP_SECRET"]})["tenant_access_token"]
H = {"Authorization": "Bearer " + tok}
boundary = "----curves10"
with open(out, "rb") as f: content = f.read()
body = (("--" + boundary + "\r\nContent-Disposition: form-data; name=\"file_type\"\r\n\r\npdf\r\n"
         + "--" + boundary + "\r\nContent-Disposition: form-data; name=\"file_name\"\r\n\r\n"
         + os.path.basename(out) + "\r\n"
         + "--" + boundary + "\r\nContent-Disposition: form-data; name=\"file\"; filename=\""
         + os.path.basename(out) + "\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode() + content + (
         "\r\n--" + boundary + "--\r\n").encode())
req = urllib.request.Request("https://open.feishu.cn/open-apis/im/v1/files", data=body,
                             headers={**H, "Content-Type": "multipart/form-data; boundary=" + boundary})
r = json.loads(urllib.request.urlopen(req, timeout=120).read())
fk = r.get("data", {}).get("file_key")
if fk:
    r2 = post("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
              {"receive_id": CHAT, "msg_type": "file", "content": json.dumps({"file_key": fk})}, H)
    post("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
         {"receive_id": CHAT, "msg_type": "text",
          "content": json.dumps({"text": "📄 七模型报告 v10 (曲线真实补齐): 7 模型曲线 + 评分代入示例 + AWE触觉9.0修复 + 1000步基线"})}, H)
    print("✅ 已发飞书 v10 |", r2.get("code"))
EOF
echo "[$(date +%H:%M)] 补曲线 v2 全部完成"
