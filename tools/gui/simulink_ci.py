#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Z-MAX Simulink 模型验证 CI · 验证器核心 (对标 MathWorks CI Support Package)
================================================================================
流水线: 构建(解析) → 测试(Model Advisor类规范检查 + 拓扑DAG校验 + 仿真执行) → 打包(报告工件) → 部署

用法:
  python3 simulink_ci.py validate flow.json          # 验证单个工作流
  python3 simulink_ci.py validate flow.json --report report.html  # 生成HTML报告
  python3 simulink_ci.py test all                    # 运行内置测试用例
  python3 simulink_ci.py pipeline flow.json          # 完整 CI 管道 (验证→报告→部署标记)

与 web 端 ECS 配合: 验证结果 POST https://datadrive.world/api/relay/upload (ci_*.json)
"""
import json, sys, os, time, random, html
from pathlib import Path

# ── 规范 (与 simulink-spec.md v1.0 / simulink_module.py 完全一致) ──
NODE_TYPES = {"condition", "model", "action", "system", "hardware", "switch"}
REQUIRED_NODE_KEYS = {"id", "type", "name", "x", "y"}
FORMAT = "zmax-simulink"
VERSION = "1.0"


class Report:
    """验证报告 (CI 工件)"""
    def __init__(self, flow_name):
        self.flow_name = flow_name
        self.checks = []   # {name, status: pass/warn/fail, detail}
        self.started = time.time()

    def add(self, name, status, detail=""):
        self.checks.append({"name": name, "status": status, "detail": detail})

    @property
    def passed(self):
        return all(c["status"] == "pass" for c in self.checks)

    def summary(self):
        n = len(self.checks)
        p = sum(1 for c in self.checks if c["status"] == "pass")
        w = sum(1 for c in self.checks if c["status"] == "warn")
        f = n - p - w
        return f"✅ {p} 通过 / ⚠️ {w} 警告 / ❌ {f} 失败 (共{n}项) · {'PASS' if self.passed else 'FAIL'}"

    def to_json(self):
        return {
            "format": FORMAT, "version": VERSION, "kind": "ci-report",
            "flow": self.flow_name, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "passed": self.passed, "duration_s": round(time.time() - self.started, 3),
            "checks": self.checks,
        }

    def to_html(self):
        rows = []
        for c in self.checks:
            icon = {"pass": "✅", "warn": "⚠️", "fail": "❌"}[c["status"]]
            color = {"pass": "#2ea043", "warn": "#d29922", "fail": "#f85149"}[c["status"]]
            rows.append(f'<tr><td style="color:{color}">{icon} {html.escape(c["name"])}</td>'
                        f'<td>{html.escape(c["detail"])}</td></tr>')
        status = "PASS" if self.passed else "FAIL"
        color = "#2ea043" if self.passed else "#f85149"
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Z-MAX Simulink CI 报告</title>
<style>body{{font-family:Consolas,monospace;background:#0d1117;color:#c9d1d9;padding:24px;}}
h1{{color:#58a6ff}} table{{border-collapse:collapse;width:100%;margin-top:16px}}
td{{border:1px solid #30363d;padding:8px 12px;font-size:13px}}
.badge{{display:inline-block;padding:4px 16px;border-radius:12px;background:{color};color:#fff;font-weight:700}}</style></head>
<body><h1>Z-MAX Simulink 模型验证 CI 报告</h1>
<p>工作流: <b>{html.escape(self.flow_name)}</b> &nbsp; {time.strftime('%Y-%m-%d %H:%M:%S')}</p>
<p><span class="badge">{status}</span> &nbsp; {self.summary()} &nbsp; 耗时 {self.to_json()['duration_s']}s</p>
<table>{"".join(rows)}</table></body></html>"""


# ════════════════════════════════════════════════════════════
# 检查项 (对标 Model Advisor 检查 + Simulink Test)
# ════════════════════════════════════════════════════════════
def check_format(flow, rep):
    ok = flow.get("format") == FORMAT
    rep.add("格式检查 (format=zmax-simulink)", "pass" if ok else "fail",
            f"format={flow.get('format', '缺失')}")
    return ok


def check_version(flow, rep):
    v = flow.get("version")
    rep.add("版本检查", "pass" if v == VERSION else "warn",
            f"version={v} (期望 {VERSION})")
    return v == VERSION


