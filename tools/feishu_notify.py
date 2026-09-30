#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📨 发飞书消息 (群) — 走 open.feishu.cn tenant_access_token, 与 cron 哨兵同一条通道。

用法:
  python3 tools/feishu_notify.py --text "内容" [--chat oc_xxx] [--text-file 文件]
  不带 --chat 时: 找群名含 "静界" 的群; 仍找不到 → 列出机器人所在群名 (便于确认)

凭据: ~/.hermes/.env 里的 FEISHU_APP_ID / FEISHU_APP_SECRET (与网关同一份)。
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request

ENV_PATH = os.path.expanduser("~/.hermes/.env")


def load_env() -> dict:
    vals = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("FEISHU_APP_ID="):
                    vals["app_id"] = line.split("=", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("FEISHU_APP_SECRET="):
                    vals["app_secret"] = line.split("=", 1)[1].strip().strip('"').strip("'")
    return vals


def http_json(url: str, method: str = "GET", body=None, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"code": e.code, "msg": e.reason, "detail": e.read().decode("utf-8", "ignore")[:300]}


def get_token(app_id: str, app_secret: str) -> str:
    r = http_json("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                  method="POST", body={"app_id": app_id, "app_secret": app_secret})
    return r.get("tenant_access_token", "")


def list_chats(token: str) -> list[dict]:
    out, page = [], ""
    for _ in range(5):
        url = "https://open.feishu.cn/open-apis/im/v1/chats?page_size=50" + (f"&page_token={page}" if page else "")
        r = http_json(url, token=token)
        if r.get("code") != 0:
            print("list_chats 失败:", r)
            break
        for it in r.get("data", {}).get("items", []):
            out.append({"chat_id": it["chat_id"], "name": it.get("name", "")})
        page = r.get("data", {}).get("page_token", "")
        if not r.get("data", {}).get("has_more"):
            break
    return out


def send(token: str, chat_id: str, text: str) -> dict:
    return http_json("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
                     method="POST", token=token,
                     body={"receive_id": chat_id, "msg_type": "text",
                           "content": json.dumps({"text": text}, ensure_ascii=False)})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", default="")
    ap.add_argument("--text-file", default="")
    ap.add_argument("--chat", default=os.environ.get("FEISHU_CHAT_ID", ""))
    ap.add_argument("--keyword", default="静界")
    a = ap.parse_args()
    text = a.text or (open(a.text_file, encoding="utf-8").read() if a.text_file else "")
    if not text.strip():
        print("❌ 空文本")
        return 2
    env = load_env()
    if not env.get("app_id") or not env.get("app_secret"):
        print("❌ ~/.hermes/.env 缺 FEISHU_APP_ID / FEISHU_APP_SECRET")
        return 2
    tok = get_token(env["app_id"], env["app_secret"])
    if not tok:
        print("❌ tenant_access_token 获取失败 (凭据过期?)")
        return 2
    chat = a.chat
    if not chat:
        chats = list_chats(tok)
        hit = next((c for c in chats if a.keyword in (c.get("name") or "")), None)
        if hit is None:
            print("机器人所在群:", [c["name"] for c in chats] or "(无)")
            return 3
        chat = hit["chat_id"]
        print(f"目标群: {hit['name']} ({chat})")
    r = send(tok, chat, text)
    ok = r.get("code") == 0
    print(f"{'✅ 已发送' if ok else '❌ 发送失败'}: {r.get('msg', '')} "
          f"{'' if ok else json.dumps(r, ensure_ascii=False)[:300]}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
