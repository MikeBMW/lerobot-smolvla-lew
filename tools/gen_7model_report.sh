#!/bin/bash
# 七模型综合对比: 7 视频 + 7 宫格拼接 + 七模型 PDF 报告 → 发飞书 (2026-08-07)
# 纯 CPU (ffmpeg + reportlab), 不碰 GPU — smolvla_peg_v7 训练不受影响
set -e
cd /home/xspace/lerobot-smolvla-lew
V=./.venv/bin/python
TS=$(date +%Y%m%d_%H%M%S)
echo "[$(date +%H:%M)] ① 合成 7 模型单视频 (CPU)..."
mkdir -p /tmp/seven_vid
declare -A DIRS=(
  [act]=reports/rollout_final_act
  [smolvla]=reports/rollout_final_smolvla
  [smolvla_lew]=reports/rollout_final_smolvla_lew
  [vla_touch]=reports/rollout_final_vla_touch
  [awe_zflow]=reports/rollout_final_awe_zflow
  [expert_mlp]=reports/rollout_mlp
  [expert_policy]=reports/rollout_expert_full
)
for p in act smolvla smolvla_lew vla_touch awe_zflow expert_mlp expert_policy; do
  d=${DIRS[$p]}
  n=$(ls $d/frame_*.png 2>/dev/null | wc -l)
  echo "  [$p] $n 帧 ← $d"
  ffmpeg -y -loglevel error -framerate 20 -pattern_type glob -i "$d/frame_*.png" \
    -vf "scale=320:240" -c:v libx264 -pix_fmt yuv420p -preset veryfast \
    /tmp/seven_vid/$p.mp4
done
echo "[$(date +%H:%M)] ② 7 宫格拼接 (3列×3行, 末行居中)..."
ffmpeg -y -loglevel error \
  -i /tmp/seven_vid/act.mp4 -i /tmp/seven_vid/smolvla.mp4 -i /tmp/seven_vid/smolvla_lew.mp4 \
  -i /tmp/seven_vid/vla_touch.mp4 -i /tmp/seven_vid/awe_zflow.mp4 \
  -i /tmp/seven_vid/expert_mlp.mp4 -i /tmp/seven_vid/expert_policy.mp4 \
  -filter_complex "[0:v][1:v][2:v][3:v][4:v][5:v][6:v]xstack=inputs=7:layout=0_0|320_0|640_0|0_240|320_240|640_240|320_480[v]" \
  -map "[v]" -c:v libx264 -pix_fmt yuv420p -loglevel error \
  reports/七模型对比_rollout_${TS}.mp4
echo "  ✅ 七模型对比视频: reports/七模型对比_rollout_${TS}.mp4"
echo "[$(date +%H:%M)] ③ 生成七模型 PDF 报告 (CPU)..."
$V - <<'EOF'
import sys, os, glob
sys.path.insert(0, "/home/xspace/lerobot-smolvla-lew/tools")
os.chdir("/home/xspace/lerobot-smolvla-lew")
import generate_report as gr
curves = gr.load_curves()
rollout_have = {}
for p in gr.MODELS:
    n = len(glob.glob(f"reports/rollout_{p}/frame_*.png"))
    if not n:
        for d in ("rollout_final_", "rollout_peg_"):
            n = len(glob.glob(f"reports/{d}{p}/frame_*.png"))
            if n:
                break
    if n:
        rollout_have[p] = n
print(f"rollout 证据: {rollout_have}")
out = "reports/七模型对比技术选型报告_20260807.pdf"
gr.build_pdf(None, curves, rollout_have, out)
print(f"✅ 报告: {out} ({os.path.getsize(out)//1024}KB)")
EOF
echo "[$(date +%H:%M)] ④ 发飞书 dataworld 群..."
python3 - <<EOF
import json, os, urllib.request
env = {}
for line in open(os.path.expanduser("~/.hermes/.env"), encoding="utf-8"):
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k] = v
CHAT = env.get("FEISHU_REPORT_CHAT_ID", "oc_c0b4048546145c5c581ddd1a9e8f565d")
def post(url, data, headers=None):
    req = urllib.request.Request(url, data=json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    return json.loads(urllib.request.urlopen(req, timeout=20).read())
tok = post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
           {"app_id": env["FEISHU_APP_ID"], "app_secret": env["FEISHU_APP_SECRET"]})["tenant_access_token"]
H = {"Authorization": "Bearer " + tok}
def send_file(path, note):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        print("跳过:", path); return
    ft = "stream" if path.endswith(".mp4") else "pdf"
    boundary = "----sevenzmax"
    with open(path, "rb") as f:
        content = f.read()
    body = (("--" + boundary + "\r\nContent-Disposition: form-data; name=\"file_type\"\r\n\r\n" + ft + "\r\n"
             + "--" + boundary + "\r\nContent-Disposition: form-data; name=\"file_name\"\r\n\r\n"
             + os.path.basename(path) + "\r\n"
             + "--" + boundary + "\r\nContent-Disposition: form-data; name=\"file\"; filename=\""
             + os.path.basename(path) + "\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode() + content + (
             "\r\n--" + boundary + "--\r\n").encode())
    req = urllib.request.Request("https://open.feishu.cn/open-apis/im/v1/files", data=body,
                                 headers={**H, "Content-Type": "multipart/form-data; boundary=" + boundary})
    r = json.loads(urllib.request.urlopen(req, timeout=120).read())
    fk = r.get("data", {}).get("file_key")
    if not fk:
        print("上传失败:", path, r.get("msg")); return
    r2 = post("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
              {"receive_id": CHAT, "msg_type": "file", "content": json.dumps({"file_key": fk})}, H)
    post("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
         {"receive_id": CHAT, "msg_type": "text", "content": json.dumps({"text": note})}, H)
    print("✅", os.path.basename(path), os.path.getsize(path), "|", r2.get("code"))
import glob as _g
cmp = sorted(_g.glob("reports/七模型对比_rollout_*.mp4"), key=os.path.getmtime)
if cmp:
    send_file(cmp[-1], "🎬 七模型插拔对比 (3×3同屏): ACT/SmolVLA/SmolVLA+LEW/VLA-Touch/AWE/MLP蒸馏/官方专家\nMLP 抓起✅插入✅距孔0.020m · 专家🏆抓起✅插入✅距孔0.011m(85%真值)")
send_file("reports/七模型对比技术选型报告_20260807.pdf",
          "📄 七模型综合对比报告: 含评分公式(8维加权) · 每模型优劣势 · 能力矩阵 · 真值锚点说明")
print("== 发送完成 ==")
EOF
echo "[$(date +%H:%M)] 全部完成 (训练未受影响: $(pgrep -f lerobot_train >/dev/null && echo 'smolvla_peg_v7 仍在跑 ✅' || echo '⚠ 训练进程不在'))"
