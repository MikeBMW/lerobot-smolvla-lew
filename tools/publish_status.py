#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本机聚合状态 (/status/all) 发布到公网: https://datadrive.world/zmax_status.json

背景 (2026-10-01 老倪「这里怎么没有版本号硬件状态等信息」):
  手机天天看的 https://datadrive.world/st/station 是**经 ECS 反代回本机 8793** 的页面,
  而硬件/模型版本/训练/3DGS 状态只在本机 127.0.0.1:8796/status/all 上 ⇒ 手机够不着。
  本脚本用既有纯 HTTP 推送端点 ss3d_push.php(白名单只加不改)把那份 JSON 落到站点根, 页面直接 fetch。

训练「空态」兜底 (2026-10-01 老倪「手机还是看不到训练模型的状态」):
  训练跑完时 /status/all 的 training.active=False、step=0/0 ⇒ 页面那一条就空了, 但他
  随时打开都该看到"上次训练了什么"。本脚本另采最新一轮 reports/joint_train_<ts>/summary.json,
  **只增一个可选顶层字段** last_training(不改 /status/all 的服务端契约, 它由另一路维护)。

用法:
  /usr/bin/python3 tools/publish_status.py              # 采一次 + 推一次
  /usr/bin/python3 tools/publish_status.py --dry-run    # 只打印, 不推
  /usr/bin/python3 tools/publish_status.py --if-changed # (留作他用; 默认每分钟推, 保证 ts 新鲜)

产物: https://datadrive.world/zmax_status.json
状态文件: /home/ubuntu/.zmax_status_publish_state.json
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import sys
import time
import urllib.request

SRC = os.environ.get("ZMAX_STATUS_SRC", "http://127.0.0.1:8796/status/all")
PUSH = os.environ.get("SS3D_PUSH", "https://datadrive.world/ss3d_push.php")
TOKEN = os.environ.get("SS3D_TOKEN", "zmax-7ce74c7f")
FNAME = "zmax_status.json"
STATE = "/home/ubuntu/.zmax_status_publish_state.json"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JT_GLOB = os.path.join(ROOT, "reports", "joint_train_*", "summary.json")


def _get(url: str, timeout: float = 6.0) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def fetch_status(timeout: float = 6.0) -> dict:
    """取本机聚合端点; 失败抛异常(调用方决定要不要保留上一次的公网副本)。"""
    raw = _get(SRC, timeout)
    d = json.loads(raw.decode("utf-8"))
    if not isinstance(d, dict) or "hw" not in d:
        raise ValueError("上游契约不符(缺 hw): %r" % (raw[:120],))
    return d


