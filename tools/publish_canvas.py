#!/usr/bin/env python3
"""一条命令发布画布全图: 渲图 → 算版本 → 推 8796(局域网) → 推 ECS(公网/手机)。

用法:
  cd /home/ubuntu/zmax
  ./gui-venv311/bin/python tools/publish_canvas.py            # 强行重渲+双推
  ./gui-venv311/bin/python tools/publish_canvas.py --if-changed   # 真源 md5 未变则跳过(cron 用)
  ./gui-venv311/bin/python tools/publish_canvas.py --no-ecs       # 只本机 8796
  ./gui-venv311/bin/python tools/publish_canvas.py --shots DIR    # 额外导出首屏/总览截图

发布产物:
  reports/canvas_pdf/canvas_<version>.pdf      带版本 (留档)
  reports/canvas_pdf/canvas_latest.pdf         最新版 (8796 /canvas.pdf 与手机固定 URL 都用它)
  reports/canvas_pdf/canvas_version.json       /canvas/version 的真源
  /home/ubuntu/.zmax_canvas_publish_state.json  --if-changed 的判据 (md5/版本/上次推送结果)

手机固定地址: https://datadrive.world/canvas_latest.pdf
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from lerobot.engineering import canvas_publish as CP                          # noqa: E402
import canvas_pdf_export as EXP                                               # noqa: E402

STATE = Path("/home/ubuntu/.zmax_canvas_publish_state.json")
LOG = "/tmp/publish_canvas.log"


def renderer_sig() -> str:
    """渲染器指纹 (导出器 + 发布模块的源码 md5) —— 只比画布 md5 的话,
    改了布局/字体这类"渲染器改动"永远不会重推手机 (实测踩到)。"""
    h = hashlib.md5()
    for f in (ROOT / "tools" / "canvas_pdf_export.py",
              ROOT / "src" / "lerobot" / "engineering" / "canvas_publish.py"):
        h.update(f.read_bytes())
    return h.hexdigest()[:8]


def read_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:                                                         # noqa: BLE001
        return {}


def write_state(d: dict) -> None:
    STATE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def local_route_check(timeout: int = 8) -> dict:
    """回读本机 8796 的 /canvas/version (证明局域网那条路由真的在服务新版本)。"""
    try:
        with urllib.request.urlopen("http://127.0.0.1:8796/canvas/version", timeout=timeout) as r:
            return {"status": r.status, "body": json.loads(r.read().decode("utf-8", "replace"))}
    except Exception as e:                                                    # noqa: BLE001
        return {"status": None, "err": "%s: %s" % (type(e).__name__, str(e)[:160])}


def shots(pdf: Path, outdir: Path, dpi: int = 110) -> list[str]:
    outdir.mkdir(parents=True, exist_ok=True)
    made = []
    for pg, tag in ((1, "p1_cover"), (2, "p2_overview"), (3, "p3_detail_rowgroup1")):
        base = outdir / ("canvas_%s" % tag)
        try:
            subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-f", str(pg), "-l", str(pg),
                            str(pdf), str(base)], check=True, capture_output=True, timeout=300)
            made += [str(p) for p in sorted(outdir.glob(base.name + "*.png"))]
        except Exception as e:                                                # noqa: BLE001
            print("[shots] 第 %d 页截图失败: %s: %s" % (pg, type(e).__name__, e))
    return made


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--if-changed", action="store_true", help="真源 md5 未变则跳过 (不重渲不上传)")
    ap.add_argument("--no-ecs", action="store_true", help="不推 ECS (只做本机 8796)")
    ap.add_argument("--no-local", action="store_true", help="不写本机产物 (只推 ECS)")
    ap.add_argument("--shots", default="", help="额外导出截图到该目录")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    def say(*msg):
        line = " ".join(str(m) for m in msg)
        print(line)
        try:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write("[%s] %s\n" % (time.strftime("%F %T"), line))
        except Exception:                                                     # noqa: BLE001
            pass

    md5 = CP.source_md5()
    version = CP.version_of(md5)
    stats = CP.canvas_stats()
    st = read_state()
    out = {"version": version, "md5": md5, "nodes": stats["nodes"], "links": stats["links"],
           "ts": time.time(), "if_changed": a.if_changed}

    rsig = renderer_sig()
    out["renderer"] = rsig
    if (a.if_changed and st.get("md5") == md5 and st.get("renderer") == rsig
            and CP.LATEST_PDF.exists()):
        out["skipped"] = True
        out["reason"] = "真源 md5 未变 (%s@%s) 且渲染器未变 (%s); 上次发布 %s" % (
            md5[:8], CP.source_json().name, rsig, st.get("version"))
        say("[skip]", out["reason"])
        print(json.dumps(out, ensure_ascii=False))
        return 0

    # ① 渲图 (矢量 PDF, 自查 89 节点/182 连线)
    meta = EXP.build(preview=False)
    if (meta["nodes_drawn"], meta["links_drawn"]) != (stats["nodes"], stats["links"]):
        say("[FAIL] PDF 自查不过: 节点 %d/%d · 连线 %d/%d" % (
            meta["nodes_drawn"], stats["nodes"], meta["links_drawn"], stats["links"]))
        out["error"] = "selfcheck_failed"
        print(json.dumps(out, ensure_ascii=False))
        return 4
    out["pdf"] = meta["pdf"]
    out["bytes"] = meta["bytes"]
    out["pages"] = meta["pages"]
    say("[1/4] 渲图 OK: %s (%.0f KB, %d 页, 节点 %d/%d 连线 %d/%d)" % (
        meta["pdf"], meta["bytes"] / 1024, meta["pages"],
        meta["nodes_drawn"], meta["nodes"], meta["links_drawn"], meta["links"]))

    if a.no_local:
        say("[2/4] --no-local: 跳过本机产物")
    else:
        # ② 本机产物: canvas_latest.pdf (原子换名) + canvas_version.json (8796 路由真源)
        tmp = CP.LATEST_PDF.with_suffix(".pdf.tmp")
        shutil.copy2(meta["pdf"], tmp)
        os.replace(tmp, CP.LATEST_PDF)
        vj = dict(meta)
        vj.update({"phone_url": CP.ECS_PHONE_URL, "local_url": "http://127.0.0.1:8796/canvas.pdf",
                   "canvas_pdf": str(CP.LATEST_PDF), "published_ts": time.time()})
        CP.write_version_json(vj)
        say("[2/4] 本机 8796 就绪: %s (%.0f KB)" % (CP.LATEST_PDF, CP.LATEST_PDF.stat().st_size / 1024))
        lc = local_route_check()
        out["local_route"] = lc
        if lc.get("status") == 200 and lc["body"].get("version") == version:
            say("      GET /canvas/version → 200 %s ✓ (当前版本一致)" % lc["body"].get("version"))
        else:
            say("      ⚠ 8796 /canvas/version 未返回新版本 (%s) — 若路由还没生效: "
                "sudo systemctl restart sam3-seg" % json.dumps(lc, ensure_ascii=False)[:200])

    # ③ 推 ECS (公网, 手机用)
    if a.no_ecs:
        say("[3/4] --no-ecs: 跳过公网推送")
    else:
        ver_name = "canvas_%s.pdf" % version
        r1 = CP.ecs_push(Path(meta["pdf"]), ver_name)
        r2 = CP.ecs_push(CP.LATEST_PDF, "canvas_latest.pdf")
        c1 = CP.ecs_check(ver_name)
        c2 = CP.ecs_check("canvas_latest.pdf")
        out["ecs"] = {"versioned": r1, "latest": r2, "check_versioned": c1, "check_latest": c2}
        say("[3/4] ECS 推送: %s → %s | %s → %s" % (
            ver_name, "ok" if r1["ok"] else r1["resp"][:120],
            "canvas_latest.pdf", "ok" if r2["ok"] else r2["resp"][:120]))
        say("      公网回读: %s HTTP %s %s %s bytes | %s HTTP %s %s %s bytes" % (
            ver_name, c1["status"], c1["content_type"], c1["content_length"],
            "canvas_latest.pdf", c2["status"], c2["content_type"], c2["content_length"]))
        if not (c1["is_pdf"] and c2["is_pdf"]):
            out["error"] = "ecs_verify_failed"

    # ④ 截图 (给人看)
    if a.shots:
        sh = shots(Path(meta["pdf"]), Path(a.shots))
        out["screenshots"] = sh
        say("[4/4] 截图 %d 张 → %s" % (len(sh), a.shots))

    if not a.no_local:
        write_state({"md5": md5, "version": version, "ts": time.time(), "renderer": rsig,
                     "pdf": meta["pdf"], "bytes": meta["bytes"], "pages": meta["pages"],
                     "nodes": stats["nodes"], "links": stats["links"],
                     "ecs_ok": bool(out.get("ecs", {}).get("check_latest", {}).get("is_pdf"))})
    say("[done]", out["version"], "→", CP.ECS_PHONE_URL)
    print(json.dumps(out, ensure_ascii=False))
    return 0 if not out.get("error") else 4


if __name__ == "__main__":
    sys.exit(main())
