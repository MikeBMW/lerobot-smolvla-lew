#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""opt_camera_client.py — 工控机 OPT 相机取图客户端 (2026-09-24 老倪: 「通过奥普特相机获得图像」)

链路 (实测): Orin(192.168.23.66) / 本机(192.168.23.50) ──HTTP──> 工控机(192.168.23.23) ──> OPT 相机
  · 10082 金手指: OPT-CC1-GG50 · SN D265250070 · 路由 /picture(?kind=topview|origin, ?grab=1, ?meta=1)
                  /crop_info /region /last_result /capture_detect   (实测 Orin→工控机 0.82ms)
  · 10083 表面  : OPT-CC1-C050-GG3-00 · SN D265250099 · **只有 /capture_detect** → 拿不到图
                  (缺口, 需工控机侧加一条 /picture 路由: docs/patch/opt_surface_10083_add_picture_route.md)

纪律 (老倪红线):
  · 调用 = **真拍产线台照片** → `grab=True` 必须显式传入; 默认只读 (probe/last_result/取已落盘图)
  · 不批量轮询; 每次真拍写审计 reports/opt_capture_log.jsonl (何时/相机/端口/kind/大小/耗时/来源)
  · 相机独占: 同一 SN 只能被一个程序打开 → 一次只服务一台相机
  · 失败如实: 500 相机初始化失败 / 404 尚无照片 原样上报, 不伪造图

两种走法: via="local" (本机直连, 默认) / via="orin" (ssh 到 Orin 再 curl, 本机不在产线网时用)
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = os.environ.get("OPT_HOST", "192.168.23.23")
ORIN = os.environ.get("OPT_ORIN", "tashan@192.168.23.66")
ORIN_PW = os.environ.get("OPT_ORIN_PW", "ts123")
LOG = os.path.join(ROOT, "reports", "opt_capture_log.jsonl")

CAMERAS = {
    1: {"name": "金手指", "port": 10082, "model": "OPT-CC1-GG50", "sn": "D265250070",
        "has_picture": True, "note": "金手指检测相机 (规整拉长 topview 960x960 供 YOLO)"},
    2: {"name": "表面", "port": 10083, "model": "OPT-CC1-C050-GG3-00", "sn": "D265250099",
        "has_picture": False, "note": "表面检测相机 (工控机侧当前无 /picture 路由 → 只能触发拍照)"},
}


def _audit(rec: dict):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        rec = dict(rec, ts=time.strftime("%F %T"))
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:                                                  # noqa: BLE001
        pass


def _curl(url: str, via: str = "local", method: str = "GET", timeout: int = 12, binary: bool = False,
          extra=None, dump_headers=False):
    """统一出口: local=本机 curl / orin=ssh 到 Orin 上 curl (二进制走 base64)。

    返回 (ok, payload, info): payload = bytes(binary) / dict(json) / str(文本)
    """
    # 🔧 生成等价 curl 命令 (给窗口显示 + 用户复制到终端执行)
    _curl_local = (f"curl -s -m {timeout} -X {method} '{url}'" + (" -o frame.png" if binary else ""))
    if via == "orin":
        b64 = " -o - | base64 -w0" if binary else ""
        cmd = (f"timeout {timeout} curl -s -m {timeout} -X {method} "
               f"-w '\\n__HTTP__%{{http_code}} %{{time_total}}' {url}{b64}")
        info_cmd = f'sshpass -p <pw> ssh {ORIN} "{_curl_local}"' 
        p = subprocess.run(["sshpass", "-p", ORIN_PW, "ssh", "-o", "StrictHostKeyChecking=no",
                            "-o", "ConnectTimeout=8", ORIN, cmd],
                           capture_output=True, timeout=timeout + 12)
        out = p.stdout
        http, ms = "", 0.0
        if b"__HTTP__" in out:
            head, _, tail = out.rpartition(b"__HTTP__")
            out = head
            try:
                code, tt = tail.decode(errors="ignore").strip().split()
                http, ms = code, float(tt) * 1000
            except Exception:                                          # noqa: BLE001
                pass
        if binary and out:
            out = base64.b64decode(out.strip() + b"=" * (-len(out.strip()) % 4))
        info = {"via": "orin", "http": http, "ms": round(ms, 1), "rc": p.returncode,
                "err": p.stderr.decode(errors="ignore")[:200], "cmd": info_cmd}
    else:
        args = ["curl", "-s", "-m", str(timeout), "-X", method,
                "-w", "\n__HTTP__%{http_code} %{time_total}"]
        if binary:
            args += ["-o", "-"]
        args.append(url)
        p = subprocess.run(args, capture_output=True, timeout=timeout + 8)
        out = p.stdout
        http, ms = "", 0.0
        if b"__HTTP__" in out:
            head, _, tail = out.rpartition(b"__HTTP__")
            out = head
            try:
                code, tt = tail.decode(errors="ignore").strip().split()
                http, ms = code, float(tt) * 1000
            except Exception:                                          # noqa: BLE001
                pass
        info = {"via": "local", "http": http, "ms": round(ms, 1), "rc": p.returncode,
                "err": p.stderr.decode(errors="ignore")[:200], "cmd": _curl_local}
    if not binary:
        try:
            return True, json.loads(out.decode("utf-8", "ignore") or "{}"), info
        except Exception:                                              # noqa: BLE001
            return True, out.decode("utf-8", "ignore")[:400], info
    return bool(out), out, info


