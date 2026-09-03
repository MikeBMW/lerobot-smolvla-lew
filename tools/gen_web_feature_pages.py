#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_web_feature_pages.py — datadrive.world 两个网页生成器 (2026-09-04 老倪)

从单一真源 src/lerobot/verification/node_func_tree.py 导出:
  1. function-list.html 功能清单网页 (规范场三层 → 22节点 → 110功能 → 用例统计)
  2. requirements-spec.html 需求规格书网页 (RFP 9指标 + 技术规格 3组12项 + 产品分级)
风格仿 datadrive.world 深色主题 (#0d1520 底 / #00d4aa 高亮 / 纯 HTML 表格 / 打印友好)
用法: gui-venv311/bin/python tools/gen_web_feature_pages.py [--out 输出目录]
默认输出 reports/web/ 下, 手动 scp 上传。
"""
import argparse
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "lerobot", "verification"))

_NFP = os.path.join(ROOT, "src", "lerobot", "verification", "node_func_tree.py")
_spec = importlib.util.spec_from_file_location("lerobot.verification.node_func_tree", _NFP)
nft = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nft)

_HEAD = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
body{{background:#0d1520;color:#d0d7de;font-family:'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;
margin:0;padding:24px 32px;font-size:14px;line-height:1.55}}
h1{{color:#fff;font-size:22px;border-bottom:2px solid #00d4aa;padding-bottom:8px}}
h2{{color:#00d4aa;font-size:17px;margin-top:26px;border-left:4px solid #00d4aa;padding-left:10px}}
h3{{color:#58a6ff;font-size:14.5px;margin-top:18px}}
h4{{color:#a371f7;font-size:13px;margin:10px 0 4px}}
table{{border-collapse:collapse;width:100%;margin:8px 0;font-size:12.5px}}
th{{background:#16233a;color:#fff;padding:6px 8px;border:1px solid #2a3a55;text-align:left;white-space:nowrap}}
td{{padding:5px 8px;border:1px solid #223049;vertical-align:top}}
tr:nth-child(even) td{{background:#0f1a2b}}
a{{color:#00d4aa;text-decoration:none}}
.tag{{display:inline-block;padding:1px 6px;border-radius:3px;font-size:11px;margin:1px}}
.tg{{background:#00d4aa22;color:#00d4aa}}.to{{background:#f0a50022;color:#f0a500}}
.tp{{background:#a371f722;color:#a371f7}}.tr{{background:#ff6b3522;color:#ff6b35}}
.tb{{background:#58a6ff22;color:#58a6ff}}
.note{{font-size:11px;color:#8b949e;padding:6px 10px;background:#0a111c;border-radius:4px;margin:6px 0}}
.ok{{color:#3fb950;font-weight:600}}.plan{{color:#f0a500;font-weight:600}}
@media print{{*{{color:#000!important;background:#fff!important}}th{{background:#eee!important}}
td,th{{border:1px solid #000!important}}h1,h2{{color:#000!important;border-color:#000!important}}}}
</style></head><body>
<a href="/">← 主页</a> · <a href="/function-list.html">🧩 功能清单</a> ·
<a href="/requirements-spec.html">📋 需求规格书</a>
<button onclick="window.print()" style="float:right;padding:6px 14px;background:#00d4aa;
color:#000;border:none;border-radius:5px;font-size:12px;font-weight:600;cursor:pointer">📄 导出PDF</button>
"""


def _fid_name():
    return {f["fid"]: f["name"] for n in nft.NODE_TREE.values() for f in n["funcs"]}


def build_function_list():
    fid_name = _fid_name()
    h = [_HEAD.format(title="🧩 功能清单 · Z-MAX 状态空间 22节点×110功能×550用例"),
         "<h1>🧩 功能清单 — 规范场三层 → 节点 → 功能 → 用例</h1>",
         f'<div class="note">三级注册表: G1场感知/G2协变操作/G3对称认知三层 · '
         f'{nft.node_count()} 节点 × {nft.func_count()} 功能(名5~10字) × '
         f'{nft.test_count()} 用例 (自动 {nft.kind_count().get("auto",0)} · '
         f'半自动 {nft.kind_count().get("semi",0)} · 手动 {nft.kind_count().get("manual",0)}) · '
         f'模块化组合链 {len(nft.FUNC_CHAINS)} 条 · 数据源 node_func_tree.py</div>']
    # 功能组合链
    h.append("<h2>⚡ 模块化功能组合链 (截面合成)</h2><table><tr><th>组合链</th><th>描述</th>"
             "<th>覆盖功能</th></tr>")
    for name, desc, chain in nft.FUNC_CHAINS:
        fs = " · ".join(f'<span class="tag tg">{fid_name.get(c, c)}</span>' for c in chain)
        h.append(f"<tr><td><b>{name}</b></td><td>{desc}</td><td>{fs}</td></tr>")
    h.append("</table>")
    # 三层节点
    for gid, zh, en, desc, nks in nft.GAUGE_LAYERS:
        nodes = [k for k in nks if k in nft.NODE_TREE]
        if not nodes:
            continue
        h.append(f'<h2>{gid} {zh} · <span style="color:#8b949e;font-weight:400">{en}</span></h2>'
                 f'<div class="note">{desc}</div>')
        for nk in nodes:
            node = nft.NODE_TREE[nk]
            h.append(f"<h3>{node['name']} <span class='tag tb'>{nk}</span> "
                     f"<span class='tag tg'>{node['fb']}</span></h3>")
            h.append("<table><tr><th>功能</th><th>说明</th><th>用例</th></tr>")
            for f in node["funcs"]:
                kinds = [t[1] for t in f["tests"]]
                h.append(f"<tr><td><b>{f['name']}</b><br><span class='tag tp'>{f['fid']}</span></td>"
                         f"<td>{f['desc']}</td>"
                         f"<td>auto {kinds.count('auto')} · semi {kinds.count('semi')} · "
                         f"手动 {kinds.count('manual')}</td></tr>")
            h.append("</table>")
    h.append("</body></html>")
    return "".join(h)


def build_requirements_spec():
    fid_name = _fid_name()
    h = [_HEAD.format(title="📋 需求规格书 · 光模块精密制造机器人系统 RFP + 技术规格"),
         "<h1>📋 需求规格书 — 客户 RFP + 供应商技术规格</h1>",
         f'<div class="note">{nft.RFP_SPEC["overview"]} · 数据源 node_func_tree.py '
         f'(RFP_SPEC/TECH_SPECS/PRODUCT_TREE)</div>']
    # 产品分级
    h.append("<h2>🎯 产品作业分级 (刚体→柔性→性能调节)</h2>")
    for lv in nft.PRODUCT_TREE:
        h.append(f"<h3>{lv['level']} {lv['lvl_name']} · {lv['kind']}</h3>"
                 f'<div class="note">{lv["desc"]}</div><table>'
                 "<tr><th>产品作业</th><th>状态</th><th>模型选型路线</th><th>泛化指标</th></tr>")
        for j in lv["jobs"]:
            status = j["status"]
            cls = "ok" if status.startswith("✅") else "plan"
            h.append(f"<tr><td><b>{j['job']}</b></td>"
                     f"<td class='{cls}'>{status}</td>"
                     f"<td>{j.get('model_route','')}</td>"
                     f"<td style='font-size:11.5px'>{j.get('gen','')}</td></tr>")
        h.append("</table>")
    # RFP 指标
    h.append("<h2>★ 客户 RFP 量化指标</h2><table><tr><th>否决</th><th>指标</th>"
             "<th>量化要求</th><th>关联作业</th></tr>")
    for name, q, veto, job, funcs in nft.RFP_SPEC["key_items"]:
        fs = " · ".join(fid_name.get(f, f) for f in funcs)
        h.append(f"<tr><td>{'<span class=tag tr>★否决</span>' if veto else ''}</td>"
                 f"<td><b>{name}</b></td><td>{q}</td>"
                 f"<td>{job}<br><span style='color:#8b949e;font-size:11px'>{fs}</span></td></tr>")
    h.append("</table>")
    # 技术规格 3 组
    h.append("<h2>🛠 供应商技术规格 (3组12项)</h2>")
    for g in nft.TECH_SPECS:
        h.append(f"<h3>{g['group']} {g['g_name']} · "
                 f"<span style='color:#8b949e;font-weight:400'>{g['g_en']}</span></h3>"
                 f'<div class="note">{g["g_desc"]}</div><table>'
                 "<tr><th>规格项</th><th>量化要求</th><th>关联作业</th></tr>")
        for it in g["items"]:
            fs = " · ".join(fid_name.get(f, f) for f in it["funcs"])
            h.append(f"<tr><td><b>{it['spec']}</b></td><td>{it['req']}</td>"
                     f"<td>{it['job']}<br><span style='color:#8b949e;font-size:11px'>{fs}</span></td></tr>")
        h.append("</table>")
    # 交付要求
    h.append("<h2>📦 交付与保障</h2><table><tr><th>条款</th><th>要求</th></tr>")
    for k, v in nft.RFP_SPEC["delivery"].items():
        h.append(f"<tr><td><b>{k}</b></td><td>{v}</td></tr>")
    h.append("</table></body></html>")
    return "".join(h)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "reports", "web"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    p1 = os.path.join(a.out, "function-list.html")
    p2 = os.path.join(a.out, "requirements-spec.html")
    with open(p1, "w", encoding="utf-8") as f:
        f.write(build_function_list())
    with open(p2, "w", encoding="utf-8") as f:
        f.write(build_requirements_spec())
    print(f"function-list.html: {os.path.getsize(p1)} bytes")
    print(f"requirements-spec.html: {os.path.getsize(p2)} bytes")
    print(f"OUT_DIR={a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
