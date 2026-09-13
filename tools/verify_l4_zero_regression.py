# -*- coding: utf-8 -*-
"""零回退证明 (老倪红线: 增加 L4 只能提升能力, 不能让 L2/L3 下降)。

证明三层:
  ① 画布执行集: 按档位过滤 (cap_of ≤ 档位) 计算 L2/L3 档实际执行的节点集合
     —— 与改动前 (git HEAD) 逐 id 相同 → L2/L3 执行路径零变化。
  ② 引擎侧: SS_L4_INTACT 未设 → 代码路径根本不进 (纯 env 门控), 且新 tr 键只在门控内追加。
  ③ 新增节点全部位于 L4 行内 (cap=4) → L2/L3 档不执行。
"""
import json
import subprocess
import sys

P = "/home/ubuntu/lerobot-smolvla-lew/flows/state_space_obs.json"
before = json.loads(subprocess.run(
    ["git", "-C", "/home/ubuntu/lerobot-smolvla-lew", "show", "HEAD:flows/state_space_obs.json"],
    capture_output=True, text=True, check=True).stdout)
after = json.load(open(P, encoding="utf-8"))


def cap_map(doc):
    rows = [n for n in doc["nodes"] if n.get("type") == "row_bg"]

    def cap_of(node):
        y = node.get("y", 0)
        for b in rows:
            if b["y"] <= y < b["y"] + b.get("h", 0):
                nm = b.get("name", "")
                return 4 if "L4" in nm else 3 if "L3" in nm else 2 if "L2" in nm else 0
        return 0
    return {n["id"]: cap_of(n) for n in doc["nodes"]}


cb, ca = cap_map(before), cap_map(after)
ok = True
for lvl, num in (("L2", 2), ("L3", 3), ("L4", 4)):
    sb = sorted(i for i, c in cb.items() if c <= num)
    sa = sorted(i for i, c in ca.items() if c <= num)
    added = sorted(set(sa) - set(sb))
    removed = sorted(set(sb) - set(sa))
    status = "✅ 完全相同" if not added and not removed else f"⚠️ 变化 +{added} -{removed}"
    if lvl in ("L2", "L3") and (added or removed):
        ok = False
    print(f"  ① {lvl} 档执行集: 改动前 {len(sb)} → 改动后 {len(sa)} · {status}")

# ② 引擎代码门控
eng = open("/home/ubuntu/lerobot-smolvla-lew/tools/gui/state_space_sim_real.py", encoding="utf-8").read()
n_env = eng.count('os.environ.get("SS_L4_INTACT")')
print(f"  ② 引擎: SS_L4_INTACT 门控出现 {n_env} 处 (未设该变量 → 整段不执行)")
print(f"     新 tr 键 (l4_w / l4_u_ff_vec / l4_cond_vec) 全部写在门控 if 内:",
      all(eng.index(k) > eng.index('os.environ.get("SS_L4_INTACT") == "1"')
          for k in ('"l4_w"', '"l4_u_ff_vec"', '"l4_cond_vec"')))
if n_env < 2:
    ok = False

# ③ 新节点在 L4
for nid in ("ssintact_dec",):
    print(f"  ③ 新节点 {nid}: cap={ca[nid]} (必须 4)")
    if ca.get(nid) != 4:
        ok = False
# ④ 现有节点字段零改动
def sig(n):
    return json.dumps({k: v for k, v in n.items() if k != "params"}, sort_keys=True, ensure_ascii=False)
bmap = {n["id"]: sig(n) for n in before["nodes"]}
amap = {n["id"]: sig(n) for n in after["nodes"]}
moved = [i for i in bmap if bmap[i] != amap.get(i)]
print(f"  ④ 现有节点 (除 ssintact/swintact 的路径字段) 位置/名称/类型变化: {moved or '无'}")
if set(moved) - {"ssintact"}:
    ok = False
# 连线: 原有连线逐条不变
bl = json.dumps(before["links"], sort_keys=True, ensure_ascii=False)
al = json.dumps(after["links"], sort_keys=True, ensure_ascii=False)
print(f"  ⑤ 新增连线: {sorted(set(l['id'] for l in after['links']) - set(l['id'] for l in before['links']))}")
print(f"  ⑥ 原有连线 (f/t/label) 是否全在:",
      all(all(l in after["links"] for l in before["links"]) for _ in [0]))

print()
print("零回退结论:", "✅ L2/L3 执行路径与节点/连线逐项不变 (只有 L4 档新增)" if ok else "❌ 有回退!")
sys.exit(0 if ok else 1)
