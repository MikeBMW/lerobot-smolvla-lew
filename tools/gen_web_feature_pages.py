#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_web_feature_pages.py — datadrive.world 两个网页生成器 (2026-09-04 老倪统稿)

从单一真源 src/lerobot/verification/node_func_tree.py 导出:
  1. function-list.html 功能清单网页
     §1 几何能力分类总纲: LFP局部精细感知 / LFO局部精细操作 / HDM全局高维
        流形泛化 (纤维丛视角: 局部截面+联络 → 全局同胚) + 三大精密作业
        (光模块插拔/光纤连接/光耦合) 跨本体泛化功能的 HDM 汇总表
     §2 五大应用场景 (FW Loading / ATS / 老化墙 / 上下料 / 光耦合) 详细描述
     §3 功能编号体系图例 (21 域三字母缩写, VIS-01 格式)
     §4 模块化功能组合链
     §5 规范场三层 → 22节点 → 110功能: 每功能含 编号|名称|详细说明|验证方法|
        几何类|应用场景|用例明细 (ref 指向 VerificationLayer 真断言)
  2. requirements-spec.html 需求规格书网页 (RFP 9指标 + 技术规格 3组12项 + 产品分级)
风格仿 datadrive.world 深色主题 (#0d1520 底 / #00d4aa 高亮 / 纯 HTML 表格 / 打印友好)
用法: gui-venv311/bin/python tools/gen_web_feature_pages.py [--out 输出目录]
默认输出 reports/web/ 下, scp 上传 ECS (39.102.211.79 /www/wwwroot/datadrive.world/)。
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
.tag{{display:inline-block;padding:1px 6px;border-radius:3px;font-size:11px;margin:1px;white-space:nowrap}}
.tg{{background:#00d4aa22;color:#00d4aa}}.to{{background:#f0a50022;color:#f0a500}}
.tp{{background:#a371f722;color:#a371f7}}.tr{{background:#ff6b3522;color:#ff6b35}}
.tb{{background:#58a6ff22;color:#58a6ff}}
.sc{{background:#00d4aa22;color:#00d4aa;border:1px solid #00d4aa55}}
.dom{{background:#a371f722;color:#a371f7}}
.gfp{{background:#58a6ff22;color:#58a6ff;border:1px solid #58a6ff55}}
.gfo{{background:#f0a50022;color:#f0a500;border:1px solid #f0a50055}}
.gdm{{background:#a371f722;color:#a371f7;border:1px solid #a371f755;font-weight:700}}
.code{{font-family:Consolas,monospace;font-weight:700;color:#ffd479;white-space:nowrap}}
.tno{{font-family:Consolas,monospace;color:#8b949e;white-space:nowrap}}
.kind{{font-size:10.5px;padding:0 5px;border-radius:3px;white-space:nowrap}}
.ka{{background:#3fb95022;color:#3fb950}}.ks{{background:#f0a50022;color:#f0a500}}.km{{background:#ff6b3522;color:#ff6b35}}
.note{{font-size:11px;color:#8b949e;padding:6px 10px;background:#0a111c;border-radius:4px;margin:6px 0}}
.ok{{color:#3fb950;font-weight:600}}.plan{{color:#f0a500;font-weight:600}}
tr.sub td{{background:#0d1420!important;color:#9aa4b2;font-size:11.5px;border-top:0}}
tr.sub td:first-child{{border-left:3px solid #2a3a55}}
tr.fn td{{background:#101b2e}}
.story{{font-size:12.5px;color:#c9d1d9}}
@media print{{*{{color:#000!important;background:#fff!important}}th{{background:#eee!important}}
td,th{{border:1px solid #000!important}}h1,h2,h3{{color:#000!important;border-color:#000!important}}
.tag,.code,.tno,.kind{{color:#000!important;border-color:#000!important}}}}
</style></head><body>
<a href="/">← 主页</a> · <a href="/function-list.html">🧩 功能清单</a> ·
<a href="/requirements-spec.html">📋 需求规格书</a>
<button onclick="window.print()" style="float:right;padding:6px 14px;background:#00d4aa;
color:#000;border:none;border-radius:5px;font-size:12px;font-weight:600;cursor:pointer">📄 导出PDF</button>
"""

_KIND = {"auto": ("自动", "ka"), "semi": ("半自动", "ks"), "manual": ("手动", "km")}
_GEOM = {g[0]: g for g in [
    ("LFP", "局部精细感知类", "gfp"),
    ("LFO", "局部精细操作类", "gfo"),
    ("HDM", "全局高维流形泛化类", "gdm"),
]}


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fid_map():
    return {f["fid"]: f for n in nft.NODE_TREE.values() for f in n["funcs"]}


def _geom_tag(f):
    gid = f.get("geom")
    if not gid:
        return ""
    g = _GEOM.get(gid)
    if not g:
        return ""
    zh, cls = g[1], g[2]
    return f'<span class="tag {cls}" title="{_esc(zh)}">{gid}</span>'


def _scene_badge(codes):
    if not codes:
        return '<span class="note" style="margin:0">平台通用</span>'
    return "".join(f'<span class="tag sc">{c}</span>' for c in codes)


def build_function_list():
    F = _fid_map()
    kc = nft.kind_count()
    h = [_HEAD.format(title="🧩 功能清单 · 几何分类(LFP/LFO/HDM) · 五大场景 · 110功能×550用例"),
         "<h1>🧩 功能清单 — 几何能力分类 → 应用场景 → 编号功能 → 验证用例</h1>",
         f'<div class="note">110 功能按纤维丛几何语义分三类 (LFP 30 / LFO 35 / '
         f'<b style="color:#a371f7">HDM 45</b>) · 五大客户场景 · 22 节点 × 110 功能 '
         f'(三字母编号, 如 VIS-01=视觉第一功能) × 550 用例 (自动 {kc.get("auto",0)} · '
         f'半自动 {kc.get("semi",0)} · 手动 {kc.get("manual",0)}) · '
         f'每功能: 详细说明 + 验证方法 + 5 条用例逐条对应 · 数据源 node_func_tree.py</div>']

    # ── §1 几何能力分类总纲 (纤维丛视角) ──
    h.append("<h2>📐 一、几何能力分类总纲 (分段式局部截面 → VLM 端到端全局流形)</h2>")
    h.append('<div class="note"><b>框架</b>: 传统分段式 = 在低维物理空间手工铺设'
             '<b>局部截面 + 联络</b> (平行移动) — 换本体时旧联络在新几何上遇'
             '<b>奇点/曲率</b>而失效; VLM 端到端 = 在高维语义-动作联合流形上学'
             '<b>全局拓扑映射</b> — 语义 Token 与本体无关, 跨本体微调即得新截面,'
             ' 无致命奇点 (拓扑不变)。<b>双系统</b>: System2 (VLM 骨干) 在流形上标'
             ' waypoints · System1 (Action Expert) 生成航点间平滑轨迹 — '
             '即 Z-MAX 左脑动作 + 右脑世界模型架构。</div>')
    h.append("<table><tr><th>几何类</th><th>纤维丛语义</th><th>覆盖功能域</th>"
             "<th>功能</th><th>用例</th></tr>")
    for gid, zh, en, sem, nd, nf, nt in nft.geom_stats():
        gcls = _GEOM[gid][1]
        h.append(f"<tr><td><b>{gid}</b><br><span class='tag {gcls}'>{zh}</span></td>"
                 f"<td style='font-size:11.5px'>{_esc(en)}<br><span class='tno'>{_esc(sem)}</span></td>"
                 f"<td>{nd} 域</td><td><b>{nf}</b></td><td>{nt}</td></tr>")
    h.append("</table>")
    # HDM 汇总: 三大精密作业跨本体泛化
    h.append("<h3>🌐 HDM 汇总 — 三大精密作业的跨本体泛化功能 (统一收进高维流形)</h3>")
    h.append('<div class="note">光模块插拔 (SC-01) / 光纤连接 (SC-02) / 光耦合 (SC-05) '
             '三作业中, 具备<b>跨本体泛化能力</b>的功能全部经 HDM 汇总: '
             '状态空间世界模型 (PRD/EST/COR/LAT — 本体无关状态方程, 换臂仅微调即新截面)、'
             '语义认知 (LLM/RSN/SKL — 概念级 waypoints 与诊断, 不绑定电机转角)、'
             '数据飞轮与仿真锚点 (DAT/WLD — 流形学习的采样与验证)。'
             'LFP 感知亦本体无关 (换本体仅重标定外参), LFO 操作绑定运动学 (换本体必须重标定)。</div>')
    h.append("<table><tr><th>精密作业</th><th>HDM 泛化功能 (跨本体不重训)</th>"
             "<th>几何定位</th></tr>")
    sc_name = {s["code"]: s["name"] for s in nft.SCENES}
    for code, fids in nft.hdm_jobs_overview():
        fs = " · ".join(f'<span class="tag gdm" title="{_esc(F[fid]["name"])}">'
                        f'{F[fid].get("code", fid)}</span>' for fid in fids)
        # 域归类简述
        doms = sorted({F[fid].get("dom", "") for fid in fids})
        h.append(f"<tr><td><b>{code}</b><br>{_esc(sc_name[code])}</td>"
                 f"<td>{fs}</td><td>{' · '.join(doms)}</td></tr>")
    h.append("</table>")

    # ── §2 五大应用场景 ──
    h.append("<h2>🎯 二、五大应用场景 (场景 ↔ 功能对应)</h2>")
    h.append("<table><tr><th>场景</th><th>工位/产线段</th><th>作业对象</th>"
             "<th>实现状态</th><th>支撑功能</th></tr>")
    for sc in nft.SCENES:
        h.append(f"<tr><td><b>{sc['code']}</b><br><span class='code'>{_esc(sc['name'])}</span></td>"
                 f"<td>{sc['station']}</td><td>{sc['object']}</td>"
                 f"<td>{sc['status']}</td>"
                 f"<td>{len(sc['funcs'])} 个功能 (见下详表)</td></tr>")
    h.append("</table>")
    for sc in nft.SCENES:
        st = sc["status"]
        cls = "ok" if st.startswith("✅") else "plan"
        h.append(f"<h3>{sc['code']} · {_esc(sc['name'])} "
                 f"<span class='tag tb'>{_esc(sc['station'])}</span> "
                 f"<span class='tag {cls}'>{_esc(st)}</span></h3>")
        h.append(f'<div class="note"><b>作业故事线：</b><span class="story">{_esc(sc["story"])}</span></div>')
        h.append("<table><tr><th>作业对象</th><th>环境与约束</th><th>量化目标 (验收锚点)</th></tr>"
                 f"<tr><td>{_esc(sc['object'])}</td><td>{_esc(sc['env'])}</td><td>"
                 + "<br>".join(f"· {_esc(t)}" for t in sc["targets"])
                 + "</td></tr></table>")
        hdm_ids = {f["fid"] for f in nft.hdm_funcs_of_scene(sc["code"])}
        h.append("<h4>本场景支撑功能 (场景 → 功能对应)</h4>"
                 "<table><tr><th>编号</th><th>功能</th><th>几何类</th><th>详细说明</th><th>验证方法</th></tr>")
        for fid in sc["funcs"]:
            f = F.get(fid)
            if not f:
                continue
            hdm_mark = ' <span class="tag gdm" title="跨本体泛化">HDM</span>' if fid in hdm_ids else ""
            h.append(f"<tr><td><span class='code'>{f.get('code', fid)}</span>"
                     f"<br><span class='tno'>{fid}</span></td>"
                     f"<td><b>{_esc(f['name'])}</b><br><span class='tag dom'>{f.get('dom','')}</span>{hdm_mark}</td>"
                     f"<td>{_geom_tag(f)}</td>"
                     f"<td>{_esc(f['desc'])}</td>"
                     f"<td>{_verify_summary(f)}</td></tr>")
        h.append("</table>")
    # 平台通用底座
    in_scene = {fid for sc in nft.SCENES for fid in sc["funcs"]}
    base = [f for n in nft.NODE_TREE.values() for f in n["funcs"] if f["fid"] not in in_scene]
    h.append('<div class="note">平台通用底座 '
             f'({len(base)} 个功能不绑定单一场景, 全场景共用: '
             + " · ".join(sorted({f["name"] for f in base}))
             + ")。</div>")

    # ── §3 编号体系图例 ──
    h.append("<h2>🔤 三、功能编号体系 (三字母域缩写 + 域内序号 + 几何类)</h2>")
    h.append('<div class="note">编号格式 <span class="code">域码-NN</span>: '
             '域码 = 业务功能族三字母缩写, NN = 族内工艺顺序。例 <span class="code">VIS-01</span> = '
             '视觉感知第一功能 (YOLO 目标类别检出)。全库 110 功能唯一编号, 与工程码 fid 并存可互换。</div>')
    h.append("<table><tr><th>域码</th><th>功能族</th><th>英文</th><th>模型角色</th>"
             "<th>几何类</th><th>覆盖画布节点</th><th>功能数</th></tr>")
    nk_name = {k: n["name"] for k, n in nft.NODE_TREE.items()}
    _dom_cnt = {dom: nf for dom, _z, _e, _r, _n, nf in nft.dom_stats()}
    for dom, zh, en, role, nks in nft.FUNC_DOMAINS:
        nf = _dom_cnt.get(dom, 0)
        if not nf:
            continue
        gid = nft.GEOM_OF_DOM.get(dom)
        g = _GEOM.get(gid)
        gtag = g[2] if g else ""
        gzh = g[1] if g else ""
        h.append(f"<tr><td><span class='code'>{dom}</span></td><td><b>{zh}</b></td>"
                 f"<td>{en}</td><td><span class='tag dom'>{role}</span></td>"
                 f"<td>{f'<span class=tag {gtag}>{gid} {gzh}</span>' if g else ''}</td>"
                 f"<td>{' · '.join(nk_name.get(k, k) for k in nks if k in nk_name)}</td>"
                 f"<td>{nf}</td></tr>")
    h.append("</table>")

    # ── §4 功能组合链 ──
    h.append("<h2>⚡ 四、模块化功能组合链 (截面合成)</h2><table><tr><th>组合链</th><th>描述</th>"
             "<th>覆盖功能</th></tr>")
    for name, desc, chain in nft.FUNC_CHAINS:
        fs = " · ".join(f'<span class="tag tg">{F.get(c, {}).get("name", c)}</span>'
                        for c in chain)
        h.append(f"<tr><td><b>{name}</b></td><td>{desc}</td><td>{fs}</td></tr>")
    h.append("</table>")

    # ── §5 三层功能总表 ──
    h.append("<h2>🧩 五、规范场三层 → 节点 → 功能 (编号 · 详细说明 · 验证方法 · 用例)</h2>")
    h.append('<div class="note">每功能固定 5 条测试用例, 逐条展开列于功能行下方子行: '
             '用例编号 = <span class="code">功能编号-T1~T5</span>; 自动/半自动用例的 ref 指向 '
             'VerificationLayer 真实断言方法 (右键画布 Test 节点一键运行全部), 手动用例给出逐条验收步骤。'
             '「几何类」徽标: <span class="tag gfp">LFP</span> 局部精细感知 · '
             '<span class="tag gfo">LFO</span> 局部精细操作 · '
             '<span class="tag gdm">HDM</span> 全局高维流形泛化。'
             '「应用场景」列: SC-xx = 支撑场景, 平台通用 = 全场景底座。</div>')
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
            h.append("<table><tr><th>编号</th><th>功能 (详细说明)</th><th>几何类</th>"
                     "<th>验证方法</th><th>应用场景</th></tr>")
            for f in node["funcs"]:
                code = f.get("code", f["fid"])
                scs = nft.scenes_of_func(f["fid"])
                kinds = [t[1] for t in f["tests"]]
                cnt = (f"<span class='tno'>auto {kinds.count('auto')} · semi "
                       f"{kinds.count('semi')} · 手动 {kinds.count('manual')}</span>")
                h.append(f"<tr class='fn'><td><span class='code'>{code}</span><br>"
                         f"<span class='tno'>{f['fid']}</span></td>"
                         f"<td><b>{_esc(f['name'])}</b><br><span class='tag dom'>{f.get('dom','')}</span>"
                         f"<br><span class='story'>{_esc(f['desc'])}</span></td>"
                         f"<td>{_geom_tag(f)}</td>"
                         f"<td>{_verify_summary(f)}<br>{cnt}</td>"
                         f"<td>{_scene_badge(scs)}</td></tr>")
                # 5 条用例子行
                for ti, (tdesc, kind, ref, step) in enumerate(f["tests"], 1):
                    kn, kcls = _KIND.get(kind, ("?", ""))
                    meth = ""
                    if ref:
                        meth = f"VerificationLayer.{ref}()"
                    elif step:
                        meth = f"步骤: {step}"
                    h.append(f"<tr class='sub'><td colspan='5'>"
                             f"<span class='tno'>{code}-T{ti}</span> "
                             f"<span class='kind {kcls}'>{kn}</span> "
                             f"<b>{_esc(tdesc)}</b>"
                             f"<br><span class='tno'>{_esc(meth)}</span></td></tr>")
            h.append("</table>")
    h.append("</body></html>")
    return "".join(h)


def _verify_summary(f):
    """功能的验证方法汇总 (程序化, 全部来自注册表真数据, ref 原样展示并去重)"""
    parts, seen = [], set()
    for _tdesc, kind, ref, step in f["tests"]:
        if kind in ("auto", "semi") and ref and ref not in seen:
            seen.add(ref)
            parts.append(f"VerificationLayer.{ref}()")
    return "<br>".join(parts) if parts else "<span class='note' style='margin:0'>见下方用例行</span>"


def build_requirements_spec():
    fid_name = {f["fid"]: f["name"] for n in nft.NODE_TREE.values() for f in n["funcs"]}
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
