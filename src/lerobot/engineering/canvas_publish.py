#!/usr/bin/env python3
"""画布 (状态空间) 全图导出与发布的共享逻辑 —— 逻辑住包内, GUI/服务只是调用方。

职责
  · 唯一的真源定位 (flows/state_space_obs.json, 走软链取 realpath)
  · 版本号 = v<YYYYMMDD 真源 mtime>-<真源 md5 前 8 位>
  · 产物目录 (reports/canvas_pdf/) 与最新版/带版本 PDF 的路径
  · 8796 只读路由的服务端实现 (serve_route) —— tools/sam3_seg.py 只做转发
  · ECS 公网发布 (datadrive.world 站点根, 走 ss3d_push.php 的 canvas_*.pdf 白名单)

真源: src/lerobot/engineering/flows/state_space_obs.json (仓库根 flows/ 是软链)
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]          # .../zmax  (src/lerobot/engineering/<file>)
FLOW_LINK = ROOT / "flows" / "state_space_obs.json"
OUT_DIR = ROOT / "reports" / "canvas_pdf"
LATEST_PDF = OUT_DIR / "canvas_latest.pdf"
VERSION_JSON = OUT_DIR / "canvas_version.json"
PREVIEW_PNG = OUT_DIR / "canvas_latest_preview.png"

ECSE = "https://datadrive.world"
ECS_PUSH = "/ss3d_push.php"
ECS_TOKEN = "zmax-7ce74c7f"
ECS_PHONE_URL = "https://datadrive.world/canvas_latest.pdf"
SECRETS = Path("/home/ubuntu/zmax_data/secrets/zmax.env")


# ───────────────────────── 真源 / 版本 ─────────────────────────
def source_json() -> Path:
    """真源 JSON 的 realpath (仓库根 flows/ 是软链, 别把软链写坏)。"""
    p = FLOW_LINK
    if not p.exists():
        raise SystemExit("画布真源不存在: %s" % p)
    return Path(os.path.realpath(p))


def load_canvas() -> dict:
    p = source_json()
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def source_md5() -> str:
    return hashlib.md5(source_json().read_bytes()).hexdigest()


def version_of(md5: str | None = None, when: float | None = None) -> str:
    """v<YYYYMMDD>-<md5[:8]>; 日期取真源 mtime (画布"发布日"), md5 变则版本必变。"""
    md5 = md5 or source_md5()
    day = _dt.datetime.fromtimestamp(when if when is not None else source_json().stat().st_mtime)
    return "v%s-%s" % (day.strftime("%Y%m%d"), md5[:8])


def versioned_pdf(version: str) -> Path:
    return OUT_DIR / ("canvas_%s.pdf" % version)


def read_version_json() -> dict:
    try:
        return json.loads(VERSION_JSON.read_text(encoding="utf-8"))
    except Exception:                                                          # noqa: BLE001
        return {}


def write_version_json(meta: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = VERSION_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, VERSION_JSON)


def canvas_stats() -> dict:
    j = load_canvas()
    return {"nodes": len(j.get("nodes", [])), "links": len(j.get("links", [])),
            "name": j.get("name", ""), "version_field": j.get("version", "")}


# ───────────────────────── 8796 只读路由 ─────────────────────────
def serve_route(path: str):
    """返回 (status, content_type, body_bytes, extra_headers) 或 None(不是我管的路径)。

    GET /canvas.pdf      → 最新版 PDF (application/pdf, 支持 Range? 简化: 全量 200)
    GET /canvas/version  → {version, ts, nodes, links, md5, pdf, bytes, pages}
    """
    p = path.split("?")[0].rstrip("/") or "/"
    if p in ("/canvas.pdf", "/canvas/canvas_latest.pdf"):
        if not LATEST_PDF.exists():
            return (404, "application/json; charset=utf-8",
                    json.dumps({"ok": False, "err": "canvas pdf 还没生成, 先跑 tools/publish_canvas.py"},
                               ensure_ascii=False).encode(), {})
        b = LATEST_PDF.read_bytes()
        return (200, "application/pdf", b,
                {"Content-Disposition": 'inline; filename="canvas_latest.pdf"',
                 "Cache-Control": "no-cache"}) if b else None
    if p == "/canvas/version":
        meta = read_version_json()
        if not meta:                                                            # 现场降级: 现算
            md5 = source_md5()
            meta = dict(canvas_stats(), version=version_of(md5), md5=md5, ts=time.time(),
                        pdf=str(LATEST_PDF), bytes=LATEST_PDF.stat().st_size if LATEST_PDF.exists() else 0)
        body = json.dumps(meta, ensure_ascii=False).encode()
        return (200, "application/json; charset=utf-8", body, {"Cache-Control": "no-cache"})
    return None


# ───────────────────────── ECS 公网发布 ─────────────────────────
def _http(method: str, url: str, data: bytes | None = None, ctype: str | None = None,
          timeout: int = 120):
    req = urllib.request.Request(url, data=data, method=method)
    if ctype:
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read() or b"", dict(e.headers or {})
    except Exception as e:                                                     # noqa: BLE001
        return None, str(e).encode(), {}


def ecs_push(local: Path, remote_name: str, timeout: int = 120) -> dict:
    """把一个文件 POST 到 ECS 站点根 (只走 HTTP, 无需 SSH/密码)。"""
    url = "%s%s?token=%s&f=%s" % (ECSE, ECS_PUSH, ECS_TOKEN, remote_name)
    st, body, _ = _http("POST", url, local.read_bytes(), "application/pdf", timeout=timeout)
    out = {"f": remote_name, "bytes": local.stat().st_size, "status": st,
           "resp": body[:200].decode("utf-8", "replace")}
    out["ok"] = bool(st == 200 and b'"ok":true' in body.replace(b" ", b""))
    return out


def ecs_check(remote_name: str = "canvas_latest.pdf", timeout: int = 60) -> dict:
    """上线后回读: 只取响应头 + 前 5 字节确认是 PDF。"""
    st, body, hdrs = _http("GET", "%s/%s?t=%d" % (ECSE, remote_name, time.time()),
                           timeout=timeout)
    head = body[:5]
    return {"status": st, "content_type": hdrs.get("Content-Type", ""),
            "content_length": hdrs.get("Content-Length", ""), "head": head.decode("latin1"),
            "is_pdf": head == b"%PDF-"}


def ecs_pw() -> str:
    for ln in SECRETS.read_text(encoding="utf-8", errors="ignore").splitlines():
        if ln.strip().startswith("ZMAX_ECS_PW="):
            return ln.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("ZMAX_ECS_PW 未在 %s 里找到" % SECRETS)


def ecs_ssh(cmd: str, timeout: int = 60) -> tuple[int, str]:
    """在 ECS 上跑一条命令 (sshpass -e 传密码, 不进 argv)。仅用于白名单/备份这类一次性运维。"""
    import subprocess
    env = dict(os.environ, SSHPASS=ecs_pw())
    p = subprocess.run(["sshpass", "-e", "ssh", "-o", "StrictHostKeyChecking=no",
                        "-o", "ConnectTimeout=15", "root@39.102.211.79", cmd],
                       capture_output=True, text=True, timeout=timeout, env=env)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def sanitize_label(s: str) -> str:
    """去掉 emoji/装饰符号 (PDF 无 emoji 字形 ⇒ 会画成黑框), 保留中英数字与常用标点。"""
    keep = []
    for ch in str(s):
        o = ord(ch)
        if (0x20 <= o <= 0x7E or 0xA0 <= o <= 0xFF or 0x2000 <= o <= 0x206F
                or 0x3000 <= o <= 0x303F or 0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF
                or 0xFF00 <= o <= 0xFFEF or 0x370 <= o <= 0x3FF):
            keep.append(ch)
    t = re.sub(r"\s+", " ", "".join(keep)).strip()
    return t or "(未命名)"