def check_nodes_schema(flow, rep):
    nodes = flow.get("nodes", [])
    if not nodes:
        rep.add("节点数量", "fail", "画布为空 (0节点)")
        return False
    ids = set()
    bad = []
    for n in nodes:
        nid = n.get("id")
        if nid in ids:
            bad.append(f"重复id:{nid}")
        ids.add(nid)
        if n.get("type") not in NODE_TYPES:
            bad.append(f"{n.get('name', '?')}: 非法type={n.get('type')}")
        for k in REQUIRED_NODE_KEYS:
            if k not in n:
                bad.append(f"{n.get('name', '?')}: 缺{k}")
    rep.add("节点 Schema 检查", "pass" if not bad else "fail",
            f"{len(nodes)}节点 " + ("; ".join(bad[:5]) if bad else "✅"))
    return not bad


def check_links(flow, rep):
    nodes = flow.get("nodes", [])
    links = flow.get("links", [])
    ids = {n["id"] for n in nodes}
    bad = []
    for l in links:
        if l.get("f") not in ids:
            bad.append(f"连线{l.get('id')}: 源节点{l.get('f')}不存在")
        if l.get("t") not in ids:
            bad.append(f"连线{l.get('id')}: 目标节点{l.get('t')}不存在")
        if l.get("f") == l.get("t"):
            bad.append(f"连线{l.get('id')}: 自环")
    rep.add("连线检查", "pass" if not bad else "fail",
            f"{len(links)}连线 " + ("; ".join(bad[:5]) if bad else "✅"))
    return not bad


def check_topology_dag(flow, rep):
    """DAG 拓扑排序: 无环则全节点有序"""
    nodes, links = flow.get("nodes", []), flow.get("links", [])
    adj = {n["id"]: [] for n in nodes}
    indeg = {n["id"]: 0 for n in nodes}
    for l in links:
        if l["f"] in adj and l["t"] in adj:
            adj[l["f"]].append(l["t"])
            indeg[l["t"]] += 1
    q = [nid for nid, d in indeg.items() if d == 0]
    order = []
    while q:
        nid = q.pop(0)
        order.append(nid)
        for m in adj[nid]:
            indeg[m] -= 1
            if indeg[m] == 0:
                q.append(m)
    cyclic = [n for n in nodes if n["id"] not in order]
    rep.add("拓扑 DAG 检查 (无环)", "pass" if not cyclic else "fail",
            f"排序{len(order)}/{len(nodes)}节点 " +
            ("✅ 无环" if not cyclic else f"⚠️ 环含: {[n['name'] for n in cyclic]}"))
    return not cyclic


def check_ports(flow, rep):
    """端口匹配: 连线 f_port/t_port 必须在源/目标节点端口集合内"""
    nodes = flow.get("nodes", [])
    links = flow.get("links", [])
    by_id = {n["id"]: n for n in nodes}
    bad = []
    for l in links:
        src, dst = by_id.get(l["f"]), by_id.get(l["t"])
        if not src or not dst:
            continue
        outs = {p["id"] for p in src.get("outputs", [])}
        ins = {p["id"] for p in dst.get("inputs", [])}
        if l.get("f_port") and l["f_port"] not in outs:
            bad.append(f"{l.get('id')}: 源端口{l.get('f_port')}不存在")
        if l.get("t_port") and l["t_port"] not in ins:
            bad.append(f"{l.get('id')}: 目标端口{l.get('t_port')}不存在")
    rep.add("端口匹配检查", "pass" if not bad else "fail",
            "✅" if not bad else "; ".join(bad[:5]))
    return not bad


def check_params(flow, rep):
    """参数类型检查: bool/int/float/str/list 合法"""
    nodes = flow.get("nodes", [])
    bad = []
    for n in nodes:
        for k, v in n.get("params", {}).items():
            if v is None or isinstance(v, (bool, int, float, str, list)):
                continue
            bad.append(f"{n['name']}.{k}: 非法类型 {type(v).__name__}")
    rep.add("参数类型检查", "pass" if not bad else "fail",
            "✅" if not bad else "; ".join(bad[:5]))
    return not bad