# ── 只读探针 ──────────────────────────────────────────────────────────────
def probe_routes(port: int, via: str = "local") -> dict:
    """OPTIONS 探路由 (零副作用, 不拍照) → {path: Allow}"""
    out = {}
    for path in ("/picture", "/crop_info", "/region", "/last_result", "/capture_detect"):
        cmd_url = f"http://{HOST}:{port}{path}"
        if via == "orin":
            p = subprocess.run(["sshpass", "-p", ORIN_PW, "ssh", "-o", "StrictHostKeyChecking=no",
                                "-o", "ConnectTimeout=8", ORIN,
                                f"timeout 6 curl -s -m 6 -i -X OPTIONS {cmd_url}"],
                               capture_output=True, timeout=20)
            txt = p.stdout.decode(errors="ignore")
        else:
            p = subprocess.run(["curl", "-s", "-m", "6", "-i", "-X", "OPTIONS", cmd_url],
                               capture_output=True, timeout=20)
            txt = p.stdout.decode(errors="ignore")
        allow = ""
        for line in txt.splitlines():
            if line.lower().startswith("allow:"):
                allow = line.split(":", 1)[1].strip()
                break
        out[path] = allow or "(路由不存在)"
    return out


def last_result(cam: int = 1, via: str = "local") -> dict:
    """工控机自家模型最近一次判决 (只读; 无结果时 code=404 原样返回)。"""
    port = CAMERAS[cam]["port"]
    ok, payload, info = _curl(f"http://{HOST}:{port}/last_result", via=via)
    d = payload if isinstance(payload, dict) else {"raw": str(payload)[:200]}
    d["_http"] = info.get("http")
    d["_ms"] = info.get("ms")
    d["_cmd"] = info.get("cmd", "")
    return d


def crop_info(cam: int = 1, via: str = "local") -> dict:
    port = CAMERAS[cam]["port"]
    ok, payload, info = _curl(f"http://{HOST}:{port}/crop_info", via=via)
    d = payload if isinstance(payload, dict) else {"raw": str(payload)[:200]}
    d["_http"], d["_ms"], d["_cmd"] = info.get("http"), info.get("ms"), info.get("cmd", "")
    return d


def region(cam: int = 1, grab: bool = False, via: str = "local") -> dict:
    """区域检测 (金手指区域框 + 对焦清晰度)。grab=True 会真拍 (默认 False 用最近一张)。"""
    port = CAMERAS[cam]["port"]
    url = f"http://{HOST}:{port}/region" + ("?grab=1" if grab else "")
    ok, payload, info = _curl(url, via=via, timeout=25 if grab else 12)
    d = payload if isinstance(payload, dict) else {"raw": str(payload)[:200]}
    d["_http"], d["_ms"], d["_cmd"] = info.get("http"), info.get("ms"), info.get("cmd", "")
    _audit({"cam": CAMERAS[cam]["name"], "port": port, "action": "region", "grab": bool(grab),
            "http": info.get("http"), "ms": info.get("ms"), "via": info.get("via")})
    return d


def picture_meta(cam: int = 1, via: str = "local") -> dict:
    """图片元数据 (?meta=1): 文件名/大小/时间戳/最近判决 (只读, 不拍照)。"""
    port = CAMERAS[cam]["port"]
    ok, payload, info = _curl(f"http://{HOST}:{port}/picture?kind=topview&meta=1", via=via)
    d = payload if isinstance(payload, dict) else {"raw": str(payload)[:200]}
    d["_http"], d["_ms"], d["_cmd"] = info.get("http"), info.get("ms"), info.get("cmd", "")
    return d