def push(d: dict, timeout: float = 8.0) -> dict:
    body = json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    url = "%s?token=%s&f=%s" % (PUSH, TOKEN, FNAME)
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "zmax-publish-status"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _hhmm(s) -> str:
    """'2026-10-01 17:56:52' -> '17:57'; 非今天 -> '10-01 17:57'。"""
    try:
        t = time.strptime(str(s)[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:                                                         # noqa: BLE001
        return str(s)[:16]
    now = time.localtime()
    return time.strftime("%H:%M" if (t.tm_yday == now.tm_yday and t.tm_year == now.tm_year)
                         else "%m-%d %H:%M", t)


def collect_last_training():
    """最近一轮 joint_train 的汇总 ⇒ 页面「上次训练」那一行。取不到给 None(页面就不画)。"""
    try:
        cands = glob.glob(JT_GLOB)
        if not cands:
            return None
        f = max(cands, key=os.path.getmtime)                 # 最新一份 = 最近一轮
        with open(f, encoding="utf-8") as fh:
            s = json.loads(fh.read())
        rows = [r for r in (s.get("rows") or []) if isinstance(r, dict)]
        if not rows:
            return None
        # 真训过的 = 有耗时 > 0 且有 rc 的行; 主层取其中 ts 最新的一条
        trained = [r for r in rows if (r.get("secs") or 0) > 0 and r.get("rc") is not None]
        if not trained:
            trained = rows
        prim = max(trained, key=lambda r: str(r.get("ts") or ""))
        # 该轮真训过的层(按顺序去重) ⇒ 页面「上次训练 L4·L3·L2 v1001-1741 ✓17:57」
        seen, layers = set(), []
        for r in trained:
            stg = r.get("stage") or ""
            if stg and stg not in seen:
                seen.add(stg)
                layers.append(stg)
        run_id = os.path.basename(os.path.dirname(f))        # joint_train_20261001_174102
        stamp = run_id.replace("joint_train_", "")
        ver = ("v%s-%s" % (stamp[4:8], stamp[9:13])) if len(stamp) >= 13 else ("v" + stamp)
        return {
            "ts": os.path.getmtime(f),                       # 该轮汇总落盘时刻
            "at": _hhmm(s.get("generated_at") or ""),
            "run": run_id,
            "layer": prim.get("stage") or "",
            "name": prim.get("layer") or "",
            "version": ver,                                  # 极短: 批次戳 v1001-1741
            "layers": "·".join(layers),                      # 真训过的层, 如 L4·L3·L2
            "steps": s.get("steps") or 0,
            "ok": all((r.get("rc") == 0) for r in trained),
            "stages": [{"stage": r.get("stage") or "", "name": r.get("layer") or "",
                        "rc": r.get("rc"), "secs": r.get("secs"),
                        "ts": r.get("ts") or "",
                        "art": [os.path.basename(str(e.get("path") or "").rstrip("/"))
                                for e in (r.get("evidence") or []) if isinstance(e, dict)]}
                       for r in rows],
        }
    except Exception:                                                         # noqa: BLE001
        return None


def read_state() -> dict:
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.loads(f.read())
    except Exception:                                                         # noqa: BLE001
        return {}


def write_state(d: dict) -> None:
    try:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    except Exception as e:                                                    # noqa: BLE001
        print("[warn] 状态文件写失败: %s" % e, file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只打印, 不推")
    ap.add_argument("--if-changed", action="store_true", help="内容 md5 未变则跳过")
    a = ap.parse_args()

    st = read_state()
    try:
        d = fetch_status()
    except Exception as e:                                                    # noqa: BLE001
        print("[ERR] 取 %s 失败: %s: %s" % (SRC, type(e).__name__, str(e)[:200]))
        print("[ERR] 公网副本保留上一次(不推空/不推旧值, 页面侧按数据龄自己降级)")
        return 1

    # 明确写清数据源与数据龄: 页面据此判断新鲜度(不推算)
    d["src"] = "127.0.0.1:8796/status/all"
    d["published_at"] = time.time()

    # 只增不改: 训练没在跑时补 last_training(可选字段); 在跑时 training 段一行不动
    lt = collect_last_training()
    if lt:
        d["last_training"] = lt
    elif not (d.get("training") or {}).get("active"):
        d["last_training"] = None

    blob = json.dumps(d, ensure_ascii=False, sort_keys=True)
    md5 = hashlib.md5(blob.encode("utf-8")).hexdigest()
    if a.if_changed and st.get("md5") == md5:
        print("[skip] 内容未变 (md5 %s)" % md5[:8])
        return 0

    gpu = (d.get("hw") or {}).get("gpu") or {}
    tr = d.get("training") or {}
    print("[collect] gpu=%s%% mem=%sMB cpu=%s%% disk=%s%% models=%d training=%s | last=%s | assets=%d" % (
        gpu.get("util"), gpu.get("mem_used_mb"),
        ((d.get("hw") or {}).get("cpu") or {}).get("util"),
        ((d.get("hw") or {}).get("disk") or {}).get("pct"),
        len(d.get("models") or []),
        ("ON(%s %s/%s)" % (tr.get("layer"), tr.get("step"), tr.get("total"))) if tr.get("active") else "off",
        ("%s %s %s" % (lt.get("layer"), lt.get("version"), lt.get("at"))) if lt else "None",
        len(d.get("assets") or [])))

    if a.dry_run:
        print("[dry-run] 未推送; 体积 %d 字节" % len(blob.encode("utf-8")))
        return 0

    try:
        resp = push(d)
    except Exception as e:                                                    # noqa: BLE001
        print("[ERR] 推 %s 失败: %s: %s" % (PUSH, type(e).__name__, str(e)[:200]))
        st.update({"last_err": str(e)[:200], "last_try": time.time()})
        write_state(st)
        return 2

    ok = bool(resp.get("ok"))
    print("[push] %s" % json.dumps(resp, ensure_ascii=False))
    st.update({"md5": md5, "bytes": resp.get("bytes"), "ok": ok,
               "last_push": time.time(), "last_err": None})
    write_state(st)
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
