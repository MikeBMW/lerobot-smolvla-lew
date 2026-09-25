#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""watch_release_build.py — 轮询 GitHub Actions 直到 Desktop 构建结束, 报结论 + Release 产物

为什么需要它: 本机**没有 `gh`**; 而打 tag 后 Windows .exe + macOS .app 要十几分钟,
人工盯不现实。凭据直接取 `~/.git-credentials`(store helper), 不打印 token。

用法:
  /home/ubuntu/INTACT-JEPA/.venv/bin/python watch_release_build.py v5.11.4
  # 或从仓库 zmax-console 技能目录拷出来跑(任何 python3 都行, 只用标准库)
"""
import json
import re
import sys
import time
import urllib.request

REPO = "MikeBMW/lerobot-smolvla-lew"
TAG = sys.argv[1] if len(sys.argv) > 1 else ""


def token() -> str:
    m = re.search(r"://([^:]+):([^@]+)@", open("/home/ubuntu/.git-credentials").read().strip())
    return m.group(2) if m else ""


TOK = token()


def api(path: str):
    req = urllib.request.Request(
        "https://api.github.com" + path,
        headers={"Authorization": f"token {TOK}", "Accept": "application/vnd.github+json"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def main() -> int:
    runs = api(f"/repos/{REPO}/actions/runs?per_page=20")["workflow_runs"]
    cand = [r for r in runs if "Desktop" in r["name"] and (not TAG or TAG in (r["head_branch"] or ""))]
    if not cand:
        print(f"❌ 没找到 tag={TAG} 的 Desktop 构建 —— 检查 tag 是否真推上去了(只提交不打 tag 不会触发)")
        return 1
    rid = cand[0]["id"]
    print(f"监控 run {rid} ({cand[0]['head_branch']}) ...", flush=True)
    for _ in range(120):                                  # 最多 ~2h
        time.sleep(60)
        try:
            d = api(f"/repos/{REPO}/actions/runs/{rid}")
        except Exception as e:                            # noqa: BLE001
            print("  轮询失败(继续):", str(e)[:80], flush=True)
            continue
        if d["status"] == "completed":
            print(f"✅ 构建结束: conclusion={d['conclusion']}", flush=True)
            break
        print(f"  [{time.strftime('%H:%M:%S')}] {d['status']} ...", flush=True)
    else:
        print("⏰ 超时未结束, 自行去 Actions 页看", flush=True)
    try:
        for j in api(f"/repos/{REPO}/actions/runs/{rid}/jobs")["jobs"]:
            print(f"  job {j['name']:34s} {j['status']:10s} {j.get('conclusion')}")
    except Exception as e:                                # noqa: BLE001
        print("  job 查询失败:", str(e)[:80])
    if TAG:
        try:
            rel = api(f"/repos/{REPO}/releases/tags/{TAG}")
            print(f"=== Release {TAG} 产物 ===")
            for a in rel.get("assets", []):
                print(f"  {a['name']:44s} {a['size']/1048576:8.1f} MB")
            print(f"  链接: {rel.get('html_url')}")
        except Exception as e:                            # noqa: BLE001
            print("  Release 查询失败:", str(e)[:120])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