def capture_detect(cam: int = 1, via: str = "local") -> dict:
    """⚠️ 真拍: POST /capture_detect (产线台会真拍一张) — 必须由调用方显式触发。"""
    port = CAMERAS[cam]["port"]
    ok, payload, info = _curl(f"http://{HOST}:{port}/capture_detect", via=via, method="POST")
    rec = {"cam": CAMERAS[cam]["name"], "port": port, "action": "capture_detect",
           "http": info.get("http"), "ms": info.get("ms"), "via": info.get("via"),
           "cmd": info.get("cmd", ""),
           "resp": payload if isinstance(payload, dict) else str(payload)[:120]}
    _audit(rec)
    return rec


def fetch_frame(cam: int = 1, kind: str = "topview", grab: bool = False, via: str = "local",
                want_meta: bool = True):
    """取图。grab=True 会**真拍一张**(显式传入才拍); kind: topview(规整拉长)|origin(原始 2448x2048)。

    返回 (rgb_ndarray|None, meta)  meta 含 http/ms/size/shape/mean/相机/来源
    """
    import numpy as np
    import cv2
    c = CAMERAS[cam]
    if not c["has_picture"]:
        return None, {"ok": False, "cam": c["name"], "port": c["port"],
                      "err": f"{c['name']}相机在工控机侧无 /picture 路由 → 只能触发拍照 (见 patch 文档)"}
    url = f"http://{HOST}:{c['port']}/picture?kind={kind}" + ("&grab=1" if grab else "")
    ok, data, info = _curl(url, via=via, timeout=25 if grab else 12, binary=True)
    meta = {"cam": c["name"], "port": c["port"], "model": c["model"], "sn": c["sn"],
            "kind": kind, "grab": bool(grab), "http": info.get("http"),
            "ms": info.get("ms"), "via": info.get("via"), "bytes": len(data) if data else 0,
            "cmd": info.get("cmd", "")}
    if not data or (info.get("http") not in ("200", "", None)):
        try:
            j = json.loads(data.decode("utf-8", "ignore"))
            meta.update({"ok": False, "err": j.get("msg") or str(j)[:160]})
        except Exception:                                              # noqa: BLE001
            meta.update({"ok": False, "err": f"HTTP {info.get('http')} 无图 (504/404? 相机或未拍照)"})
        _audit(dict(meta, action="fetch_fail"))
        return None, meta
    arr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if arr is None:
        meta.update({"ok": False, "err": "解码失败 (非图像字节)"})
        return None, meta
    rgb = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
    meta.update({"ok": True, "shape": list(rgb.shape), "mean": round(float(rgb.mean()), 1),
                 "mean_gray": round(float(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).mean()), 1)})
    if grab:
        _audit({k: meta[k] for k in ("cam", "port", "kind", "http", "ms", "via", "bytes", "shape")}
               | {"action": "fetch_grab"})
    return rgb, meta


def health(via: str = "local") -> dict:          # noqa: D401
    """逐相机体检 (只读: 路由 + 判决通道; 不拍照)。"""
    out = {"host": HOST, "via": via, "cams": {}}
    for cam, c in CAMERAS.items():
        r = probe_routes(c["port"], via=via)
        lr = last_result(cam, via=via) if c["has_picture"] else {"code": 404, "msg": "无该路由"}
        out["cams"][c["name"]] = {"port": c["port"], "sn": c["sn"], "model": c["model"],
                                  "routes": r, "last_result": lr, "has_picture": c["has_picture"]}
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="工控机 OPT 相机取图 (默认只读; --grab 才真拍)")
    ap.add_argument("--cam", type=int, default=1, choices=[1, 2], help="1=金手指 2=表面")
    ap.add_argument("--kind", default="topview", choices=["topview", "origin"])
    ap.add_argument("--grab", action="store_true", help="⚠️ 真拍一张产线台照片")
    ap.add_argument("--via", default="local", choices=["local", "orin"])
    ap.add_argument("--health", action="store_true", help="只读体检 (路由+判决)")
    ap.add_argument("--last-result", action="store_true", help="读工控机判决")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if a.health:
        print(json.dumps(health(a.via), ensure_ascii=False, indent=1)); raise SystemExit(0)
    if a.last_result:
        print(json.dumps(last_result(a.cam, a.via), ensure_ascii=False, indent=1)); raise SystemExit(0)
    rgb, meta = fetch_frame(a.cam, a.kind, grab=a.grab, via=a.via)
    print(json.dumps(meta, ensure_ascii=False, indent=1))
    if rgb is not None and a.out:
        import cv2
        cv2.imwrite(a.out, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        print(f"→ {a.out}")
