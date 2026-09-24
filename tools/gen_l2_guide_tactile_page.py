#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧪 gen_l2_guide_tactile_page.py — 生成并部署「L2 3D视觉引导 / 触觉反馈闭环」功能+用例页

单一真源 (不手抄数字):
  · 功能定义   ← src/lerobot/verification/capability_levels.py  (L2-A12 / L2-A13)
  · 测试用例   ← src/lerobot/verification/verification_layer.py (FEATURES + FEATURE_META, F-B12 / F-B13)
  · 分层功能树 ← src/lerobot/verification/node_func_tree.py     (FN2d06 / FNtac06)
  · 实测结果   ← **现场真跑**这两条用例 (--run, 默认开), 把 PASS + 实测明细写进页面

产物:
  reports/web/l2-guidance-tactile.html  (深色主题, 同 datadrive.world; 顶部有「下载 Markdown / 复制 Markdown」)
  reports/web/l2-guidance-tactile.md    (同内容 Markdown, 静态可下载)

部署: ZMAX_ECS_PW=<密码> 时 scp 到 ECS (39.102.211.79:/www/wwwroot/datadrive.world/) 并 HTTP 复核。
用法:
  ./gui-venv311/bin/python tools/gen_l2_guide_tactile_page.py            # 生成 + 部署
  ./gui-venv311/bin/python tools/gen_l2_guide_tactile_page.py --no-run   # 不跑用例(用上次实测)
  ./gui-venv311/bin/python tools/gen_l2_guide_tactile_page.py --html-only
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VER = os.path.join(ROOT, "src", "lerobot", "verification")
FNAME_HTML = "l2-guidance-tactile.html"
FNAME_MD = "l2-guidance-tactile.md"
ECS = "39.102.211.79"
ECSDIR = "/www/wwwroot/datadrive.world"
SITE = "https://datadrive.world"
MEASURED = os.path.join(ROOT, "reports", "l2_guide_tactile_measured.json")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def collect() -> dict:
    cl = _load(os.path.join(VER, "capability_levels.py"), "capability_levels")
    vl = _load(os.path.join(VER, "verification_layer.py"), "verification_layer")
    nft = _load(os.path.join(VER, "node_func_tree.py"), "node_func_tree")

    want_funcs = {"L2-A12", "L2-A13"}
    feats = {}
    for lv, d in cl.CAPABILITY_LEVELS.items():
        for f in d.get("funcs", []):
            if f["fid"] in want_funcs:
                feats[f["fid"]] = {**f, "level": lv, "level_name": d["name"]}
    tset = {f[0] for f in vl.FEATURES}
    tests = {}
    for f in vl.FEATURES:
        if f[0] in ("F-B12", "F-B13"):
            tests[f[0]] = {"fid": f[0], "domain": f[1], "name": f[2], "src": f[3],
                           "mode": f[4], "method": f[5], "level": f[6],
                           "meta": vl.FEATURE_META.get(f[0], ("", "", ""))}
    funcs = []
    for nk in ("ss2d3d", "sstactile", "sssensor"):
        nd = nft.NODE_TREE.get(nk, {})
        for fn in nd.get("funcs", []):
            if fn["fid"] in ("FN2d06", "FNtac06"):
                funcs.append({"node": nk, "node_name": nd.get("name", nk),
                              "fb": nd.get("fb", ""), **fn})
    return {"features": feats, "tests": tests, "funcs": funcs,
            "counts": {"features": cl.func_count() if hasattr(cl, "func_count") else None,
                       "tests": len(vl.FEATURES), "nodes": len(nft.NODE_TREE),
                       "test_ids_known": sorted(tset)[:3]}}


def run_tests(run: bool) -> dict:
    """现场真跑两条用例 (真物理引擎) → {fid: {ok, detail}}"""
    if not run:
        return {}
    os.environ.setdefault("MUJOCO_GL", "egl")
    vl = _load(os.path.join(VER, "verification_layer.py"), "verification_layer")
    v = vl.VerificationLayer()
    import numpy as np
    out = {}
    for fid in ("F-B12", "F-B13"):
        t0 = time.time()
        try:
            ok, detail = getattr(v, "t_" + fid.replace("-", "_"))(np)
            out[fid] = {"ok": bool(ok), "detail": str(detail), "sec": round(time.time() - t0, 1)}
        except Exception as e:                                              # noqa: BLE001
            out[fid] = {"ok": False, "detail": f"{type(e).__name__}: {e}", "sec": round(time.time() - t0, 1)}
        print(f"  {'✅' if out[fid]['ok'] else '❌'} {fid} ({out[fid]['sec']}s): {out[fid]['detail'][:150]}")
    return out


