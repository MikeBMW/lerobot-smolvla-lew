#!/usr/bin/env python3
"""飞书发送工具 (2026-09-07) — 文本消息 + 可选视频文件 → dataworld 群
用法: python3 tools/send_feishu.py "文本" [视频路径]
"""
import json, os, sys, urllib.request

def load_env():
    env = {}
    p = os.path.expanduser("~/.hermes/.env")
    if os.path.isfile(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env

def post(url, data=None, headers=None, raw=None, ctype=None):
    hdrs = dict(headers or {})
    if data is not None and "Content-Type" not in hdrs:
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=raw if raw is not None else
                                 (json.dumps(data).encode() if data is not None else None),
                                 headers=hdrs, method="POST")
    if ctype:
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "body": e.read().decode()[:300]}
    except Exception as e:
        return {"error": str(e)}

def main():
    text = sys.argv[1] if len(sys.argv) > 1 else "静静报告"
    video = sys.argv[2] if len(sys.argv) > 2 else None
    env = load_env()
    app_id, app_secret = env.get("FEISHU_APP_ID", ""), env.get("FEISHU_APP_SECRET", "")
    chat_id = env.get("FEISHU_REPORT_CHAT_ID", "oc_c0b4048546145c5c581ddd1a9e8f565d")
    if not app_id or not app_secret:
        print("❌ .env 缺 FEISHU_APP_ID/SECRET"); return 1
    tok = post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
               {"app_id": app_id, "app_secret": app_secret}).get("tenant_access_token")
    if not tok:
        print("❌ token 获取失败"); return 1
    H = {"Authorization": f"Bearer {tok}"}
    # 1) 文本
    r = post("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
             {"receive_id": chat_id, "msg_type": "text",
              "content": json.dumps({"text": text}, ensure_ascii=False)}, H)
    print("文本:", "✅" if r.get("code") == 0 else f"❌ {r}")
    # 2) 视频文件
    if video and os.path.isfile(video):
        boundary = "----zmax" + os.urandom(8).hex()
        with open(video, "rb") as f:
            body = f.read()
        head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file_type\"\r\n\r\nmp4\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file_name\"\r\n\r\n{os.path.basename(video)}\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{os.path.basename(video)}\"\r\n"
                f"Content-Type: video/mp4\r\n\r\n").encode()
        raw = head + body + f"\r\n--{boundary}--\r\n".encode()
        r2 = post("https://open.feishu.cn/open-apis/im/v1/files", None,
                  {**H, "Content-Type": f"multipart/form-data; boundary={boundary}"},
                  raw=raw)
        fk = (r2.get("data") or {}).get("file_key")
        if fk:
            # 视频/音频用 msg_type=media (file 类型只能发文档类, 230055 实锤)
            r3 = post("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
                      {"receive_id": chat_id, "msg_type": "media",
                       "content": json.dumps({"file_key": fk})}, H)
            print("视频:", "✅" if r3.get("code") == 0 else f"❌ {r3}")
        else:
            print("视频上传失败:", r2)
    return 0

if __name__ == "__main__":
    sys.exit(main())
