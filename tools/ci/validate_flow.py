#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Z-MAX Simulink 模型验证器 (对标 MathWorks Model Advisor)
CI/CD 管道第一环: 校验工作流 JSON 的标准合规性
- 节点合法性 (类型枚举/必填字段)
- 连线合法性 (f/t 引用存在, 无自环, 无重复)
- DAG 无环检测 (拓扑排序)
- 未连接节点告警 (可选, 参照 Model Advisor "未连接线" 检查)
用法:
  python3 tools/ci/validate_flow.py flow.json [--strict]
  python3 tools/ci/validate_flow.py --all   # 扫描仓库内所有 flow*.json
退出码: 0=通过 1=有错误 2=用法错误
"""
import json, sys, os

NODE_TYPES = {"condition", "data", "model", "action", "system", "hardware", "switch",
              "train_gate", "mode_switch", "yolo_gate", "coord_overlay", "row_bg",
              "pdf_report", "skill", "scene"}
REQUIRED = {"id", "type", "name", "x", "y"}


def validate_flow(flow, strict=False):
    """返回 (ok, issues)"""
    issues = []
    nodes = flow.get("nodes", [])
    links = flow.get("links", [])

    if not isinstance(nodes, list) or not isinstance(links, list):
        return False, ["格式错误: nodes/links 必须是数组"]

    ids = set()
    for i, n in enumerate(nodes):
        if not isinstance(n, dict):
            issues.append(f"节点[{i}] 不是对象"); continue
        for k in REQUIRED:
            if k not in n:
                issues.append(f"节点[{i}] 缺少必填字段 '{k}'")
        if n.get("type") not in NODE_TYPES:
            issues.append(f"节点[{i}] 类型非法: {n.get('type')!r} (应为 {sorted(NODE_TYPES)})")
        if "id" in n:
            if n["id"] in ids:
                issues.append(f"节点 id 重复: {n['id']}")
            ids.add(n["id"])

    seen = set()
    for j, l in enumerate(links):
        if not isinstance(l, dict) or "f" not in l or "t" not in l:
            issues.append(f"连线[{j}] 缺少 f/t 字段"); continue
        f, t = l["f"], l["t"]
        if f not in ids:
            issues.append(f"连线[{j}] 源节点不存在: {f}")
        if t not in ids:
            issues.append(f"连线[{j}] 目标节点不存在: {t}")
        if f == t:
            issues.append(f"连线[{j}] 自环: {f}->{f}")
        key = (f, t)
        if key in seen:
            issues.append(f"连线[{j}] 重复: {f}->{t}")
        seen.add(key)

    # DAG 环检测 (拓扑排序)
    # 🐛 2026-08-28: 状态空间类模板 (含 "状态空间"/"obs"/"前馈加速器" 节点) 是闭环
    #   反馈系统 (卡尔曼校正环/感知-决策-执行闭环), 环是架构特性不是错误 —
    #   simulink_module._topo_sort 用「剩余(有环)追加」优雅处理 → 此类环降级为警告。
    #   普通模板 (训练管线等) 有环仍是硬错误。
    is_state_space = any("状态空间" in (n.get("name") or "") or "obs" in (n.get("name") or "")
                         or "前馈加速器" in (n.get("name") or "") for n in nodes)
    if ids:
        adj = {i: [] for i in ids}
        indeg = {i: 0 for i in ids}
        for l in links:
            if l["f"] in adj and l["t"] in adj:
                adj[l["f"]].append(l["t"])
                indeg[l["t"]] += 1
        q = [i for i, d in indeg.items() if d == 0]
        cnt = 0
        while q:
            nid = q.pop(0); cnt += 1
            for m in adj[nid]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    q.append(m)
        if cnt != len(ids):
            msg = f"存在环 (无法拓扑排序), 涉及节点: {len(ids) - cnt} 个"
            if is_state_space:
                print(f"  ℹ️ {msg} (状态空间闭环反馈, 允许)")
            else:
                issues.append(msg)

    # 未连接节点 (仅 strict 模式视为错误)
    if nodes:
        connected = set()
        for l in links:
            connected.add(l["f"]); connected.add(l["t"])
        dangling = [n["id"] for n in nodes if n["id"] not in connected]
        if dangling:
            msg = f"未连接节点 {len(dangling)} 个: {dangling[:5]}{'...' if len(dangling) > 5 else ''}"
            if strict:
                issues.append(msg)
            else:
                print(f"  ⚠️ {msg}")

    return len(issues) == 0, issues


def main():
    if len(sys.argv) < 2:
        print("用法: validate_flow.py flow.json [--strict] | --all")
        return 2
    strict = "--strict" in sys.argv[1:]
    targets = []
    if "--all" in sys.argv:
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        for root, _, files in os.walk(base):
            if ".git" in root or "node_modules" in root or ".venv" in root:
                continue
            for f in files:
                if f.startswith("flow") and f.endswith(".json"):
                    targets.append(os.path.join(root, f))
    else:
        targets = [a for a in sys.argv[1:] if not a.startswith("--")]

    ok_all = True
    for path in targets:
        try:
            flow = json.load(open(path, encoding="utf-8"))
        except Exception as ex:
            print(f"✗ {path}: 无法解析 ({ex})")
            ok_all = False
            continue
        ok, issues = validate_flow(flow, strict)
        status = "✓ PASS" if ok else "✗ FAIL"
        print(f"{status} {path} ({len(flow.get('nodes', []))}节点 {len(flow.get('links', []))}连线)")
        for iss in issues:
            print(f"    ✗ {iss}")
        ok_all = ok_all and ok

    print()
    print("RESULT:", "ALL PASS" if ok_all else "FAILED")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
