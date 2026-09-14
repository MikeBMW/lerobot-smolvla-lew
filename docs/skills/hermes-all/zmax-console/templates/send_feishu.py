#!/usr/bin/env python3
"""📤 飞书发文件到 dataworld 群 — 可复用模板 (2026-08-09 实测通过)

要点 (踩坑记录见 zmax-console references/remote-training-debugging.md 第13节):
- mp4 必须 msg_type="media" (视频消息), 用 "file" → 230055 类型不匹配
- multipart 与 JSON post 都要显式 Content-Length, 否则 urllib HTTP 400
- 上传成功标志 r2["data"]["file_key"]
用法: 改 ROOT 下文件清单 + send_file 调用即可; 凭据自动读 ~/.hermes/.env (FEISHU_APP_ID/SECRET/REPORT_CHAT_ID)
"""
import json, urllib.request, urllib.error, os, sys

def load_env():
    env = {}
    p = os.path.expanduser("~/.hermes/.env")
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k] = v
    return env

def post(url, data, headers=None):
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json",
                                          "Content-Length": str(len(body)), **(headers or {})})
    return json.loads(urllib.request.urlopen(req, timeout=15).read())

def send_file(env, path, text_msg, file_type):
    app_id, app_secret = env["FEISHU_APP_ID"], env["FEISHU_APP_SECRET"]
    chat_id = env.get("FEISHU_REPORT_CHAT_ID", "oc_c0b4048546145c5c581ddd1a9e8f565d")
    r = post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
             {"app_id": app_id, "app_secret": app_secret})
    tok = r.get("tenant_access_token")
    if not tok:
        print(f"❌ {path}: token 失败 {r}")
        return False
    H = {"Authorization": "Bearer " + tok}
    boundary = "----zmaxfile"
    fname = os.path.basename(path)
    with open(path, "rb") as f:
        content = f.read()
    body = (("--" + boundary + "\r\n"
             "Content-Disposition: form-data; name=\"file_type\"\r\n\r\n" + file_type + "\r\n" +
             "--" + boundary + "\r\n"
             "Content-Disposition: form-data; name=\"file_name\"\r\n\r\n" + fname + "\r\n" +
             "--" + boundary + "\r\n"
             "Content-Disposition: form-data; name=\"file\"; filename=\"" + fname + "\"\r\n"
             "Content-Type: application/octet-stream\r\n\r\n").encode() + content + ("\r\n--" + boundary + "--\r\n").encode())
    req = urllib.request.Request("https://open.feishu.cn/open-apis/im/v1/files",
                                 data=body, headers={"Content-Type": "multipart/form-data; boundary=" + boundary,
                                                     "Content-Length": str(len(body)), **H})
    try:
        r2 = json.loads(urllib.request.urlopen(req, timeout=30).read())
    except urllib.error.HTTPError as e:
        print(f"❌ 上传 400: {e.read().decode()[:200]}")
        return False
    if r2.get("code") != 0:
        print(f"❌ 上传失败: {r2}")
        return False
    fkey = r2["data"]["file_key"]
    # mp4 → media(视频)消息; 其他 → file 消息 (飞书 230055: 上传类型须与消息类型匹配)
    msg_type = "media" if file_type == "mp4" else "file"
    post("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
         {"receive_id": chat_id, "msg_type": msg_type,
          "content": json.dumps({"file_key": fkey})}, headers=H)
    post("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
         {"receive_id": chat_id, "msg_type": "text",
          "content": json.dumps({"text": text_msg + "\n(文件: " + fname + ")"})}, headers=H)
    print(f"✅ 已发: {fname} ({len(content)/1e6:.1f}MB)")
    return True

if __name__ == "__main__":
    env = load_env()
    if not env.get("FEISHU_APP_ID"):
        print("❌ 无飞书凭据 (~/.hermes/.env)")
        sys.exit(1)
    # ==== 示例: 替换为实际文件清单 ====
    ROOT = "/home/xspace/lerobot-smolvla-lew/reports"
    send_file(env, os.path.join(ROOT, "Model Zoo_rollout_*.mp4"), "🎬 对比视频", "mp4")
    send_file(env, os.path.join(ROOT, "rollout_final_act.mp4"), "🎥 ACT rollout", "mp4")
    pdf = sorted([f for f in os.listdir(ROOT) if f.endswith(".pdf")])[-1]
    send_file(env, os.path.join(ROOT, pdf), "📄 报告", "pdf")
