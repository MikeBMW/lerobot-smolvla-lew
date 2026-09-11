# -*- coding: utf-8 -*-
"""按操作性判据核算留一角度泛化: 预测决策的角(φ*) 在实测里是否真能夹住。

判据: 抽出该 fold 的 (φ, 实测Δz_norm, 预测Δz, 预测P成功) 曲线 →
  φ* = argmax 预测Δz (与执行器同规则); 查该 φ 的**实测**Δz 是否 > 0.4 (=80mm/0.2, 即探针 ok 阈值)
  两种决策规则都算: (a) argmax 预测Δz  (b) argmax P(成功)
"""
import json
import sys

p = sys.argv[1]
d = json.load(open(p, encoding="utf-8"))
OK = 0.4          # 实测 Δz_norm > 0.4 == 探针 ok (抬升 >80mm)
print(f"文件: {p} · 分组键={d.get('group_key')} · 行数={d.get('n_rows')}")
print(f"判据: 预测角在实测里 Δz_norm > {OK} (即真能夹起) 记 ✅\n")
for f in d["folds"]:
    if not f["fold"].startswith("留出"):
        continue
    g = list(f["eval"]["groups"].values())[0]      # [(φ, 实测Δz, 预测Δz, 预测P), ...]
    a_dz = max(g, key=lambda t: t[2])
    a_p = max(g, key=lambda t: t[3])
    print(f"{f['fold']:16s} acc={f['eval']['ok_acc']:.3f}")
    print(f"   (a) argmax 预测Δz  → φ*={a_dz[0]:+6.1f}°  实测Δz={a_dz[1]:.3f} "
          f"{'✅ 能夹住' if a_dz[1] > OK else '❌ 夹不住'}")
    print(f"   (b) argmax P(成功) → φ*={a_p[0]:+6.1f}°  实测Δz={a_p[1]:.3f} "
          f"{'✅ 能夹住' if a_p[1] > OK else '❌ 夹不住'}")
    feas = [t[0] for t in g if t[1] > OK]
    print(f"   该来料角实测可夹住的角集合: {feas}")
    print(f"   实测最优角={max(g, key=lambda t: t[1])[0]:+.1f}° "
          f"(Δz={max(t[1] for t in g):.3f})\n")
