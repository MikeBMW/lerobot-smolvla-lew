#!/usr/bin/env python3
"""📤 飞书发【纯文本】消息到 dataworld 群 (2026-09-08 v5.3.0 发布实测)

配套 templates/send_feishu.py (发文件/视频版) 的 text-only 变体。
用法: python3 send_feishu_text.py "消息内容"  → 回执 code=0 success
凭据自动读 ~/.hermes/.env (FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_REPORT_CHAT_ID,
缺省 chat = oc_c0b4048546145c5c581ddd1a9e8f565d dataworld 群)。
发布流程两个时机用: tag 推送后发"发布启动", CI 完成+资产验证后发"下载链接"。
"""
import json, urllib.request, os, sys

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

def main():
    env = load_env()
    app_id, app_secret = env["FEISHU_APP_ID"], env["FEISHU_APP_SECRET"]
    chat_id = env.get("FEISHU_REPORT_CHAT_ID", "oc_c0b4048546145c5c581ddd1a9e8f565d")
    text = sys.argv[1] if len(sys.argv) > 1 else "test"
    r = post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
             {"app_id": app_id, "app_secret": app_secret})
    tok = r.get("tenant_access_token")
    if not tok:
        print("❌ token 失败", r); sys.exit(1)
    H = {"Authorization": "Bearer " + tok}
    r2 = post("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
              {"receive_id": chat_id, "msg_type": "text",
               "content": json.dumps({"text": text}, ensure_ascii=False)}, headers=H)
    print("✅" if r2.get("code") == 0 else "❌", "feishu:", r2.get("code"), r2.get("msg"))

if __name__ == "__main__":
    main()