def measured() -> dict:
    try:
        return json.load(open(MEASURED, encoding="utf-8"))
    except Exception:                                                       # noqa: BLE001
        return {}


HEAD = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>__TITLE__</title><style>
body{background:#0d1520;color:#d0d7de;font-family:'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;
margin:0;padding:24px 32px;font-size:14px;line-height:1.6}
h1{color:#fff;font-size:23px;border-bottom:2px solid #00d4aa;padding-bottom:8px}
h2{color:#00d4aa;font-size:17px;margin-top:26px;border-left:4px solid #00d4aa;padding-left:10px}
h3{color:#58a6ff;font-size:14.5px;margin-top:18px}
table{border-collapse:collapse;width:100%;margin:10px 0}
th{background:#111c2b;color:#8b949e;text-align:left;padding:7px 9px;border:1px solid #1f2937;font-weight:600}
td{padding:7px 9px;border:1px solid #1f2937;vertical-align:top}
code{background:#111c2b;color:#7ee787;padding:1px 5px;border-radius:3px;font-size:12.5px}
.ok{color:#3fb950;font-weight:700}.bad{color:#f85149;font-weight:700}.warn{color:#d29922;font-weight:700}
.meta{color:#8b949e;font-size:12.5px}
.tools{margin:14px 0;display:flex;gap:10px;flex-wrap:wrap}
a.btn{background:#00d4aa;color:#04121a;font-weight:700;text-decoration:none;padding:9px 16px;border-radius:6px}
a.btn.alt{background:#1f6feb;color:#fff}
pre{background:#111c2b;border:1px solid #1f2937;border-radius:6px;padding:12px;overflow:auto;font-size:12.5px}
</style></head><body>"""


def render_html(d: dict, res: dict) -> str:
    f12, f13 = d["features"]["L2-A12"], d["features"]["L2-A13"]
    t12, t13 = d["tests"]["F-B12"], d["tests"]["F-B13"]
    m = d["measured"]
    g, t = m.get("3d_guide", {}), m.get("tactile", {})
    rows = []
    for fid in ("F-B12", "F-B13"):
        tst = d["tests"][fid]
        r = res.get(fid)
        badge = ("<span class='ok'>✅ PASS</span>" if r and r["ok"] else
                 ("<span class='bad'>❌ FAIL</span>" if r else "<span class='meta'>未跑 (--no-run)</span>"))
        rows.append(f"<tr><td><code>{fid}</code></td><td>{tst['name']}</td><td>{tst['domain']}</td>"
                    f"<td>{tst['mode']}</td><td>{badge}</td><td>{tst['method']}</td></tr>")
    detail = []
    for fid in ("F-B12", "F-B13"):
        r = res.get(fid)
        if r:
            detail.append(f"<tr><td><code>{fid}</code></td><td>{r['detail']}</td><td>{r['sec']}s</td></tr>")
    fn_rows = "".join(
        f"<tr><td>{f['node_name']} <span class='meta'>({f['node']})</span></td><td><code>{f['fid']}</code></td>"
        f"<td>{f['name']}</td><td>{f['desc']}</td><td>" +
        "<br>".join(f"{'·'} {x[0]} <span class='meta'>[{x[1]}]</span>" for x in f["tests"]) + "</td></tr>"
        for f in d["funcs"])
    html = HEAD.replace("__TITLE__", "L2 3D 视觉引导 · 触觉反馈闭环 — 功能与测试用例")
    html += f"""
<h1>🔧 L2 · 3D 视觉引导 &amp; 触觉反馈闭环<span class="meta"> — 功能定义 + 测试用例 (实测)</span></h1>
<p class="meta">生成 {d['ts']} · 单一真源: capability_levels.py / verification_layer.py / node_func_tree.py
· 实测引擎: state_space_sim_real.py (metaworld 真物理, seed104, 400 步) · 页面 <code>{SITE}/{FNAME_HTML}</code></p>

<div class="tools">
  <a class="btn" href="./{FNAME_MD}" download>⬇ 下载 Markdown</a>
  <a class="btn alt" href="./function-list.html">← 功能清单总表</a>
  <button class="btn alt" onclick="copyMd()">📋 复制 Markdown</button>
  <span class="meta" id="copyMsg"></span>
</div>

<h2>一、功能定义 (L2 基础辅助功能)</h2>
<table><tr><th>编号</th><th>名称</th><th>定义与实测指标</th><th>能力分组</th></tr>
<tr><td><code>{f12['fid']}</code></td><td><b>{f12['name']}</b></td><td>{f12['desc']}</td><td>{' / '.join(f12.get('groups', []))}</td></tr>
<tr><td><code>{f13['fid']}</code></td><td><b>{f13['name']}</b></td><td>{f13['desc']}</td><td>{' / '.join(f13.get('groups', []))}</td></tr>
</table>

<h2>二、测试用例与**本次实测**结果</h2>
<table><tr><th>用例</th><th>断言内容</th><th>域</th><th>方式</th><th>结果</th><th>真源方法</th></tr>{''.join(rows)}</table>
{'<h3>实测明细 (现场真跑)</h3><table><tr><th>用例</th><th>实测明细</th><th>耗时</th></tr>' + ''.join(detail) + '</table>' if detail else ''}

<h2>三、关键实测数字 (真物理引擎, 非估计)</h2>
<table><tr><th>指标</th><th>实测值</th><th>判据</th></tr>
<tr><td>引导向量范数 (中位)</td><td>{g.get('引导向量范数_中位_mm')} mm</td><td>—</td></tr>
<tr><td>横向偏差 前1/3 → 后1/3</td><td>{g.get('横向偏差_前1/3_中位_mm')} → {g.get('横向偏差_后1/3_中位_mm')} mm</td><td>后1/3 ≤ 前1/3 × 0.50</td></tr>
<tr><td>末端法向偏离 首 → 末</td><td>{(g.get('mani_dperp_首末_mm') or ['—','—'])[0]} → {(g.get('mani_dperp_首末_mm') or ['—','—'])[1]} mm</td><td>末帧 &lt; 1 mm</td></tr>
<tr><td>触觉通道↔状态 互补一致率</td><td class="ok">{t.get('tactile4_通道0==gripper_一致率')} (互补口径 1.000)</td><td>≥ 0.99</td></tr>
<tr><td>力 → 接触概率 相关性</td><td>{t.get('corr(contact_p, 力)')}</td><td>≥ 0.80</td></tr>
<tr><td>插入段 contact_p 中位</td><td>{t.get('contact_p_插入段_中位')}</td><td>≥ 0.90</td></tr>
<tr><td>接触力上界 (力保护)</td><td>{t.get('力_上界_实测')} N</td><td>≤ 1.0 N</td></tr>
<tr><td>触觉通道 2/3 (前向/侧向力)</td><td class="warn">引擎恒 0</td><td>真机触觉缺口 — 如实标注, 未冒充</td></tr>
</table>
<p class="meta">注: 触觉通道 0 = 钳口**原始开度**, 轨迹 gripper = **夹紧度 = 1 − 开度** (既有约定), 故断言用**互补一致率**;
「静态目标向量 vs 逐帧速度」方向一致率仅 ~0.21 —— 该口径不含阶段子目标, 故判据用**偏差收敛 + 法向偏离归零**。</p>

<h2>四、功能树登记 (分层功能 → 用例映射)</h2>
<table><tr><th>节点</th><th>功能编号</th><th>功能</th><th>说明</th><th>用例</th></tr>{fn_rows}</table>

<h2>五、链路与源码</h2>
<table><tr><th>环节</th><th>位置</th></tr>
<tr><td>功能定义 (功能清单节点数据源)</td><td><code>src/lerobot/verification/capability_levels.py</code> → L2-A12 / L2-A13</td></tr>
<tr><td>测试用例 (测试用例节点数据源)</td><td><code>src/lerobot/verification/verification_layer.py</code> → F-B12 / F-B13 + t_F_B12 / t_F_B13</td></tr>
<tr><td>分层功能树 (网页总表数据源)</td><td><code>src/lerobot/verification/node_func_tree.py</code> → FN2d06 / FNtac06</td></tr>
<tr><td>真物理引擎 (断言数据源)</td><td><code>tools/gui/state_space_sim_real.py</code> (metaworld, seed104)</td></tr>
<tr><td>画布节点</td><td>📐 2D→3D 解算 (ss2d3d) · 🖐 触觉感知 (sstactile) · 📡 传感器融合 (sssensor)</td></tr>
<tr><td>复现命令</td><td><code>MUJOCO_GL=egl gui-venv311/bin/python tools/ss_feature_tests.py --only F-B12</code> / <code>--only F-B13</code></td></tr>
</table>

<script>
async function copyMd() {{
  const msg = document.getElementById('copyMsg');
  try {{
    const r = await fetch('./{FNAME_MD}');
    await navigator.clipboard.writeText(await r.text());
    msg.textContent = '✅ 已复制 Markdown 到剪贴板';
  }} catch (e) {{ msg.textContent = '⚠ 复制失败, 请用「下载 Markdown」按钮: ' + e; }}
}}
</script>
</body></html>"""
    return html


def render_md(d: dict, res: dict) -> str:
    f12, f13 = d["features"]["L2-A12"], d["features"]["L2-A13"]
    m = d["measured"]
    g, t = m.get("3d_guide", {}), m.get("tactile", {})
    L = [f"# L2 · 3D 视觉引导 & 触觉反馈闭环 — 功能定义 + 测试用例 (实测)",
         "",
         f"- 生成时间: {d['ts']}",
         f"- 单一真源: `capability_levels.py` (功能) · `verification_layer.py` (用例) · `node_func_tree.py` (功能树)",
         f"- 实测引擎: `state_space_sim_real.py` (metaworld 真物理, seed104, 400 步)",
         f"- 在线页面: {SITE}/{FNAME_HTML}",
         "", "## 一、功能定义 (L2 基础辅助功能)", "",
         "| 编号 | 名称 | 定义与实测指标 | 能力分组 |", "|---|---|---|---|",
         f"| {f12['fid']} | {f12['name']} | {f12['desc']} | {' / '.join(f12.get('groups', []))} |",
         f"| {f13['fid']} | {f13['name']} | {f13['desc']} | {' / '.join(f13.get('groups', []))} |",
         "", "## 二、测试用例与实测结果", "",
         "| 用例 | 断言内容 | 域 | 方式 | 结果 | 真源方法 |", "|---|---|---|---|---|---|"]
    for fid in ("F-B12", "F-B13"):
        tst = d["tests"][fid]
        r = res.get(fid)
        badge = "✅ PASS" if (r and r["ok"]) else ("❌ FAIL" if r else "未跑")
        L.append(f"| {fid} | {tst['name']} | {tst['domain']} | {tst['mode']} | {badge} | `{tst['method']}` |")
    if res:
        L += ["", "### 实测明细 (现场真跑)", "", "| 用例 | 明细 | 耗时 |", "|---|---|---|"]
        for fid in ("F-B12", "F-B13"):
            if fid in res:
                L.append(f"| {fid} | {res[fid]['detail']} | {res[fid]['sec']}s |")
    L += ["", "## 三、关键实测数字", "", "| 指标 | 实测值 | 判据 |", "|---|---|---|",
          f"| 引导向量范数 (中位) | {g.get('引导向量范数_中位_mm')} mm | — |",
          f"| 横向偏差 前1/3 → 后1/3 | {g.get('横向偏差_前1/3_中位_mm')} → {g.get('横向偏差_后1/3_中位_mm')} mm | 后1/3 ≤ 前1/3 × 0.50 |",
          f"| 末端法向偏离 首 → 末 | {(g.get('mani_dperp_首末_mm') or ['—','—'])[0]} → {(g.get('mani_dperp_首末_mm') or ['—','—'])[1]} mm | 末帧 < 1 mm |",
          f"| 触觉通道↔状态 互补一致率 | {t.get('tactile4_通道0==gripper_一致率')} (互补口径 1.000) | ≥ 0.99 |",
          f"| 力 → 接触概率 相关性 | {t.get('corr(contact_p, 力)')} | ≥ 0.80 |",
          f"| 插入段 contact_p 中位 | {t.get('contact_p_插入段_中位')} | ≥ 0.90 |",
          f"| 接触力上界 (力保护) | {t.get('力_上界_实测')} N | ≤ 1.0 N |",
          f"| 触觉通道 2/3 (前向/侧向力) | 引擎恒 0 | 真机触觉缺口 — 如实标注 |",
          "", "> 注: 触觉通道 0 = 钳口**原始开度**, 轨迹 gripper = **夹紧度 = 1 − 开度** (既有约定), 故用**互补一致率**断言;",
          "> 「静态目标向量 vs 逐帧速度」方向一致率仅 ~0.21 — 该口径不含阶段子目标, 故判据用**偏差收敛 + 法向偏离归零**。",
          "", "## 四、功能树登记", "", "| 节点 | 功能编号 | 功能 | 用例 |", "|---|---|---|---|"]
    for f in d["funcs"]:
        L.append("| " + f"{f['node_name']} | {f['fid']} | {f['name']} | "
                 + " / ".join(x[0] for x in f["tests"]) + " |")
    L += ["", "## 五、链路与源码", "",
          "| 环节 | 位置 |", "|---|---|",
          "| 功能定义 (功能清单节点数据源) | `src/lerobot/verification/capability_levels.py` → L2-A12 / L2-A13 |",
          "| 测试用例 (测试用例节点数据源) | `src/lerobot/verification/verification_layer.py` → F-B12 / F-B13 |",
          "| 分层功能树 (网页总表数据源) | `src/lerobot/verification/node_func_tree.py` → FN2d06 / FNtac06 |",
          "| 真物理引擎 (断言数据源) | `tools/gui/state_space_sim_real.py` (metaworld, seed104) |",
          "| 画布节点 | ss2d3d · sstactile · sssensor |",
          "", "复现: `MUJOCO_GL=egl gui-venv311/bin/python tools/ss_feature_tests.py --only F-B12`"]
    return "\n".join(L) + "\n"


def deploy(paths: list[str]) -> bool:
    pw = os.environ.get("ZMAX_ECS_PW", "")
    if not pw:
        print("⚠️ 未设置 ZMAX_ECS_PW → 跳过部署")
        return False
    ok = True
    for p in paths:
        r = subprocess.run(["sshpass", "-p", pw, "scp", "-o", "StrictHostKeyChecking=no", p,
                            f"root@{ECS}:{ECSDIR}/{os.path.basename(p)}"],
                           capture_output=True, timeout=90)
        if r.returncode != 0:
            print(f"❌ 上传失败 {os.path.basename(p)}: {r.stderr.decode(errors='ignore')[:160]}")
            ok = False
        else:
            print(f"✅ 已上传 {os.path.basename(p)}")
    subprocess.run(["sshpass", "-p", pw, "ssh", "-o", "StrictHostKeyChecking=no", ECS,
                    f"chmod 644 {ECSDIR}/{FNAME_HTML} {ECSDIR}/{FNAME_MD}"],
                   capture_output=True, timeout=60)
    return ok


def verify_http() -> None:
    for url in (f"{SITE}/{FNAME_HTML}", f"{SITE}/{FNAME_MD}"):
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                body = r.read().decode("utf-8", "ignore")
            mark = "触觉反馈闭环" in body
            print(f"🔎 {url} → HTTP {r.status} · {len(body)}B · 含关键内容={mark}")
        except Exception as e:                                              # noqa: BLE001
            print(f"🔎 {url} → 复核失败 {type(e).__name__}: {e}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-run", action="store_true", help="不现场跑用例 (用已有实测 JSON)")
    ap.add_argument("--html-only", action="store_true", help="只生成, 不部署")
    a = ap.parse_args()
    d = collect()
    print(f"真源: 功能 {len(d['features'])} 条 · 用例 {len(d['tests'])} 条 · 功能树 {len(d['funcs'])} 条")
    print("现场真跑两条用例:")
    res = run_tests(not a.no_run)
    d["measured"] = measured()
    d["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
    outdir = os.path.join(ROOT, "reports", "web")
    os.makedirs(outdir, exist_ok=True)
    ph = os.path.join(outdir, FNAME_HTML)
    pm = os.path.join(outdir, FNAME_MD)
    open(ph, "w", encoding="utf-8").write(render_html(d, res))
    open(pm, "w", encoding="utf-8").write(render_md(d, res))
    print(f"✅ HTML {os.path.getsize(ph)//1024}KB → {ph}")
    print(f"✅ MD   {os.path.getsize(pm)//1024}KB → {pm}")
    if not a.html_only:
        if deploy([ph, pm]):
            time.sleep(1)
            verify_http()
    print("L2_PAGE_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
