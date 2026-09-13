# -*- coding: utf-8 -*-
"""🛡 零回退体检 (老倪红线: 增加 L4 只能提升能力, 不能让 L2/L3 下降)。

只认三件**语义**不变量 (布局坐标不算语义, 允许为 UI 重排而移动):
  ① 档位归属 (cap 级) 逐节点不变 —— 决定"哪个档位执行哪些节点"的唯一依据
  ② 各档执行集 (cap ≤ 2 / 3 / 4) 逐 id 相同; L4 档只允许**增加**新节点
  ③ 连线拓扑 (f→t 二元组 + label) 不变 —— 端口号可调整, 连线关系不许变
对照对象: git HEAD 的 flows/state_space_obs.json
用法: gui-venv311/bin/python tools/verify_l4_zero_regression.py
"""
import json
import subprocess
import sys

P = "/home/ubuntu/lerobot-smolvla-lew/flows/state_space_obs.json"
ROOT = "/home/ubuntu/lerobot-smolvla-lew"


def cap_of(node, nodes):
    """节点档位 (按所在 row_bg 色带): L4行=4 / L3行=3 / L2行=2 / 其它行=0 恒包含。"""
    y = node.get("y", 0)
    for b in nodes:
        if b.get("type") != "row_bg":
            continue
        if b["y"] <= y < b["y"] + b.get("h", 0):
            nm = b.get("name", "")
            return 4 if "L4" in nm else 3 if "L3" in nm else 2 if "L2" in nm else 0
    return 0


def main() -> int:
    before = json.loads(subprocess.run(
        ["git", "-C", ROOT, "show", "HEAD:flows/state_space_obs.json"],
        capture_output=True, text=True, check=True).stdout)
    after = json.load(open(P, encoding="utf-8"))
    nb = {n["id"]: n for n in before["nodes"]}
    na = {n["id"]: n for n in after["nodes"]}
    ok = True

    # ① 档位归属
    moved = [i for i in nb if i in na and cap_of(nb[i], before["nodes"]) != cap_of(na[i], after["nodes"])]
    print(f"  ① 档位归属 (cap) 变化: {moved or '无'} {'✅' if not moved else '❌'}")
    ok &= not moved

    # ② 各档执行集
    for lvl, num in (("L2", 2), ("L3", 3), ("L4", 4)):
        sb = {i for i in nb if cap_of(nb[i], before["nodes"]) <= num}
        sa = {i for i in na if cap_of(na[i], after["nodes"]) <= num}
        added, removed = sa - sb, sb - sa
        good = (not removed) and (not added if lvl != "L4" else True)
        print(f"  ② {lvl} 档执行集: {len(sb)} → {len(sa)}  新增 {sorted(added) or '-'} "
              f"移除 {sorted(removed) or '-'} {'✅' if good else '❌'}")
        ok &= good

    # ③ 连线拓扑 (f→t + label)
    tb = sorted((l["f"], l["t"], l.get("label", "")) for l in before["links"])
    ta = sorted((l["f"], l["t"], l.get("label", "")) for l in after["links"])
    lost = [x for x in tb if x not in ta]
    added_l = [x for x in ta if x not in tb]
    print(f"  ③ 连线拓扑: 原有 {len(tb)} 条丢失 {len(lost)} {lost[:3] or ''} · "
          f"新增 {len(added_l)} {[f'{a[0]}→{a[1]}' for a in added_l] or ''} "
          f"{'✅' if not lost else '❌'}")
    ok &= not lost

    print()
    print("零回退结论:", "✅ L2/L3 执行路径与连线拓扑逐项不变 (布局坐标变动不影响语义)"
          if ok else "❌ 有回退!")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
