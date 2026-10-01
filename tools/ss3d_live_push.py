#!/usr/bin/env python3
"""Z-MAX 实况推送 (2026-10-01 老倪「手机操作反馈不及时」)

背景: 手机页 state-3d.html 用**相对地址**读 ss3d_live.json ⇒ 必须落在站点根(www/wwwroot)。
      旧守护进程放 /tmp(重启即失) + 用 sshpass scp 上传(SSH 不通) ⇒ 实况冻结 25 天(实测 09-06→10-01)。
本脚本: 每 ~1s 采集**真机真实状态**, 经 https://datadrive.world/ss3d_push.php 推到站点根(纯 HTTP, 无 SSH)。
        这次落在仓库 + systemd, 不再放 /tmp。
口径: 所有时间戳用本机 monotonic/wall; beat=推送时刻 ⇒ 手机端可算帧龄(老倪要求实时数据标拍照时间·帧龄)。
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

PUSH = os.environ.get("SS3D_PUSH", "https://datadrive.world/ss3d_push.php")
TOKEN = os.environ.get("ZMAX_PUSH_TOKEN", "zmax-7ce74c7f")
INTERVAL = float(os.environ.get("SS3D_PUSH_INTERVAL", "1.0"))
RUN_ID = os.environ.get("SS3D_RUN_ID", "live_real")   # ⚠️ 固定不变: run_id 一变页面会去拉(已过期的)轨迹


def _get(url: str, t: float = 3.0):
    try:
        with urllib.request.urlopen(url, timeout=t) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def _post(obj: dict) -> bool:
    url = f"{PUSH}?token={TOKEN}&f=ss3d_live.json"
    req = urllib.request.Request(url, data=json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            return r.status == 200
    except Exception as e:                                    # noqa: BLE001
        print(f"  ⚠️ 推送失败: {type(e).__name__}: {e}", flush=True)
        return False


def collect() -> dict:
    """采集真机当前的**真实**状态(只读接口, 不碰任何执行)."""
    st = _get("http://127.0.0.1:8791/stats") or {}           # 相机链路
    inf = _get("http://127.0.0.1:8790/health") or {}          # L4 本地推理
    pose = None
    for p in ("/home/ubuntu/zmax_data/rokae_sdk/tcp_out/latest.json",  # 珞石 TCP 真值采样
              "/home/ubuntu/zmax/rokae_sdk/tcp_out/latest.json"):
        try:
            with open(p, encoding="utf-8") as f:
                pose = json.load(f)
            break
        except Exception:
            continue
    cams = {}
    for k, v in (st.items() if isinstance(st, dict) else []):
        if isinstance(v, dict) and "age_s" in v:
            cams[k] = {"on": bool(v.get("online")), "fps": v.get("fps"), "age_s": v.get("age_s")}
    return {
        "run_id": RUN_ID, "playing": True, "i": 0, "n": 0, "done": False, "dist": 0,
        "beat": round(time.time(), 3),                        # 手机端据此算帧龄
        "hw": {
            "infer": {"on": bool(inf.get("online")), "device": inf.get("device"),
                      "last_ms": inf.get("last_ms"), "n": inf.get("infer_count")},
            "cams": cams,
            "tcp_pose": (pose or {}).get("tcp") or (pose or {}).get("pose"),
            "pose_ts": (pose or {}).get("ts") or (pose or {}).get("time"),
        },
    }


def main() -> None:
    print(f"📡 实况推送 → {PUSH} (每 {INTERVAL}s · run_id={RUN_ID})", flush=True)
    ok = fail = 0
    while True:
        d = collect()
        if _post(d):
            ok += 1
        else:
            fail += 1
        if (ok + fail) % 60 == 0:
            print(f"  已推 {ok} 次 / 失败 {fail} 次 · 相机 {len(d['hw']['cams'])} 路在线", flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
