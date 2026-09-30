#!/usr/bin/env python3
"""Z-MAX simulink 工程完整性检查 (2026-08-28)"""
import re, json, os, sys

ROOT = os.path.expanduser("~/lerobot-smolvla-lew")
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

def extract_keys(path, varname="NODE_TYPES"):
    src = open(path).read()
    # 兼容 dict {key: {...}} 和 set {"a", "b"} 两种写法 (set 可能单行/跨行)
    m = re.search(varname + r"\s*=\s*\{(.*?)\n?\}", src, re.S)
    if not m:
        return set(), src
    body = m.group(1)
    keys = set(re.findall(r"\"([a-zA-Z0-9_]+)\"\s*:", body))
    if not keys:  # set 写法
        keys = set(re.findall(r"\"([a-zA-Z0-9_]+)\"", body))
    return keys, src

print("=" * 60)
print("[1] NODE_TYPES 三处同步检查")
print("=" * 60)
s1, src1 = extract_keys(os.path.join(ROOT, "tools/gui/simulink_module.py"))
s2, _ = extract_keys(os.path.join(ROOT, "tools/ci/validate_flow.py"))
s3, _ = extract_keys(os.path.join(ROOT, "tools/gui/simulink_ci.py"))
print(f"simulink_module: {len(s1)} 种")
print(f"validate_flow:   {len(s2)} 种 | 缺: {sorted(s1-s2)} | 多: {sorted(s2-s1)}")
print(f"simulink_ci:     {len(s3)} 种 | 缺: {sorted(s1-s3)} | 多: {sorted(s3-s1)}")

print()
print("=" * 60)
print("[2] node_logic 注册 vs 画布 flows 节点名")
print("=" * 60)
import node_logic
flows_dir = os.path.join(ROOT, "flows")
flow_files = [f for f in os.listdir(flows_dir) if f.endswith(".json")]
all_node_names = set()
for ff in flow_files:
    try:
        d = json.load(open(os.path.join(flows_dir, ff)))
        if isinstance(d, dict):
            for n in d.get("nodes", []):
                all_node_names.add(n.get("name", ""))
        # list 结构 (atomic_skills_*.json) 跳过 — 非画布流
    except Exception as e:
        print(f"  ⚠️ {ff} 读取失败: {e}")
reg_names = set()
for entry in node_logic.NODE_LOGIC.values():
    # 结构: {"match": [关键字...], "fn": fn, "doc": doc}
    if isinstance(entry, dict):
        for nm in entry.get("match", []):
            reg_names.add(nm)
# 画布节点里没有注册逻辑的 (允许: row_bg/观察类)
unmatched = []
for nm in sorted(all_node_names):
    if not nm:
        continue
    if node_logic.match_node(nm) is None:
        unmatched.append(nm)
print(f"画布节点总数: {len(all_node_names)} | 节点逻辑注册名: {len(reg_names)}")
print(f"未匹配节点逻辑的画布节点 ({len(unmatched)}):")
for u in unmatched:
    print(f"  - {u}")

print()
print("=" * 60)
print("[3] 按钮创建/挂载检查 (mk_btn 但没 addWidget)")
print("=" * 60)
btn_creates = re.findall(r"(self\.\w+)\s*=\s*mk_btn\(", src1)
btn_missing = []
for b in btn_creates:
    # 检查这个按钮名在 addWidget 或 addLayout 或布局 add 中出现
    if f"addWidget({b}" not in src1 and f"addWidget({b}," not in src1:
        btn_missing.append(b)
print(f"mk_btn 创建: {len(btn_creates)} 个 | 疑似未挂布局: {btn_missing or '无'}")

print()
print("=" * 60)
print("[4] REFERENCE_APPS 模板完整性")
print("=" * 60)
from simulink_module import REFERENCE_APPS
for item in REFERENCE_APPS:
    nm = item[0]
    if len(item) == 4:
        nodes, links, layout = item[1], item[2], item[3]
        n_nodes = len(nodes)
        n_links = len(links)
        # layout 单元格数 (含重复引用, 共享节点多行出现) — 至少覆盖全部唯一节点
        cells = [c for row in layout for c in row if c]
        unique_in_layout = len(set(cells))
        node_names = {n[1] if isinstance(n, (list, tuple)) else n["name"] for n in nodes}
        # 设计上允许不在 layout 的节点: 共享「🧩 结构条件」由 load_reference_app 显式跳过
        # (已下放各模型行 "结构条件 · X"), 不进 layout 是正确的
        skip_names = {"🧩 结构条件"}
        missing = (node_names - set(cells)) - skip_names
        print(f"  {nm}: {n_nodes}节点 {n_links}连线 | layout 格={len(cells)} 去重={unique_in_layout} "
              f"{'✓' if not missing else '✗ 布局缺节点: ' + str(missing)[:60]}")
    else:
        print(f"  {nm}: {len(item[1])}节点 {len(item[2])}连线 (3元组, 无 layout)")

print()
print("=" * 60)
print("[5] flows/*.json 画布数据完整性")
print("=" * 60)
for ff in sorted(flow_files):
    d = json.load(open(os.path.join(flows_dir, ff)))
    if not isinstance(d, dict):
        print(f"  {ff}: (非画布流, list 结构, 跳过)")
        continue
    nodes = d.get("nodes", [])
    links = d.get("links", [])
    ids = {n["id"] for n in nodes}
    names = {n["name"] for n in nodes}
    dup_ids = len(ids) != len(nodes)
    bad_links = [l for l in links if l["f"] not in ids or l["t"] not in ids]
    # 孤立节点 (无入边无出边, 非 row_bg)
    out_ids = {l["f"] for l in links}
    in_ids = {l["t"] for l in links}
    isolated = [n["name"] for n in nodes if n["type"] != "row_bg"
                and n["id"] not in out_ids and n["id"] not in in_ids]
    print(f"  {ff}: {len(nodes)}节点 {len(links)}连线 | 重复id={'是!' if dup_ids else '否'} "
          f"| 断线={len(bad_links)} | 孤立非背景节点={isolated or '无'}")