def check_simulation(flow, rep, steps=10):
    """仿真执行测试 (对标 Simulink Test): 按拓扑执行, 检测运行时错误"""
    nodes, links = flow.get("nodes", []), flow.get("links", [])
    if not nodes:
        rep.add("仿真执行", "fail", "无节点可执行")
        return False
    # 拓扑排序
    adj = {n["id"]: [] for n in nodes}
    indeg = {n["id"]: 0 for n in nodes}
    for l in links:
        if l["f"] in adj and l["t"] in adj:
            adj[l["f"]].append(l["t"])
            indeg[l["t"]] += 1
    q = [nid for nid, d in indeg.items() if d == 0]
    order = []
    while q:
        nid = q.pop(0)
        order.append(nid)
        for m in adj[nid]:
            indeg[m] -= 1
            if indeg[m] == 0:
                q.append(m)
    for n in nodes:
        if n["id"] not in order:
            order.append(n["id"])
    errors = []
    for step in range(steps):
        for nid in order:
            n = next(x for x in nodes if x["id"] == nid)
            t = n["type"]
            try:
                if t == "model":
                    _ = n.get("params", {}).get("checkpoint", "model")
                elif t == "action":
                    p = n.get("params", {})
                    if p.get("pos") and not isinstance(p["pos"], list):
                        raise ValueError("pos 需为list")
                elif t == "hardware":
                    _ = n.get("params", {}).get("ip", "-")
            except Exception as ex:
                errors.append(f"step{step} {n['name']}: {ex}")
                break
    rep.add("仿真执行测试", "pass" if not errors else "fail",
            f"{steps}步×{len(order)}节点 " + ("✅ 无运行时错误" if not errors else "; ".join(errors[:3])))
    return not errors


# ════════════════════════════════════════════════════════════
# CI 管道
# ════════════════════════════════════════════════════════════
def run_checks(flow):
    rep = Report(flow.get("name", "untitled"))
    check_format(flow, rep)
    check_version(flow, rep)
    check_nodes_schema(flow, rep)
    check_links(flow, rep)
    check_topology_dag(flow, rep)
    check_ports(flow, rep)
    check_params(flow, rep)
    check_simulation(flow, rep)
    return rep


def pipeline(flow_path, report_path=None, upload=False):
    """完整 CI 管道: 验证 → 报告工件 → (可选) 推送 ECS"""
    print(f"🔨 构建: 解析 {flow_path}")
    flow = json.load(open(flow_path, encoding="utf-8"))
    print(f"   {len(flow.get('nodes', []))}节点 / {len(flow.get('links', []))}连线 / sim={flow.get('sim')}")
    print(f"🧪 测试: 模型验证...")
    rep = run_checks(flow)
    print(f"   {rep.summary()}")
    if report_path:
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(report_path).write_text(rep.to_html(), encoding="utf-8")
        print(f"📦 打包: 报告 → {report_path}")
    if upload:
        try:
            import requests
            r = requests.post("https://datadrive.world/api/relay/upload",
                              json={"name": f"ci_{time.strftime('%Y%m%d_%H%M%S')}.json",
                                    "meta": {"kind": "ci-report", "passed": rep.passed},
                                    "data": rep.to_json()}, timeout=10)
            print(f"📤 上传报告: {r.json().get('ok')}")
        except Exception as ex:
            print(f"⚠️ 上传失败: {ex}")
    return rep


def run_tests():
    """内置自测 (CI 回归)"""
    ok = True
    good = {"format": "zmax-simulink", "version": "1.0", "name": "t_good",
            "nodes": [{"id": "a", "type": "model", "name": "ACT", "x": 0, "y": 0,
                       "params": {"checkpoint": "act"}, "outputs": [{"id": "o"}]},
                      {"id": "b", "type": "action", "name": "取料", "x": 100, "y": 0,
                       "inputs": [{"id": "i"}]}],
            "links": [{"id": "l1", "f": "a", "t": "b", "f_port": "o", "t_port": "i"}]}
    bad = {"format": "zmax-simulink", "version": "1.0", "name": "t_bad",
           "nodes": [{"id": "a", "type": "model", "name": "ACT", "x": 0, "y": 0,
                      "params": {"pos": "not-a-list"}}],
           "links": [{"id": "l1", "f": "a", "t": "ghost"}]}
    rep_good = run_checks(good)
    rep_bad = run_checks(bad)
    print("GOOD用例:", rep_good.summary())
    print("BAD 用例:", rep_bad.summary())
    ok = rep_good.passed and not rep_bad.passed
    print("回归:", "PASS ✅" if ok else "FAIL ❌")
    return ok


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "test" or (args and args[0] == "all"):
        sys.exit(0 if run_tests() else 1)
    if args[0] == "pipeline":
        flow = args[1]
        report = args[args.index("--report") + 1] if "--report" in args else None
        up = "--upload" in args
        rep = pipeline(flow, report, up)
        sys.exit(0 if rep.passed else 1)
    if args[0] == "validate":
        flow = args[1]
        rep = run_checks(json.load(open(flow, encoding="utf-8")))
        print(rep.summary())
        if "--report" in args:
            p = args[args.index("--report") + 1]
            Path(p).parent.mkdir(parents=True, exist_ok=True)
            Path(p).write_text(rep.to_html(), encoding="utf-8")
            print(f"📦 报告: {p}")
        sys.exit(0 if rep.passed else 1)
    print(__doc__)
